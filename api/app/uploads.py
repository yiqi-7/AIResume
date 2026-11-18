import asyncio
from contextlib import asynccontextmanager

from fastapi import Request
from starlette.formparsers import MultiPartException, MultiPartParser

from .schemas import Problem

MAX_BODY_BYTES = 8 * 1024 * 1024


class BoundedMemoryParser(MultiPartParser):
    # The request middleware caps the whole body before the spool can reach disk.
    spool_max_size = MAX_BODY_BYTES

    def __init__(self, request: Request, file_limit: int, field_limit: int):
        super().__init__(request.headers, request.stream(), max_files=1, max_fields=3,
                         max_part_size=field_limit)
        self.file_limit = file_limit
        self.file_bytes = 0

    def on_part_begin(self):
        super().on_part_begin()
        self.file_bytes = 0

    def on_part_data(self, data: bytes, start: int, end: int):
        if self._current_part.file is not None:
            self.file_bytes += end - start
            if self.file_bytes > self.file_limit:
                raise Problem("FILE_TOO_LARGE", "简历超过 5 MB，请精简后重试。", 413)
        super().on_part_data(data, start, end)


@asynccontextmanager
async def upload_form(request: Request, file_limit: int, field_limit: int, timeout: float):
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise Problem("MATERIAL_REQUIRED", "请上传 Word 或 PDF 并粘贴目标岗位描述。", 422)
    parser = BoundedMemoryParser(request, file_limit, field_limit)
    form = None
    try:
        try:
            async with asyncio.timeout(timeout):
                form = await parser.parse()
        except MultiPartException:
            raise Problem("INVALID_FORM", "上传表单不完整或内容超过限制，请重新选择文件。", 422)
        except TimeoutError:
            raise Problem("UPLOAD_TIMEOUT", "上传耗时过长，请检查网络后重试。", 408)
        yield form
    finally:
        if form is not None:
            await form.close()
        # An incomplete final part is not added to FormData.items by the parser.
        for spool in parser._files_to_close_on_error:
            spool.close()
