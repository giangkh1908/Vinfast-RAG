"""Direct fetch node — chạy tool plan deterministic (không cần LLM chọn tool).

Kết quả cùng shape với execute_tools_node để validate/generate/respond
dùng lại nguyên vẹn.
"""

import asyncio
import logging
import time

from app.agent.direct_plan import build_direct_plan, needs_kb
from app.agent.graph_state import AgentState
from app.agent.llm import INPUT_MAX_TOKENS, truncate_messages
from app.agent.prompts import build_system_message
from app.agent.tools import TOOL_REGISTRY

logger = logging.getLogger("bds.graph.direct")


async def direct_fetch_node(state: AgentState) -> dict:
    t0 = time.time()
    plan = build_direct_plan(state)
    entities = state.get("entities") or {}
    tool_results: list[dict] = []

    if plan:
        # Gọi TẤT CẢ tool song song, BAO GỒM cả search_knowledge_base nếu cần
        names_args = plan["calls"]
        coros = []
        for name, args in names_args:
            func = TOOL_REGISTRY.get(name)
            coros.append(func(**args) if func else None)

        # Auto-inject knowledge base NGAY TỪ ĐẦU (song song với các tool khác)
        # BỎ QUA khi intent là feature check — specs đã đủ, KB noise làm phình context
        kb_task = None
        if needs_kb(state) and state.get("intent") not in ("feature_presence", "cross_model_feature"):
            model_code = entities.get("model_code", "")
            if model_code:
                from app.agent.tools import search_knowledge_base

                kb_task = search_knowledge_base(state.get("query", ""), model_id=model_code)
                coros.append(kb_task)

        # Chạy TẤT CẢ song song
        gathered = await asyncio.gather(*coros, return_exceptions=True)

        # Xử lý kết quả từ các tool chính
        for (name, args), res in zip(names_args, gathered[: len(names_args)], strict=False):
            if isinstance(res, Exception):
                logger.warning("direct %s(%s) failed: %s", name, args, res)
                tool_results.append({"tool": name, "result": {"error": str(res)}, "success": False})
            else:
                tool_results.append({"tool": name, "result": res, "success": True})

        # Xử lý kết quả từ knowledge base (nếu có)
        if kb_task:
            kb_result = gathered[-1]  # KB result là cái cuối cùng
            if isinstance(kb_result, Exception):
                logger.warning("direct KB inject failed: %s", kb_result)
            else:
                tool_results.append(
                    {
                        "tool": "search_knowledge_base",
                        "result": kb_result,
                        "success": True,
                        "auto_injected": True,
                    }
                )

    # Build messages để generate_node có system prompt + lịch sử
    messages = [await build_system_message(state.get("summary"))]
    for msg in state.get("history", []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": state["query"]})

    # Input budget: drop history cũ / cắt message dài nếu vượt tổng token
    truncate_messages(messages, INPUT_MAX_TOKENS)

    return {
        "messages": messages,
        "tool_results": tool_results,
        "iteration": 1,
        "t_retrieve_start": t0,
        "t_retrieve_end": time.time(),
    }
