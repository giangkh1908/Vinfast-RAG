from langgraph.graph import StateGraph, END

from app.agent.graph_state import AgentState
from app.agent.nodes.classify import classify_node
from app.agent.nodes.messages import build_messages_node
from app.agent.nodes.tools import execute_tools_node
from app.agent.nodes.generate import generate_node
from app.agent.nodes.validate import validate_node
from app.agent.nodes.respond import respond_node
from app.agent.edges import route_after_classify, route_after_tools, route_after_validate


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("classify", classify_node)
    g.add_node("build_messages", build_messages_node)
    g.add_node("execute_tools", execute_tools_node)
    g.add_node("generate", generate_node)
    g.add_node("validate", validate_node)
    g.add_node("respond", respond_node)

    g.set_entry_point("classify")

    g.add_conditional_edges("classify", route_after_classify, {
        "out_of_scope": "respond",
        "respond": "respond",
        "build_messages": "build_messages",
    })

    g.add_edge("build_messages", "execute_tools")

    g.add_conditional_edges("execute_tools", route_after_tools, {
        "execute_tools": "execute_tools",
        "generate": "generate",
        "validate": "validate",
        "respond": "respond",
    })

    g.add_edge("generate", "validate")

    g.add_conditional_edges("validate", route_after_validate, {
        "respond": "respond",
    })

    g.add_edge("respond", END)

    return g


_compiled = None


def get_compiled_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph().compile()
    return _compiled
