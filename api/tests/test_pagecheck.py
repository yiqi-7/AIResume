import asyncio
import io
import os
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
from docx import Document

from app.pagecheck import PageChecker
from app.pagecheck_task import has_active_content
from app.pagecheck_worker import validate_sandbox
from app.schemas import Problem
from tests.test_api import HEADERS, JD
from tests.test_api import client as client
from tests.test_documents import make_docx, replace_part
from tests.test_llm import station


@pytest.mark.parametrize("status,payload,code", [
    (200, {"pages": 9}, "PAGE_LIMIT"),
    (200, {"pages": 0}, "PAGECHECK_UNAVAILABLE"),
    (200, {"pages": True}, "PAGECHECK_UNAVAILABLE"),
    (200, {}, "PAGECHECK_UNAVAILABLE"),
    (422, {"code": "PAGE_LIMIT"}, "PAGE_LIMIT"),
    (422, {"code": "ACTIVE_CONTENT"}, "ACTIVE_CONTENT"),
    (422, {"code": "PAGECHECK_TIMEOUT"}, "PAGECHECK_FAILED"),
    (503, {"private": "must-not-be-disclosed"}, "PAGECHECK_UNAVAILABLE"),
    (429, {}, "PAGECHECK_BUSY"),
])
async def test_pagecheck_rejects_unverified_results_without_saving(client, status, payload, code):
    c, app = client
    await app.state.pagecheck.close()
    app.state.pagecheck.http = httpx.AsyncClient(
        base_url="http://pagecheck",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
    )
    result = await c.post("/api/sessions", files={"file": ("fictional.docx", make_docx())},
                          data={"jd": JD, "consent": "true"})
    assert result.status_code in {422, 429, 503} and result.json()["code"] == code
    assert "must-not-be-disclosed" not in result.text
    assert "set-cookie" not in result.headers
    assert not list(app.state.store.root.iterdir())
    # A failed check must release upload capacity as well.
    await app.state.pagecheck.http.aclose()
    app.state.pagecheck.http = httpx.AsyncClient(
        base_url="http://pagecheck",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"pages": 8})),
    )
    accepted = await c.post("/api/sessions", files={"file": ("fictional.docx", make_docx())},
                            data={"jd": JD, "consent": "true"})
    assert accepted.status_code == 201
    assert accepted.json()["resume"]["rendered_pages"] == 8
    assert (await c.delete(f"/api/sessions/{accepted.json()['id']}")).status_code == 204


async def test_disconnected_pagecheck_fails_closed(tmp_path):
    checker = PageChecker(str(tmp_path / "absent.sock"))
    try:
        with pytest.raises(Problem, match="PAGECHECK_UNAVAILABLE"):
            await checker.count(make_docx())
    finally:
        await checker.close()


def test_worker_cannot_start_as_an_ordinary_process():
    with pytest.raises((RuntimeError, PermissionError)):
        validate_sandbox()


def test_macro_and_external_resource_packages_are_rejected_but_hyperlinks_are_allowed():
    raw = make_docx()
    assert not has_active_content(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        rels = package.read("word/_rels/document.xml.rels")
        types = package.read("[Content_Types].xml")
        document = package.read("word/document.xml")
    hyperlink = (b'<Relationship Id="rId100" Target="https://example.invalid" '
                 b'TargetMode="External" Type="http://schemas.openxmlformats.org/'
                 b'officeDocument/2006/relationships/hyperlink"/>')
    linked = replace_part(raw, "word/_rels/document.xml.rels",
                          rels.replace(b"</Relationships>", hyperlink + b"</Relationships>"))
    assert not has_active_content(linked)
    assert has_active_content(replace_part(linked, "word/_rels/document.xml.rels",
                                           rels.replace(b"</Relationships>",
                                                        hyperlink.replace(b"/hyperlink", b"/image")
                                                        + b"</Relationships>")))
    macro_type = (b'<Override PartName="/word/unexpected.bin" '
                  b'ContentType="application/vnd.ms-office.vbaProject"/>')
    assert has_active_content(replace_part(raw, "[Content_Types].xml", types.replace(
        b"</Types>", macro_type + b"</Types>")))
    field = b'<w:p><w:fldSimple w:instr="INCLUDETEXT file:///etc/passwd"/></w:p>'
    assert has_active_content(replace_part(raw, "word/document.xml", document.replace(
        b"<w:body>", b"<w:body>" + field)))


def test_separate_complex_fields_do_not_hide_split_external_commands():
    raw = make_docx()
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        document = source.read("word/document.xml")

    def field(*parts):
        return (b'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                + b"".join(b"<w:r><w:instrText>" + part + b"</w:instrText></w:r>"
                           for part in parts)
                + b'<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')

    harmless = field(b"PAGE") + field(b"DATE")
    assert not has_active_content(replace_part(raw, "word/document.xml", document.replace(
        b"<w:body>", b"<w:body>" + harmless)))
    for dangerous in [field(b"INCLUDETEXT file:///etc/passwd"),
                      field(b"INCLU", b"DETEXT file:///etc/passwd")]:
        for prefix in [b"", harmless]:
            modified = replace_part(raw, "word/document.xml", document.replace(
                b"<w:body>", b"<w:body>" + prefix + dangerous))
            assert has_active_content(modified)


@pytest.mark.parametrize("extension", ["xml", "dat"])
def test_relocated_parts_and_xml_without_xml_extension_cannot_hide_external_fields(extension):
    from app.documents import parse_docx

    raw = make_docx()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(output, "w") as dest:
        for item in source.infolist():
            name = item.filename.replace("word/", "payload/")
            content = source.read(item)
            if item.filename.endswith(".xml") or item.filename.endswith(".rels"):
                content = content.replace(b"word/", b"payload/")
            if item.filename == "word/document.xml":
                field = b'<w:p><w:fldSimple w:instr="INCLUDETEXT file:///etc/passwd"/></w:p>'
                content = content.replace(b"<w:body>", b"<w:body>" + field)
                dest.writestr("word/document.xml", source.read(item))  # Harmless decoy.
            if extension == "dat":
                content = content.replace(b"document.xml", b"document.dat")
                name = name.replace("document.xml", "document.dat")
            dest.writestr(name, content)
    relocated = output.getvalue()
    assert has_active_content(relocated)
    with pytest.raises(Problem, match="STRUCTURE_UNSUPPORTED"):
        parse_docx(relocated)


def paged_docx(pages: int, metadata: int | None = 1):
    doc = Document()
    for index in range(pages):
        if index:
            doc.add_page_break()
        doc.add_paragraph(
            f"第 {index + 1} 页 · 以下均为虚构测试材料。参与校园项目需求分析、访谈与原型设计。"
            "根据同学反馈整理使用流程，与设计同学核对页面信息和交互细节。"
        )
    output = io.BytesIO()
    doc.save(output)
    raw = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        app = source.read("docProps/app.xml")
    new_value = b"" if metadata is None else f"<Pages>{metadata}</Pages>".encode()
    return replace_part(raw, "docProps/app.xml", app.replace(b"<Pages>1</Pages>", new_value))


@pytest.mark.parametrize("pages,metadata,accepted", [
    (8, 1, True), (9, 1, False), (9, None, False), (1, 99, True), (8, None, True),
])
async def test_real_isolated_pagination_and_api_no_metadata_bypass(tmp_path, pages, metadata, accepted):
    socket_path = os.environ.get("TEST_PAGECHECK_SOCKET")
    if not socket_path:
        pytest.skip("Requires the real systemd pagination sandbox")
    from app.main import create_app

    settings = station().model_copy(update={"data_dir": tmp_path / "private",
                                           "pagecheck_socket": socket_path})
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test", headers=HEADERS) as c:
            result = await c.post("/api/sessions", files={"file": ("fictional.docx",
                                                                  paged_docx(pages, metadata))},
                                  data={"jd": JD, "consent": "true"})
            if accepted:
                assert result.status_code == 201, result.text
                resume = result.json()["resume"]
                assert resume["rendered_pages"] == pages and resume["page_count_verified"]
                await c.delete(f"/api/sessions/{result.json()['id']}")
            else:
                assert result.status_code == 422 and result.json()["code"] == "PAGE_LIMIT"
                assert "set-cookie" not in result.headers
            assert not list(app.state.store.root.iterdir())
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket_path),
                                 base_url="http://pagecheck", timeout=10) as c:
        health = (await c.get("/healthz")).json()
        assert health["isolated"] and health["active_jobs"] == health["temporary_jobs"] == 0


async def test_real_service_rejects_active_content_and_recovers():
    socket_path = os.environ.get("TEST_PAGECHECK_SOCKET")
    if not socket_path:
        pytest.skip("Requires the real systemd pagination sandbox")
    raw = make_docx()
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        types = source.read("[Content_Types].xml")
    malicious = replace_part(raw, "[Content_Types].xml", types.replace(
        b"</Types>", b'<Override PartName="/word/not-executed.bin" '
        b'ContentType="application/vnd.ms-office.vbaProject"/></Types>'))
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket_path),
                                 base_url="http://pagecheck", timeout=35) as c:
        denied = await c.post("/count", content=malicious)
        assert denied.status_code == 422 and denied.json()["code"] == "ACTIVE_CONTENT"
        assert (await c.post("/count", content=make_docx())).json() == {"pages": 1}
        assert (await c.get("/healthz")).json()["temporary_jobs"] == 0


async def test_real_service_deadline_busy_rejection_and_recovery():
    socket_path = os.environ.get("TEST_PAGECHECK_SOCKET")
    if not socket_path:
        pytest.skip("Requires the real systemd pagination sandbox")

    async def stalled_upload():
        yield b"partial fictional DOCX"
        await asyncio.sleep(40)

    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket_path),
                                 base_url="http://pagecheck", timeout=35) as c:
        stalled = asyncio.create_task(c.post("/count", content=stalled_upload()))
        try:
            for _ in range(100):
                if (await c.get("/healthz")).json()["active_jobs"] == 1:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("The real service did not admit the slow request")
            busy = await c.post("/count", content=make_docx())
            assert busy.status_code == 429
            # Request-body streaming cannot be interrupted by the response on all
            # HTTP clients, so observe the server's own state and deadline directly.
            for _ in range(65):
                health = (await c.get("/healthz")).json()
                if health["active_jobs"] == 0:
                    break
                await asyncio.sleep(0.5)
            else:
                pytest.fail("The pagination deadline did not release capacity")
            assert health["temporary_jobs"] == 0
        finally:
            stalled.cancel()
            await asyncio.gather(stalled, return_exceptions=True)
        assert (await c.post("/count", content=make_docx())).json() == {"pages": 1}


@pytest.mark.parametrize("failure", ["exception", "no_pdf", "timeout"])
async def test_worker_failure_closes_temporary_directory_and_releases_capacity(tmp_path,
                                                                             monkeypatch, failure):
    from app import pagecheck_worker

    original_temp = pagecheck_worker.tempfile.TemporaryDirectory

    def temporary(*args, **kwargs):
        kwargs["dir"] = tmp_path
        return original_temp(*args, **kwargs)

    async def fail_task(directory):
        assert (directory / "source.docx").is_file()
        if failure == "timeout":
            await asyncio.sleep(10)
        if failure == "exception":
            raise RuntimeError("synthetic-private-content")
        return None, "PAGECHECK_FAILED"

    monkeypatch.setattr(pagecheck_worker.tempfile, "TemporaryDirectory", temporary)
    monkeypatch.setattr(pagecheck_worker, "task_process", fail_task)
    monkeypatch.setattr(pagecheck_worker, "TASK_SECONDS", 0.05)
    worker = pagecheck_worker.create_worker()
    # Deliberately no lifespan: this test exercises only HTTP cleanup; actual
    # sandbox startup and rendering are tested separately with the real service.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),
                                 base_url="http://pagecheck") as c:
        failed = await c.post("/count", content=make_docx())
        assert failed.status_code in {422, 503}
        assert "synthetic-private-content" not in failed.text
        assert not list(tmp_path.iterdir())

        async def successful_task(directory):
            return 1, None

        monkeypatch.setattr(pagecheck_worker, "task_process", successful_task)
        assert (await c.post("/count", content=make_docx())).json() == {"pages": 1}
        assert not list(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "linux", reason="Process groups are Linux-only")
async def test_task_cancellation_kills_descendants_and_leaves_no_running_child(tmp_path, monkeypatch):
    from app import pagecheck_worker

    # A real process tree substitutes for a stuck renderer, without modifying the actual service.
    fixture = tmp_path / "fixture.py"
    marker = tmp_path / "child.pid"
    fixture.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    original = asyncio.create_subprocess_exec

    async def fixture_process(*args, **kwargs):
        return await original(sys.executable, str(fixture), str(marker), **kwargs)

    monkeypatch.setattr(pagecheck_worker.asyncio, "create_subprocess_exec", fixture_process)
    task = asyncio.create_task(pagecheck_worker.task_process(tmp_path))
    try:
        for _ in range(200):
            if marker.exists():
                break
            await asyncio.sleep(0.01)
        assert marker.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        child = int(marker.read_text())
        for _ in range(100):
            status = Path(f"/proc/{child}/status")
            if not status.exists() or "\nState:\tZ" in status.read_text():
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("Renderer descendant is still running after task cancellation")
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
