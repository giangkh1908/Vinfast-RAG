"""Prometheus /metrics endpoint — export realtime metrics cho Grafana scraping.

Convention: GET /metrics trả `text/plain; version=0.0.4`. Bảo mật: trong môi
trường production phải chặn ở tầng reverse-proxy / mạng nội bộ (endpoint không
lộ thông tin nhạy cảm ngoài counters/histograms).
"""

import logging

from fastapi import APIRouter
from fastapi.responses import Response

logger = logging.getLogger("bds.prometheus_api")

router = APIRouter(tags=["Prometheus"])


@router.get("/metrics", summary="Prometheus metrics export")
async def prometheus_metrics():
    try:
        from app.core.telemetry.prometheus import generate

        body = generate()
    except ImportError:
        body = b"# prometheus-client not installed\n"
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
