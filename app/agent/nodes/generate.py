import logging
import time

from openai import AsyncOpenAI

from app.config import settings
from app.agent.graph_state import AgentState
from app.agent.context_builder import build_structured_context
from app.agent.prompts import SYNTHESIZE_PROMPT

logger = logging.getLogger("bds.graph.generate")


async def generate_node(state: AgentState) -> dict:
    if state.get("final_response"):
        return {}

    tool_results = state.get("tool_results", [])

    if not tool_results:
        return {"final_response": "", "decision": "refuse", "reason_code": "insufficient_evidence"}

    context = build_structured_context(tool_results)
    query = state.get("query", "")

    system_prompt = state["messages"][0]["content"] if state.get("messages") else ""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": SYNTHESIZE_PROMPT.format(context=context, query=query)},
    ]

    llm = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    t_generate_start = time.time()

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
            "t_generate_start": t_generate_start,
        }

    return {"final_response": final_response, "t_generate_start": t_generate_start}
