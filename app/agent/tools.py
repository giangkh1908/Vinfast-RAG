import asyncio
import json
from collections import Counter

from app.config import settings
from app.core.db import get_pool
from app.core.cache import (
    cache, 
    make_tool_price_key, make_tool_specs_key, make_tool_colors_key, make_tool_models_key,
    TOOL_PRICE_TTL, TOOL_DATA_TTL
)


def _model_id(model_code: str) -> str:
    # Direct mapping for known mismatches between code and DB (case-insensitive)
    MODEL_ID_MAP = {
        "vf 8 all new": "VF8NEW",
        "vf8 all new": "VF8NEW",
    }
    return MODEL_ID_MAP.get(model_code.lower().strip(), model_code.replace(" ", ""))


async def get_price(model_code: str, version: str = None) -> dict:
    # Check cache trước. cache_key=None khi PG unreachable → skip cache
    cache_key = await make_tool_price_key(model_code, version)
    if cache_key is not None:
        cached = await cache.get_json(cache_key)
        if cached:
            return cached
    
    pool = await get_pool()
    mid = _model_id(model_code)

    async with pool.acquire() as conn:
        if version:
            rows = await conn.fetch(
                "SELECT edition_id, price_list_vnd, price_promo_vnd, promo_label, source_url "
                "FROM price_list_active WHERE model_id=$1 AND edition_id=$2 ORDER BY price_list_vnd",
                mid, version,
            )
        else:
            rows = await conn.fetch(
                "SELECT edition_id, price_list_vnd, price_promo_vnd, promo_label, source_url "
                "FROM price_list_active WHERE model_id=$1 ORDER BY price_list_vnd",
                mid,
            )

        related = await conn.fetch(
            "SELECT model_id, edition_id, price_list_vnd, price_promo_vnd "
            "FROM price_list_active WHERE model_id != $1 ORDER BY price_list_vnd LIMIT 10",
            mid,
        )

    source_url = rows[0]["source_url"] if rows and rows[0].get("source_url") else ""
    related_models = []
    seen = set()
    for r in related:
        rm = r["model_id"]
        if rm not in seen:
            seen.add(rm)
            related_models.append({
                "model_code": rm,
                "price_vnd": r["price_list_vnd"],
                "version_name": r["edition_id"],
            })

    result = {
        "model_code": model_code,
        "source_url": source_url,
        "prices": [
            {
                "version_name": r["edition_id"],
                "price_vnd": r["price_list_vnd"],
                "promo_price_vnd": r["price_promo_vnd"],
                "promo_label": r["promo_label"] or "",
            }
            for r in rows
        ],
        "related_models": related_models,
        "note": "Giá niêm yết chưa bao gồm chi phí lăn bánh. Khuyến mãi có thể thay đổi theo thời gian và khu vực.",
    }
    
    # Set cache. Skip nếu cache_key=None (PG down)
    if cache_key is not None:
        await cache.set_json(cache_key, result, TOOL_PRICE_TTL)
    return result


async def get_colors(model_code: str, version: str = None) -> dict:
    """Lấy danh sách màu sắc và nội thất từ car_colors.

    Lưu ý: car_colors dùng cột model_id dạng compact (VF8, VF8NEW, VFMPV7...)
    trong khi LLM truyền model_code dạng label ("VF 8 All New") → phải map
    qua _model_id().
    """
    # Check cache trước. cache_key=None khi PG unreachable → skip cache
    cache_key = await make_tool_colors_key(model_code, version)
    if cache_key is not None:
        cached = await cache.get_json(cache_key)
        if cached:
            return cached
    
    pool = await get_pool()
    mid = _model_id(model_code)

    async with pool.acquire() as conn:
        if version:
            rows = await conn.fetch(
                "SELECT version_name, color_name, color_type, color_fee_vnd, interior_name, source_url "
                "FROM car_colors WHERE model_id = $1 AND version_name = $2 "
                "ORDER BY color_name, interior_name",
                mid, version,
            )
        else:
            rows = await conn.fetch(
                "SELECT version_name, color_name, color_type, color_fee_vnd, interior_name, source_url "
                "FROM car_colors WHERE model_id = $1 "
                "ORDER BY version_name, color_name, interior_name",
                mid,
            )

    if not rows:
        result = {"model_code": model_code, "source_url": "", "variants": [], "colors": [], "interiors": []}
        if cache_key is not None:
            await cache.set_json(cache_key, result, TOOL_DATA_TTL)
        return result

    colors = sorted(set(r["color_name"] for r in rows if r["color_name"]))
    interiors = sorted(set(r["interior_name"] for r in rows if r["interior_name"]))
    source_url = next((r["source_url"] for r in rows if r["source_url"]), "")

    result = {
        "model_code": model_code,
        "source_url": source_url,
        "colors": colors,
        "interiors": interiors,
        "variants": [
            {
                "version": r["version_name"],
                "color": r["color_name"],
                "color_type": r.get("color_type") or "",
                "interior": r["interior_name"],
                "color_fee_vnd": r["color_fee_vnd"] or 0,
            }
            for r in rows
        ],
    }
    
    if cache_key is not None:
        await cache.set_json(cache_key, result, TOOL_DATA_TTL)
    return result


async def get_specs(model_code: str, version: str = None, category: str = None, keys: list[str] = None) -> dict:
    # Check cache trước. cache_key=None khi PG unreachable → skip cache
    cache_key = await make_tool_specs_key(model_code, version, category, keys)
    if cache_key is not None:
        cached = await cache.get_json(cache_key)
        if cached:
            return cached
    
    pool = await get_pool()

    conditions = ["model_code = $1"]
    params = [model_code]
    idx = 2

    if version:
        conditions.append(f"(version_name = ${idx} OR version_name IS NULL)")
        params.append(version)
        idx += 1

    if category:
        conditions.append(f"spec_category = ${idx}")
        params.append(category)
        idx += 1

    if keys:
        conditions.append(f"spec_key = ANY(${idx}::text[])")
        params.append(list(keys))
        idx += 1

    where = " AND ".join(conditions)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT version_name, version_code, spec_category, spec_key, spec_value, spec_unit, source_url "
            f"FROM car_specs WHERE {where} ORDER BY spec_category, spec_key, version_name",
            *params,
        )

        related = await conn.fetch(
            "SELECT DISTINCT model_code FROM car_specs WHERE model_code != $1 ORDER BY model_code LIMIT 10",
            model_code,
        )

    source_urls = set(r["source_url"] for r in rows if r["source_url"])
    # Ưu tiên URL chứa tên model (tránh lấy nhầm brochure xe khác)
    primary_source = ""
    if source_urls:
        model_slug = model_code.lower().replace(" ", "")
        # Tìm URL chứa tên model
        for url in source_urls:
            if model_slug in url.lower():
                primary_source = url
                break
        # Fallback: lấy URL đầu tiên
        if not primary_source:
            primary_source = next(iter(source_urls))

    related_models = [{"model_code": r["model_code"]} for r in related]

    result = {
        "model_code": model_code,
        "source_url": primary_source,
        "specs": [
            {
                "version_name": r["version_name"] or "ALL",
                "category": r["spec_category"],
                "key": r["spec_key"],
                "value": r["spec_value"],
                "unit": r["spec_unit"] or "",
                "page": r.get("page") or "",
            }
            for r in rows
        ],
        "related_models": related_models,
        "note": "Thông số có thể khác nhau giữa các phiên bản. Tham khảo thêm model liên quan để so sánh.",
    }
    
    if cache_key is not None:
        await cache.set_json(cache_key, result, TOOL_DATA_TTL)
    return result


async def search_knowledge_base(query: str, model_id: str = None, skip_rerank: bool = False) -> dict:
    from app.core.retrieval import hybrid_search
    mid = _model_id(model_id) if model_id else None
    results = await hybrid_search(query, model_id=mid, top_k=5, skip_rerank=skip_rerank)

    # Filter chunks score thấp (< 0.3) để tránh LLM bịa thông tin từ KB nhiễu
    filtered_results = [
        {
            "id": r.get("id", ""),
            "text": r["text"],
            "model_id": r["model_id"],
            "text_type": r["text_type"],
            "source_type": r["source_type"],
            "source_url": r["source_url"],
            "page": r.get("page", ""),
            "section": r.get("section", ""),
            "score": round(r["score"], 3),
        }
        for r in results
        if r.get("score", 0) >= 0.3
    ]

    return {
        "query": query,
        "results": filtered_results,
    }


async def list_available_models() -> dict:
    # Check cache trước. cache_key=None khi PG unreachable → skip cache
    cache_key = await make_tool_models_key()
    if cache_key is not None:
        cached = await cache.get_json(cache_key)
        if cached:
            return cached
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT model_id, model_label, edition_id, edition_label, year_range "
            "FROM edition_active ORDER BY model_id, edition_id"
        )

    by_model = {}
    for r in rows:
        mid = r["model_id"]
        if mid not in by_model:
            by_model[mid] = {
                "model_code": r["model_label"],
                "model_id": mid,
                "year_range": r["year_range"] or "",
                "versions": [],
            }
        by_model[mid]["versions"].append(r["edition_id"])

    # Add source_url for citation
    models = []
    for mid, info in by_model.items():
        model_lower = mid.lower().replace(" ", "-")
        info["source_url"] = f"https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-{model_lower}.html"
        models.append(info)

    result = {"models": models}
    if cache_key is not None:
        await cache.set_json(cache_key, result, TOOL_DATA_TTL)
    return result


UTILITY_LINKS = {
    "onroad_cost": {"url": "https://shop.vinfastauto.com/vn_vi/du-toan-chi-phi-lan-banh", "label": "Dự toán chi phí lăn bánh"},
    "loan_estimate": {"url": "https://shop.vinfastauto.com/vn_vi/du-toan-chi-phi-tra-gop", "label": "Dự toán trả góp"},
    "loan_appraisal": {"url": "https://shop.vinfastauto.com/vn_vi/tham-dinh-vay", "label": "Thẩm định vay"},
    "showroom_charging": {"url": "https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac", "label": "Tìm Showroom & Trạm sạc"},
    "maintenance_booking": {"url": "https://shop.vinfastauto.com/vn_vi/dat-lich-dich-vu-bao-duong.html", "label": "Đặt lịch bảo dưỡng"},
    "test_drive_booking": {"url": "https://shop.vinfastauto.com/vn_vi/dang-ky-lai-thu.html", "label": "Đăng ký lái thử"},
    "promotions": {"url": "https://shop.vinfastauto.com/vn_vi", "label": "Khuyến mãi đang áp dụng"},
}


async def get_active_promotions(model_code: str = None) -> dict:
    return {
        "url": UTILITY_LINKS["promotions"]["url"],
        "label": UTILITY_LINKS["promotions"]["label"],
        "note": "Khuyến mãi liên tục thay đổi. Vui lòng truy cập link để xem ưu đãi mới nhất.",
    }


async def get_onroad_cost_link() -> dict:
    return UTILITY_LINKS["onroad_cost"]


async def get_loan_estimate_link() -> dict:
    return {"links": [UTILITY_LINKS["loan_estimate"], UTILITY_LINKS["loan_appraisal"]]}


async def get_showroom_charging_link() -> dict:
    return UTILITY_LINKS["showroom_charging"]


async def get_booking_link(type: str) -> dict:
    key = "maintenance_booking" if type == "maintenance" else "test_drive_booking"
    return UTILITY_LINKS[key]


async def get_maintenance_link(car_model: str, year: int = None) -> dict:
    return {
        "links": [{"year": year or "all", "source_url": "https://vinfastauto.com/vn_vi/dich-vu-bao-duong-oto"}],
        "note": "Truy cập link để xem lịch bảo dưỡng theo model và năm.",
    }


async def ask_clarification(model_id: str = None, suggested_categories: list[str] = None) -> dict:
    """LLM calls this when query is too broad or missing version. Returns available categories for the model."""
    categories = suggested_categories or [
        "phiên_bản", "thông_số_kỹ_thuật", "kích_thước",
        "pin_sạc", "phạm_vi_di_chuyển", "an_toàn",
        "nội_thất", "ngoại_thất", "tính_năng"
    ]
    if model_id:
        return {
            "action": "clarify",
            "model_id": model_id,
            "available_categories": categories,
            "message": f"Bạn muốn tìm thông tin nào về {model_id}?",
        }
    return {
        "action": "clarify",
        "model_id": model_id,
        "available_categories": categories,
        "message": "Bạn muốn tìm thông tin nào về xe VinFast?",
    }


TOOL_REGISTRY = {
    "get_price": get_price,
    "get_colors": get_colors,
    "get_specs": get_specs,
    "search_knowledge_base": search_knowledge_base,
    "list_available_models": list_available_models,
    "get_active_promotions": get_active_promotions,
    "get_onroad_cost_link": get_onroad_cost_link,
    "get_loan_estimate_link": get_loan_estimate_link,
    "get_showroom_charging_link": get_showroom_charging_link,
    "get_booking_link": get_booking_link,
    "get_maintenance_link": get_maintenance_link,
    "ask_clarification": ask_clarification,
}
