"""Redis client for caching and session management."""

import redis.asyncio as aioredis
import json
import logging
from config import get_settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        await init_redis()
    return _redis


async def init_redis():
    global _redis
    settings = get_settings()
    _redis = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
    )
    await _redis.ping()
    logger.info("Redis connection established.")


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("Redis connection closed.")


# ─── Cache helpers ───────────────────────────────────────────────

async def cache_get(key: str):
    """Get a cached JSON value."""
    r = await get_redis()
    val = await r.get(key)
    if val:
        return json.loads(val)
    return None


async def cache_set(key: str, value, ttl_seconds: int = 300):
    """Set a JSON value in cache with TTL."""
    r = await get_redis()
    await r.set(key, json.dumps(value), ex=ttl_seconds)


async def cache_delete(key: str):
    """Delete a cached value."""
    r = await get_redis()
    await r.delete(key)


async def cache_delete_pattern(pattern: str):
    """Delete all keys matching a pattern."""
    r = await get_redis()
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break
