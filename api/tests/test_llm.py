import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.documents import parse_docx
from app.llm import ModelClient, grounded
from app.metadata import Metadata
from app.schemas import Candidate, Problem, Session
from tests.test_documents import make_docx

JD = "能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。"


def sample():
    resume = parse_docx(make_docx())
    block = resume.sections[-1].blocks[0]
    candidate = Candidate(title="表达行动", priority="P1", target_block_id=block.id,
                          resume_quote=block.text, jd_quote="能够进行需求分析",
                          reason="突出已有行动", rewrite="访谈同学，整理需求，完成平台原型。")
    session = Session(id="test", auth_hash="", ip_key="hash", expires_at=9999999999,
                      resume=resume, jd=JD)
    return session, candidate


def station():
    return Settings(llm_base_url="https://model.example.invalid/v1", llm_model="test-model",
                    llm_api_key=SecretStr("test-key-not-real"), llm_protocol="chat_completions")


def response(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 50}})


def test_quotes_punctuation_and_numeric_tokens_are_not_fuzzy_matches():
    session, candidate = sample()
    assert grounded(candidate, session.resume, JD)
    assert not grounded(candidate.model_copy(update={"jd_quote": "原文未写的技能"}),
                        session.resume, JD)
    assert not grounded(candidate.model_copy(update={"rewrite": "访谈了 10 位同学"}),
                        session.resume, JD)
    assert not grounded(candidate.model_copy(update={"rewrite": "访谈了 1 位同学"}),
                        session.resume, JD, fact="访谈了 10 位同学")
    gap = candidate.model_copy(update={"needs_fact": True, "rewrite": "", "question": "怎样沟通？"})
    gap = gap.model_copy(update={"target_block_id": None, "resume_quote": ""})
    assert grounded(gap, session.resume, JD)
    assert not grounded(gap.model_copy(update={"rewrite": "擅长沟通"}), session.resume, JD)
    assert not grounded(gap.model_copy(update={"target_block_id": "missing",
                                               "resume_quote": "管理 20 人团队"}), session.resume, JD)


async def test_json_and_grounding_failures_share_one_retry():
    session, candidate = sample()
    calls = []

    def upstream(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return response("not JSON")
        invented = candidate.model_copy(update={"rewrite": "将转化率提升了 80%"})
        return response(json.dumps({"items": [candidate.model_dump(), invented.model_dump()]}))

    settings = station()
    metadata = Metadata(settings)
    client = ModelClient(settings, metadata, httpx.MockTransport(upstream))
    try:
        result = await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 2 and len(result) == 1
        assert result[0].rewrite == candidate.rewrite
        assert (await metadata.stats())["dropped_ungrounded"] == 1
    finally:
        await client.close()


async def test_bad_key_is_not_retried_or_reflected():
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(401, text="test-key-not-real private upstream details")

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        with pytest.raises(Problem, match="MODEL_KEY_INVALID") as error:
            await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 1
        assert "test-key-not-real" not in error.value.message
    finally:
        await client.close()


async def test_success_envelope_with_client_restriction_keeps_actionable_error_without_retry():
    calls = []
    refusal = "仅限 Coding 客户端使用。synthetic-private-refusal"

    def upstream(req):
        calls.append(req)
        return response(refusal)

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        with pytest.raises(Problem, match="MODEL_CLIENT_RESTRICTED") as error:
            await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 1
        assert refusal not in error.value.message
        assert "synthetic-private-refusal" not in error.value.message
    finally:
        await client.close()


async def test_missing_station_and_byok_allowlist_and_fact_answer():
    settings = Settings(_env_file=None, llm_base_url="", llm_model="", llm_api_key=SecretStr(""))
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(
        lambda req: response(json.dumps({"rewrite": "整理用户反馈，与同学核对原型。"}))))
    session, candidate = sample()
    try:
        with pytest.raises(Problem, match="MODEL_NOT_CONFIGURED"):
            client.resolve("station", "", None)
        with pytest.raises(Problem, match="MODEL_KEY_REQUIRED"):
            client.resolve("https://internal.invalid", "model", "fake")
        credentials = client.resolve("deepseek", "test-model", "fake-test-key")
        text = await client.answer(session, candidate, "整理用户反馈，与同学核对原型。", credentials)
        assert text == "整理用户反馈，与同学核对原型。"
        assert "budget" not in json.dumps(client.metadata.values)
    finally:
        await client.close()


@pytest.mark.parametrize("status,code,attempts", [
    (400, "MODEL_REQUEST_REJECTED", 1),
    (403, "MODEL_ACCESS_DENIED", 1),
    (404, "MODEL_REQUEST_REJECTED", 1),
    (429, "MODEL_RATE_LIMITED", 1),
    (503, "MODEL_UPSTREAM", 2),
])
async def test_upstream_failures_keep_their_cause_instead_of_becoming_invalid_json(status, code, attempts):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(status, text="test-key-not-real private upstream detail")

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        with pytest.raises(Problem, match=code) as error:
            await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == attempts
        assert "test-key-not-real" not in error.value.message
        assert "private upstream detail" not in error.value.message
    finally:
        await client.close()


@pytest.mark.parametrize("protocol", ["chat_completions", "responses", "anthropic_messages"])
async def test_station_uses_its_configured_protocol_and_accounts_tokens(protocol):
    settings = station().model_copy(update={"llm_protocol": protocol})
    calls = []

    def upstream(request):
        calls.append(request)
        if protocol == "responses":
            assert request.url.path == "/v1/responses"
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": '{"items":[]}'}]}],
                "usage": {"input_tokens": 5, "output_tokens": 7}})
        if protocol == "anthropic_messages":
            assert request.url.path == "/v1/messages"
            assert request.headers["x-api-key"] == "test-key-not-real"
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
                {"type": "text", "text": '{"items":[]}'}],
                "usage": {"input_tokens": 5, "output_tokens": 7}})
        assert request.url.path == "/v1/chat/completions"
        return response('{"items":[]}')

    metadata = Metadata(settings)
    client = ModelClient(settings, metadata, httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        credentials = client.resolve("station", "ignored-model", "ignored-key", protocol="responses")
        assert credentials.protocol == protocol and credentials.model == "test-model"
        assert await client.dimension("content", session, credentials) == []
        assert len(calls) == 1
        stats = await metadata.stats()
        assert stats["station_prompt_tokens"] == (100 if protocol == "chat_completions" else 5)
    finally:
        await client.close()


@pytest.mark.parametrize("protocol", ["chat_completions", "responses", "anthropic_messages"])
async def test_reasoning_output_limit_is_reported_without_retrying_truncated_json(protocol):
    settings = station().model_copy(update={"llm_output_tokens": 8192, "llm_protocol": protocol})
    calls = []

    def upstream(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if protocol == "responses":
            assert payload["max_output_tokens"] == 8192
            return httpx.Response(200, json={"status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"}, "output": []})
        assert payload["max_tokens"] == 8192
        if protocol == "anthropic_messages":
            return httpx.Response(200, json={"stop_reason": "max_tokens", "content": []})
        return httpx.Response(200, json={"choices": [{"finish_reason": "length",
            "message": {"content": ""}}]})

    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        with pytest.raises(Problem, match="MODEL_OUTPUT_LIMIT"):
            await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 1
    finally:
        await client.close()


async def test_network_timeout_has_a_distinct_error_and_is_not_retried():
    calls = []

    def upstream(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic-private-timeout", request=request)

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        with pytest.raises(Problem, match="MODEL_TIMEOUT") as error:
            await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 1 and 'synthetic-private-timeout' not in error.value.message
    finally:
        await client.close()
