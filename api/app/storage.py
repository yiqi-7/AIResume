import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .metadata import Metadata
from .schemas import Problem, Resume, Session

logger = logging.getLogger("resume.events")


class Store:
    ENCRYPTED_PREFIX = b"AIRESUME1:"

    def __init__(self, settings: Settings, metadata: Metadata):
        self.settings, self.metadata = settings, metadata
        self.root = settings.data_dir.resolve()
        key = settings.data_encryption_key.get_secret_value()
        self.cipher = Fernet(key.encode("ascii")) if key else Fernet(Fernet.generate_key())
        self.locks: dict[str, asyncio.Lock] = {}
        self.lock_users: dict[str, int] = {}
        self.jobs: dict[str, asyncio.Task] = {}
        self.job_guard = asyncio.Lock()

    def directory(self, sid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise Problem("SESSION_GONE", "当前会话已结束，请重新上传。", 410)
        return self.root / sid

    @asynccontextmanager
    async def lock(self, sid: str):
        lock = self.locks.setdefault(sid, asyncio.Lock())
        self.lock_users[sid] = self.lock_users.get(sid, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self.lock_users[sid] -= 1
            if not self.lock_users[sid] and not self.directory(sid).exists():
                self.lock_users.pop(sid, None)
                self.locks.pop(sid, None)

    async def start(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self._migrate_plaintext()
        await self.sweep(recover=True)

    def _encode(self, value: bytes) -> bytes:
        return self.ENCRYPTED_PREFIX + self.cipher.encrypt(value)

    def _decode(self, value: bytes) -> bytes:
        if not value.startswith(self.ENCRYPTED_PREFIX):
            return value
        try:
            return self.cipher.decrypt(value[len(self.ENCRYPTED_PREFIX):])
        except InvalidToken as exc:
            raise ValueError("Stored session data cannot be decrypted") from exc

    def _read_private(self, path: Path) -> bytes:
        return self._decode(path.read_bytes())

    def _write_private(self, path: Path, value: bytes):
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes(self._encode(value))
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, path)

    def _migrate_plaintext(self):
        for directory in self.root.iterdir():
            if not directory.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", directory.name):
                continue
            for name in ("raw.docx", "session.json", "session.tmp"):
                path = directory / name
                try:
                    value = path.read_bytes()
                    if not value.startswith(self.ENCRYPTED_PREFIX):
                        self._write_private(path, value)
                except OSError:
                    continue

    async def create(self, raw: bytes, resume: Resume, jd: str, ip_key: str):
        sid, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        now = time.time()
        deadline = now + min(self.settings.idle_seconds, self.settings.hard_seconds)
        if not await self.metadata.claim_ip(ip_key, sid, math.ceil(deadline - now)):
            raise Problem(
                "ACTIVE_SESSION",
                "当前网络已有一个有效会话，请先结束原会话再开始。", 409
            )
        session = Session(
            id=sid, created_at=now, last_active=now, expires_at=deadline,
            auth_hash=hashlib.sha256(token.encode()).hexdigest(),
            ip_key=ip_key, resume=resume, jd=jd,
        )
        directory = self.directory(sid)
        reserved = False
        async with self.lock(sid):
            try:
                await self.metadata.reserve_session()
                reserved = True
                directory.mkdir(mode=0o700)
                self._write_private(directory / "raw.docx", raw)
                self._write(session)
                await self.save_metadata(session)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                if reserved:
                    await self.metadata.release_session()
                await self.metadata.release_ip(ip_key, sid)
                raise
        return session, sid + "." + token

    def _write(self, session: Session):
        directory = self.directory(session.id)
        if not directory.is_dir():
            raise Problem("SESSION_GONE", "当前会话已结束，请重新上传。", 410)
        temp = directory / "session.tmp"
        self._write_private(temp, session.model_dump_json().encode("utf-8"))
        os.replace(temp, directory / "session.json")

    async def save_metadata(self, session: Session):
        ttl = max(1, math.ceil(session.expires_at - time.time()))
        await self.metadata.set(
            "session:" + session.id,
            json.dumps({"auth_hash": session.auth_hash, "expires_at": session.expires_at,
                        "state": session.state, "revision": session.revision}),
            ttl,
        )

    async def read(self, sid: str) -> Session:
        path = self.directory(sid) / "session.json"
        try:
            session = Session.model_validate_json(self._read_private(path))
        except (OSError, ValueError):
            raise Problem("SESSION_GONE", "当前会话已结束，请重新上传。", 410)
        if session.expires_at <= time.time():
            raise Problem("SESSION_GONE", "会话已超时，材料正在清除，请重新上传。", 410)
        return session

    async def authorize(self, sid: str, cookie: str | None):
        self.directory(sid)
        try:
            cookie_sid, token = (cookie or "").split(".", 1)
        except ValueError:
            raise Problem("SESSION_GONE", "找不到有效会话，请重新上传。", 410)
        if not hmac.compare_digest(cookie_sid, sid):
            raise Problem("SESSION_GONE", "找不到有效会话，请重新上传。", 410)
        raw = await self.metadata.get("session:" + sid)
        if not raw:
            raise Problem("SESSION_GONE", "会话已结束或已超时，请重新上传。", 410)
        meta = json.loads(raw)
        if not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), meta["auth_hash"]
        ):
            raise Problem("SESSION_GONE", "找不到有效会话，请重新上传。", 410)

    async def write(self, session: Session, touch: bool = False):
        if touch:
            now = time.time()
            session.last_active = now
            session.expires_at = min(
                now + self.settings.idle_seconds,
                session.created_at + self.settings.hard_seconds,
            )
            if session.expires_at <= now:
                raise Problem("SESSION_GONE", "会话已超时，请重新上传。", 410)
            await self.metadata.refresh_ip(
                session.ip_key, session.id, math.ceil(session.expires_at - now)
            )
        # The session lock protects writes and purge in this single-worker app.
        self._write(session)
        await self.save_metadata(session)

    async def purge(self, sid: str, reason: str = "ended", expired_only: bool = False):
        path = self.directory(sid)
        pending_key = "purge-pending:" + sid
        async with self.lock(sid):
            if expired_only:
                try:
                    current = json.loads(self._read_private(path / "session.json"))
                    if float(current["expires_at"]) > time.time():
                        return
                except (OSError, ValueError, KeyError):
                    pass
            await self.metadata.delete("session:" + sid)
            job = self.jobs.get(sid)
            if job and job is not asyncio.current_task() and not job.done():
                job.cancel()
            ip_key = ""
            try:
                data = json.loads(self._read_private(path / "session.json"))
                ip_key = data["ip_key"]
            except (OSError, ValueError, KeyError):
                pass
            if path.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, path)
                except OSError:
                    await self.metadata.set(pending_key, reason, self.settings.hard_seconds + 3600)
                    logger.error(json.dumps({"event": "purge_failed", "reason": reason}))
                    raise Problem("CLEANUP_RETRY", "材料清理暂时失败，系统会继续重试。", 503)
            await self.metadata.delete(pending_key)
            if ip_key:
                await self.metadata.release_ip(ip_key, sid)
        await self.metadata.stat("purged")
        logger.info(json.dumps({"event": "session_purged", "reason": reason}))

    async def sweep(self, recover: bool = False):
        if not self.root.exists():
            return
        for path in self.root.iterdir():
            if not path.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", path.name):
                continue
            try:
                data = json.loads(self._read_private(path / "session.json"))
                expired = float(data["expires_at"]) <= time.time()
                if recover and self.settings.metadata_backend == "memory":
                    expired = True
                purge_reason = await self.metadata.get("purge-pending:" + path.name)
                if purge_reason:
                    await self.purge(path.name, purge_reason)
                elif expired:
                    await self.purge(path.name, "expired", expired_only=not recover)
                elif recover and data["state"] in {"analyzing", "answering"}:
                    async with self.lock(path.name):
                        session = await self.read(path.name)
                        session.state, session.error = "interrupted", "PROCESS_RESTARTED"
                        await self.write(session)
            except Problem:
                continue
            except (OSError, ValueError, KeyError):
                # Malformed directories have no usable content; a later sweep retries deletion.
                try:
                    await self.purge(path.name, "orphan")
                except Problem:
                    pass

    async def close(self):
        jobs = list(self.jobs.values())
        for task in jobs:
            task.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
