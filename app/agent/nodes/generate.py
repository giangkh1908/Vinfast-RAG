import logging
import time

from openai import AsyncOpenAI

from app.config import settings
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.generate")


async def generate_node(state: AgentState) -> dict:
    if state.get("final_response"):
        return {}

    messages = list(state["messages"])
    tool_results = state.get("tool_results", [])

    if not tool_results:
        return {"final_response": "", "decision": "refuse", "reason_code": "insufficient_evidence"}

    messages.append({
        "role": "user",
        "content": "Dựa vào kết quả tool trên, trả lời câu hỏi gốc. Dẫn nguồn URL khi có.",
    })

    llm = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tool_choice="none",
        )
        final_response = resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("generate_node LLM error: %s", e)
        return {
            "final_response": "",
            "decision": "refuse",
            "reason_code": "system_error",
            "response_text": "Mình chưa thể hoàn tất câu trả lời lúc này. Vui lòng thử lại.",
        }

    return {"final_response": final_response, "messages": messages}
