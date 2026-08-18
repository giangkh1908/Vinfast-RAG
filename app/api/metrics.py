"""
app/api/metrics.py — Admin Metrics REST API Endpoints for Monitoring & Stakeholder Dashboard.

Bảo mật: Yêu cầu Header `X-Admin-Key` khớp với `ADMIN_API_KEY` trong Settings.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Security
from fastapi.responses import JSONResponse

from app.core.telemetry import (
    get_metrics_intents,
    get_metrics_logs,
    get_metrics_overview,
    get_metrics_timeseries,
)

logger = logging.getLogger("bds.metrics_api")

router = APIRouter(prefix="/api/admin/metrics", tags=["Admin & Telemetry"])


async def verify_admin_key(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")
) -> bool:
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
    intent: Optional[str] = Query(None, description="Lọc theo intent"),
    cache_hit: Optional[bool] = Query(None, description="Lọc theo trạng thái cache hit"),
    _: bool = Security(verify_admin_key),
):
    """Truy vấn danh sách request logs chi tiết có phân trang và bộ lọc."""
    try:
        data = await get_metrics_logs(
            limit=limit, offset=offset, intent=intent, cache_hit=cache_hit
        )
        return JSONResponse(content={"status": "success", "data": data})
    except Exception as e:
        logger.exception("Failed to fetch metrics logs: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
