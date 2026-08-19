"""Deterministic tool plan — LLM KHÔNG chọn tool / đoán tham số.

Intent + entities (từ classifier hybrid) → danh sách (tool, args) chính xác.
Thiếu dữ liệu bắt buộc (model) → trả None → classify đã xử lý clarify từ trước;
route_after_classify sẽ đưa về build_messages (LLM loop) làm fallback cuối cùng.
"""

import re

from app.agent.classifier import MODEL_RE, normalize_model
from app.agent.intent import MAIN_MODELS, classify_intent

# Fallback topic→category (khi keyword map không khớp)
_TOPIC_TO_CATEGORY = {
    "pin_và_sạc": "battery",
    "phạm_vi_di_chuyển": "battery",
    "kích_thước": "dimension",
    "an_toàn": "safety",
    "nội_thất": "interior",
    "ngoại_thất": "exterior",
    "tính_năng_nổi_bật": None,
    "thông_số_kỹ_thuật": None,
}

# Topic cần bổ sung knowledge base (kiến thức sản phẩm mở rộng)
_NEEDS_KB = {"an_toàn", "nội_thất", "ngoại_thất", "tính_năng_nổi_bật"}

# Utility subtype → tool plan
_UTILITY_PATTERNS = [
    (re.compile(r"(lăn\s*bánh|onroad|đăng\s*ký\s*xe)", re.I), lambda m: [("get_onroad_cost_link", {})]),
    (re.compile(r"(trả\s*góp|vay|thẩm\s*định)", re.I), lambda m: [("get_loan_estimate_link", {})]),
    (re.compile(r"(showroom|trạm\s*sạc|đại\s*lý|chi\s*nhánh)", re.I), lambda m: [("get_showroom_charging_link", {})]),
    (
        re.compile(r"(đặt\s*lịch|booking|lịch\s*hẹn|test\s*drive|lái\s*thử)", re.I),
        lambda m: [("get_booking_link", {"type": "test_drive"})],
    ),
    (
        re.compile(r"(link\s*bảo\s*dưỡng|lịch\s*bảo\s*dưỡng)", re.I),
        lambda m: [("get_maintenance_link", {"car_model": m or "VF 8"})],
    ),
    (re.compile(r"(khuyến\s*mãi|ưu\s*đãi|voucher)", re.I), lambda m: [("get_active_promotions", {"model_code": m})]),
    (re.compile(r"(hotline|liên\s*hệ|gặp\s*sales)", re.I), lambda m: [("get_showroom_charging_link", {})]),
]


def _norm_model(raw: str) -> str:
    return normalize_model(raw)


def _models_in_query(query: str, model: str | None) -> list[str]:
    found = {_norm_model(m) for m in MODEL_RE.findall(query)}
    if model:
        found.add(_norm_model(model))
    return sorted(found)


def needs_kb(state) -> bool:
    return state.get("category", "") in _NEEDS_KB


def build_tool_plan(state) -> list[tuple[str, dict]] | None:
    """Intent + entities → [(tool, args)]. None = không đủ điều kiện (→ LLM loop/clarify)."""
    intent = state.get("intent") or classify_intent(state.get("query", ""), state.get("category", "general"))
    entities = state.get("entities") or {}
    query = state.get("query", "")
    model = entities.get("model_code")
    version = entities.get("version")
    category = entities.get("spec_category") or _TOPIC_TO_CATEGORY.get(state.get("category", ""))

    if intent == "out_of_scope":
        return []

    if intent == "utility":
        for pat, plan_fn in _UTILITY_PATTERNS:
            if pat.search(query):
                return plan_fn(model)
        return [("get_showroom_charging_link", {})]

    if intent == "price":
        if not model:
            return None
        return [("get_price", {"model_code": model, "version": version})]

    if intent == "spec_query":
        if not model:
            return None
        return [("get_specs", {"model_code": model, "version": version, "category": category})]

    if intent == "feature_presence":
        if not model:
            return None
        # version=None → get_specs trả về TẤT CẢ phiên bản (đủ để trả lời "bản nào có")
        # keys=[spec_key] → chỉ lấy đúng field cần (context nhỏ, generate nhanh)
        args: dict = {"model_code": model, "version": None, "category": category}
        if entities.get("spec_key"):
            args["keys"] = [entities["spec_key"]]
        return [("get_specs", args)]

    if intent == "cross_model_feature":
        # scan toàn bộ model chính — chỉ lấy đúng field cần (feature check)
        args = {"version": None, "category": category}
        if entities.get("spec_key"):
            args["keys"] = [entities["spec_key"]]
        return [("get_specs", {"model_code": m, **args}) for m in MAIN_MODELS]

    if intent == "compare":
        models = _models_in_query(query, model)
        if not models:
            return None
        calls = [("get_specs", {"model_code": m, "version": None, "category": category}) for m in models]
        if re.search(r"(giá|bao\s*nhiêu\s*tiền)", query, re.I):
            calls += [("get_price", {"model_code": m, "version": None}) for m in models]
        return calls

    if intent == "versions_list":
        if not model:
            return None
        # get_price trả về đủ phiên bản + giá (nhẹ hơn get_specs toàn bộ)
        return [("get_price", {"model_code": model, "version": None})]

    if intent == "models_list":
        return [("list_available_models", {})]

    if intent == "colors":
        if not model:
            return None
        return [("get_colors", {"model_code": model, "version": version})]

    # policy / general → knowledge base (nội dung chính sách, bảo hành...)
    return [("search_knowledge_base", {"query": query, "model_id": model})]


def build_direct_plan(state) -> dict | None:
    """Alias cũ (edges/direct_fetch dùng). Trả {calls: [...]} hoặc None."""
    plan = build_tool_plan(state)
    if plan is None:
        return None
    return {"calls": plan}
