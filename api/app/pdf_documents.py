"""Text PDFs only. Run in the disposable, resource-bounded extraction process."""

import io

from pypdf import PdfReader

from .documents import resume_from_parts
from .schemas import Problem


def has_images(resources, seen=None):
    seen = seen if seen is not None else set()
    if not resources:
        return False
    objects = resources.get("/XObject", {})
    objects = objects.get_object() if hasattr(objects, "get_object") else objects
    for reference in objects.values():
        obj = reference.get_object()
        marker = id(obj)
        if marker in seen:
            continue
        seen.add(marker)
        if len(seen) > 1500:
            raise ValueError("Too many PDF objects")
        if obj.get("/Subtype") == "/Image":
            return True
        if obj.get("/Subtype") == "/Form" and has_images(obj.get("/Resources"), seen):
            return True
    return False


def parse_pdf(raw: bytes):
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise Problem("ENCRYPTED_PDF", "PDF 已加密，请移除密码后重新上传。", 422)
        pages = len(reader.pages)
        if not 1 <= pages <= 8:
            raise Problem("PAGE_LIMIT", "PDF 最多支持 8 页，请精简后重试。", 422)
        parts, total = [], 0
        for page in reader.pages:
            text = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False)
            if not text.strip() and (has_images(page.get("/Resources")) or page.get_contents()):
                raise Problem("PDF_TEXT_REQUIRED",
                              "PDF 含有无法读取文字的页面。仅支持可复制文字的 PDF，暂不支持扫描件或图片型 PDF。", 422)
            if any(char in text for char in ("\ufffd", "\x00")):
                raise Problem("PDF_TEXT_UNREADABLE", "PDF 的文字编码无法完整读取，请从原始 Word 重新导出 PDF。", 422)
            total += len(text)
            if total > 30000:
                raise Problem("CONTEXT_TOO_LONG", "简历文字超过处理范围，请精简后重试；系统不会静默截断。", 422)
            parts.extend((line, False) for line in text.splitlines())
        resume = resume_from_parts(parts, [
            "已读取 PDF 文字层，按页面位置提取；请核对分栏、表格、日期及换行顺序。",
            "图片和照片不参与分析或导出；图片内的文字不会被识别。",
        ])
        resume.rendered_pages, resume.page_count_verified = pages, True
        return resume
    except Problem:
        raise
    except Exception:
        raise Problem("CORRUPT_PDF", "这份 PDF 无法完整读取，请从原始文档重新导出后重试。", 422) from None
