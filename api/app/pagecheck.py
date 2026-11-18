"""Client for the private, separately sandboxed pagination service."""

import asyncio
import sys

import httpx

from .schemas import Problem

MAX_PAGES = 8


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
        try:
            if not self.available:
                raise ValueError("The isolated pagination service requires Linux")
            async with asyncio.timeout(35):
                response = await self.http.post("/count", content=raw)
            if response.status_code == 429:
                raise Problem("PAGECHECK_BUSY", "正在校验其他简历的页数，请稍后重试。", 429)
            if response.status_code == 422:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Invalid pagination response")
                code = payload.get("code")
                if code == "PAGE_LIMIT":
                    raise Problem("PAGE_LIMIT", "服务器排版结果超过 8 页，请精简简历后重试。", 422)
                if code == "ACTIVE_CONTENT":
                    raise Problem(
                        "ACTIVE_CONTENT", "文件包含嵌入对象或外部资源，请另存为普通 DOCX 后重试。", 422,
                    )
                raise Problem(
                    "PAGECHECK_FAILED", "无法完成页数校验，请将简历另存为普通 DOCX 后重试。", 422,
                )
            response.raise_for_status()
            pages = response.json()["pages"]
            if type(pages) is not int or pages < 1:
                raise ValueError("Invalid page count")
            if pages > MAX_PAGES:
                raise Problem("PAGE_LIMIT", "服务器排版结果超过 8 页，请精简简历后重试。", 422)
            return pages
        except Problem:
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            raise Problem(
                "PAGECHECK_UNAVAILABLE", "页数校验服务暂不可用，材料尚未保存，请稍后重试。", 503,
            ) from None

    async def close(self):
        await self.http.aclose()
