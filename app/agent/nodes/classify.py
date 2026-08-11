import logging
import re

from app.config import settings
from app.agent.classifier import get_classifier
from app.agent.decision import get_oos_messages
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.classify")

VERSION_QUERY_RE = re.compile(
    r"(phi[eê]n\s+b[aả]n|b[aả]n\s+n[aà]o|c[oó]\s+m[aấ]y\s+b[aả]n|version|edition|có\s+mấy)",
    re.IGNORECASE,
)

# ── Topic classification (spec's 9 supported topics) ────────────────────────

_TOPIC_KEYWORDS = {
    "thông_số_kỹ_thuật": [
        r"công\s*suất", r"mô[\s-]*men", r"xoắn", r"tốc\s*độ", r"tốc\s*tối\s*đa",
        r"quãng\s*đường", r"phạm\s*vi\s*di\s*chuyển",
        r"pin", r"dung\s*lượng", r"sạc", r"battery", r"range",
        r"kích\s*thước", r"chiều\s*dài", r"chiều\s*rộng", r"chiều\s*cao",
        r"trọng\s*lượng", r"wheelbase", r"ground\s*clearance",
        r"power", r"torque", r"speed", r"km/h", r"kWh", r"Nm", r"kW",
        r"thông\s*số", r"specs", r"spec", r"trọng\s*tải",
    ],
    "pin_và_sạc": [
        r"sạc\s*nhanh", r"sạc\s*chậm", r"sạc\s*đầy", r"thời\s*gian\s*sạc",
        r"trạm\s*sạc", r"charger", r"charging", r"ổ\s*điện",
        r"pin\s*(lithium|lipo|LFP)", r"dung\s*lượng\s*pin",
    ],
    "phạm_vi_di_chuyển": [
        r"đi\s*được\s*bao\s*xa", r"quãng\s*đường", r"di\s*chuyển",
        r"range", r"phạm\s*vi", r"đi\s*được\s*bao\s*nhiêu\s*km",
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
}

_TOPIC_RE = {topic: re.compile("|".join(kw), re.IGNORECASE) for topic, kw in _TOPIC_KEYWORDS.items()}

# Topic → allowed tools
_TOPIC_TOOLS = {
    "thông_số_kỹ_thuật": {"get_specs", "search_all", "ask_clarification"},
    "pin_và_sạc": {"get_specs", "search_knowledge_base", "search_all", "ask_clarification"},
    "phạm_vi_di_chuyển": {"get_specs", "search_all", "ask_clarification"},
    "an_toàn": {"get_specs", "search_knowledge_base", "search_all", "ask_clarification"},
    "nội_thất": {"search_knowledge_base", "search_all", "get_specs", "ask_clarification"},
    "ngoại_thất": {"search_knowledge_base", "search_all", "get_specs", "ask_clarification"},
    "tính_năng_nổi_bật": {"search_knowledge_base", "search_all", "get_specs", "ask_clarification"},
    "phiên_bản": {"list_available_models", "get_specs", "ask_clarification"},
    "kích_thước": {"get_specs", "search_all", "ask_clarification"},
    "general": None,
}

# Topics where data is typically the same across versions (BDS-04)
_VERSION_INDEPENDENT_TOPICS = {
    "kích_thước", "phiên_bản",
}


def _classify_topic(query: str) -> str:
    for topic, pattern in _TOPIC_RE.items():
        if pattern.search(query):
            return topic
    return "general"


def _is_broad_topic(query: str) -> bool:
    """Check if query is too broad (BDS-05)."""
    broad_patterns = [
        r"(cho\s*tôi\s*biết|thông\s*tin\s*về|giới\s*thiệu|"
        r"có\s*gì\s*hay|thế\s*nào|như\s*thế\s*nào|"
        r"xe\s*này|tổng\s*quan|overview)",
    ]
    broad_re = re.compile("|".join(broad_patterns), re.IGNORECASE)
    return bool(broad_re.search(query))


async def classify_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])

    classifier = get_classifier()
    cr = classifier.classify(query, history)

    # ── Decision Order (spec section 3) ──

    # 1. OOS check (BDS-02A, BDS-10..17)
    if cr.decision == "out_of_scope":
        oos_msgs = get_oos_messages()
        oos_type = "model_oos"
        for key in oos_msgs:
            if key in cr.reason:
                oos_type = key
                break
        return {
            "decision": "out_of_scope",
            "reason_code": oos_type,
            "response_text": oos_msgs.get(oos_type, oos_msgs.get("model_oos", "")),
            "entities": cr.entities,
            "specificity": cr.specificity,
        }

    # BDS-10: Multi-model clarify (handled by classifier)
    if cr.decision == "clarify":
        ml = " hoặc ".join(settings.scope_models)
        return {
            "decision": "clarify",
            "reason_code": cr.reason.split(":")[0] if ":" in cr.reason else "missing_context",
            "response_text": f"Bạn muốn hỏi về {ml}?",
            "entities": cr.entities,
            "specificity": "unclear",
        }

    has_model = bool(cr.entities.get("model_code"))
    has_version = bool(cr.entities.get("version"))
    topic = _classify_topic(query)

    # 2. BDS-02: Missing model
    if not has_model and topic != "general":
        ml = " hoặc ".join(settings.scope_models)
        return {
            "decision": "clarify",
            "reason_code": "missing_model",
            "response_text": f"Bạn muốn hỏi về {ml}?",
            "entities": cr.entities,
            "specificity": "unclear",
            "category": topic,
        }

    # 3. BDS-05: Broad topic (when model is known but topic is vague)
    if has_model and _is_broad_topic(query):
        model = cr.entities["model_code"]
        return {
            "decision": "clarify",
            "reason_code": "missing_topic",
            "response_text": f"Bạn muốn tìm thông tin nào về {model}: phiên bản, thông số, pin/sạc, phạm vi di chuyển, an toàn, nội thất hay ngoại thất?",
            "entities": cr.entities,
            "specificity": "unclear",
            "category": "general",
        }

    # 4. BDS-03: Missing version (when data differs between versions)
    if has_model and not has_version and not VERSION_QUERY_RE.search(query):
        if topic not in _VERSION_INDEPENDENT_TOPICS:
            model = cr.entities["model_code"]
            return {
                "decision": "clarify",
                "reason_code": "missing_version",
                "response_text": f"Bạn muốn hỏi phiên bản nào của {model}? ({', '.join(settings.scope_versions)})",
                "entities": cr.entities,
                "specificity": "unclear",
                "category": topic,
            }

    # 5. BDS-01: Answer
    return {
        "decision": "answer",
        "reason_code": "sufficient_direct_evidence",
        "entities": cr.entities,
        "specificity": cr.specificity,
        "category": topic,
        "allowed_tools": _TOPIC_TOOLS.get(topic),
    }
