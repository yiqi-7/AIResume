import io
import zipfile

import pytest
from docx import Document

from app.documents import export_docx, final_resume, parse_docx
from app.schemas import Problem, Session, Suggestion


def make_docx():
    doc = Document()
    doc.add_paragraph("陈同学")
    doc.add_paragraph("应届毕业生，求职方向为产品经理，以下均为虚构测试内容。")
    doc.add_heading("项目经历", level=1)
    doc.add_paragraph("访谈同学并整理需求，梳理发布和检索流程，完成平台原型。")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def replace_part(raw, part, content):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(output, "w") as dest:
        for entry in source.infolist():
            dest.writestr(entry.filename, content if entry.filename == part else source.read(entry))
    return output.getvalue()


def test_parse_round_trip_and_source_is_untouched():
    resume = parse_docx(make_docx())
    assert [s.kind for s in resume.sections] == ["contact", "projects"]
    assert resume.page_count_verified is False
    block = resume.sections[1].blocks[0]
    session = Session(id="test", auth_hash="", ip_key="", expires_at=9999999999,
                      resume=resume, jd="虚构岗位")
    session.suggestions.append(Suggestion(
        id="one", dimension="content", title="写清行动", priority="P1",
        target_block_id=block.id, resume_quote=block.text, jd_quote="岗位",
        reason="表达更清楚", rewrite="围绕校园交易场景访谈同学，整理需求并完成平台原型。",
        decision="accepted",
    ))
    final = final_resume(session)
    assert final.sections[1].blocks[0].text != block.text
    assert session.resume.sections[1].blocks[0].text == block.text
    raw = export_docx(final)
    doc = Document(io.BytesIO(raw))
    assert final.sections[1].blocks[0].text in [p.text for p in doc.paragraphs]
    assert doc.core_properties.author == ""
    assert abs(doc.sections[0].page_width.mm - 210) < 0.1
    assert parse_docx(raw).sections[1].kind == "projects"


def test_reject_invalid_zip_and_textboxes_and_oversized_page_metadata():
    with pytest.raises(Problem, match="INVALID_DOCX"):
        parse_docx(b"not a docx")
    raw = make_docx()
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        xml = source.read("word/document.xml")
        app = source.read("docProps/app.xml")
    with pytest.raises(Problem, match="TEXTBOX_UNSUPPORTED"):
        parse_docx(replace_part(raw, "word/document.xml", xml.replace(
            b"<w:body>", b"<w:body><w:p><w:txbxContent/></w:p>")))
    with pytest.raises(Problem, match="PAGE_LIMIT_ESTIMATED"):
        parse_docx(replace_part(raw, "docProps/app.xml", app.replace(b"<Pages>1</Pages>",
                                                                  b"<Pages>9</Pages>")))


def test_table_rows_are_preserved_in_source_order():
    doc = Document(io.BytesIO(make_docx()))
    row = doc.add_table(rows=1, cols=2).rows[0]
    row.cells[0].text, row.cells[1].text = "测试大学", "计算机科学"
    doc.add_paragraph("表格之后的说明")
    output = io.BytesIO()
    doc.save(output)
    resume = parse_docx(output.getvalue())
    blocks = resume.sections[-1].blocks
    assert blocks[-2].text == "测试大学 | 计算机科学"
    assert blocks[-1].text == "表格之后的说明"
    assert any("表格" in warning for warning in resume.warnings)
