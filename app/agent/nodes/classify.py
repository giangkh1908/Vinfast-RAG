import logging
import re

from app.agent.classifier import get_classifier
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.classify")

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
        r"nội\s*thất", r"ghế", r"màn\s*hình", r"loa", r"âm\s*thanh",
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
        r"chỗ\s*ngồi", r"ốp\s*lưng", r"boot", r"cốp",
    ],
    "thông_số_kỹ_thuật": [
        r"công\s*suất", r"mô[\s-]*men", r"xoắn", r"tốc\s*độ", r"tốc\s*tối\s*đa",
        r"battery", r"kWh", r"pin(?!.*sạc)",
        r"trọng\s*lượng", r"wheelbase", r"ground\s*clearance",
        r"power", r"torque", r"speed", r"km/h", r"Nm", r"kW",
        r"thông\s*số", r"specs", r"spec", r"trọng\s*tải",
        r"tăng\s*tốc", r"gia\s*tốc", r"tốc\s*độ\s*tối\s*đa",
    ],
}

_TOPIC_RE = {topic: re.compile("|".join(kw), re.IGNORECASE) for topic, kw in _TOPIC_KEYWORDS.items()}

# Topic → allowed tools
_TOPIC_TOOLS = {
    "thông_số_kỹ_thuật": {"get_specs", "search_all", "ask_clarification"},
    "pin_và_sạc": {"get_specs", "search_all", "ask_clarification"},
    "phạm_vi_di_chuyển": {"get_specs", "search_all", "ask_clarification"},
    # Feature topics: force search_all (specs + KB) — LLM tends to use get_specs
    # alone which returns raw specs without Vietnamese descriptions
    "an_toàn": {"search_all", "ask_clarification"},
    "nội_thất": {"search_all", "ask_clarification"},
    "ngoại_thất": {"search_all", "ask_clarification"},
    "tính_năng_nổi_bật": {"search_all", "ask_clarification"},
    "phiên_bản": {"list_available_models", "get_specs", "ask_clarification"},
    "kích_thước": {"get_specs", "search_all", "ask_clarification"},
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
    """Extract model, version, and topic from conversation history."""
    ctx: dict = {"model_code": None, "version": None, "topic": None}
    classifier = get_classifier()
    for msg in history:
        if msg.get("role") != "user":
            continue
        text = msg.get("content", "")
        try:
            cr = classifier.classify(text)
            if cr.entities.get("model_code") and not ctx["model_code"]:
                ctx["model_code"] = cr.entities["model_code"]
            if cr.entities.get("version") and not ctx["version"]:
                ctx["version"] = cr.entities["version"]
        except Exception:
            pass
        t = _classify_topic(text)
        if t != "general" and not ctx["topic"]:
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
            "response_text": "Bạn muốn hỏi về xe nào?",
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

    # Missing model — but utility queries don't need model
    if not has_model:
        # Utility queries (showroom, charging, booking, loan, promotions) → answer directly
        if _UTILITY_QUERY_RE.search(query):
            return {
                "decision": "answer",
                "reason_code": "utility_query",
                "entities": cr.entities,
                "specificity": "unclear",
                "category": "utility",
            }
        if _AMBIGUOUS_PRONOUN_RE.search(query):
            return {
                "decision": "clarify",
                "reason_code": "ambiguous_context",
                "response_text": "Bạn muốn hỏi về xe nào?",
                "entities": cr.entities,
                "specificity": "unclear",
                "category": topic,
            }
        if topic != "general":
            return {
                "decision": "clarify",
                "reason_code": "missing_model",
                "response_text": "Bạn muốn hỏi về xe VinFast nào?",
                "entities": cr.entities,
                "specificity": "unclear",
                "category": topic,
            }

    # Broad topic (model known, topic vague, NOT a follow-up)
    if has_model and topic == "general" and _is_broad_topic(query) and not is_followup:
        model = cr.entities["model_code"]
        return {
            "decision": "clarify",
            "reason_code": "missing_topic",
            "response_text": f"Bạn muốn tìm thông tin nào về {model}?",
            "entities": cr.entities,
            "specificity": "unclear",
            "category": "general",
        }

    # Missing version (only for version-dependent topics)
    if has_model and not has_version and not VERSION_QUERY_RE.search(query):
        if topic in _VERSION_DEPENDENT_TOPICS:
            model = cr.entities["model_code"]
            return {
                "decision": "clarify",
                "reason_code": "missing_version",
                "response_text": f"Bạn muốn hỏi phiên bản nào của {model}?",
                "entities": cr.entities,
                "specificity": "unclear",
                "category": topic,
            }

    # Answer
    return {
        "decision": "answer",
        "reason_code": "sufficient_direct_evidence",
        "entities": cr.entities,
        "specificity": cr.specificity,
        "category": topic,
        "allowed_tools": _TOPIC_TOOLS.get(topic),
    }
