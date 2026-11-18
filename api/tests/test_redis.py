import asyncio
import os
import time
import uuid

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.documents import parse_docx
from app.metadata import Metadata
from app.schemas import Problem
from app.storage import Store
from tests.test_documents import make_docx


@pytest.fixture
async def redis_metadata(tmp_path):
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is required for the isolated Redis integration test")
    settings = Settings(
        metadata_backend="redis", redis_url=url, data_dir=tmp_path,
        data_encryption_key=Fernet.generate_key().decode(),
        free_daily=1, global_daily=2, idle_seconds=20, hard_seconds=60,
    )
    namespace = "qa-" + uuid.uuid4().hex

    class TestMetadata(Metadata):
        @property
        def day(self):
            return namespace

    metadata = TestMetadata(settings)
    await metadata.start()
    try:
        yield metadata
    finally:
        keys = [key async for key in metadata.client.scan_iter(match="ro:*" + namespace + "*")]
        if keys:
            await metadata.client.delete(*keys)
        await metadata.close()


async def test_redis_limits_are_atomic_and_expire(redis_metadata):
    metadata = redis_metadata
    results = await asyncio.gather(
        *(metadata.reserve_analysis(metadata.day, False) for _ in range(5)),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, Problem) for result in results) == 4
    key = "ro:daily:" + metadata.day + ":ip:" + metadata.day
    assert 0 < await metadata.client.ttl(key) <= 90000
    await metadata.set(metadata.day, "temporary", 1)
    await asyncio.sleep(1.1)
    assert await metadata.get(metadata.day) is None


async def test_encrypted_session_recovers_with_redis_then_purges(redis_metadata):
    metadata = redis_metadata
    store = Store(metadata.settings, metadata)
    await store.start()
    raw = make_docx()
    session, cookie = await store.create(raw, parse_docx(raw), "虚构岗位内容", metadata.day)
    try:
        session.state = "analyzing"
        await store.write(session)
        restarted = Store(metadata.settings, metadata)
        await restarted.start()
        await restarted.authorize(session.id, cookie)
        recovered = await restarted.read(session.id)
        assert recovered.state == "interrupted"
        assert recovered.error == "PROCESS_RESTARTED"
        snapshot = await metadata.get("session:" + session.id)
        assert "虚构岗位" not in snapshot and "陈同学" not in snapshot
        assert recovered.jd == "虚构岗位内容"
        recovered.expires_at = time.time() - 1
        restarted._write(recovered)
        await restarted.sweep()
        assert not restarted.directory(session.id).exists()
        assert await metadata.get("session:" + session.id) is None
        assert await metadata.get("active:" + metadata.day) is None
        assert int((await metadata.stats())["purged"]) >= 1
        await restarted.close()
    finally:
        await store.purge(session.id)
        await store.close()
