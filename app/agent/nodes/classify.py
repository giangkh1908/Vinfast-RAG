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

# Topic → tool routing
_TOPIC_KEYWORDS = {
    "specs": [
        r"công\s*suất", r"mô[\s-]*men", r"xoắn", r"tốc\s*độ", r"quãng\s*đường",
        r"pin", r"dung\s*lượng", r"phạm\s*vi", r"sạc", r"battery", r"range",
        r"kích\s*thước", r"chiều\s*dài", r"chiều\s*rộng", r"chiều\s*cao",
        r"trọng\s*lượng", r"wheelbase", r"ground\s*clearance",
        r"power", r"torque", r"speed", r"km/h", r"kWh", r"Nm", r"kW",
    ],
    "price": [
        r"giá", r"price", r"niêm\s*yết", r"ưu\s*đãi", r"bao\s*nhiêu",
        r"VNĐ", r"triệu", r"tỷ", r"trả\s*góp", r"lăn\s*bánh", r"cost",
    ],
    "features": [
        r"tính\s*năng", r"trang\s*bị", r"camera", r"HUD", r"ADAS",
        r"túi\s*khí", r"airbag", r"ghế", r"loa", r"đèn", r"màn\s*hình",
        r"nội\s*thất", r"ngoại\s*thất", r"an\s*toàn", r"phanh",
        r"cruise", r"lane", r"parking", r"bluetooth", r"navigation",
    ],
    "model_info": [
        r"phiên\s*bản", r"version", r"mẫu\s*xe", r"danh\s*sách",
        r"có\s*mấy", r"khác\s*nhau", r"so\s*sánh",
    ],
}

_TOPIC_RE = {topic: re.compile("|".join(kw), re.IGNORECASE) for topic, kw in _TOPIC_KEYWORDS.items()}


def _classify_topic(query: str) -> str:
    """Classify query topic for tool routing. Returns topic name."""
    for topic, pattern in _TOPIC_RE.items():
        if pattern.search(query):
            return topic
    return "general"


# Tools allowed per topic
_TOPIC_TOOLS = {
    "specs": {"get_specs", "search_all", "ask_clarification"},
    "price": {"get_price", "ask_clarification"},
    "features": {"search_knowledge_base", "search_all", "get_specs", "ask_clarification"},
    "model_info": {"list_available_models", "get_specs", "ask_clarification"},
    "general": None,  # None = no constraint, LLM decides
}


async def classify_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])

    classifier = get_classifier()
    cr = classifier.classify(query, history)

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

    has_model = bool(cr.entities.get("model_code"))
    has_version = bool(cr.entities.get("version"))
    topic = _classify_topic(query)

    # Missing model: ask clarification for topic-specific queries
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

    # Missing version (when model is known)
    if has_model and not has_version and not VERSION_QUERY_RE.search(query):
        model = cr.entities["model_code"]
        return {
            "decision": "clarify",
            "reason_code": "missing_version",
            "response_text": f"Bạn muốn hỏi phiên bản nào của {model}? ({', '.join(settings.scope_versions)})",
            "entities": cr.entities,
            "specificity": "unclear",
            "category": topic,
        }

    return {
        "decision": "answer",
        "reason_code": "sufficient_direct_evidence",
        "entities": cr.entities,
        "specificity": cr.specificity,
        "category": topic,
        "allowed_tools": _TOPIC_TOOLS.get(topic),
    }
