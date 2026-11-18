import io

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.documents import upload_format
from app.pagecheck import PageChecker
from app.pdf_documents import parse_pdf
from app.schemas import Problem
from tests.test_api import JD
from tests.test_api import client as client
from tests.test_documents import make_docx

PDF_LINES = ["Fictional Candidate - 2024 - fictional@example.invalid",
             "Projects", "Python / SQL: improved synthetic process by 20%."]


def make_pdf(pages=1, encrypted=False, image_page=False):
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    for index in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        resources = DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font)})})
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        if image_page and index == pages - 1:
            image = DecodedStreamObject()
            image.set_data(b"\x00\x00\x00")
            image.update({NameObject("/Type"): NameObject("/XObject"),
                          NameObject("/Subtype"): NameObject("/Image"),
                          NameObject("/Width"): NumberObject(1),
                          NameObject("/Height"): NumberObject(1),
                          NameObject("/BitsPerComponent"): NumberObject(8),
                          NameObject("/ColorSpace"): NameObject("/DeviceRGB")})
            resources[NameObject("/XObject")] = DictionaryObject({
                NameObject("/Im1"): writer._add_object(image)})
            content.set_data(b"q 500 0 0 700 40 40 cm /Im1 Do Q")
        else:
            content.set_data(("BT /F1 12 Tf 40 790 Td 18 TL "
                              + " T* ".join(f"({line}) Tj" for line in PDF_LINES)
                              + " ET").encode())
        page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_reads_text_order_facts_and_original_page_count():
    resume = parse_pdf(make_pdf(2))
    assert resume.rendered_pages == 2 and resume.page_count_verified
    texts = [b.text for s in resume.sections for b in s.blocks]
    assert texts.count(PDF_LINES[0]) == 2
    assert texts.count(PDF_LINES[-1]) == 2
    assert any("PDF 文字层" in warning for warning in resume.warnings)


def test_pdf_unicode_mapping_preserves_chinese_and_digits():
    writer = PdfWriter(io.BytesIO(make_pdf()))
    page = writer.pages[0]
    text = "陈测试 2024 Python 项目效率提升 20% 以下均为虚构测试材料"
    # A real two-byte font and ToUnicode map; do not depend on system fonts in unit tests.
    mapping = DecodedStreamObject()
    pairs = "\n".join(f"<{index:04x}> <{char.encode('utf-16-be').hex()}>"
                      for index, char in enumerate(text, 1))
    mapping.set_data(("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
                      "1 begincodespacerange <0000> <ffff> endcodespacerange\n"
                      f"{len(text)} beginbfchar\n{pairs}\nendbfchar\n"
                      "endcmap CMapName currentdict /CMap defineresource pop end end").encode())
    cid = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/CIDFontType0"),
                            NameObject("/BaseFont"): NameObject("/STSong-Light")})
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type0"),
                             NameObject("/BaseFont"): NameObject("/STSong-Light"),
                             NameObject("/Encoding"): NameObject("/Identity-H"),
                             NameObject("/DescendantFonts"): ArrayObject([writer._add_object(cid)]),
                             NameObject("/ToUnicode"): writer._add_object(mapping)})
    page["/Resources"]["/Font"][NameObject("/F1")] = writer._add_object(font)
    stream = DecodedStreamObject()
    encoded = "".join(f"{index:04x}" for index in range(1, len(text) + 1))
    stream.set_data(f"BT /F1 12 Tf 40 700 Td <{encoded}> Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    # Resume minimum is 40 characters, append a normal textual page as well.
    merged = PdfWriter(io.BytesIO(output.getvalue()))
    merged.append(io.BytesIO(make_pdf()))
    output = io.BytesIO()
    merged.write(output)
    resume = parse_pdf(output.getvalue())
    assert text in [b.text for s in resume.sections for b in s.blocks]


@pytest.mark.parametrize("raw,code", [
    (b"%PDF-1.7\nbroken", "CORRUPT_PDF"),
    (make_pdf(encrypted=True), "ENCRYPTED_PDF"),
    (make_pdf(9), "PAGE_LIMIT"),
    (make_pdf(image_page=True), "PDF_TEXT_REQUIRED"),
    (make_pdf(2, image_page=True), "PDF_TEXT_REQUIRED"),
])
def test_unreadable_pdf_never_returns_partial_success(raw, code):
    with pytest.raises(Problem, match=code):
        parse_pdf(raw)


@pytest.mark.parametrize("drawing", [b"q BI /W 1 /H 1 /BPC 8 /CS /RGB ID \x00\x00\x00 EI Q",
                                     b"0 0 100 100 re S"])
def test_nontext_page_with_inline_image_or_vector_content_is_not_silently_omitted(drawing):
    writer = PdfWriter(io.BytesIO(make_pdf()))
    page = writer.add_blank_page(width=595, height=842)
    stream = DecodedStreamObject()
    stream.set_data(drawing)
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(Problem, match="PDF_TEXT_REQUIRED"):
        parse_pdf(output.getvalue())


@pytest.mark.parametrize("name,raw,expected", [
    ("resume.DOCX", make_docx(), "docx"),
    ("resume.PDF", make_pdf(), "pdf"),
    ("resume.doc", bytes.fromhex("d0cf11e0a1b11ae1"), "doc"),
    ("resume.pdf", make_docx(), "FORMAT_MISMATCH"),
    ("resume.docx", make_pdf(), "FORMAT_MISMATCH"),
    ("resume.doc", b"{\\rtf1", "FORMAT_MISMATCH"),
    ("resume.exe", make_pdf(), "UNSUPPORTED_FORMAT"),
])
def test_upload_format_uses_extension_and_signature(name, raw, expected):
    if expected in {"docx", "pdf", "doc"}:
        assert upload_format(name, raw) == expected
    else:
        with pytest.raises(Problem, match=expected):
            upload_format(name, raw)


async def test_pdf_api_routes_to_sandbox_then_review_and_purge(client):
    c, app = client
    raw = make_pdf()
    resume = parse_pdf(raw)
    calls = []

    def isolated(request):
        calls.append(str(request.url))
        assert request.content == raw
        return httpx.Response(200, json={"pages": 1, "resume": resume.model_dump()})

    await app.state.pagecheck.http.aclose()
    app.state.pagecheck.http = httpx.AsyncClient(base_url="http://pagecheck",
                                               transport=httpx.MockTransport(isolated))
    result = await c.post("/api/sessions", files={"file": ("fictional.pdf", raw)},
                          data={"jd": JD, "consent": "true"})
    assert result.status_code == 201, result.text
    session = result.json()
    assert calls == ["http://pagecheck/extract?format=pdf"]
    assert session["state"] == "parsed" and not session["suggestions"]
    assert session["resume"]["page_count_verified"]
    sid = session["id"]
    stored = app.state.store.directory(sid) / "raw.docx"
    assert stored.read_bytes().startswith(b"AIRESUME1:")
    assert app.state.store._read_private(stored) == raw
    assert (await c.delete(f"/api/sessions/{sid}")).status_code == 204
    assert not app.state.store.directory(sid).exists()


@pytest.mark.parametrize("payload", [{"pages": 1}, {"pages": 1, "resume": {}},
                                    {"pages": 1, "resume": {"sections": []}}])
async def test_extract_client_does_not_accept_incomplete_result(payload):
    checker = PageChecker("unused", httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(Problem, match="PAGECHECK_UNAVAILABLE"):
            await checker.extract(make_pdf(), "pdf")
    finally:
        await checker.close()


@pytest.mark.parametrize("code", ["ENCRYPTED_PDF", "PDF_TEXT_REQUIRED", "CORRUPT_PDF"])
async def test_pdf_rejection_does_not_create_session_or_cookie(client, code):
    c, app = client
    await app.state.pagecheck.http.aclose()
    app.state.pagecheck.http = httpx.AsyncClient(base_url="http://pagecheck", transport=
        httpx.MockTransport(lambda r: httpx.Response(422, json={"code": code, "private": "secret"})))
    result = await c.post("/api/sessions", files={"file": ("fictional.pdf", make_pdf())},
                          data={"jd": JD, "consent": "true"})
    assert result.status_code == 422 and result.json()["code"] == code
    assert "secret" not in result.text and "set-cookie" not in result.headers
    assert not list(app.state.store.root.iterdir())
