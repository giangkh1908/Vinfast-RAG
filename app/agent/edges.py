from app.agent.graph_state import AgentState
from app.agent.direct_plan import build_direct_plan

MAX_ITERATIONS = 3


def route_after_classify(state: AgentState) -> str:
    """Route after classify_node. Trust classify_node's decision."""
    decision = state.get("decision", "answer")
    if decision in ("out_of_scope", "clarify", "refuse"):
        return "respond"
    if build_direct_plan(state) is not None:
        return "direct_fetch"
    return "build_messages"


def route_after_tools(state: AgentState) -> str:
    if state.get("decision") == "refuse":
        return "respond"
    if state.get("decision") == "clarify":
        return "respond"
    final = state.get("final_response", "")
    if final:
        # Only re-generate if LLM refused without checking data
        refusal_phrases = (
            "chưa thể xác nhận", "không có thông tin",
            "hiện chưa có", "không có dữ liệu",
        )
        if any(p in final.lower() for p in refusal_phrases):
            return "generate"
        return "validate"
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return "generate"
    return "execute_tools"


def route_after_validate(state: AgentState) -> str:
    return "respond"
