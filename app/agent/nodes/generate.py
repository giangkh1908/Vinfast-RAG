import logging
import re
import time

from openai import AsyncOpenAI

from app.config import settings
from app.agent.graph_state import AgentState
from app.agent.context_builder import build_structured_context
from app.agent.prompts import SYNTHESIZE_PROMPT

logger = logging.getLogger("bds.graph.generate")

_REFUSAL_RE = re.compile(
    r"(chưa thể xác nhận|không có thông tin|không đủ thông tin|"
    r"hiện chưa có|không có dữ liệu|không tìm thấy)",
    re.IGNORECASE,
)

_llm_client: AsyncOpenAI | None = None


def _get_llm() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    return _llm_client


async def generate_node(state: AgentState) -> dict:
    final_response = state.get("final_response", "")
    tool_results = state.get("tool_results", [])

    if not tool_results:
        return {"final_response": "", "decision": "refuse", "reason_code": "insufficient_evidence"}

    # If LLM already generated a real answer (not refusal), keep it
    if final_response and not _REFUSAL_RE.search(final_response):
        return {}

    # Re-generate using context_builder (has Vietnamese labels for spec keys)
    query = state.get("query", "")
    context = build_structured_context(tool_results, query=query)

    # Build history-aware query for multi-turn
    history = state.get("history", [])
    if history:
        history_context = "\n".join(
            f"{m['role']}: {m['content']}" for m in history[-4:]
        )
        full_query = f"Lịch sử hội thoại:\n{history_context}\n\nCâu hỏi hiện tại: {query}"
    else:
        full_query = query

    system_prompt = state["messages"][0]["content"] if state.get("messages") else ""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": SYNTHESIZE_PROMPT.format(context=context, query=full_query)},
    ]

    llm = _get_llm()
    t_generate_start = time.time()

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
        )
        new_response = resp.choices[0].message.content or ""
        if new_response:
            final_response = new_response
    except Exception as e:
        logger.error("generate_node LLM error: %s", e)
        return {
            "final_response": final_response,
            "t_generate_start": t_generate_start,
            "t_generate_end": time.time(),
        }

    return {
        "final_response": final_response,
        "t_generate_start": t_generate_start,
        "t_generate_end": time.time(),
    }
