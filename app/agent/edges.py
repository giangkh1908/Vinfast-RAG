import re

from app.agent.graph_state import AgentState

MAX_ITERATIONS = 3

VERSION_QUERY_RE = re.compile(
    r"(phi[eê]n\s+b[aả]n|b[aả]n\s+n[aà]o|c[oó]\s+m[aấ]y\s+b[aả]n|version|edition|có\s+mấy)",
    re.IGNORECASE,
)


def route_after_classify(state: AgentState) -> str:
    if state.get("decision") == "out_of_scope":
        return "respond"
    if state.get("decision") == "clarify":
        return "respond"
    entities = state.get("entities", {})
    has_model = bool(entities.get("model_code"))
    has_version = bool(entities.get("version"))
    if has_model and not has_version:
        query = state.get("query", "")
        if VERSION_QUERY_RE.search(query):
            return "build_messages"
        return "respond"
    return "build_messages"


def route_after_tools(state: AgentState) -> str:
    if state.get("decision") == "refuse":
        return "respond"
    if state.get("decision") == "clarify":
        return "respond"
    if state.get("final_response"):
        return "validate"
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return "generate"
    return "execute_tools"


def route_after_validate(state: AgentState) -> str:
    return "respond"
