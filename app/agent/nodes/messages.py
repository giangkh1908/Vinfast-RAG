from app.agent.prompts import get_system_prompt
from app.agent.graph_state import AgentState


async def build_messages_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])

    system_prompt = await get_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": query})

    return {"messages": messages, "iteration": 0, "tool_results": []}
