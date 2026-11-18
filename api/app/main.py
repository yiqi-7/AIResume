import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .documents import export_docx, final_resume, parse_docx
from .llm import PROVIDERS, ModelClient
from .metadata import Metadata
from .pagecheck import PageChecker
from .schemas import AnalyzeRequest, FactAnswer, Problem, Session, Suggestion, SuggestionEdit
from .storage import Store
from .uploads import MAX_BODY_BYTES, upload_form

logger = logging.getLogger("resume.events")


def public_session(session: Session):
    return session.model_dump(exclude={
        "auth_hash", "ip_key", "charged", "analysis_attempts", "answer_attempts"
    })


def create_app(settings: Settings | None = None, model_transport=None, pagecheck_transport=None):
    settings = settings or Settings()
    metadata = Metadata(settings)
    store = Store(settings, metadata)
    model = ModelClient(settings, metadata, transport=model_transport)
    pagecheck = PageChecker(settings.pagecheck_socket, transport=pagecheck_transport)
    upload_slots = asyncio.BoundedSemaphore(settings.max_active_uploads)

    async def sweeper():
        while True:
            await asyncio.sleep(60)
            try:
                await store.sweep()
            except Exception:
                logger.error(json.dumps({"event": "sweep_failed"}))

    @asynccontextmanager
    async def lifespan(app):
        await metadata.start()
        await store.start()
        cleanup = asyncio.create_task(sweeper())
        yield
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
        await store.close()
        await model.close()
        await pagecheck.close()
        await metadata.close()

    app = FastAPI(title="AIResume", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs" if settings.environment == "development" else None,
                  redoc_url=None, openapi_url="/api/openapi.json"
                  if settings.environment == "development" else None)
    app.state.store, app.state.model, app.state.settings = store, model, settings
    app.state.metadata = metadata
    app.state.pagecheck = pagecheck
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Resume-Client", "X-LLM-Key", "Authorization"],
    )

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        request_id = secrets.token_hex(8)
        upload_reserved = False
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (
                request.headers.get("x-resume-client") != "web"
                or (origin and origin not in settings.allowed_origins)
                or request.headers.get("sec-fetch-site") == "cross-site"
            ):
                return JSONResponse(
                    {"code": "ORIGIN_REJECTED", "message": "请求来源无效，请从本站页面重试。"},
                    status_code=403,
                )
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
                return JSONResponse(
                    {"code": "BODY_TOO_LARGE", "message": "上传内容超过大小限制。"},
                    status_code=413,
                )
            received = 0
            original_receive = request._receive

            async def receive():
                nonlocal received
                message = await original_receive()
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    request.state.body_too_large = True
                    raise Problem("BODY_TOO_LARGE", "上传内容超过大小限制。", 413)
                return message
            request._receive = receive
        if request.method == "POST" and request.url.path == "/api/sessions":
            if upload_slots.locked():
                return JSONResponse(
                    {"code": "BUSY", "message": "正在读取其他简历，请稍后重试上传。"},
                    status_code=429,
                )
            await upload_slots.acquire()
            upload_reserved = True
        try:
            response = await call_next(request)
        except Problem as exc:
            response = JSONResponse(
                {"code": exc.code, "message": exc.message}, status_code=exc.status
            )
        except Exception:
            # Never serialize upstream exceptions, request bodies, headers, or local paths.
            if not getattr(request.state, "body_too_large", False):
                logger.error(json.dumps({"event": "request_failed", "request_id": request_id}))
            response = JSONResponse(
                {"code": "SERVER_ERROR", "message": "处理暂时失败，请稍后重试。"},
                status_code=503,
            )
        finally:
            if upload_reserved:
                upload_slots.release()
        if getattr(request.state, "body_too_large", False):
            response = JSONResponse(
                {"code": "BODY_TOO_LARGE", "message": "上传内容超过大小限制。"}, status_code=413,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        return JSONResponse(
            {"code": "INVALID_INPUT", "message": "提交内容不完整或格式不正确，请检查后重试。"},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request, exc):
        return JSONResponse(
            {"code": "INVALID_REQUEST", "message": "请求格式不正确或内容超过限制。"},
            status_code=exc.status_code,
        )

    async def authenticated(sid: str, request: Request):
        await store.authorize(sid, request.cookies.get(settings.cookie_name))
        return await store.read(sid)

    def set_cookie(response: Response, token: str):
        response.set_cookie(
            settings.cookie_name, token, httponly=True, secure=settings.secure_cookie,
            samesite="strict", path="/api", max_age=settings.hard_seconds,
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/api/config")
    async def configuration():
        return {
            "station_configured": bool(settings.llm_base_url and settings.llm_model
                                       and settings.llm_api_key.get_secret_value()),
            "providers": [{"id": k, "name": v["name"]} for k, v in PROVIDERS.items()],
            "upload_bytes": settings.upload_bytes,
            "idle_seconds": settings.idle_seconds,
            "hard_seconds": settings.hard_seconds,
            "development": settings.environment == "development",
        }

    @app.get("/api/session")
    async def current(request: Request, response: Response):
        token = request.cookies.get(settings.cookie_name)
        if not token:
            return {"session": None}
        try:
            sid = token.split(".", 1)[0]
            session = await authenticated(sid, request)
            return {"session": public_session(session)}
        except Problem:
            response.delete_cookie(settings.cookie_name, path="/api")
            return {"session": None}

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: Request, response: Response):
        async with upload_form(request, settings.upload_bytes, settings.jd_bytes + 1024,
                               settings.upload_timeout) as form:
            upload = form.get("file")
            jd = form.get("jd")
            consent = form.get("consent")
            if consent != "true":
                raise Problem("CONSENT_REQUIRED", "请先阅读并确认本次数据处理说明。", 422)
            if not hasattr(upload, "read") or not isinstance(jd, str):
                raise Problem("MATERIAL_REQUIRED", "请上传 DOCX 并粘贴目标岗位描述。", 422)
            if len(jd.strip()) < 40:
                raise Problem("JD_TOO_SHORT", "岗位描述太短，请补充岗位职责和任职要求。", 422)
            if len(jd.encode("utf-8")) > settings.jd_bytes:
                raise Problem("JD_TOO_LONG", "岗位描述超过 2 MB，请仅保留本岗位的职责与要求。", 413)
            name = getattr(upload, "filename", "") or ""
            if not name.casefold().endswith(".docx"):
                raise Problem("INVALID_DOCX", "目前仅支持 DOCX 文件。", 415)
            raw = bytearray()
            while chunk := await upload.read(65536):
                raw.extend(chunk)
                if len(raw) > settings.upload_bytes:
                    raise Problem("FILE_TOO_LARGE", "简历超过 5 MB，请精简后重试。", 413)
            resume = await asyncio.to_thread(parse_docx, bytes(raw))
            chars = sum(len(b.text) for s in resume.sections for b in s.blocks) + len(jd)
            if chars > settings.max_analysis_chars:
                raise Problem(
                    "CONTEXT_TOO_LONG",
                    "材料超出当前模型处理范围，请精简 JD 或简历；系统不会静默截断。", 422
                )
            resume.rendered_pages = await pagecheck.count(bytes(raw))
            resume.page_count_verified = True
            resume.warnings.append("页数按服务器排版结果校验，可能与本机 Word 的字体和分页不同。")
            ip = request.client.host if request.client else "unknown"
            ip_key = hmac.new(
                settings.ip_salt.get_secret_value().encode(), ip.encode(), hashlib.sha256
            ).hexdigest()
            session, cookie = await store.create(bytes(raw), resume, jd.strip(), ip_key)
        set_cookie(response, cookie)
        await metadata.stat("session_started")
        await metadata.stat("parse_ok")
        return public_session(session)

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str, request: Request):
        return public_session(await authenticated(sid, request))

    @app.post("/api/sessions/{sid}/touch")
    async def touch(sid: str, request: Request):
        await store.authorize(sid, request.cookies.get(settings.cookie_name))
        async with store.lock(sid):
            session = await store.read(sid)
            await store.write(session, touch=True)
        return {"expires_at": session.expires_at}

    async def run_analysis(sid: str, credentials, dimensions):
        async def run_dimension(dimension, snapshot):
            try:
                items = await model.dimension(dimension, snapshot, credentials)
                status = "complete"
                error = None
            except Problem as exc:
                items, status, error = [], "failed", exc.code
            async with store.lock(sid):
                session = await store.read(sid)
                session.dimensions[dimension] = status
                session.suggestions.extend(
                    Suggestion(**item.model_dump(), id=secrets.token_hex(8),
                               dimension=dimension) for item in items
                )
                if error:
                    session.error = error
                await store.write(session)
            return status

        try:
            snapshot = await store.read(sid)
            async with asyncio.timeout(settings.task_timeout):
                await asyncio.gather(
                    *(run_dimension(d, snapshot) for d in dimensions)
                )
            async with store.lock(sid):
                session = await store.read(sid)
                completed = sum(status == "complete" for status in session.dimensions.values())
                session.state = "ready" if completed == 3 else "partial" if completed else "failed"
                section_weights = {"experience": 3, "projects": 3, "education": 2, "skills": 1}
                positions = {b.id: (section_weights.get(s.kind, 0), i)
                             for s in session.resume.sections for i, b in enumerate(s.blocks)}
                session.suggestions.sort(key=lambda item: (
                    item.priority,
                    -positions.get(item.target_block_id, (0, 0))[0],
                    positions.get(item.target_block_id, (0, 0))[1],
                ))
                session.revision += 1
                await store.write(session)
                await metadata.stat("analyze_" + session.state)
                await metadata.stat("suggestion_shown", len(session.suggestions))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with store.lock(sid):
                try:
                    session = await store.read(sid)
                    session.state = "failed"
                    session.error = "MODEL_TIMEOUT" if isinstance(exc, TimeoutError) else "ANALYSIS_FAILED"
                    await store.write(session)
                except Problem:
                    pass
            await metadata.stat("analyze_failed")
        finally:
            if store.jobs.get(sid) is asyncio.current_task():
                store.jobs.pop(sid, None)

    @app.post("/api/sessions/{sid}/analyze", status_code=202)
    async def analyze(sid: str, data: AnalyzeRequest, request: Request,
                      x_llm_key: str | None = Header(default=None)):
        await store.authorize(sid, request.cookies.get(settings.cookie_name))
        credentials = model.resolve(data.provider, data.model, x_llm_key)
        async with store.job_guard:
            async with store.lock(sid):
                session = await store.read(sid)
                if sid in store.jobs or session.state == "ready":
                    return public_session(session)
                dimensions = [
                    dimension for dimension in ["structure", "content", "relevance"]
                    if session.dimensions.get(dimension) != "complete"
                ]
                if not dimensions:
                    return public_session(session)
                if len(store.jobs) >= settings.max_active_jobs:
                    raise Problem("BUSY", "当前正在处理其他简历，请稍后重试。", 429)
                if session.analysis_attempts >= 3:
                    raise Problem("RETRY_LIMIT", "本次会话分析重试已达上限，请结束后重新开始。", 429)
                if not session.charged:
                    await metadata.reserve_analysis(session.ip_key, credentials[3])
                    session.charged = True
                session.state, session.error = "analyzing", None
                session.analysis_attempts += 1
                for dimension in dimensions:
                    session.dimensions[dimension] = "analyzing"
                await store.write(session, touch=True)
                store.jobs[sid] = asyncio.create_task(run_analysis(sid, credentials, dimensions))
        return public_session(session)

    @app.patch("/api/sessions/{sid}/suggestions/{gid}")
    async def edit_suggestion(sid: str, gid: str, data: SuggestionEdit, request: Request):
        await store.authorize(sid, request.cookies.get(settings.cookie_name))
        async with store.lock(sid):
            session = await store.read(sid)
            if session.state not in {"ready", "partial"}:
                raise Problem("NOT_READY", "请等待当前分析完成。", 409)
            if data.revision != session.revision:
                raise Problem("REVISION_CONFLICT", "这份简历已在其他页面更新，请刷新后继续。", 409)
            item = next((i for i in session.suggestions if i.id == gid), None)
            if not item:
                raise Problem("NOT_FOUND", "没有找到这条建议。", 404)
            if data.action in {"accept", "edit"}:
                if item.needs_fact or not item.rewrite:
                    raise Problem("FACT_REQUIRED", "请先补充真实信息并生成改写。", 422)
                if not data.confirmed_facts:
                    raise Problem("CONFIRM_FACTS", "采纳前请确认改写内容符合你的真实经历。", 422)
                if item.target_block_id and any(
                    other.id != item.id and other.target_block_id == item.target_block_id
                    and other.decision == "accepted" for other in session.suggestions
                ):
                    raise Problem("BLOCK_CONFLICT", "这段已有其他改写，请先撤销原建议再采纳这一条。", 409)
                if data.text is not None:
                    if not data.text.strip():
                        raise Problem("EMPTY_REWRITE", "改写内容不能为空。", 422)
                    item.edited_text = data.text.strip()
                item.decision = "accepted"
                await metadata.stat("suggestion_accepted")
            elif data.action == "skip":
                item.decision = "skipped"
            else:
                item.decision = "pending"
                item.edited_text = None
            session.revision += 1
            await store.write(session, touch=True)
        return public_session(session)

    async def run_answer(sid, gid, data, credentials):
        try:
            session = await store.read(sid)
            item = next(i for i in session.suggestions if i.id == gid)
            async with asyncio.timeout(settings.task_timeout):
                rewrite = await model.answer(session, item, data.answer, credentials)
            async with store.lock(sid):
                session = await store.read(sid)
                item = next(i for i in session.suggestions if i.id == gid)
                item.rewrite, item.user_fact = rewrite, data.answer
                item.target_block_id, item.target_section_id = None, data.section_id
                item.needs_fact = False
                session.state = (
                    "ready" if all(v == "complete" for v in session.dimensions.values())
                    else "partial"
                )
                session.error = None
                session.revision += 1
                await store.write(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with store.lock(sid):
                try:
                    session = await store.read(sid)
                    session.state = (
                        "ready" if all(v == "complete" for v in session.dimensions.values())
                        else "partial"
                    )
                    session.error = exc.code if isinstance(exc, Problem) else "ANSWER_FAILED"
                    await store.write(session)
                except Problem:
                    pass
        finally:
            if store.jobs.get(sid) is asyncio.current_task():
                store.jobs.pop(sid, None)

    @app.post("/api/sessions/{sid}/suggestions/{gid}/answer", status_code=202)
    async def answer(sid: str, gid: str, data: FactAnswer, request: Request,
                     x_llm_key: str | None = Header(default=None)):
        await store.authorize(sid, request.cookies.get(settings.cookie_name))
        if not data.confirmed:
            raise Problem("CONFIRM_FACTS", "请确认补充的信息真实。", 422)
        credentials = model.resolve(data.provider, data.model, x_llm_key)
        async with store.job_guard:
            async with store.lock(sid):
                session = await store.read(sid)
                if sid in store.jobs:
                    raise Problem("BUSY", "请等待当前处理完成。", 409)
                if len(store.jobs) >= settings.max_active_jobs:
                    raise Problem("BUSY", "当前服务繁忙，请稍后重试。", 429)
                item = next((i for i in session.suggestions if i.id == gid), None)
                if not item or not item.needs_fact:
                    raise Problem("NOT_FOUND", "这条建议目前不需要补充信息。", 404)
                if data.section_id not in {s.id for s in session.resume.sections}:
                    raise Problem("INVALID_SECTION", "请选择一个现有简历章节。", 422)
                attempts = session.answer_attempts.get(gid, 0)
                if attempts >= 3:
                    raise Problem("RETRY_LIMIT", "这条补充的改写重试已达上限，可以跳过。", 429)
                session.answer_attempts[gid] = attempts + 1
                session.state, session.error = "answering", None
                await store.write(session, touch=True)
                store.jobs[sid] = asyncio.create_task(run_answer(sid, gid, data, credentials))
        return public_session(session)

    @app.get("/api/sessions/{sid}/preview")
    async def preview(sid: str, request: Request):
        async with store.lock(sid):
            session = await authenticated(sid, request)
            return final_resume(session)

    @app.post("/api/sessions/{sid}/export")
    async def export(sid: str, request: Request):
        async with store.lock(sid):
            session = await authenticated(sid, request)
            if session.state not in {"ready", "partial"}:
                raise Problem("NOT_READY", "请先完成分析，再导出简历。", 409)
            await metadata.stat("export_started")
            try:
                raw = await asyncio.to_thread(export_docx, final_resume(session))
            except Exception:
                await metadata.stat("export_failed")
                raise Problem("EXPORT_FAILED", "文档生成失败，你的修改仍保留在会话中，请重试。", 503)
        await metadata.stat("export_succeeded")
        return Response(
            raw,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="resume.docx"'},
            background=BackgroundTask(store.purge, sid, "exported"),
        )

    @app.delete("/api/sessions/{sid}", status_code=204)
    async def end(sid: str, request: Request, response: Response):
        try:
            await authenticated(sid, request)
        except Problem:
            # Do not allow an unauthenticated request to purge an existing session.
            response.delete_cookie(settings.cookie_name, path="/api")
            return
        await store.purge(sid)
        response.delete_cookie(settings.cookie_name, path="/api")

    @app.get("/admin/stats")
    async def stats(authorization: str | None = Header(default=None)):
        expected = settings.admin_token.get_secret_value()
        if not expected or not hmac.compare_digest(authorization or "", "Bearer " + expected):
            raise Problem("NOT_FOUND", "页面不存在。", 404)
        return {"date_utc": metadata.day, "counters": await metadata.stats()}

    @app.post("/admin/cleanup")
    async def cleanup(authorization: str | None = Header(default=None)):
        expected = settings.admin_token.get_secret_value()
        if not expected or not hmac.compare_digest(authorization or "", "Bearer " + expected):
            raise Problem("NOT_FOUND", "页面不存在。", 404)
        await store.sweep()
        return {"status": "ok"}

    return app


app = create_app()
