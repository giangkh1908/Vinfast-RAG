import asyncio
import logging
import time

import asyncpg

from app.config import settings

logger = logging.getLogger("bds.schemas")

# TTL cache (5 minutes)
_schemas_cache = None
_schemas_cache_time = 0
_CACHE_TTL = 300

PG_URL = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")


async def _pg_fetch(sql: str, *params, retries: int = 2) -> list:
    for attempt in range(retries + 1):
        try:
            conn = await asyncpg.connect(PG_URL)
            try:
                rows = await conn.fetch(sql, *params)
                return rows
            finally:
                await conn.close()
        except (asyncpg.exceptions.ConnectionDoesNotExistError,
                asyncpg.InterfaceError, OSError) as e:
            if attempt < retries:
                logger.warning("PG connect retry %d/%d: %s", attempt + 1, retries, e)
                await asyncio.sleep(0.5 * (attempt + 1))
            else:
                raise


async def _get_model_list() -> list[str]:
    # Union: edition_active + car_specs (to cover models not yet in edition_active)
    rows = await _pg_fetch(
        "SELECT DISTINCT model_label FROM edition_active "
        "UNION "
        "SELECT DISTINCT model_code AS model_label FROM car_specs WHERE model_code IS NOT NULL "
        "ORDER BY model_label"
    )
    return [r["model_label"] for r in rows]


async def _get_version_list() -> list[str]:
    rows = await _pg_fetch(
        "SELECT DISTINCT edition_id FROM edition_active "
        "UNION "
        "SELECT DISTINCT version_name AS edition_id FROM car_specs WHERE version_name IS NOT NULL "
        "ORDER BY edition_id"
    )
    return [r["edition_id"] for r in rows]


async def _get_spec_categories() -> list[str]:
    rows = await _pg_fetch("SELECT DISTINCT spec_category FROM car_specs ORDER BY spec_category")
    return [r["spec_category"] for r in rows]


async def build_tool_schemas() -> list[dict]:
    global _schemas_cache, _schemas_cache_time
    if _schemas_cache and (time.time() - _schemas_cache_time) < _CACHE_TTL:
        return _schemas_cache
    models = await _get_model_list()
    versions = await _get_version_list()
    categories = await _get_spec_categories()
    model_list_str = ", ".join(models)

    all_schemas = [
        {
            "type": "function",
            "function": {
                "name": "get_price",
                "description": f"Lấy giá bán xe VinFast. Models: {model_list_str}. Giá niêm yết và ưu đãi cho từng phiên bản.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {"type": "string", "enum": models, "description": "Mã xe VinFast"},
                        "version": {"type": "string", "enum": versions, "description": "Phiên bản. Để trống = tất cả."},
                    },
                    "required": ["model_code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_specs",
                "description": f"Thông số kỹ thuật xe VinFast. Models: {model_list_str}. Công suất, pin, kích thước, an toàn, ADAS, nội thất, ngoại thất.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {"type": "string", "enum": models, "description": "Mã xe VinFast"},
                        "version": {"type": "string", "enum": versions, "description": "Phiên bản. Để trống = tất cả."},
                        "category": {"type": "string", "enum": categories, "description": "Loại thông số. Để trống = tất cả."},
                    },
                    "required": ["model_code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": f"Tìm mô tả sản phẩm, tính năng, FAQ từ knowledge base. Models: {model_list_str}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Câu hỏi hoặc từ khóa"},
                        "model_id": {"type": "string", "enum": models, "description": "Filter theo model."},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_all",
                "description": f"Tìm specs + knowledge base song song. Models: {model_list_str}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {"type": "string", "enum": models, "description": "Mã xe VinFast"},
                        "query": {"type": "string", "description": "Câu hỏi hoặc từ khóa"},
                        "version": {"type": "string", "enum": versions, "description": "Phiên bản. Để trống = tất cả."},
                    },
                    "required": ["model_code", "query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_available_models",
                "description": "Liệt kê tất cả model VinFast đang bán. Không tham số.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_active_promotions",
                "description": f"Khuyến mãi đang áp dụng. Models: {model_list_str}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {"type": "string", "enum": models, "description": "Lọc theo model (optional)"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_onroad_cost_link",
                "description": "Link dự toán chi phí lăn bánh.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_loan_estimate_link",
                "description": "Link dự toán trả góp + thẩm định vay.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_showroom_charging_link",
                "description": "Link tìm showroom & trạm sạc.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_booking_link",
                "description": "Link đặt lịch bảo dưỡng hoặc đăng ký lái thử.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["maintenance", "test_drive"], "description": "Loại booking"},
                    },
                    "required": ["type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_maintenance_link",
                "description": f"Link bảo dưỡng theo model + năm. Models: {model_list_str}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "car_model": {"type": "string", "enum": models, "description": "Model xe"},
                        "year": {"type": "integer", "description": "Năm (optional)"},
                    },
                    "required": ["car_model"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_clarification",
                "description": "Gọi khi thiếu model (không biết người dùng hỏi xe nào).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_id": {"type": "string", "enum": models, "description": "Model xe (nếu biết)"},
                        "suggested_categories": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Các khía cạnh có thể hỏi",
                        },
                    },
                    "required": [],
                },
            },
        },
    ]

    _schemas_cache = all_schemas
    _schemas_cache_time = time.time()
    return all_schemas
