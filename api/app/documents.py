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
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
SECTION_NAMES = [
    ("education", {"教育", "教育背景", "教育经历", "教育信息", "学历", "学历背景", "学历信息",
                   "education", "educationalbackground"}),
    ("experience", {"实习", "实习经历", "实习经验", "工作", "工作经历", "工作经验", "任职经历",
                    "实习与工作经历", "工作与实习经历", "职业经历", "experience", "workexperience",
                    "internshipexperience", "employment", "employmenthistory"}),
    ("projects", {"项目", "项目经历", "项目经验", "科研经历", "科研项目", "project", "projects",
                  "projectexperience", "selectedprojects"}),
    ("skills", {"技能", "证书", "个人技能", "专业技能", "相关技能", "技术技能", "技能特长",
                "技能证书", "技能与证书", "skills", "technicalskills", "certification",
                "certifications"}),
    ("contact", {"基本信息", "个人信息", "联系方式", "联系信息", "contact", "contactinformation"}),
    ("other", {"自我评价", "个人评价", "个人简介", "校园经历", "荣誉", "荣誉奖项", "获奖情况",
               "其他", "summary", "awards", "honors"}),
]


def visible_children(element):
    """Use one textual AlternateContent representation, never both copies."""
    for child in element:
        if child.tag == MC + "AlternateContent":
            choices = list(child)
            chosen = next((c for c in choices if c.find(".//" + W + "txbxContent")
                           is not None), None)
            if chosen is None:
                chosen = choices[0] if choices else None
            if chosen is not None:
                yield from visible_children(chosen)
        else:
            yield child


def paragraph_parts(paragraph):
    """Split anchored text boxes into paragraphs at their XML anchor position."""
    pieces = []

    def walk(element):
        for child in visible_children(element):
            if child.tag == W + "txbxContent":
                if pieces:
                    yield "".join(pieces), False
                    pieces.clear()
                yield from story_parts(child)
            elif child.tag == W + "t":
                pieces.append(child.text or "")
            elif child.tag == W + "tab":
                pieces.append("\t")
            elif child.tag in {W + "br", W + "cr"}:
                pieces.append("\n")
            else:
                yield from walk(child)

    yield from walk(paragraph)
    if pieces:
        yield "".join(pieces), paragraph.find(".//" + W + "numPr") is not None


def story_parts(story):
    for child in visible_children(story):
        if child.tag == W + "p":
            yield from paragraph_parts(child)
        elif child.tag == W + "tbl":
            for row in child.findall(W + "tr"):
                cells = ["\n".join(text.strip() for text, _ in story_parts(cell)
                                   if text.strip()) for cell in row.findall(W + "tc")]
                yield " | ".join(cell for cell in cells if cell), False
        elif any((node.text or "").strip() for node in child.iter(W + "t")):
            raise Problem("STRUCTURE_UNSUPPORTED",
                          "检测到当前无法完整读取的正文结构，请转换为普通段落或表格后重试。", 422)


def resume_from_parts(parts, warnings=None, estimated_pages=None):
    sections = [Section(id="sec_contact", kind="contact", title="基本信息", blocks=[])]
    block_index, total = 0, 0
    for text, is_bullet in parts:
        text = text.strip()
        if not text:
            continue
        if len(text) > 12000:
            raise Problem("PARAGRAPH_TOO_LONG", "单段文字过长，请先整理简历内容。", 422)
        total += len(text)
        if total > 30000:
            raise Problem("CONTEXT_TOO_LONG", "简历文字超过处理范围，请精简后重试；系统不会静默截断。", 422)
        heading_kind = next(
            (kind for kind, names in SECTION_NAMES
             if re.sub(r"\s+", "", text).strip(":：").casefold() in names), None
        )
        if heading_kind:
            sections.append(Section(id=f"sec_{len(sections)}", kind=heading_kind,
                                    title=text, blocks=[]))
        else:
            block_index += 1
            sections[-1].blocks.append(Block(id=f"b{block_index}", text=text,
                                            kind="bullet" if is_bullet else "paragraph"))
    if sum(len(b.text) for s in sections for b in s.blocks) < 40:
        raise Problem("EMPTY_RESUME", "读取到的文字太少，请确认文件中包含可选择的简历正文。", 422)
    return Resume(sections=[s for s in sections if s.blocks],
                  warnings=list(dict.fromkeys(warnings or [])), estimated_pages=estimated_pages)


def upload_format(name: str, raw: bytes) -> str:
    suffix = Path(name).suffix.casefold()
    if suffix not in {".docx", ".doc", ".pdf"}:
        raise Problem("UNSUPPORTED_FORMAT", "请上传 DOC、DOCX 或可复制文字的 PDF 文件。", 415)
    matches = {".docx": raw.startswith(b"PK\x03\x04"),
               ".doc": raw.startswith(bytes.fromhex("d0cf11e0a1b11ae1")),
               ".pdf": raw.startswith(b"%PDF-")}
    if not matches[suffix]:
        raise Problem("FORMAT_MISMATCH", "文件内容与扩展名不符，请使用 Word 或 PDF 的原始文件重新上传。", 415)
    return suffix[1:]


def parse_docx(raw: bytes) -> Resume:
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise Problem("INVALID_DOCX", "请上传有效且未加密的 DOCX 文件。", 415)
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
            # The text and safety checks below must inspect the actual main part,
            # not a harmless decoy while python-docx opens a relocated document.
            package_rels = SafeET.fromstring(archive.read("_rels/.rels"))
            main_parts = [rel for rel in package_rels
                          if rel.attrib.get("Type", "").endswith("/officeDocument")]
            if (len(main_parts) != 1
                    or main_parts[0].attrib.get("Target") not in {
                        "word/document.xml", "/word/document.xml"}
                    or main_parts[0].attrib.get("TargetMode", "").casefold() == "external"):
                raise Problem(
                    "STRUCTURE_UNSUPPORTED",
                    "文档使用了非标准正文结构，请在 Word 中另存为普通 DOCX 后重试。", 422,
                )
            document_xml = archive.read("word/document.xml")
            root = SafeET.fromstring(document_xml)
            # Never resolve external relationships, including linked images.
            for name in names:
                if name.endswith(".rels"):
                    SafeET.fromstring(archive.read(name))
            warnings = []
            for name in names:
                if re.fullmatch(r"word/(?:header|footer)\d+\.xml", name):
                    story = SafeET.fromstring(archive.read(name))
                    if any((element.text or "").strip() for element in story.iter(W + "t")):
                        warnings.append("页眉或页脚中的文字未作为简历正文读取；请核对姓名与联系方式，必要时放入正文后重传。")
                        break
            if root.findall(".//" + W + "txbxContent"):
                warnings.append("已读取文本框内容，按其在正文中的锚点排列；请核对姓名、联系方式与经历顺序。")
            columns = root.findall(".//" + W + "cols")
            if any(int(c.attrib.get(W + "num", "1")) > 1 for c in columns):
                warnings.append("原简历使用分栏，请核对提取顺序；导出会统一为单栏。")
            if root.findall(".//" + W + "drawing") or root.findall(".//" + W + "pict"):
                warnings.append("图片和照片不会进入导出文件，请确认经历信息均已写在正文里。")
            page_estimate = None
            if "docProps/app.xml" in names:
                app = SafeET.fromstring(archive.read("docProps/app.xml"))
                for element in app.iter():
                    if element.tag.endswith("}Pages") and (element.text or "").isdigit():
                        page_estimate = int(element.text)
        if root.find(".//" + W + "tbl") is not None:
            warnings.append("已将表格内容按行提取；请核对单位、日期与经历的对应关系。")
        body = root.find(W + "body")
        if body is None:
            raise ValueError("Missing body")
        return resume_from_parts(story_parts(body), warnings, page_estimate)
    except Problem:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, etree.XMLSyntaxError):
        raise Problem("CORRUPT_DOCX", "这份文档无法读取，请在 Word 中另存为 DOCX 后重试。", 422)
    except Exception:
        raise Problem("CORRUPT_DOCX", "这份文档无法完整读取，请另存为普通 DOCX 后重试。", 422)


def final_resume(session: Session) -> Resume:
    resume = session.resume.model_copy(deep=True)
    # The upload's pagination does not certify the edited, newly templated output.
    resume.estimated_pages = resume.rendered_pages = None
    resume.page_count_verified = False
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
