import asyncio
import json
import logging
import time

from openai import AsyncOpenAI

from app.config import settings
from app.agent.schemas import build_tool_schemas
from app.agent.tools import TOOL_REGISTRY
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.tools")

MAX_ITERATIONS = 3

_llm_client: AsyncOpenAI | None = None


def _get_llm() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
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

    # Retry once on rate limit / timeout
    resp = None
    for attempt in range(2):
        try:
            resp = await llm.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=tool_schemas,
                tool_choice=force_tool,
            )
            break
        except Exception as e:
            logger.warning("LLM call attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(3)  # Brief wait before retry
            else:
                # Final fail: return with iteration increment so route_after_tools
                # eventually hits MAX_ITERATIONS and goes to generate_node
                return {
                    "final_response": "",
                    "iteration": iteration + 1,
                    "t_retrieve_start": t_retrieve_start,
                }

    choice = resp.choices[0]

    if not choice.message.tool_calls:
        return {
            "final_response": choice.message.content or "",
            "messages": messages,
            "iteration": iteration + 1,
            "t_retrieve_start": t_retrieve_start,
        }

    results = await _execute_tools_parallel(choice.message.tool_calls)

    # Auto-inject search_knowledge_base based on detected_topic.
    # KB results are labeled as supplementary (auto_injected=True) so
    # assess_evidence treats them as partial support, not direct evidence.
    category = state.get("category", "general")
    _NEEDS_KB = {"an_toàn", "nội_thất", "ngoại_thất", "tính_năng_nổi_bật"}
    auto_kb_calls = []
    kb_results = []

    if category in _NEEDS_KB:
        for tc, res in zip(choice.message.tool_calls, results):
            if tc.function.name in ("get_specs", "get_colors") and res.get("success"):
                args = json.loads(tc.function.arguments)
                model_code = args.get("model_code", "")
                if model_code:
                    auto_kb_calls.append({
                        "model_id": model_code,
                        "query": state.get("query", ""),
                        "tool_call_id": f"auto_kb_{tc.id}",
                    })
                    break  # One KB call per model is enough

    if auto_kb_calls:
        from app.agent.tools import search_knowledge_base
        kb_tasks = [
            search_knowledge_base(kb["query"], model_id=kb["model_id"])
            for kb in auto_kb_calls
        ]
        kb_results = await asyncio.gather(*kb_tasks, return_exceptions=True)
        for kb, kb_result in zip(auto_kb_calls, kb_results):
            if isinstance(kb_result, Exception):
                logger.warning("Auto-inject KB failed: %s", kb_result)
                continue
            results.append({
                "tool": "search_knowledge_base",
                "result": kb_result,
                "success": True,
                "auto_injected": True,  # Label: supplementary, not primary
            })
            logger.info("Auto-inject KB: topic=%s model=%s results=%d",
                        category, kb["model_id"], len(kb_result.get("results", [])))

    tool_results.extend(results)

    # Build messages: assistant tool_calls + all tool results (original + auto KB)
    new_messages = messages + [choice.message]
    # Original tool results
    for tc, res in zip(choice.message.tool_calls, results[:len(choice.message.tool_calls)]):
        new_messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(res["result"], ensure_ascii=False),
        })
    # Auto-injected KB results
    for kb, kb_result in zip(auto_kb_calls, kb_results if auto_kb_calls else []):
        if not isinstance(kb_result, Exception):
            new_messages.append({
                "role": "tool",
                "tool_call_id": kb["tool_call_id"],
                "content": json.dumps(kb_result, ensure_ascii=False),
            })

    # Handle ask_clarification: override if classify already decided answer
    # with a version-independent topic
    _VERSION_INDEPENDENT = {
        "kích_thước", "phiên_bản", "pin_và_sạc",
        "tính_năng_nổi_bật", "an_toàn", "nội_thất", "ngoại_thất",
    }
    category = state.get("category", "general")

    for tc, res in zip(choice.message.tool_calls, results):
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
