"""
app/api/health.py — Production Health & Readiness Probes for Kubernetes / Docker / Cloud.

Endpoints:
- /healthz: Liveness probe (nhẹ, <1ms) — kiểm tra FastAPI event loop còn sống.
- /ready: Readiness probe (sâu) — kiểm tra kết nối PostgreSQL, Qdrant, Cache, LLM Config.
- /api/health: Backward compatibility alias cho frontend status bar.
"""
import datetime
import logging
import time
from typing import Any

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.db import get_pool, pool_stats

logger = logging.getLogger("bds.health")

router = APIRouter(tags=["Health & Diagnostics"])


@router.get("/healthz", summary="Liveness Probe")
async def healthz():
    """Liveness probe: Trả về 200 ngay lập tức nếu uvicorn server đang hoạt động."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "alive",
            "app_version": settings.app_version,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )


@router.get("/ready", summary="Readiness Probe")
async def readiness_probe(response: Response):
    """Readiness probe: Kiểm tra toàn diện DB (PostgreSQL), Vector DB (Qdrant), Cache (Redis)
    và LLM API keys. Trả về 503 nếu service cốt lõi gặp sự cố.
    """
    checks: dict[str, Any] = {}
    is_ready = True

    # 1. Check PostgreSQL Connection & Pool
    t0 = time.monotonic()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1")
            db_latency_ms = round((time.monotonic() - t0) * 1000, 2)
            if val == 1:
                checks["postgres"] = {
                    "status": "ok",
                    "latency_ms": db_latency_ms,
                    "pool": pool_stats(),
                }
            else:
                checks["postgres"] = {"status": "degraded", "detail": "unexpected_result"}
                is_ready = False
    except Exception as e:
        db_latency_ms = round((time.monotonic() - t0) * 1000, 2)
        checks["postgres"] = {
            "status": "error",
            "latency_ms": db_latency_ms,
            "error": str(e),
        }
        is_ready = False

    # 2. Check Qdrant Vector DB
    t0 = time.monotonic()
    try:
        from app.core.retrieval import get_qdrant_client
        q_client = get_qdrant_client()
        if q_client:
            cols = await q_client.get_collections()
            q_latency_ms = round((time.monotonic() - t0) * 1000, 2)
            checks["qdrant"] = {
                "status": "ok",
                "latency_ms": q_latency_ms,
                "collections_count": len(cols.collections) if cols else 0,
            }
        else:
            checks["qdrant"] = {"status": "not_configured"}
    except Exception as e:
        q_latency_ms = round((time.monotonic() - t0) * 1000, 2)
        checks["qdrant"] = {
            "status": "error",
            "latency_ms": q_latency_ms,
            "error": str(e),
        }
        # Qdrant là core service cho RAG
        is_ready = False

    # 3. Check Cache (Redis / Upstash)
    try:
        from app.core.cache import cache
        if cache.enabled:
            # Test cache ping / set-get
            test_key = "health:ping"
            await cache.set_json(test_key, {"ping": "pong"}, ttl=10)
            res = await cache.get_json(test_key)
            checks["cache"] = {
                "status": "ok" if res and res.get("ping") == "pong" else "degraded",
                "enabled": True,
            }
        else:
            checks["cache"] = {"status": "disabled", "enabled": False}
    except Exception as e:
        checks["cache"] = {"status": "error", "error": str(e), "enabled": True}

    # 4. Check LLM Configuration & Credentials
    has_deepinfra = bool(settings.deepinfra_api_key)
    has_openrouter = bool(settings.openrouter_api_key)
    checks["llm_config"] = {
        "chat_model": settings.llm_model,
        "fallback_model": settings.llm_fallback_model,
        "deepinfra_configured": has_deepinfra,
        "openrouter_configured": has_openrouter,
    }

    if not has_deepinfra:
        checks["llm_config"]["status"] = "warning_missing_deepinfra_key"

    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if is_ready else "not_ready",
            "app_version": settings.app_version,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "checks": checks,
        },
    )


@router.get("/api/health", summary="Legacy Healthcheck Endpoint")
async def legacy_health():
    """Endpoint tương thích ngược cho frontend và monitoring cũ."""
    stats = pool_stats()
    return JSONResponse(content={"status": "ok", "pool": stats, "version": settings.app_version})
