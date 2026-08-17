"""asyncpg connection pool dùng chung cho Neon.

Thiết kế cho Neon Pooler (pgbouncer transaction mode):
- statement_cache_size=0: pgbouncer transaction mode không hỗ trợ prepared
  statements persistent → nếu asyncpg cache prepared stmts sẽ gây lỗi
  "prepared statement does not exist" hoặc "prepared statement already exists".
- min_size=5: giữ 5 connections sẵn sàng để tránh cold-start latency.
- max_size=30: burst capacity. Neon pooler (free tier) cho phép ~100-200
  concurrent clients, nhưng mỗi request chỉ giữ connection ~2-3ms (trừ SSE stream).
  30 connections đủ cho ~300-500 RPM với query <5ms.
- max_queries=10000: recycle connections thường xuyên (Neon serverless có thể
  drop idle connections).
- command_timeout=15s: query nào chạy quá 15s thì fail (thay vì 30s cũ).

Monitor: exposes pool_stats() để check live connection count.
"""
import asyncio
import logging
import time

import asyncpg

from app.config import settings

logger = logging.getLogger("bds.db")

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()

# Pool stats for monitoring
_stats = {"created_at": 0.0, "acquire_count": 0, "acquire_wait_count": 0}


def _pg_url() -> str:
    return settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    _pg_url(),
                    min_size=5,
                    max_size=30,
                    max_queries=10000,
                    max_inactive_connection_lifetime=300.0,
                    command_timeout=15,
                    # CRITICAL: pgbouncer transaction mode khong ho tro prepared
                    # statements persistent. Neu asyncpg cache prepared stmts
                    # se bi pgbouncer invalidate -> loi "prepared statement does
                    # not exist".  Set = 0 de disable entirely.
                    statement_cache_size=0,
                )
                _stats["created_at"] = time.time()
                logger.info(
                    "PG pool created: min=5 max=30 statement_cache=0 "
                    "(Neon pooler compatible)"
                )
    return _pool


def pool_stats() -> dict:
    """Live pool statistics for monitoring endpoint."""
    if _pool is None:
        return {"status": "not_initialized"}
    # asyncpg Pool internal state
    return {
        "status": "active",
        "min_size": _pool.get_min_size(),
        "max_size": _pool.get_max_size(),
        "size": _pool.get_size(),
        "free_size": _pool.get_idle_size(),
        "min_idle": _pool.get_min_idle_size(),
        "uptime_seconds": int(time.time() - _stats["created_at"]),
    }


class TimedAcquire:
    """Context manager that times pool.acquire() to detect contention."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._conn = None
        self._acquire_time = 0.0
        self._wait_time = 0.0

    async def __aenter__(self):
        self._acquire_time = time.monotonic()
        self._conn = await self._pool.acquire()
        self._wait_time = time.monotonic() - self._acquire_time
        if self._wait_time > 0.1:
            # Log slow acquire (pool contention)
            logger.warning(
                "Slow pool acquire: %.2fs (pool_size=%s, free=%s)",
                self._wait_time,
                self._pool.get_size(),
                self._pool.get_idle_size(),
            )
        return self._conn

    async def __aexit__(self, *exc):
        if self._conn is not None:
            await self._pool.release(self._conn)
        return False
