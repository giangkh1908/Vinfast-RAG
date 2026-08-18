import logging
import re

from app.agent.classifier import get_classifier, MODEL_RE
from app.agent.intent import (
    classify_intent,
    extract_spec_category,
    extract_spec_key,
    llm_classify_fallback,
)
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.classify")

# Câu trả lời mặc định cho các case không trả lời được
_DEFAULT_REPLY = "Xin lỗi, mình chưa có thông tin phù hợp. Bạn có thể hỏi lại bằng câu khác được không?"

VERSION_QUERY_RE = re.compile(
    r"(phi[eê]n\s+b[aả]n|b[aả]n\s+n[aà]o|c[oó]\s+m[aấ]y\s+b[aả]n|version|edition|có\s*mấy)",
    re.IGNORECASE,
)

_AMBIGUOUS_PRONOUN_RE = re.compile(
    r"(xe\s*này|mẫu\s*này|chiếc\s*này|em\s*này)",
    re.IGNORECASE,
)

# Utility queries — don't require model, LLM calls utility tools directly
_UTILITY_QUERY_RE = re.compile(
    r"(showroom|trạm\s*sạc|đại\s*lý|cửa\s*hàng|chi\s*nhánh|"
    r"lái\s*thử|test\s*drive|đăng\s*ký\s*lái|"
    r"bảo\s*dưỡng|đặt\s*lịch|booking|"
    r"trả\s*góp|vay|thẩm\s*định|lăn\s*bánh|"
    r"khuyến\s*mãi|ưu\s*đãi|voucher|"
    r"hotline|liên\s*hệ|gặp\s*sales)",
    re.IGNORECASE,
)

# ── Topic classification (spec's 9 supported topics) ────────────────────────

_TOPIC_KEYWORDS = {
    "pin_và_sạc": [
        r"sạc\s*nhanh", r"sạc\s*chậm", r"sạc\s*đầy", r"thời\s*gian\s*sạc",
        r"trạm\s*sạc", r"charger", r"charging", r"ổ\s*điện",
        r"pin\s*(lithium|lipo|LFP)", r"dung\s*lượng\s*pin",
        r"sạc", r"nạp\s*pin", r"phút.*10.*70", r"10.*70.*phút",
    ],
    "phạm_vi_di_chuyển": [
        r"đi\s*được\s*bao\s*xa", r"di\s*chuyển",
        r"range", r"phạm\s*vi", r"đi\s*được\s*bao\s*nhiêu\s*km",
        r"quãng\s*đường",
    ],
    "an_toàn": [
        r"túi\s*khí", r"airbag", r"ADAS", r"phanh", r"ABS", r"EBD", r"ESC",
        r"collision", r"cảnh\s*báo", r"camera\s*lùi", r"camera\s*360",
        r"an\s*toàn", r"an\s*toàn\s*không", r"có\s*an\s*toàn",
    ],
    "nội_thất": [
        r"nội\s*thất", r"ghế", r"số\s*chỗ", r"chỗ\s*ngồi", r"mấy\s*chỗ",
        r"5\s*chỗ", r"7\s*chỗ",
        r"màn\s*hình", r"loa", r"âm\s*thanh",
        r"điều\s*hòa", r"khoang\s*xe", r"vô\s*lăng", r"HUD",
        r"leatherette", r"speaker", r"display",
    ],
    "ngoại_thất": [
        r"ngoại\s*thất", r"đèn", r"màu\s*xe", r"mâm", r"la-zăng",
        r"gương", r"body", r"design", r"kiểu\s*dáng",
        r"headlight", r"tail\s*light", r"DRL",
    ],
    "tính_năng_nổi_bật": [
        r"tính\s*năng", r"trang\s*bị", r"công\s*nghệ", r"thông\s*minh",
        r"tiện\s*nghi", r"OTA", r"navigation", r"bluetooth",
        r"apple\s*carplay", r"android\s*auto", r"gaming",
    ],
    "phiên_bản": [
        r"phiên\s*bản", r"version", r"bản\s*nào", r"có\s*mấy\s*bản",
        r"danh\s*sách", r"khác\s*nhau\s*giữa",
    ],
    "kích_thước": [
        r"kích\s*thước", r"chiều\s*dài", r"chiều\s*rộng", r"chiều\s*cao",
        r"trọng\s*lượng", r"wheelbase", r"không\s*gian",
        r"ốp\s*lưng", r"boot", r"cốp",
    ],
    "thông_số_kỹ_thuật": [
        r"công\s*suất", r"mô[\s-]*men", r"xoắn", r"tốc\s*độ", r"tốc\s*tối\s*đa",
        r"battery", r"kWh", r"pin(?!.*sạc)",
        r"trọng\s*lượng", r"wheelbase", r"ground\s*clearance",
        r"power", r"torque", r"speed", r"km/h", r"Nm", r"kW",
        r"thông\s*số", r"specs", r"spec", r"trọng\s*tải",
        r"tăng\s*tốc", r"gia\s*tốc", r"tốc\s*độ\s*tối\s*đa",
    ],
    "giá": [
        r"giá\s*bao\s*nhiêu", r"giá\s*bán", r"giá\s*niêm\s*yết",
        r"bao\s*nhiêu\s*tiền", r"chi\s*phí", r"ưu\s*đãi",
        r"giá\s*(xe|VF)", r"price",
    ],
}

_TOPIC_RE = {topic: re.compile("|".join(kw), re.IGNORECASE) for topic, kw in _TOPIC_KEYWORDS.items()}

# Topic → allowed tools
# Note: execute_tools_node auto-injects search_knowledge_base parallel to get_specs/get_colors
_TOPIC_TOOLS = {
    "thông_số_kỹ_thuật": {"get_specs", "ask_clarification"},
    "pin_và_sạc": {"get_specs", "ask_clarification"},
    "phạm_vi_di_chuyển": {"get_specs", "ask_clarification"},
    "an_toàn": {"get_specs", "ask_clarification"},
    "nội_thất": {"get_specs", "ask_clarification"},
    "ngoại_thất": {"get_specs", "ask_clarification"},
    "tính_năng_nổi_bật": {"get_specs", "ask_clarification"},
    "phiên_bản": {"list_available_models", "get_specs", "ask_clarification"},
    "kích_thước": {"get_specs", "ask_clarification"},
    "giá": {"get_price", "ask_clarification"},
    "general": None,
}

# Topics where data typically differs between versions — require version (BDS-03)
_VERSION_DEPENDENT_TOPICS = {"thông_số_kỹ_thuật", "phạm_vi_di_chuyển"}


def _classify_topic(query: str) -> str:
    for topic, pattern in _TOPIC_RE.items():
        if pattern.search(query):
            return topic
    return "general"


def _is_broad_topic(query: str) -> bool:
    """Check if query is too broad (BDS-05)."""
    broad_patterns = [
        r"(cho\s*tôi\s*biết|thông\s*tin\s*về|giới\s*thiệu|"
        r"có\s*gì\s*hay|tổng\s*quan|overview|"
        r"thế\s*nào|như\s*thế\s*nào|ra\s*sao)",
    ]
    broad_re = re.compile("|".join(broad_patterns), re.IGNORECASE)
    return bool(broad_re.search(query))


def _extract_history_context(history: list[dict]) -> dict:
    """Extract model, version, and topic from conversation history.

    Duyệt NGƯỢC (mới → cũ) để lấy model/version/topic GẦN NHẤT — follow-up bỏ trống
    model (VD "pin xe bao nhiêu") phải dùng model vừa nói ở lượt trước (VF 8 sau
    "vf8 thì sao"), chứ không phải model đầu hội thoại (VF 6).
    """
    ctx: dict = {"model_code": None, "version": None, "topic": None}
    classifier = get_classifier()
    for msg in reversed(history):
        if msg.get("role") != "user":
            continue
        text = msg.get("content", "")
        try:
            cr = classifier.classify(text)
        except Exception:
            cr = None
        if cr is not None:
            if not ctx["model_code"] and cr.entities.get("model_code"):
                ctx["model_code"] = cr.entities["model_code"]
            if not ctx["version"] and cr.entities.get("version"):
                ctx["version"] = cr.entities["version"]
        if not ctx["topic"]:
            t = _classify_topic(text)
            if t != "general":
                ctx["topic"] = t
    return ctx


def _is_followup_to_clarify(history: list[dict]) -> bool:
    """Check if conversation indicates a follow-up to a clarify question."""
    if not history:
        return False
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = msg.get("content", "").lower()
            clarify_indicators = [
                "bạn muốn hỏi", "bạn muốn tìm", "phiên bản nào",
                "vf 6 hay vf 8", "vf6 hay vf8",
                "thông tin nào", "chủ đề nào",
            ]
            return any(ind in content for ind in clarify_indicators)
    return False


async def classify_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])

    classifier = get_classifier()
    cr = classifier.classify(query, history)

    # ── Decision Order ──

    # Classifier always returns "answer" now (no OOS).
    # If classifier returned clarify (multi-model), handle it.
    if cr.decision == "clarify":
        return {
            "decision": "clarify",
            "reason_code": "missing_context",
            "response_text": _DEFAULT_REPLY,
            "entities": cr.entities,
            "specificity": "unclear",
        }

    # ── Extract history context for multi-turn ──
    hist_ctx = _extract_history_context(history)
    is_followup = _is_followup_to_clarify(history)

    # Merge history model/version into entities if current turn missing them
    if not cr.entities.get("model_code") and hist_ctx["model_code"]:
        cr.entities["model_code"] = hist_ctx["model_code"]
    if not cr.entities.get("version") and hist_ctx["version"]:
        cr.entities["version"] = hist_ctx["version"]

    has_model = bool(cr.entities.get("model_code"))
    has_version = bool(cr.entities.get("version"))
    topic = _classify_topic(query)

    # Inherit topic from history if current query topic is general
    if topic == "general" and hist_ctx["topic"]:
        topic = hist_ctx["topic"]

    # ── Hybrid intent: rule trước → LLM fallback khi rule ra "general" ──
    # TÍNH TRƯỚC các nhánh clarify — intent cụ thể (price/policy/spec...) không
    # được phép bị chặn bởi "broad topic" hay "missing model" không cần thiết.
    entities = dict(cr.entities)
    intent = classify_intent(query, topic)
    # Fallback rule: query có keyword spec rõ ("công suất", "sạc"...) nhưng chưa
    # match intent rule → coi là spec_query (category từ map, không để LLM đoán)
    if intent == "general" and extract_spec_category(query):
        intent = "spec_query"
    spec_category = (
        extract_spec_category(query)
        if intent in ("spec_query", "feature_presence", "cross_model_feature", "compare")
        else None
    )
    # Feature check: intent so sánh/kiểm tra 1 tính năng cụ thể → lấy ĐÚNG field
    spec_key = extract_spec_key(query) if intent in ("feature_presence", "cross_model_feature") else None

    # Intent KHÔNG cần model → đi thẳng (KB search, cross-model scan, danh sách, link...)
    _NO_MODEL_INTENTS = {"greeting", "thanks", "identity", "cross_model_feature", "models_list", "policy", "general", "utility", "out_of_scope"}

    # Xử lý các câu chào hỏi / cảm ơn / giới thiệu bot thân thiện như Vivi VinFast
    if intent == "greeting":
        return {
            "decision": "respond",
            "reason_code": "greeting",
            "response_text": "Xin chào Quý khách! Vivi rất hân hạnh được hỗ trợ. Quý khách đang quan tâm đến sản phẩm hoặc dịch vụ nào của VinFast ạ? 😊",
            "entities": entities,
            "specificity": "clear",
            "category": "general",
            "intent": "greeting",
        }
    if intent == "thanks":
        return {
            "decision": "respond",
            "reason_code": "thanks",
            "response_text": "Dạ không có gì ạ! Vivi rất vui được hỗ trợ Quý khách. Nếu cần thêm thông tin gì về xe VinFast, Quý khách cứ nhắn Vivi nhé! 😊",
            "entities": entities,
            "specificity": "clear",
            "category": "general",
            "intent": "thanks",
        }
    if intent == "identity":
        return {
            "decision": "respond",
            "reason_code": "identity",
            "response_text": "Xin chào Quý khách! Mình là Vivi — trợ lý ảo tư vấn xe VinFast. Mình có thể hỗ trợ Quý khách tra cứu thông tin sản phẩm, giá bán, thông số kỹ thuật, so sánh xe và các chính sách ưu đãi của các dòng ô tô điện VinFast (VF 3, VF 5, VF 6, VF 7, VF 8, VF 9...). Quý khách đang quan tâm đến mẫu xe nào ạ? 😊",
            "entities": entities,
            "specificity": "clear",
            "category": "general",
            "intent": "identity",
        }

    # Missing model — chỉ clarify khi intent THẬT SỰ cần model
    if not has_model and intent not in _NO_MODEL_INTENTS:
        if _AMBIGUOUS_PRONOUN_RE.search(query):
            return {
                "decision": "clarify",
                "reason_code": "ambiguous_context",
                "response_text": _DEFAULT_REPLY,
                "entities": cr.entities,
                "specificity": "unclear",
                "category": topic,
            }
        return {
            "decision": "clarify",
            "reason_code": "missing_model",
            "response_text": _DEFAULT_REPLY,
            "entities": cr.entities,
            "specificity": "unclear",
            "category": topic,
        }

    # Broad topic / Tổng quan: Nếu đã có model (VF 3, VF 8...) thì cho phép trả lời tổng quan (KB search) thay vì từ chối
    # Missing version → KHÔNG ngắt hỏi lại (UX kém). Chuyển decision=answer,
    # prompt sẽ điều hướng LLM trả lời bản mặc định (Eco) + liệt kê bản khác.

    # LLM fallback (hybrid) — rule vẫn "general" nhưng query rõ ràng là câu hỏi thật
    if intent == "general" and (has_model or len(query.split()) >= 4):
        llm_res = await llm_classify_fallback(query, history)
        if llm_res:
            intent = llm_res["intent"]
            if llm_res.get("model_code") and not entities.get("model_code"):
                entities["model_code"] = llm_res["model_code"]
            if llm_res.get("version") and not entities.get("version"):
                entities["version"] = llm_res["version"]
            if llm_res.get("spec_category"):
                spec_category = llm_res["spec_category"]

    if spec_category:
        entities["spec_category"] = spec_category
    if spec_key:
        entities["spec_key"] = spec_key

    # Answer
    return {
        "decision": "answer",
        "reason_code": "sufficient_direct_evidence",
        "entities": entities,
        "specificity": cr.specificity,
        "category": topic,
        "intent": intent,
        "allowed_tools": _TOPIC_TOOLS.get(topic),
    }
