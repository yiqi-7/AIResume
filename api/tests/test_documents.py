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


def test_reject_invalid_zip_and_textboxes_but_do_not_trust_page_metadata():
    with pytest.raises(Problem, match="INVALID_DOCX"):
        parse_docx(b"not a docx")
    raw = make_docx()
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        xml = source.read("word/document.xml")
        app = source.read("docProps/app.xml")
    with pytest.raises(Problem, match="TEXTBOX_UNSUPPORTED"):
        parse_docx(replace_part(raw, "word/document.xml", xml.replace(
            b"<w:body>", b"<w:body><w:p><w:txbxContent/></w:p>")))
    resume = parse_docx(replace_part(raw, "docProps/app.xml", app.replace(b"<Pages>1</Pages>",
                                                                      b"<Pages>99</Pages>")))
    assert resume.estimated_pages == 99 and not resume.page_count_verified


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


def test_short_fact_lines_are_not_misclassified_as_section_headings():
    doc = Document(io.BytesIO(make_docx()))
    facts = ["参与教育产品项目研发", "熟悉办公软件，具备数据分析技能", "拥有英语六级证书"]
    for text in facts:
        doc.add_paragraph(text)
    doc.add_heading("专业技能", level=1)
    doc.add_paragraph("Python、SQL 与需求文档整理")
    output = io.BytesIO()
    doc.save(output)

    resume = parse_docx(output.getvalue())

    extracted = [block.text for section in resume.sections for block in section.blocks]
    assert all(text in extracted for text in facts)
    assert resume.sections[-1].kind == "skills"
    assert resume.sections[-1].blocks[0].text == "Python、SQL 与需求文档整理"


def test_runs_tabs_and_line_breaks_preserve_facts_in_body_and_table():
    doc = Document(io.BytesIO(make_docx()))
    paragraph = doc.add_paragraph()
    paragraph.add_run("2023\t2024\n负责需求整理")
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].add_run("20")
    cell.paragraphs[0].add_run("24 年 · Py")
    cell.paragraphs[0].add_run("thon")
    output = io.BytesIO()
    doc.save(output)

    resume = parse_docx(output.getvalue())

    extracted = [block.text for section in resume.sections for block in section.blocks]
    assert "2023\t2024\n负责需求整理" in extracted
    assert "2024 年 · Python" in extracted


def test_header_text_omission_is_disclosed_and_unknown_body_text_is_rejected():
    doc = Document(io.BytesIO(make_docx()))
    doc.sections[0].header.paragraphs[0].text = "虚构姓名 · fictional@example.invalid"
    output = io.BytesIO()
    doc.save(output)
    assert any("页眉或页脚" in warning for warning in parse_docx(output.getvalue()).warnings)
    raw = make_docx()
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        xml = package.read("word/document.xml")
    unknown = (b'<w:sdt><w:sdtContent><w:p><w:r><w:t>preserve this fact</w:t>'
               b'</w:r></w:p></w:sdtContent></w:sdt>')
    with pytest.raises(Problem, match="STRUCTURE_UNSUPPORTED"):
        parse_docx(replace_part(raw, "word/document.xml", xml.replace(b"<w:body>",
                                                                     b"<w:body>" + unknown)))
