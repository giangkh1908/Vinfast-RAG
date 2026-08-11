import asyncio
import logging
import time

import asyncpg

from app.config import settings

logger = logging.getLogger("bds.schemas")

# Tools exposed in BDS mode (Trust Foundation slice)
BDS_TOOL_NAMES = {"get_specs", "search_knowledge_base", "list_available_models", "ask_clarification"}

# TTL cache (5 minutes)
_schemas_cache = None
_schemas_cache_time = 0
_CACHE_TTL = 300

PG_URL = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")


async def _pg_fetch(sql: str, *params, retries: int = 2) -> list:
    """Execute PG query with retry on connection failure (Neon serverless)."""
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
    if settings.scope_enabled and settings.scope_models:
        placeholders = ", ".join(f"${i+1}" for i in range(len(settings.scope_models)))
        rows = await _pg_fetch(
            f"SELECT DISTINCT model_label FROM edition_active "
            f"WHERE model_label IN ({placeholders}) ORDER BY model_label",
            *settings.scope_models,
        )
    else:
        rows = await _pg_fetch("SELECT DISTINCT model_label FROM edition_active ORDER BY model_label")
    return [r["model_label"] for r in rows]


async def _get_version_list() -> list[str]:
    if settings.scope_enabled and settings.scope_models:
        placeholders = ", ".join(f"${i+1}" for i in range(len(settings.scope_models)))
        rows = await _pg_fetch(
            f"SELECT DISTINCT edition_id FROM edition_active "
            f"WHERE model_label IN ({placeholders}) ORDER BY edition_id",
            *settings.scope_models,
        )
    else:
        rows = await _pg_fetch("SELECT DISTINCT edition_id FROM edition_active ORDER BY edition_id")
    return [r["edition_id"] for r in rows]


async def _get_spec_categories() -> list[str]:
    if settings.scope_enabled and settings.scope_models:
        placeholders = ", ".join(f"${i+1}" for i in range(len(settings.scope_models)))
        rows = await _pg_fetch(
            f"SELECT DISTINCT spec_category FROM car_specs "
            f"WHERE model_code IN ({placeholders}) ORDER BY spec_category",
            *settings.scope_models,
        )
    else:
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
                "description": f"Lấy giá bán xe VinFast. Models: {model_list_str}. Bao gồm giá niêm yết và giá ưu đãi cho từng phiên bản.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {
                            "type": "string",
                            "enum": models,
                            "description": "Mã xe VinFast",
                        },
                        "version": {
                            "type": "string",
                            "enum": versions,
                            "description": "Phiên bản. Để trống = lấy tất cả.",
                        },
                    },
                    "required": ["model_code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_specs",
                "description": f"Lấy thông số kỹ thuật xe VinFast. Models: {model_list_str}. Công suất, quãng đường, pin, kích thước, nội thất, an toàn, ADAS, ngoại thất.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {
                            "type": "string",
                            "enum": models,
                            "description": "Mã xe VinFast",
                        },
                        "version": {
                            "type": "string",
                            "enum": versions,
                            "description": "Phiên bản. Để trống = lấy tất cả.",
                        },
                        "category": {
                            "type": "string",
                            "enum": categories,
                            "description": "Loại thông số. Để trống = lấy tất cả.",
                        },
                    },
                    "required": ["model_code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": f"Tìm kiếm mô tả sản phẩm, tính năng, chính sách, FAQ từ knowledge base. Models: {model_list_str}. LUÔN truyền model_id nếu user hỏi về model cụ thể.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Câu hỏi hoặc từ khóa tìm kiếm",
                        },
                        "model_id": {
                            "type": "string",
                            "enum": models,
                            "description": "Model xe để filter kết quả. Bắt buộc khi user hỏi về model cụ thể.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_all",
                "description": f"Tìm kiếm THÔNG SỐ KỸ THUẬT + KNOWLEDGE BASE song song. Dùng khi câu hỏi về tính năng, trang bị, hoặc bất kỳ thông tin nào có thể nằm trong cả 2 nguồn (specs + mô tả). Models: {model_list_str}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {
                            "type": "string",
                            "enum": models,
                            "description": "Mã xe VinFast",
                        },
                        "query": {
                            "type": "string",
                            "description": "Câu hỏi hoặc từ khóa tìm kiếm",
                        },
                        "version": {
                            "type": "string",
                            "enum": versions,
                            "description": "Phiên bản. Để trống = lấy tất cả.",
                        },
                    },
                    "required": ["model_code", "query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_available_models",
                "description": "Liệt kê các model VinFast đang bán. Dùng để xác nhận model tồn tại trước khi gọi tool khác.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_active_promotions",
                "description": f"Khuyến mãi đang áp dụng. Models: {model_list_str}. Voucher chuyển đổi, ưu đãi đặt cọc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_code": {
                            "type": "string",
                            "enum": models,
                            "description": "Lọc theo model (optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_onroad_cost_link",
                "description": "Link dự toán chi phí lăn bánh chính chủ VinFast. KHÔNG tự tính.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_loan_estimate_link",
                "description": "Link dự toán trả góp + thẩm định vay chính chủ VinFast.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_showroom_charging_link",
                "description": "Link tìm showroom & trạm sạc chính chủ VinFast.",
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
                        "type": {
                            "type": "string",
                            "enum": ["maintenance", "test_drive"],
                            "description": "Loại booking",
                        },
                    },
                    "required": ["type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_maintenance_link",
                "description": f"Link bảo dưỡng theo model + năm. Models: {model_list_str}. Trả link, KHÔNG trả nội dung.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "car_model": {
                            "type": "string",
                            "enum": models,
                            "description": "Model xe",
                        },
                        "year": {
                            "type": "integer",
                            "description": "Năm (optional, fallback năm mới nhất)",
                        },
                    },
                    "required": ["car_model"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_clarification",
                "description": "Gọi khi: (1) câu hỏi thiếu model, hoặc (2) câu hỏi thiếu phiên bản (Eco/Plus) mà thông số khác nhau giữa các phiên bản (range, battery, power). VD: 'VF 8 đi được bao nhiêu km?' → hỏi lại 'Eco hay Plus?'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_id": {
                            "type": "string",
                            "enum": models,
                            "description": "Model xe người dùng đang hỏi (nếu biết)",
                        },
                        "suggested_categories": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["phiên_bản", "thông_số_kỹ_thuật", "kích_thước",
                                         "pin_sạc", "phạm_vi_di_chuyển", "an_toàn",
                                         "nội_thất", "ngoại_thất", "tính_năng"],
                            },
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
