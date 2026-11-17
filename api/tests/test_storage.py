import asyncio
import json
import time

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.documents import parse_docx
from app.metadata import Metadata
from app.schemas import Problem
from app.storage import Store
from tests.test_documents import make_docx


@pytest.fixture
async def store(tmp_path):
    settings = Settings(data_dir=tmp_path / "private", idle_seconds=20, hard_seconds=60)
    metadata = Metadata(settings)
    instance = Store(settings, metadata)
    await instance.start()
    yield instance
    await instance.close()


async def create(store, ip="ip-hash"):
    raw = make_docx()
    return await store.create(raw, parse_docx(raw), "虚构岗位内容", ip)


async def test_authentication_ip_lock_and_metadata_has_no_personal_content(store):
    session, cookie = await create(store)
    await store.authorize(session.id, cookie)
    with pytest.raises(Problem):
        await store.authorize(session.id, session.id + ".incorrect-secret")
    with pytest.raises(Problem, match="ACTIVE_SESSION"):
        await create(store)
    metadata_text = json.dumps(store.metadata.values, ensure_ascii=False)
    assert "陈同学" not in metadata_text and "虚构岗位" not in metadata_text
    assert cookie not in metadata_text
    await store.purge(session.id)
    assert not store.directory(session.id).exists()
    assert session.id not in store.locks
    await create(store)


async def test_session_files_are_encrypted_at_rest(store):
    raw = make_docx()
    session, _ = await store.create(raw, parse_docx(raw), "虚构岗位内容", "ip-hash")
    directory = store.directory(session.id)
    raw_file = (directory / "raw.docx").read_bytes()
    session_file = (directory / "session.json").read_bytes()
    assert raw_file.startswith(store.ENCRYPTED_PREFIX)
    assert session_file.startswith(store.ENCRYPTED_PREFIX)
    assert "陈同学".encode() not in raw_file + session_file
    assert "虚构岗位".encode() not in session_file
    assert store._read_private(directory / "raw.docx") == raw
    assert "虚构岗位" in store._read_private(directory / "session.json").decode()


async def test_existing_plaintext_session_is_migrated(store):
    session, _ = await create(store)
    directory = store.directory(session.id)
    (directory / "raw.docx").write_bytes(make_docx())
    (directory / "session.json").write_text(session.model_dump_json(), encoding="utf-8")

    store._migrate_plaintext()

    assert (directory / "raw.docx").read_bytes().startswith(store.ENCRYPTED_PREFIX)
    assert (directory / "session.json").read_bytes().startswith(store.ENCRYPTED_PREFIX)
    assert (await store.read(session.id)).id == session.id


def test_production_requires_a_valid_encryption_key(tmp_path):
    common = {
        "environment": "production",
        "metadata_backend": "redis",
        "data_dir": tmp_path,
        "ip_salt": "random-production-salt",
        "allowed_origins": ["https://key123456.online"],
    }
    with pytest.raises(ValidationError, match="data encryption key"):
        Settings(**common)
    Settings(**common, data_encryption_key=Fernet.generate_key().decode())


async def test_polling_does_not_touch_idle_deadline_and_hard_limit_is_enforced(store):
    session, _ = await create(store)
    deadline = session.expires_at
    assert (await store.read(session.id)).expires_at == deadline
    async with store.lock(session.id):
        session.created_at = time.time() - 55
        await store.write(session, touch=True)
    assert session.expires_at <= session.created_at + 60
    assert session.expires_at < deadline
    session.expires_at = time.time() - 1
    store._write(session)
    with pytest.raises(Problem, match="SESSION_GONE"):
        await store.read(session.id)
    await store.sweep()
    assert not store.directory(session.id).exists()


async def test_purge_cancels_job_and_is_idempotent(store):
    session, _ = await create(store)
    started = asyncio.Event()

    async def background():
        started.set()
        await asyncio.sleep(100)

    job = asyncio.create_task(background())
    store.jobs[session.id] = job
    await started.wait()
    await store.purge(session.id)
    await asyncio.gather(job, return_exceptions=True)
    assert job.cancelled()
    await store.purge(session.id)
    with pytest.raises(Problem):
        store.directory("../not-a-session")


async def test_memory_restart_clears_unrecoverable_sessions(store):
    session, _ = await create(store)
    restarted = Store(store.settings, Metadata(store.settings))
    await restarted.start()
    assert not restarted.directory(session.id).exists()


async def test_daily_quota_is_atomic_and_byok_still_has_global_limit(tmp_path):
    metadata = Metadata(Settings(free_daily=1, global_daily=2, data_dir=tmp_path))
    outcomes = await asyncio.gather(*(metadata.reserve_analysis("same-ip", False)
                                      for _ in range(5)), return_exceptions=True)
    assert sum(result is None for result in outcomes) == 1
    assert sum(isinstance(result, Problem) for result in outcomes) == 4
    await metadata.reserve_analysis("same-ip", True)
    sessions = await asyncio.gather(*(metadata.reserve_session() for _ in range(5)),
                                    return_exceptions=True)
    assert sum(result is None for result in sessions) == 2
    assert sum(isinstance(result, Problem) for result in sessions) == 3
    await metadata.release_session()
    await metadata.reserve_session()
    await metadata.reserve_tokens(100)
    with pytest.raises(Problem, match="TOKEN_BUDGET"):
        await metadata.reserve_tokens(metadata.settings.daily_tokens)
