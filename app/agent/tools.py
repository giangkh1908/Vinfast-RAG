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
    await conn.close()

    source_url = rows[0]["source_url"] if rows and rows[0].get("source_url") else ""
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
    rows = await conn.fetch(
        f"SELECT version_name, version_code, spec_category, spec_key, spec_value, spec_unit, source_url "
        f"FROM car_specs WHERE {where} ORDER BY spec_category, spec_key, version_name",
        *params,
    )
    await conn.close()

    source_urls = set(r["source_url"] for r in rows if r["source_url"])
    primary_source = source_urls.pop() if source_urls else ""

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
            }
            for r in rows
        ],
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

    if settings.scope_enabled and settings.scope_models:
        placeholders = ", ".join(f"${i+1}" for i in range(len(settings.scope_models)))
        rows = await conn.fetch(
            f"SELECT model_id, model_label, edition_id, edition_label, year_range "
            f"FROM edition_active WHERE model_label IN ({placeholders}) ORDER BY model_id, edition_id",
            *settings.scope_models,
        )
    else:
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
    """LLM calls this when query is too broad. Returns available categories for the model."""
    categories = suggested_categories or [
        "phiên_bản", "thông_số_kỹ_thuật", "kích_thước",
        "pin_sạc", "phạm_vi_di_chuyển", "an_toàn",
        "nội_thất", "ngoại_thất", "tính_năng"
    ]
    return {
        "action": "clarify",
        "model_id": model_id,
        "available_categories": categories,
        "message": f"Bạn muốn tìm thông tin nào{(' về ' + model_id) if model_id else ''}?",
    }


TOOL_REGISTRY = {
    "get_price": get_price,
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
