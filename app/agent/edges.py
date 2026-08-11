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
    if state.get("final_response"):
        return "validate"
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return "generate"
    return "execute_tools"


def route_after_validate(state: AgentState) -> str:
    return "respond"
