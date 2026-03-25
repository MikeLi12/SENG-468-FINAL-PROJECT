"""Redis client for caching and session management (synchronous for Flask)."""

import redis
import json
import logging
from config import get_settings

logger = logging.getLogger(__name__)

_redis = None


def get_redis():
    global _redis
    if _redis is None:
        init_redis()
    return _redis


def init_redis():
    global _redis
    settings = get_settings()
    _redis = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
    )
    _redis.ping()
    logger.info("Redis connection established.")


def close_redis():
    global _redis
    if _redis:
        _redis.close()
        _redis = None
        logger.info("Redis connection closed.")


# ─── Cache helpers ───────────────────────────────────────────────

def cache_get(key):
    """Get a cached JSON value."""
    r = get_redis()
    val = r.get(key)
    if val:
        return json.loads(val)
    return None


def cache_set(key, value, ttl_seconds=300):
    """Set a JSON value in cache with TTL."""
    r = get_redis()
    r.set(key, json.dumps(value), ex=ttl_seconds)


def cache_delete(key):
    """Delete a cached value."""
    r = get_redis()
    r.delete(key)


def cache_delete_pattern(pattern):
    """Delete all keys matching a pattern."""
    r = get_redis()
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            r.delete(*keys)
        if cursor == 0:
            break
