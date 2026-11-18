"""Client for the private, separately sandboxed pagination service."""

import asyncio
import sys

import httpx

from .schemas import Problem, Resume

MAX_PAGES = 8
EXTRACTION_ERRORS = {
    "PAGE_LIMIT": "简历超过 8 页，请精简后重试。",
    "ENCRYPTED_PDF": "PDF 已加密，请移除密码后重新上传。",
    "PDF_TEXT_REQUIRED": "PDF 含有无法读取文字的页面。仅支持可复制文字的 PDF，暂不支持扫描件或图片型 PDF。",
    "PDF_TEXT_UNREADABLE": "PDF 的文字编码无法完整读取，请从原始 Word 重新导出 PDF。",
    "CORRUPT_PDF": "这份 PDF 无法完整读取，请从原始文档重新导出后重试。",
    "EMPTY_RESUME": "读取到的文字太少，请确认文件中包含可选择的简历正文。",
    "CONTEXT_TOO_LONG": "简历文字超过处理范围，请精简后重试；系统不会静默截断。",
    "PARAGRAPH_TOO_LONG": "单段文字过长，请先整理简历内容。",
    "STRUCTURE_UNSUPPORTED": "检测到无法完整读取的 Word 结构，请另存为普通 DOCX 后重试。",
    "CORRUPT_DOCX": "Word 转换结果无法完整读取，请另存为普通 DOCX 后重试。",
    "UNSAFE_DOCX": "Word 文件过于复杂或已加密，请另存为简洁的 DOCX。",
}


class PageChecker:
    def __init__(self, socket_path: str, transport=None):
        self.available = transport is not None or sys.platform == "linux"
        self.http = httpx.AsyncClient(
            base_url="http://pagecheck",
            transport=transport or httpx.AsyncHTTPTransport(uds=socket_path),
            timeout=35,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            trust_env=False,
        )

    async def count(self, raw: bytes) -> int:
        return (await self._request("/count", raw))["pages"]

    async def extract(self, raw: bytes, format: str) -> Resume:
        if format not in {"doc", "pdf"}:
            raise ValueError("Unsupported extraction format")
        payload = await self._request("/extract?format=" + format, raw)
        try:
            resume = Resume.model_validate(payload["resume"])
            chars = sum(len(b.text) for s in resume.sections for b in s.blocks)
            if not 40 <= chars <= 30000 or any(
                    not b.text.strip() or len(b.text) > 12000
                    for s in resume.sections for b in s.blocks):
                raise ValueError("Invalid extracted text")
            resume.rendered_pages = payload["pages"]
            resume.page_count_verified = True
            return resume
        except (ValueError, KeyError, TypeError):
            raise Problem("PAGECHECK_UNAVAILABLE", "文件读取服务暂不可用，材料尚未保存，请稍后重试。", 503) from None

    async def _request(self, path: str, raw: bytes) -> dict:
        try:
            if not self.available:
                raise ValueError("The isolated pagination service requires Linux")
            async with asyncio.timeout(35):
                response = await self.http.post(path, content=raw)
            if response.status_code == 429:
                raise Problem("PAGECHECK_BUSY", "正在读取其他简历，请稍后重试。", 429)
            if response.status_code == 422:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Invalid pagination response")
                code = payload.get("code")
                if code == "PAGE_LIMIT":
                    raise Problem("PAGE_LIMIT", "简历超过 8 页，请精简后重试。", 422)
                if code == "ACTIVE_CONTENT":
                    raise Problem(
                        "ACTIVE_CONTENT", "文件包含嵌入对象或外部资源，请另存为普通 Word 后重试。", 422,
                    )
                if code in EXTRACTION_ERRORS:
                    raise Problem(code, EXTRACTION_ERRORS[code], 422)
                raise Problem(
                    "PAGECHECK_FAILED", "无法完整读取文件或校验页数，请另存为普通 Word 或文字型 PDF 后重试。", 422,
                )
            response.raise_for_status()
            pages = response.json()["pages"]
            if type(pages) is not int or pages < 1:
                raise ValueError("Invalid page count")
            if pages > MAX_PAGES:
                raise Problem("PAGE_LIMIT", "服务器排版结果超过 8 页，请精简简历后重试。", 422)
            return response.json()
        except Problem:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            raise Problem(
                "PAGECHECK_UNAVAILABLE", "页数校验服务暂不可用，材料尚未保存，请稍后重试。", 503,
            ) from None

    async def close(self):
        await self.http.aclose()
