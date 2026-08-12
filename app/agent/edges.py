import re

from app.agent.graph_state import AgentState

MAX_ITERATIONS = 3


def route_after_classify(state: AgentState) -> str:
    """Route after classify_node. Trust classify_node's decision."""
    decision = state.get("decision", "answer")
    if decision == "out_of_scope":
        return "respond"
    if decision == "clarify":
        return "respond"
    if decision == "refuse":
        return "respond"
    return "build_messages"


def route_after_tools(state: AgentState) -> str:
    if state.get("decision") == "refuse":
        return "respond"
    if state.get("decision") == "clarify":
        return "respond"
    final = state.get("final_response", "")
    if final:
        # Only re-generate if LLM refused without checking data
        # Otherwise go straight to validate (saves 1 LLM call)
        refusal_re = __import__("re").compile(
            r"(chưa thể xác nhận|không có thông tin|hiện chưa có|không có dữ liệu)",
            __import__("re").IGNORECASE,
        )
        if refusal_re.search(final):
            return "generate"  # Re-synthesize with context_builder
        return "validate"      # LLM answered, validate it
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return "generate"
    return "execute_tools"


def route_after_validate(state: AgentState) -> str:
    return "respond"
