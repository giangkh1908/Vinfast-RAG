import asyncio
import json
import logging
import time

from openai import AsyncOpenAI

from app.config import settings
from app.agent.schemas import build_tool_schemas
from app.agent.tools import TOOL_REGISTRY
from app.agent.semantic_prefilter import classify_specificity
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.tools")

MAX_ITERATIONS = 3


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

    try:
        specificity_result = classify_specificity(state["query"])
        specificity_flag = specificity_result.specific
        specificity_category = specificity_result.category
    except Exception:
        specificity_flag = has_model and has_version
        specificity_category = None

    llm = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    tool_schemas = await build_tool_schemas()

    # Constrain tools based on topic classification from classify node
    allowed_tools = state.get("allowed_tools")
    if allowed_tools is not None:
        tool_schemas = [s for s in tool_schemas if s["function"]["name"] in allowed_tools]
        if not tool_schemas:
            tool_schemas = await build_tool_schemas()

    t_retrieve_start = state.get("t_retrieve_start") or time.time()

    # Force tool calls on first iteration when classify decided "answer"
    # Prevents gpt-4o-mini from refusing without checking database
    decision = state.get("decision", "answer")
    force_tool = "required" if (decision == "answer" and not tool_results) else "auto"

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=tool_schemas,
            tool_choice=force_tool,
        )
    except Exception as e:
        return {
            "decision": "refuse",
            "reason_code": "system_error",
            "response_text": "Mình chưa thể hoàn tất câu trả lời lúc này. Vui lòng thử lại.",
            "final_response": "",
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
    tool_results.extend(results)

    new_messages = messages + [choice.message]
    for tc, res in zip(choice.message.tool_calls, results):
        new_messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(res["result"], ensure_ascii=False),
        })

    for tc, res in zip(choice.message.tool_calls, results):
        if tc.function.name == "ask_clarification" and res.get("success"):
            category = state.get("category", "general")
            # Version-independent topics: model known → don't clarify for version
            _VERSION_INDEPENDENT = {"kích_thước", "phiên_bản", "pin_và_sạc", "tính_năng_nổi_bật", "an_toàn", "nội_thất", "ngoại_thất"}
            if has_model and category in _VERSION_INDEPENDENT:
                logger.info("ask_clarification overridden: version-independent topic=%s", category)
                new_messages.append({
                    "role": "user",
                    "content": f"Thông tin '{category}' áp dụng cho cả hai phiên bản. Trả lời trực tiếp. KHÔNG gọi lại ask_clarification.",
                })
                break
            elif specificity_flag and has_model and has_version:
                logger.info("ask_clarification overridden: specific=%s category=%s", specificity_flag, specificity_category)
                new_messages.append({
                    "role": "user",
                    "content": f"Câu hỏi có topic rõ ràng ({specificity_category}). Trả lời trực tiếp bằng tool. KHÔNG gọi lại ask_clarification.",
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
