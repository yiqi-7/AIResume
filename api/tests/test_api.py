import asyncio
import io
import json

import httpx
import pytest
from docx import Document

from app.main import create_app
from tests.test_documents import make_docx
from tests.test_llm import JD, response, station

HEADERS = {"X-Resume-Client": "web", "Origin": "http://127.0.0.1:4321"}


def mock_model(req):
    data = json.loads(json.loads(req.content)["messages"][1]["content"])
    if "confirmed_fact" in data:
        return response(json.dumps({"rewrite": data["confirmed_fact"]}))
    if data["dimension"] == "structure":
        return response('{"items": []}')
    block = data["resume"]["sections"][-1]["blocks"][0]
    gap = data["dimension"] == "relevance"
    return response(json.dumps({"items": [{
        "title": "补充真实沟通经历" if gap else "写清个人行动", "priority": "P0" if gap else "P1",
        "target_block_id": None if gap else block["id"],
        "resume_quote": "" if gap else block["text"], "jd_quote": "能够进行需求分析",
        "reason": "补充原文没有写出的事实" if gap else "调整已有事实的表达顺序",
        "rewrite": "" if gap else "访谈同学，整理需求，梳理流程并完成平台原型。",
        "needs_fact": gap, "question": "你怎样和同学沟通需求？" if gap else "",
    }]}))


@pytest.fixture
async def client(tmp_path):
    settings = station().model_copy(update={"data_dir": tmp_path / "private"})
    app = create_app(settings, httpx.MockTransport(mock_model))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test", headers=HEADERS) as client:
            yield client, app


async def upload(client):
    result = await client.post("/api/sessions", files={"file": ("fictional.docx", make_docx())},
                               data={"jd": JD, "consent": "true"})
    assert result.status_code == 201, result.text
    assert "HttpOnly" in result.headers["set-cookie"]
    return result.json()


async def wait_ready(client, sid):
    for _ in range(100):
        result = (await client.get(f"/api/sessions/{sid}")).json()
        if result["state"] not in {"analyzing", "answering"}:
            return result
        await asyncio.sleep(0.01)
    pytest.fail("mocked model task did not finish")


async def test_end_to_end_parse_confirm_analyze_decide_fact_preview_export_and_purge(client):
    c, app = client
    session = await upload(c)
    sid = session["id"]
    assert session["state"] == "parsed" and not session["suggestions"]
    assert "auth_hash" not in session and "ip_key" not in session
    assert (await c.get("/api/session")).json()["session"]["id"] == sid
    assert (await c.post(f"/api/sessions/{sid}/analyze", json={})).status_code == 202
    session = await wait_ready(c, sid)
    assert session["state"] == "ready" and len(session["suggestions"]) == 2
    gap, item = session["suggestions"]
    assert gap["priority"] == "P0" and item["dimension"] == "content"
    path = f"/api/sessions/{sid}/suggestions/{item['id']}"
    assert (await c.patch(path, json={"action": "accept", "revision": session["revision"]})).status_code == 422
    result = await c.patch(path, json={"action": "accept", "revision": session["revision"],
                                       "confirmed_facts": True, "text": "访谈同学，整理需求并完成原型。"})
    assert result.status_code == 200
    assert (await c.patch(path, json={"action": "skip", "revision": session["revision"]})).status_code == 409
    session = result.json()
    answer_path = f"/api/sessions/{sid}/suggestions/{gap['id']}/answer"
    section_id = session["resume"]["sections"][-1]["id"]
    assert (await c.post(answer_path, json={"answer": "和同学核对需求文档。", "section_id": "missing",
                                          "confirmed": True})).status_code == 422
    answer = await c.post(answer_path, json={"answer": "和同学核对需求文档。", "section_id": section_id,
                                            "confirmed": True})
    assert answer.status_code == 202
    session = await wait_ready(c, sid)
    gap_path = f"/api/sessions/{sid}/suggestions/{gap['id']}"
    result = await c.patch(gap_path, json={"action": "accept", "revision": session["revision"],
                                          "confirmed_facts": True})
    assert result.status_code == 200
    preview = (await c.get(f"/api/sessions/{sid}/preview")).json()
    assert preview["sections"][-1]["blocks"][-1]["text"] == "和同学核对需求文档。"
    exported = await c.post(f"/api/sessions/{sid}/export")
    assert exported.status_code == 200
    document = Document(io.BytesIO(exported.content))
    assert "访谈同学，整理需求并完成原型。" in [p.text for p in document.paragraphs]
    assert "和同学核对需求文档。" in [p.text for p in document.paragraphs]
    assert not app.state.store.directory(sid).exists()
    assert (await c.get(f"/api/sessions/{sid}")).status_code == 410
    assert (await c.get("/api/session")).json()["session"] is None


async def test_unauthorized_client_cannot_read_or_delete_another_session(client):
    c, app = client
    sid = (await upload(c))["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test", headers=HEADERS) as stranger:
        assert (await stranger.get(f"/api/sessions/{sid}")).status_code == 410
        assert (await stranger.delete(f"/api/sessions/{sid}")).status_code == 204
    assert app.state.store.directory(sid).exists()
    assert (await c.delete(f"/api/sessions/{sid}")).status_code == 204
    assert not app.state.store.directory(sid).exists()


async def test_upload_boundaries_csrf_and_no_secrets_in_errors(client):
    c, _ = client
    assert (await c.post("/api/sessions", headers={"Origin": "https://evil.invalid"})).status_code == 403
    assert (await c.post("/api/sessions", headers={"Content-Length": str(9 * 1024 * 1024)})).status_code == 413
    result = await c.post("/api/sessions", files={"file": ("private-filename.docx", b"bad")},
                          data={"jd": JD, "consent": "true"})
    assert result.status_code == 415
    assert "private-filename" not in result.text
    assert (await c.get("/admin/stats")).status_code == 404


async def test_missing_model_preserves_parsed_material(client):
    c, app = client
    sid = (await upload(c))["id"]
    app.state.model.settings.llm_base_url = ""
    result = await c.post(f"/api/sessions/{sid}/analyze", json={})
    assert result.status_code == 503 and result.json()["code"] == "MODEL_NOT_CONFIGURED"
    session = (await c.get(f"/api/sessions/{sid}")).json()
    assert session["state"] == "parsed"


async def test_partial_analysis_retries_only_failed_dimension_and_keeps_decisions(client):
    c, app = client
    sid = (await upload(c))["id"]
    attempts = 0

    def fail_once(req):
        nonlocal attempts
        payload = json.loads(req.content)
        data = json.loads(payload["messages"][1]["content"])
        if data.get("dimension") == "content":
            attempts += 1
            if attempts <= 2:
                return httpx.Response(503)
        return mock_model(req)

    await app.state.model.close()
    app.state.model.http = httpx.AsyncClient(transport=httpx.MockTransport(fail_once))
    response = await c.post(f"/api/sessions/{sid}/analyze", json={})
    partial = await wait_ready(c, sid)
    assert response.status_code == 202 and partial["state"] == "partial"
    assert partial["dimensions"]["content"] == "failed"
    existing = partial["suggestions"][0]
    path = f"/api/sessions/{sid}/suggestions/{existing['id']}"
    accepted = await c.patch(path, json={"action": "skip", "revision": partial["revision"]})
    assert accepted.status_code == 200
    retry = await c.post(f"/api/sessions/{sid}/analyze", json={})
    ready = await wait_ready(c, sid)
    assert retry.status_code == 202 and ready["state"] == "ready"
    assert attempts == 3
    kept = next(item for item in ready["suggestions"] if item["id"] == existing["id"])
    assert kept["decision"] == "skipped"


async def test_failed_fact_rewrite_preserves_completed_analysis_for_retry(client):
    c, app = client
    sid = (await upload(c))["id"]
    await c.post(f"/api/sessions/{sid}/analyze", json={})
    session = await wait_ready(c, sid)
    gap = next(item for item in session["suggestions"] if item["needs_fact"])
    await app.state.model.close()
    app.state.model.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    result = await c.post(
        f"/api/sessions/{sid}/suggestions/{gap['id']}/answer",
        json={"answer": "和同学核对需求文档。", "section_id": session["resume"]["sections"][-1]["id"],
              "confirmed": True},
    )
    assert result.status_code == 202
    failed = await wait_ready(c, sid)
    assert failed["state"] == "ready" and failed["error"] == "MODEL_UPSTREAM"
    assert all(value == "complete" for value in failed["dimensions"].values())
    assert next(item for item in failed["suggestions"] if item["id"] == gap["id"])["needs_fact"]


@pytest.mark.parametrize("fact_fails", [False, True])
async def test_fact_answer_keeps_failed_dimension_retryable(client, fact_fails):
    c, app = client
    sid = (await upload(c))["id"]
    attempts = 0

    def fail_once(req):
        nonlocal attempts
        payload = json.loads(req.content)
        data = json.loads(payload["messages"][1]["content"])
        if data.get("dimension") == "content":
            attempts += 1
            if attempts <= 2:
                return httpx.Response(503)
        if fact_fails and "confirmed_fact" in data:
            return httpx.Response(503)
        return mock_model(req)

    await app.state.model.close()
    app.state.model.http = httpx.AsyncClient(transport=httpx.MockTransport(fail_once))
    await c.post(f"/api/sessions/{sid}/analyze", json={})
    partial = await wait_ready(c, sid)
    assert partial["state"] == "partial"
    gap = next(item for item in partial["suggestions"] if item["needs_fact"])
    section = partial["resume"]["sections"][-1]["id"]
    result = await c.post(
        f"/api/sessions/{sid}/suggestions/{gap['id']}/answer",
        json={"answer": "和同学核对需求文档。", "section_id": section, "confirmed": True},
    )
    assert result.status_code == 202
    answered = await wait_ready(c, sid)
    assert answered["state"] == "partial"
    assert answered["error"] == ("MODEL_UPSTREAM" if fact_fails else None)
    answered_gap = next(item for item in answered["suggestions"] if item["id"] == gap["id"])
    assert answered_gap["needs_fact"] is fact_fails
    assert answered_gap["user_fact"] == ("" if fact_fails else "和同学核对需求文档。")
    await c.post(f"/api/sessions/{sid}/analyze", json={})
    ready = await wait_ready(c, sid)
    assert ready["state"] == "ready" and attempts == 3
    assert next(item for item in ready["suggestions"] if item["id"] == gap["id"])["user_fact"] == (
        "" if fact_fails else "和同学核对需求文档。"
    )
