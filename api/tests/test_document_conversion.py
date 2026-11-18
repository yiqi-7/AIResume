import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app import pagecheck_task
from app.pdf_documents import parse_pdf
from tests.test_documents import make_textbox_docx


@pytest.fixture(scope="module")
def office():
    executable = (Path(r"E:\LibreOffice_26.2.5\program\soffice.exe") if os.name == "nt"
                  else Path(shutil.which("libreoffice") or "/usr/bin/libreoffice"))
    if not executable.is_file():
        pytest.skip("Requires LibreOffice for real Word/PDF fixtures")
    original = subprocess.run

    def native(command, **kwargs):
        assert command[0] == "/usr/bin/libreoffice"
        return original([str(executable), *command[1:]],
                        timeout=60 if os.name == "nt" else 25, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pagecheck_task.subprocess, "run", native)
        yield


@pytest.fixture(scope="module")
def word_fixtures(tmp_path_factory, office):
    tmp_path = tmp_path_factory.mktemp("fictional-formats")
    source = tmp_path / "source.docx"
    source.write_bytes(make_textbox_docx())
    doc = pagecheck_task.convert(tmp_path, source, "doc:MS Word 97")
    pdf = pagecheck_task.convert(tmp_path, source, "pdf:writer_pdf_Export")
    return source.read_bytes(), doc.read_bytes(), pdf.read_bytes()


def test_real_libreoffice_pdf_preserves_chinese_textbox_and_numeric_facts(word_fixtures):
    _, _, pdf = word_fixtures
    resume = parse_pdf(pdf)
    text = "\n".join(b.text for s in resume.sections for b in s.blocks)
    assert "fictional@example.invalid" in text
    assert "陈测试" in text and "陈同学" in text
    assert "2024" in text and "Python / SQL" in text and "20%" in text


def test_legacy_doc_task_converts_then_extracts_textboxes(tmp_path, word_fixtures):
    _, doc, _ = word_fixtures
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.doc").write_bytes(doc)
    (job / "extract").touch()
    assert pagecheck_task.run(job) == 0
    resume = json.loads((job / "result.json").read_text(encoding="utf-8"))
    text = "\n".join(b["text"] for s in resume["sections"] for b in s["blocks"])
    assert "陈测试" in text and "fictional@example.invalid" in text
    assert "2024" in text and "20%" in text
    assert resume["rendered_pages"] == 1 and resume["page_count_verified"]


@pytest.mark.parametrize("format", ["doc", "pdf"])
async def test_real_sandbox_extracts_word_and_pdf_and_cleans_up(word_fixtures, format):
    socket_path = os.environ.get("TEST_PAGECHECK_SOCKET")
    if not socket_path:
        pytest.skip("Requires the real systemd extraction sandbox")
    raw = word_fixtures[1 if format == "doc" else 2]
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket_path),
                                 base_url="http://pagecheck", timeout=35) as c:
        response = await c.post("/extract", params={"format": format}, content=raw)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["pages"] == 1
        text = "\n".join(b["text"] for s in result["resume"]["sections"] for b in s["blocks"])
        assert "陈测试" in text and "fictional@example.invalid" in text
        assert "2024" in text and "20%" in text
        health = (await c.get("/healthz")).json()
        assert health["isolated"] and health["active_jobs"] == health["temporary_jobs"] == 0
