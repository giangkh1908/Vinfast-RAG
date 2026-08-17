from app.agent.prompts import build_system_message
from app.agent.graph_state import AgentState
from app.agent.llm import INPUT_MAX_TOKENS, truncate_messages


async def build_messages_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])  # đã sanitize + bounded (≤7 turn)

    messages = [await build_system_message(state.get("summary"))]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": query})

    # Input budget: drop history cũ / cắt message dài nếu vượt tổng token
    truncate_messages(messages, INPUT_MAX_TOKENS)

    return {"messages": messages, "iteration": 0, "tool_results": []}
