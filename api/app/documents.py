import io
import json
import re
import zipfile
from pathlib import Path

from defusedxml import ElementTree as SafeET
from docx import Document
from docx.shared import Cm, Pt
from lxml import etree

from .schemas import Block, Problem, Resume, Section, Session

TEMPLATE = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "template.json").read_text()
)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SECTION_NAMES = [
    ("education", r"教育|学历|education"),
    ("experience", r"实习|工作经历|工作经验|任职|experience|employment"),
    ("projects", r"项目|project"),
    ("skills", r"技能|证书|skills|certificat"),
    ("contact", r"基本信息|个人信息|contact"),
    ("other", r"自我评价|个人评价|荣誉|其他|summary|awards"),
]


def parse_docx(raw: bytes) -> Resume:
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise Problem("INVALID_DOCX", "请上传未加密的 DOCX 文件；暂不支持 PDF、DOC 或图片。", 415)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 1500
                or sum(i.file_size for i in entries) > 40 * 1024 * 1024
                or any(i.flag_bits & 1 for i in entries)
            ):
                raise Problem("UNSAFE_DOCX", "这份文件过于复杂或已加密，请另存为简洁的 DOCX。", 422)
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise Problem("INVALID_DOCX", "文件不是有效的 Word DOCX 文档。", 422)
            document_xml = archive.read("word/document.xml")
            root = SafeET.fromstring(document_xml)
            # Never resolve external relationships, including linked images.
            for name in names:
                if name.endswith(".rels"):
                    SafeET.fromstring(archive.read(name))
            warnings = []
            if root.findall(".//" + W + "txbxContent"):
                raise Problem(
                    "TEXTBOX_UNSUPPORTED",
                    "检测到文本框，可能无法完整读取。请将文本框内容粘贴为普通正文后重新上传。",
                    422,
                )
            columns = root.findall(".//" + W + "cols")
            if any(int(c.attrib.get(W + "num", "1")) > 1 for c in columns):
                warnings.append("原简历使用分栏，请核对提取顺序；导出会统一为单栏。")
            if root.findall(".//" + W + "drawing"):
                warnings.append("图片和照片不会进入导出文件，请确认经历信息均已写在正文里。")
            page_estimate = None
            if "docProps/app.xml" in names:
                app = SafeET.fromstring(archive.read("docProps/app.xml"))
                for element in app.iter():
                    if element.tag.endswith("}Pages") and (element.text or "").isdigit():
                        page_estimate = int(element.text)
            if page_estimate and page_estimate > 8:
                raise Problem(
                    "PAGE_LIMIT_ESTIMATED",
                    "文件记录的页数超过 8 页。请精简，或在 Word 中重新保存以更新页数后再试。",
                    422,
                )
            if page_estimate is None:
                warnings.append("文件未提供页数信息。请自行确认原简历不超过 8 页。")
            else:
                warnings.append("页数来自文档元数据，仅供参考，并非重新排版后的准确页数。")
        # Load with python-docx only after bounding the decompressed package.
        doc = Document(io.BytesIO(raw))
        sections = [Section(id="sec_contact", kind="contact", title="基本信息", blocks=[])]
        block_index = 0
        for child in doc.element.body:
            if child.tag == W + "p":
                paragraphs = [child]
            elif child.tag == W + "tbl":
                warnings.append("已将表格内容按行提取；请核对单位、日期与经历的对应关系。")
                paragraphs = []
                for row in child.findall(W + "tr"):
                    cells = []
                    for cell in row.findall(W + "tc"):
                        cells.append(" ".join(t.text or "" for t in cell.iter(W + "t")))
                    text = " | ".join(c.strip() for c in cells if c.strip())
                    if text:
                        block_index += 1
                        sections[-1].blocks.append(
                            Block(id=f"b{block_index}", text=text, kind="paragraph")
                        )
                continue
            else:
                continue
            for paragraph in paragraphs:
                text = "".join(t.text or "" for t in paragraph.iter(W + "t")).strip()
                if not text:
                    continue
                if len(text) > 12000:
                    raise Problem("PARAGRAPH_TOO_LONG", "单段文字过长，请先整理简历内容。", 422)
                heading_kind = next(
                    (kind for kind, pattern in SECTION_NAMES
                     if len(text) <= 22 and re.search(pattern, text, re.I)), None
                )
                if heading_kind:
                    sections.append(
                        Section(id=f"sec_{len(sections)}", kind=heading_kind,
                                title=text, blocks=[])
                    )
                else:
                    block_index += 1
                    is_bullet = paragraph.find(".//" + W + "numPr") is not None
                    sections[-1].blocks.append(
                        Block(id=f"b{block_index}", text=text,
                              kind="bullet" if is_bullet else "paragraph")
                    )
        if sum(len(b.text) for s in sections for b in s.blocks) < 40:
            raise Problem("EMPTY_RESUME", "读取到的文字太少，请确认文件中包含可选择的简历正文。", 422)
        if not doc.paragraphs and not doc.tables:
            raise Problem("EMPTY_RESUME", "没有读取到简历正文。", 422)
        return Resume(
            sections=[s for s in sections if s.blocks],
            warnings=list(dict.fromkeys(warnings)),
            estimated_pages=page_estimate,
        )
    except Problem:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, etree.XMLSyntaxError):
        raise Problem("CORRUPT_DOCX", "这份文档无法读取，请在 Word 中另存为 DOCX 后重试。", 422)
    except Exception:
        raise Problem("CORRUPT_DOCX", "这份文档无法完整读取，请另存为普通 DOCX 后重试。", 422)


def final_resume(session: Session) -> Resume:
    resume = session.resume.model_copy(deep=True)
    blocks = {b.id: b for s in resume.sections for b in s.blocks}
    sections = {s.id: s for s in resume.sections}
    for item in session.suggestions:
        if item.decision != "accepted":
            continue
        text = item.edited_text if item.edited_text is not None else item.rewrite
        if item.target_block_id and item.target_block_id in blocks:
            blocks[item.target_block_id].text = text
        elif item.user_fact and item.target_section_id in sections:
            sections[item.target_section_id].blocks.append(
                Block(id="added_" + item.id, text=text, kind="bullet")
            )
    order = TEMPLATE["sectionOrder"]
    resume.sections.sort(key=lambda s: order.index(s.kind))
    return resume


def export_docx(resume: Resume) -> bytes:
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(TEMPLATE["pageWidthMm"] / 10)
    section.page_height = Cm(TEMPLATE["pageHeightMm"] / 10)
    section.top_margin = section.bottom_margin = Cm(TEMPLATE["marginMm"] / 10)
    section.left_margin = section.right_margin = Cm(TEMPLATE["marginMm"] / 10)
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(TEMPLATE["bodyPt"])
    normal.paragraph_format.line_spacing = TEMPLATE["lineHeight"]
    normal.paragraph_format.space_after = Pt(4)
    fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(W + "eastAsia", "等线")
    heading = document.styles["Heading 1"]
    heading.font.name = "Arial"
    heading.font.size = Pt(TEMPLATE["headingPt"])
    heading.font.bold = True
    heading.paragraph_format.space_before = Pt(10)
    heading.paragraph_format.space_after = Pt(5)
    heading.paragraph_format.keep_with_next = True
    heading.element.get_or_add_rPr().get_or_add_rFonts().set(W + "eastAsia", "等线")
    first_contact = True
    for group in resume.sections:
        if group.kind != "contact":
            document.add_heading(group.title, level=1)
        for block in group.blocks:
            paragraph = document.add_paragraph(
                block.text, style="List Bullet" if block.kind == "bullet" else "Normal"
            )
            if group.kind == "contact" and first_contact:
                first_contact = False
                if len(block.text) <= 24:
                    for run in paragraph.runs:
                        run.font.size = Pt(TEMPLATE["namePt"])
                        run.font.bold = True
            paragraph.paragraph_format.widow_control = True
    # Strip source metadata: generated files contain only the confirmed resume.
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.core_properties.title = "简历"
    document.core_properties.comments = ""
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()
