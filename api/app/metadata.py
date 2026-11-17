import asyncio
import json
import time
from datetime import UTC, datetime

import redis.asyncio as redis

from .config import Settings
from .schemas import Problem


# Only non-content metadata passes through this class. Redis RDB may be shared.
class Metadata:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = (
            redis.from_url(settings.redis_url, decode_responses=True)
            if settings.metadata_backend == "redis" else None
        )
        self.values: dict[str, tuple[str, float]] = {}
        self.lock = asyncio.Lock()

    async def start(self):
        if self.client:
            await self.client.ping()  # Failure is fatal; never silently disable production limits.

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def get(self, key: str) -> str | None:
        key = "ro:" + key
        if self.client:
            return await self.client.get(key)
        value, expiry = self.values.get(key, ("", 0))
        if expiry <= time.time():
            self.values.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl: int):
        key = "ro:" + key
        if self.client:
            await self.client.set(key, value, ex=max(1, ttl))
        else:
            self.values[key] = (value, time.time() + max(1, ttl))

    async def delete(self, key: str):
        if self.client:
            await self.client.delete("ro:" + key)
        else:
            self.values.pop("ro:" + key, None)

    async def claim_ip(self, ip_key: str, sid: str, ttl: int) -> bool:
        key = "ro:active:" + ip_key
        if self.client:
            return bool(await self.client.set(key, sid, nx=True, ex=max(1, ttl)))
        async with self.lock:
            value, expiry = self.values.get(key, ("", 0))
            if expiry > time.time() and value != sid:
                return False
            self.values[key] = (sid, time.time() + max(1, ttl))
            return True

    async def release_ip(self, ip_key: str, sid: str):
        key = "ro:active:" + ip_key
        if self.client:
            await self.client.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then "
                "return redis.call('DEL',KEYS[1]) else return 0 end", 1, key, sid
            )
        else:
            async with self.lock:
                if self.values.get(key, (None, 0))[0] == sid:
                    self.values.pop(key, None)

    async def refresh_ip(self, ip_key: str, sid: str, ttl: int):
        key = "ro:active:" + ip_key
        if self.client:
            return await self.client.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then "
                "redis.call('EXPIRE',KEYS[1],ARGV[2]);return 1 else return 0 end",
                1, key, sid, max(1, ttl),
            )
        async with self.lock:
            if self.values.get(key, (None, 0))[0] != sid:
                return False
            self.values[key] = (sid, time.time() + max(1, ttl))
            return True

    @property
    def day(self):
        return datetime.now(UTC).strftime("%Y%m%d")

    async def reserve_analysis(self, ip_key: str, byok: bool):
        keys = ["ro:daily:" + self.day + ":sessions",
                "ro:daily:" + self.day + ":ip:" + ip_key]
        daily = self.settings.global_daily
        free = 0 if byok else self.settings.free_daily
        if self.client:
            script = """
local all=tonumber(redis.call('GET',KEYS[1]) or '0')
local own=tonumber(redis.call('GET',KEYS[2]) or '0')
if all>=tonumber(ARGV[1]) then return 1 end
if tonumber(ARGV[2])>0 and own>=tonumber(ARGV[2]) then return 2 end
redis.call('INCR',KEYS[1]);redis.call('EXPIRE',KEYS[1],90000)
if tonumber(ARGV[2])>0 then
redis.call('INCR',KEYS[2]);redis.call('EXPIRE',KEYS[2],90000) end
return 0
"""
            result = int(await self.client.eval(script, 2, *keys, daily, free))
        else:
            async with self.lock:
                now = time.time()
                counts = [int(self.values.get(k, ("0", 0))[0])
                          if self.values.get(k, ("0", 0))[1] > now else 0 for k in keys]
                result = 1 if counts[0] >= daily else (
                    2 if free and counts[1] >= free else 0
                )
                if not result:
                    self.values[keys[0]] = (str(counts[0] + 1), now + 90000)
                    if free:
                        self.values[keys[1]] = (str(counts[1] + 1), now + 90000)
        if result:
            raise Problem(
                "DAILY_LIMIT",
                "今日体验额度已用完，请稍后再试。" if result == 1 else
                "当前网络今日免费额度已用完，可以使用自己的模型 Key。",
                429,
            )

    async def reserve_tokens(self, amount: int):
        key = "ro:daily:" + self.day + ":budget"
        if self.client:
            result = await self.client.eval(
                "local n=tonumber(redis.call('GET',KEYS[1]) or '0');"
                "if n+tonumber(ARGV[1])>tonumber(ARGV[2]) then return 0 end;"
                "redis.call('INCRBY',KEYS[1],ARGV[1]);"
                "redis.call('EXPIRE',KEYS[1],90000);return 1",
                1, key, amount, self.settings.daily_tokens,
            )
        else:
            async with self.lock:
                value, expiry = self.values.get(key, ("0", 0))
                count = int(value) if expiry > time.time() else 0
                result = count + amount <= self.settings.daily_tokens
                if result:
                    self.values[key] = (str(count + amount), time.time() + 90000)
        if not result:
            raise Problem("TOKEN_BUDGET", "今日模型处理额度已用完，请稍后再试。", 429)

    async def stat(self, field: str, count: int = 1):
        key = "ro:stats:" + self.day
        if self.client:
            async with self.client.pipeline(transaction=True) as pipe:
                await pipe.hincrby(key, field, count).expire(key, 90 * 86400).execute()
        else:
            async with self.lock:
                raw, _ = self.values.get(key, ("{}", 0))
                values = json.loads(raw)
                values[field] = values.get(field, 0) + count
                self.values[key] = (json.dumps(values), time.time() + 90 * 86400)

    async def stats(self):
        key = "ro:stats:" + self.day
        if self.client:
            return await self.client.hgetall(key)
        return json.loads(self.values.get(key, ("{}", 0))[0])
