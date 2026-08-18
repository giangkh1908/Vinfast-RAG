import asyncio
import json
import logging
import time

from openai import AsyncOpenAI

from app.config import settings
from app.agent.llm import TOOL_CALL_MAX_TOKENS, stream_chat_with_fallback
from app.agent.schemas import build_tool_schemas
from app.agent.tools import TOOL_REGISTRY
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.tools")

MAX_ITERATIONS = 3

_llm_client: AsyncOpenAI | None = None


class _ToolCall:
    """Giữ shape giống OpenAI tool_call object (tc.id, tc.function.name/arguments)
    vì stream response không có message hoàn chỉnh."""

    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        import types
        self.function = types.SimpleNamespace(name=name, arguments=arguments)


def _get_llm() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=settings.deepinfra_api_key, base_url=settings.deepinfra_base_url)
    return _llm_client


async def _execute_tools_parallel(tool_calls: list) -> list[dict]:
    async def _safe(tc):
        name = tc.function.name
        args = json.loads(tc.function.arguments)
        func = TOOL_REGISTRY.get(name)
        if not func:
            return {"tool": name, "result": {"error": f"Unknown tool: {name}"}, "success": False}
        try:
            result = await func(**args) if asyncio.iscoroutinefunction(func) else func(**args)
            return {"tool": name, "result": result, "success": True}
        except Exception as e:
            return {"tool": name, "result": {"error": str(e)}, "success": False}

    return await asyncio.gather(*[_safe(tc) for tc in tool_calls])


async def execute_tools_node(state: AgentState) -> dict:
    messages = list(state["messages"])
    tool_results = list(state.get("tool_results", []))
    iteration = state.get("iteration", 0)
    entities = state.get("entities", {})

    has_model = bool(entities.get("model_code"))
    has_version = bool(entities.get("version"))

    llm = _get_llm()
    tool_schemas = await build_tool_schemas()

    # Constrain tools based on topic classification from classify node
    allowed_tools = state.get("allowed_tools")
    if allowed_tools is not None:
        tool_schemas = [s for s in tool_schemas if s["function"]["name"] in allowed_tools]
        if not tool_schemas:
            tool_schemas = await build_tool_schemas()

    t_retrieve_start = state.get("t_retrieve_start") or time.time()

    # Force tool calls on first iteration when classify decided "answer"
    decision = state.get("decision", "answer")
    force_tool = "required" if (decision == "answer" and not tool_results) else "auto"

    # Stream LLM với fallback model (gemini chính → haiku dự phòng).
    # Fallback chỉ kích hoạt khi chưa stream token nào ra client.
    try:
        final_content, tool_calls_acc, _used_model = await stream_chat_with_fallback(
            llm,
            messages,
            tools=tool_schemas,
            tool_choice=force_tool,
            max_tokens=TOOL_CALL_MAX_TOKENS,
        )
    except Exception as e:
        logger.warning("LLM exhausted all models: %s", e)
        # Final fail: return with iteration increment so route_after_tools
        # eventually hits MAX_ITERATIONS and goes to generate_node
        return {
            "final_response": "",
            "iteration": iteration + 1,
            "t_retrieve_start": t_retrieve_start,
        }

    if not tool_calls_acc:
        return {
            "final_response": final_content,
            "messages": messages,
            "iteration": iteration + 1,
            "t_retrieve_start": t_retrieve_start,
        }

    tool_calls = [
        _ToolCall(v["id"] or f"call_{i}", v["name"], v["arguments"])
        for i, (_, v) in enumerate(sorted(tool_calls_acc.items()))
    ]

    # Kiểm tra xem có cần auto-inject KB không (chạy song song với tool calls)
    category = state.get("category", "general")
    _NEEDS_KB = {"an_toàn", "nội_thất", "ngoại_thất", "tính_năng_nổi_bật"}
    should_inject_kb = category in _NEEDS_KB

    # Tạo tasks cho tool calls và KB search (nếu cần)
    tasks = [_execute_tools_parallel(tool_calls)]
    kb_task = None

    if should_inject_kb:
        # Tìm model_code từ tool calls
        model_code = None
        for tc in tool_calls:
            if tc.function.name in ("get_specs", "get_colors"):
                args = json.loads(tc.function.arguments)
                model_code = args.get("model_code", "")
                if model_code:
                    break

        if model_code:
            from app.agent.tools import search_knowledge_base
            # Chạy KB search song song (sẽ quyết định skip_rerank sau)
            kb_task = search_knowledge_base(state.get("query", ""), model_id=model_code, skip_rerank=True)
            tasks.append(kb_task)

    # Chạy tất cả tasks song song
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    results = gathered[0] if not isinstance(gathered[0], Exception) else []
    kb_result = gathered[1] if len(gathered) > 1 else None

    # Thêm KB result vào tool_results (nếu có và thành công)
    if kb_result and not isinstance(kb_result, Exception):
        results.append({
            "tool": "search_knowledge_base",
            "result": kb_result,
            "success": True,
            "auto_injected": True,  # Label: supplementary, not primary
        })
        logger.info("Auto-inject KB: topic=%s results=%d",
                    category, len(kb_result.get("results", [])))
    elif isinstance(kb_result, Exception):
        logger.warning("Auto-inject KB failed: %s", kb_result)

    tool_results.extend(results)

    # Build messages: assistant tool_calls + original tool results ONLY.
    # Auto-injected KB results go to tool_results (for assess_evidence +
    # context_builder) but NOT to new_messages — they don't have matching
    # tool_calls in the assistant message, so adding them as 'tool' role
    # breaks OpenAI API contract.
    new_messages = messages + [{
        "role": "assistant",
        "content": final_content or None,
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ],
    }]
    for tc, res in zip(tool_calls, results[:len(tool_calls)]):
        new_messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(res["result"], ensure_ascii=False),
        })

    # Handle ask_clarification: override if classify already decided answer
    # with a version-independent topic
    _VERSION_INDEPENDENT = {
        "kích_thước", "phiên_bản", "pin_và_sạc",
        "tính_năng_nổi_bật", "an_toàn", "nội_thất", "ngoại_thất",
    }
    category = state.get("category", "general")

    for tc, res in zip(tool_calls, results):
        if tc.function.name == "ask_clarification" and res.get("success"):
            if has_model and category in _VERSION_INDEPENDENT:
                logger.info("ask_clarification overridden: version-independent topic=%s", category)
                new_messages.append({
                    "role": "user",
                    "content": f"Thông tin '{category}' áp dụng cho cả hai phiên bản. Trả lời trực tiếp. KHÔNG gọi lại ask_clarification.",
                })
                break
            elif has_model and has_version:
                logger.info("ask_clarification overridden: model+version known")
                new_messages.append({
                    "role": "user",
                    "content": "Câu hỏi đã có model và version rõ ràng. Trả lời trực tiếp bằng tool. KHÔNG gọi lại ask_clarification.",
                })
                break
            else:
                clarify_msg = res["result"].get("message", "Bạn muốn tìm thông tin nào?")
                return {
                    "decision": "clarify",
                    "reason_code": "missing_topic",
                    "response_text": clarify_msg,
                    "final_response": "",
                    "messages": new_messages,
                    "tool_results": tool_results,
                    "iteration": iteration + 1,
                    "t_retrieve_start": t_retrieve_start,
                    "t_retrieve_end": time.time(),
                }

    return {
        "messages": new_messages,
        "tool_results": tool_results,
        "iteration": iteration + 1,
        "t_retrieve_start": t_retrieve_start,
        "t_retrieve_end": time.time(),
    }
