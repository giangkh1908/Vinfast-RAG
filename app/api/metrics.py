"""
app/api/metrics.py — Admin Metrics REST API Endpoints for Monitoring & Stakeholder Dashboard.

Bảo mật: Yêu cầu Header `X-Admin-Key` khớp với `ADMIN_API_KEY` trong Settings.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Query, Security
from fastapi.responses import JSONResponse

from app.core.telemetry.telemetry import (
    get_metrics_intents,
    get_metrics_logs,
    get_metrics_overview,
    get_metrics_sessions,
    get_metrics_timeseries,
    get_metrics_top_ips,
)

logger = logging.getLogger("bds.metrics_api")

router = APIRouter(prefix="/api/admin/metrics", tags=["Admin & Telemetry"])


async def verify_admin_key(x_admin_key: str | None = Header(None, alias="X-Admin-Key")) -> bool:
    """Mở trực tiếp toàn bộ API không cần kiểm tra Admin Key (phục vụ test và dev nhanh)."""
    return True


@router.get("/overview", summary="Tổng quan KPI vận hành")
async def metrics_overview(
    hours: int = Query(24, ge=1, le=720, description="Khoảng thời gian tính theo giờ (1-720)"),
    _: bool = Security(verify_admin_key),
):
    """Trả về các chỉ số KPI: Tổng queries, Token consumption, Chi phí ($ & VNĐ),
    TTFT P50/P95, Latency P50/P95, Tỷ lệ Cache Hit, Tỷ lệ lỗi.
    """
    try:
        data = await get_metrics_overview(hours=hours)
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch metrics overview: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/timeseries", summary="Chuỗi thời gian (Requests, Latency, Cost)")
async def metrics_timeseries(
    hours: int = Query(24, ge=1, le=720, description="Khoảng thời gian tính theo giờ"),
    _: bool = Security(verify_admin_key),
):
    """Dữ liệu chuỗi thời gian phân đoạn theo giờ để hiển thị biểu đồ đường."""
    try:
        data = await get_metrics_timeseries(hours=hours)
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch timeseries metrics: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/intents", summary="Phân bổ Intent & câu hỏi người dùng")
async def metrics_intents(
    hours: int = Query(168, ge=1, le=720, description="Khoảng thời gian tính theo giờ (mặc định 7 ngày)"),
    _: bool = Security(verify_admin_key),
):
    """Thống kê các intent (specs, price, policy...) được quan tâm nhiều nhất."""
    try:
        data = await get_metrics_intents(hours=hours)
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch intent metrics: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/logs", summary="Danh sách Request Logs chi tiết")
async def metrics_logs(
    limit: int = Query(50, ge=1, le=200, description="Số lượng bản ghi mỗi trang"),
    offset: int = Query(0, ge=0, description="Vị trí bắt đầu phân trang"),
    intent: str | None = Query(None, description="Lọc theo intent"),
    cache_hit: bool | None = Query(None, description="Lọc theo trạng thái cache hit"),
    _: bool = Security(verify_admin_key),
):
    """Truy vấn danh sách request logs chi tiết có phân trang và bộ lọc."""
    try:
        data = await get_metrics_logs(limit=limit, offset=offset, intent=intent, cache_hit=cache_hit)
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch metrics logs: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/sessions", summary="Thống kê theo Session (Top token/chi phí)")
async def metrics_sessions(
    hours: int = Query(168, ge=1, le=720, description="Khoảng thời gian tính theo giờ (mặc định 7 ngày)"),
    limit: int = Query(20, ge=1, le=100, description="Số lượng session trả về"),
    _: bool = Security(verify_admin_key),
):
    """Lấy danh sách các session tốn nhiều token và chi phí nhất."""
    try:
        data = await get_metrics_sessions(limit=limit, hours=hours)
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch session metrics: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/top-ips", summary="Thống kê Top IP và phát hiện Spam/Abuse")
async def metrics_top_ips(
    hours: int = Query(24, ge=1, le=720, description="Khoảng thời gian tính theo giờ (mặc định 24h)"),
    limit: int = Query(20, ge=1, le=100, description="Số lượng IP trả về"),
    _: bool = Security(verify_admin_key),
):
    """Thống kê các IP gọi nhiều nhất, số lượt bị chặn 429 và tỷ lệ lỗi."""
    try:
        data = await get_metrics_top_ips(limit=limit, hours=hours)
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch top IPs metrics: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/alerts", summary="Danh sách sự kiện cảnh báo hệ thống (System Alerts)")
async def metrics_alerts(
    limit: int = Query(50, ge=1, le=200, description="Số lượng cảnh báo trả về"),
    severity: str | None = Query(None, description="Lọc theo mức độ: WARNING hoặc CRITICAL"),
    _: bool = Security(verify_admin_key),
):
    """Lấy danh sách cảnh báo hệ thống từ bảng system_alerts."""
    try:
        from app.core.storage.db import get_pool
        from app.core.telemetry.email_alert import ensure_alerts_schema

        await ensure_alerts_schema()
        pool = await get_pool()
        async with pool.acquire() as conn:
            if severity:
                rows = await conn.fetch(
                    """
                    SELECT id, alert_type, severity, title, message, details, email_sent, created_at
                    FROM system_alerts
                    WHERE UPPER(severity) = UPPER($1)
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    severity,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, alert_type, severity, title, message, details, email_sent, created_at
                    FROM system_alerts
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )

        alerts = [
            {
                "id": r["id"],
                "alert_type": r["alert_type"],
                "severity": r["severity"],
                "title": r["title"],
                "message": r["message"],
                "details": r["details"],
                "email_sent": r["email_sent"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            }
            for r in rows
        ]
        return JSONResponse(content={"status": "success", "count": len(alerts), "alerts": alerts})
    except Exception as e:
        logger.exception("Failed to fetch alerts: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/alerts/test", summary="Gửi thử nghiệm cảnh báo Email qua Kafka")
async def trigger_test_alert(
    severity: str = Query("CRITICAL", description="Mức độ cảnh báo: WARNING hoặc CRITICAL"),
    _: bool = Security(verify_admin_key),
):
    """Bắn thử nghiệm 1 cảnh báo qua Kafka Cloud và Email để kiểm tra hệ thống."""
    try:
        from app.core.telemetry.kafka_producer import KafkaProducerService

        producer = await KafkaProducerService.get_instance()
        sent = await producer.send_alert(
            alert_type="MANUAL_TEST_ALERT",
            severity=severity,
            title="Thử nghiệm Cảnh báo Hệ thống VinFast",
            message="Đây là cảnh báo thử nghiệm được gửi từ Admin Dashboard để kiểm tra Kafka Cloud & Email Dispatcher.",
            details={
                "triggered_by": "Admin User",
                "severity": severity,
                "kafka_enabled": True,
            },
        )
        return JSONResponse(
            content={
                "status": "success",
                "message": "Đã bắn cảnh báo thử nghiệm vào Kafka Cloud!",
                "kafka_sent": sent,
            }
        )
    except Exception as e:
        logger.exception("Failed to trigger test alert: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
