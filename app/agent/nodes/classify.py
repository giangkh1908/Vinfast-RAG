import logging
import re

from app.config import settings
from app.agent.classifier import get_classifier
from app.agent.decision import get_oos_messages, get_clarify_messages
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.classify")

VERSION_QUERY_RE = re.compile(
    r"(phi[eê]n\s+b[aả]n|b[aả]n\s+n[aà]o|c[oó]\s+m[aấ]y\s+b[aả]n|version|edition|có\s+mấy)",
    re.IGNORECASE,
)


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

    if has_model and not has_version and not VERSION_QUERY_RE.search(query):
        clarify_msgs = get_clarify_messages()
        model = cr.entities["model_code"]
        return {
            "decision": "clarify",
            "reason_code": "missing_version",
            "response_text": f"Bạn muốn hỏi phiên bản nào của {model}? ({', '.join(settings.scope_versions)})",
            "entities": cr.entities,
            "specificity": "unclear",
        }

    return {
        "decision": "answer",
        "reason_code": "sufficient_direct_evidence",
        "entities": cr.entities,
        "specificity": cr.specificity,
    }
