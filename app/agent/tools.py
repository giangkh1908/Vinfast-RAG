import asyncio
import json
from collections import Counter

import asyncpg

from app.config import settings


async def _conn():
    pg_url = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(pg_url)


def _model_id(model_code: str) -> str:
    return model_code.replace(" ", "")


async def get_price(model_code: str, version: str = None) -> dict:
    conn = await _conn()
    mid = _model_id(model_code)

    # Try primary model_id first, then fallback variations
    mids_to_try = [mid]
    # "VF8AllNew" → also try "VF8NEW", "VF8_ALLNEW", "VF8-ALLNEW"
    mid_upper = mid.upper()
    if "ALLNEW" in mid_upper or "ALL" in mid_upper:
        base = mid_upper.replace("ALLNEW", "").replace("ALL", "")
        mids_to_try.extend([base + "NEW", base + "_NEW", base + "-NEW"])

    rows = []
    for try_mid in mids_to_try:
        if version:
            rows = await conn.fetch(
                "SELECT edition_id, price_list_vnd, price_promo_vnd, promo_label, source_url "
                "FROM price_list_active WHERE model_id=$1 AND edition_id=$2 ORDER BY price_list_vnd",
                try_mid, version,
            )
        else:
            rows = await conn.fetch(
                "SELECT edition_id, price_list_vnd, price_promo_vnd, promo_label, source_url "
                "FROM price_list_active WHERE model_id=$1 ORDER BY price_list_vnd",
                try_mid,
            )
        if rows:
            mid = try_mid  # Use the matching model_id for related query
            break

    related = await conn.fetch(
        "SELECT model_id, edition_id, price_list_vnd, price_promo_vnd "
        "FROM price_list_active WHERE model_id != $1 ORDER BY price_list_vnd LIMIT 10",
        mid,
    )
    await conn.close()

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

    return {
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


async def get_colors(model_code: str, version: str = None) -> dict:
    """Lấy danh sách màu sắc và nội thất từ car_colors."""
    conn = await _conn()

    if version:
        rows = await conn.fetch(
            "SELECT version_name, color_name, color_type, color_fee_vnd, interior_name "
            "FROM car_colors WHERE model_code = $1 AND version_name = $2 "
            "ORDER BY color_name, interior_name",
            model_code, version,
        )
    else:
        rows = await conn.fetch(
            "SELECT version_name, color_name, color_type, color_fee_vnd, interior_name "
            "FROM car_colors WHERE model_code = $1 "
            "ORDER BY version_name, color_name, interior_name",
            model_code,
        )
    await conn.close()

    if not rows:
        return {"model_code": model_code, "variants": [], "colors": [], "interiors": []}

    colors = sorted(set(r["color_name"] for r in rows if r["color_name"]))
    interiors = sorted(set(r["interior_name"] for r in rows if r["interior_name"]))

    return {
        "model_code": model_code,
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


async def get_specs(model_code: str, version: str = None, category: str = None) -> dict:
    conn = await _conn()

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

    where = " AND ".join(conditions)
    try:
        rows = await conn.fetch(
            f"SELECT version_name, version_code, spec_category, spec_key, spec_value, spec_unit, source_url, page "
            f"FROM car_specs WHERE {where} ORDER BY spec_category, spec_key, version_name",
            *params,
        )
    except Exception:
        # page column may not exist in all DB schemas
        rows = await conn.fetch(
            f"SELECT version_name, version_code, spec_category, spec_key, spec_value, spec_unit, source_url "
            f"FROM car_specs WHERE {where} ORDER BY spec_category, spec_key, version_name",
            *params,
        )

    related = await conn.fetch(
        "SELECT DISTINCT model_code FROM car_specs WHERE model_code != $1 ORDER BY model_code LIMIT 10",
        model_code,
    )
    await conn.close()

    source_urls = set(r["source_url"] for r in rows if r["source_url"])
    primary_source = source_urls.pop() if source_urls else ""

    related_models = [{"model_code": r["model_code"]} for r in related]

    return {
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


async def search_knowledge_base(query: str, model_id: str = None) -> dict:
    from app.core.retrieval import hybrid_search
    mid = model_id.replace(" ", "") if model_id else None
    results = await hybrid_search(query, model_id=mid, top_k=5)
    return {
        "query": query,
        "results": [
            {
                "text": r["text"],
                "model_id": r["model_id"],
                "text_type": r["text_type"],
                "source_type": r["source_type"],
                "source_url": r["source_url"],
                "score": round(r["score"], 3),
            }
            for r in results
        ],
    }


async def list_available_models() -> dict:
    conn = await _conn()
    rows = await conn.fetch(
        "SELECT model_id, model_label, edition_id, edition_label, year_range "
        "FROM edition_active ORDER BY model_id, edition_id"
    )
    await conn.close()

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

    return {"models": models}


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


async def search_all(model_code: str, query: str, version: str = None) -> dict:
    specs_task = get_specs(model_code, version=version)
    kb_task = search_knowledge_base(query, model_id=model_code)
    specs_result, kb_result = await asyncio.gather(specs_task, kb_task)
    return {
        "model_code": model_code,
        "specs": specs_result,
        "knowledge_base": kb_result,
    }


TOOL_REGISTRY = {
    "get_price": get_price,
    "get_colors": get_colors,
    "get_specs": get_specs,
    "search_knowledge_base": search_knowledge_base,
    "search_all": search_all,
    "list_available_models": list_available_models,
    "get_active_promotions": get_active_promotions,
    "get_onroad_cost_link": get_onroad_cost_link,
    "get_loan_estimate_link": get_loan_estimate_link,
    "get_showroom_charging_link": get_showroom_charging_link,
    "get_booking_link": get_booking_link,
    "get_maintenance_link": get_maintenance_link,
    "ask_clarification": ask_clarification,
}
