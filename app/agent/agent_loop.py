import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import settings
from app.agent.schemas import build_tool_schemas
from app.agent.tools import TOOL_REGISTRY
from app.agent.prompts import get_system_prompt, get_prompt_hash
from app.agent.classifier import get_classifier
from app.agent.decision import (
    assess_evidence,
    validate_citations,
    make_decision_log,
    log_store,
    REFUSAL_MESSAGES,
    get_oos_messages,
    get_clarify_messages,
)

logger = logging.getLogger("bds.agent")


@dataclass
class AgentResult:
    response: str
    sources: list[dict] = field(default_factory=list)
    needs_clarification: bool = False
    classify_result: dict = field(default_factory=dict)
    decision: str = "answer"
    decision_log: dict = field(default_factory=dict)


class AgentLoop:
    MAX_ITERATIONS = 3

    def __init__(self):
        self.llm = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.classifier = get_classifier()

    async def _build_messages(self, query: str, history: list[dict]) -> list[dict]:
        system_prompt = await get_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})
        return messages

    async def _execute_tools_parallel(self, tool_calls: list) -> list[dict]:
        async def _safe_execute(tc):
            func_name = tc.function.name
            args = json.loads(tc.function.arguments)
            func = TOOL_REGISTRY.get(func_name)
            if not func:
                return {"tool": func_name, "result": {"error": f"Unknown tool: {func_name}"}, "success": False}
            try:
                result = await func(**args) if asyncio.iscoroutinefunction(func) else func(**args)
                return {"tool": func_name, "result": result, "success": True}
            except Exception as e:
                return {"tool": func_name, "result": {"error": str(e)}, "success": False}

        return await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])

    def _has_meaningful_results(self, tool_results: list[dict]) -> bool:
        for tr in tool_results:
            if not tr.get("success"):
                continue
            result = tr["result"]
            tool = tr["tool"]
            if tool == "get_price" and result.get("prices"):
                return True
            if tool == "get_specs" and result.get("specs"):
                return True
            if tool == "search_knowledge_base" and result.get("results"):
                return True
            if tool == "list_available_models" and result.get("models"):
                return True
            if tool == "get_active_promotions" and result.get("url"):
                return True
            if tool in ("get_onroad_cost_link", "get_showroom_charging_link", "get_booking_link") and result.get("url"):
                return True
            if tool == "get_loan_estimate_link" and result.get("links"):
                return True
            if tool == "get_maintenance_link" and result.get("links"):
                return True
        return False

    def _check_grounding(self, response: str, tool_results: list[dict]) -> bool:
        if not tool_results:
            return False

        has_kb = any(
            tr.get("success") and tr["tool"] == "search_knowledge_base"
            for tr in tool_results
        )
        if not has_kb:
            return True

        def _extract_numbers(text: str) -> set[float]:
            nums = set()
            cleaned = re.sub(r"\d+[-–]\d+", "", text)
            for m in re.findall(r"\d[\d.,]*\d|\d+", cleaned):
                clean = m.replace(",", "").replace(".", "")
                try:
                    val = float(clean)
                    nums.add(val)
                except ValueError:
                    pass
            return nums

        response_numbers = _extract_numbers(response)
        if not response_numbers:
            return True

        context_parts = []
        for tr in tool_results:
            if not tr.get("success"):
                continue
            result = tr["result"]
            if tr["tool"] == "get_specs":
                for s in result.get("specs", []):
                    context_parts.append(s.get("value", ""))
            elif tr["tool"] == "get_price":
                for p in result.get("prices", []):
                    context_parts.append(str(p.get("price_vnd", "")))
                    context_parts.append(str(p.get("promo_price_vnd", "")))
            elif tr["tool"] == "search_knowledge_base":
                for r in result.get("results", []):
                    context_parts.append(r.get("text", ""))

        context_numbers = _extract_numbers(" ".join(context_parts))

        for num in response_numbers:
            if num < 100 and num == int(num):
                continue
            if num not in context_numbers:
                return False

        return True

    def _generate_clarification(self, classify_result) -> str:
        model = classify_result.entities.get("model_code")
        missing = classify_result.missing_fields
        clarify_msgs = get_clarify_messages()

        if "model_code" in missing:
            return clarify_msgs["model_code"]
        if "topic" in missing:
            if model:
                return clarify_msgs["topic"].format(model=model)
            ml = " hoặc ".join(settings.scope_models)
            return f"Bạn muốn hỏi về {ml}, và muốn biết thông tin gì?"
        if "version" in missing:
            return clarify_msgs["version"]
        return "Bạn có thể đặt câu hỏi cụ thể hơn không?"

    def _build_log_kwargs(self, t0: float, t_retrieval: float, t_generation: float) -> dict:
        return {
            "latency_ms": (time.time() - t0) * 1000,
            "latency_retrieval_ms": t_retrieval * 1000,
            "latency_generation_ms": t_generation * 1000,
            "prompt_hash": get_prompt_hash(),
        }

    async def run(self, query: str, history: list[dict]) -> AgentResult:
        t0 = time.time()

        classify_result = self.classifier.classify(query, history)

        # Decision Order Step 1: Out-of-scope check
        if classify_result.decision == "out_of_scope":
            oos_type = classify_result.intents[0] if classify_result.intents else "unknown"
            oos_msgs = get_oos_messages()
            response = oos_msgs.get(oos_type, oos_msgs.get("model_oos", ""))
            dlog = make_decision_log(query, classify_result, [], response, [], **self._build_log_kwargs(t0, 0, 0))
            log_store.add(dlog)
            logger.info("BDS decision=%s reason_code=%s", "out_of_scope", dlog.reason_code)
            return AgentResult(
                response=response,
                decision="out_of_scope",
                classify_result={"decision": "out_of_scope", "reason_code": dlog.reason_code, "entities": classify_result.entities},
                decision_log=dlog.to_dict(),
            )

        # Retrieve + Generate — LLM handles clarification via ask_clarification tool
        messages = await self._build_messages(query, history)
        tool_schemas = await build_tool_schemas()
        tool_results = []
        force_tool = classify_result.topic is not None
        final_response = ""

        t_retrieve_start = time.time()
        for i in range(self.MAX_ITERATIONS):
            try:
                resp = await self.llm.chat.completions.create(
                    model=settings.llm_model,
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="required" if force_tool and i == 0 else "auto",
                )
            except Exception as e:
                t_retrieval = time.time() - t_retrieve_start
                dlog = make_decision_log(
                    query, classify_result, [], REFUSAL_MESSAGES["system_error"], [],
                    **self._build_log_kwargs(t0, t_retrieval, 0),
                    error_stage="retrieval", error_type=type(e).__name__, error_message=str(e)[:200],
                )
                log_store.add(dlog)
                return AgentResult(
                    response=REFUSAL_MESSAGES["system_error"],
                    decision="refuse",
                    classify_result={"decision": "refuse", "reason_code": "system_error"},
                    decision_log=dlog.to_dict(),
                )

            choice = resp.choices[0]

            # LLM returned text directly (no more tool calls) — this IS the final answer
            if not choice.message.tool_calls:
                final_response = choice.message.content or ""
                break

            # Execute tools
            results = await self._execute_tools_parallel(choice.message.tool_calls)
            tool_results.extend(results)

            # Check if LLM called ask_clarification → return immediately
            for tc, res in zip(choice.message.tool_calls, results):
                if tc.function.name == "ask_clarification" and res.get("success"):
                    clarify_result = res["result"]
                    response_text = clarify_result.get("message", "Bạn muốn tìm thông tin nào?")
                    dlog = make_decision_log(query, classify_result, tool_results, response_text, [], **self._build_log_kwargs(t0, time.time() - t_retrieve_start, 0))
                    dlog.decision = "clarify"
                    dlog.reason_code = "missing_topic"
                    log_store.add(dlog)
                    return AgentResult(
                        response=response_text,
                        needs_clarification=True,
                        decision="clarify",
                        sources=tool_results,
                        classify_result={"decision": "clarify", "reason_code": "missing_topic", "entities": classify_result.entities},
                        decision_log=dlog.to_dict(),
                    )

            # Append tool call + results to messages for next iteration
            messages.append(choice.message)
            for tc, res in zip(choice.message.tool_calls, results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res["result"], ensure_ascii=False)})

            # After tool execution, if we have results, let LLM answer in next iteration
            # (loop continues — LLM will see tool results and generate final answer)

        t_retrieval = time.time() - t_retrieve_start

        # If LLM never produced text (all iterations were tool calls), force one more call
        if not final_response and tool_results:
            t_gen_start = time.time()
            try:
                # Add instruction to answer directly
                messages.append({"role": "user", "content": "Dựa vào kết quả tool trên, trả lời câu hỏi gốc. Dẫn nguồn URL khi có."})
                resp = await self.llm.chat.completions.create(
                    model=settings.llm_model,
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="none",  # Force text output, no more tools
                )
                final_response = resp.choices[0].message.content or ""
            except Exception as e:
                t_generation = time.time() - t_gen_start
                dlog = make_decision_log(
                    query, classify_result, tool_results, REFUSAL_MESSAGES["system_error"], [],
                    **self._build_log_kwargs(t0, t_retrieval, t_generation),
                    error_stage="generation", error_type=type(e).__name__, error_message=str(e)[:200],
                )
                log_store.add(dlog)
                return AgentResult(
                    response=REFUSAL_MESSAGES["system_error"],
                    sources=tool_results,
                    decision="refuse",
                    classify_result={"decision": "refuse", "reason_code": "system_error"},
                    decision_log=dlog.to_dict(),
                )
            t_generation = time.time() - t_gen_start
        else:
            t_generation = time.time() - t_retrieve_start - t_retrieval

        # Evidence assessment
        assessment, valid_sources = assess_evidence(tool_results, query)

        if assessment == "insufficient":
            response_text = REFUSAL_MESSAGES["insufficient_evidence"]
            dlog = make_decision_log(query, classify_result, tool_results, response_text, [], **self._build_log_kwargs(t0, t_retrieval, 0))
            log_store.add(dlog)
            logger.info("BDS decision=refuse reason_code=insufficient_evidence")
            return AgentResult(
                response=response_text,
                sources=tool_results,
                decision="refuse",
                classify_result={"decision": "refuse", "reason_code": "insufficient_evidence", "assessment": assessment},
                decision_log=dlog.to_dict(),
            )

        # Citation check
        citations = validate_citations(valid_sources)

        if not citations and final_response:
            has_numbers = bool(re.search(r"\d[\d.,]+", final_response))
            if has_numbers:
                response_text = REFUSAL_MESSAGES["no_citation"]
                dlog = make_decision_log(query, classify_result, tool_results, response_text, [], **self._build_log_kwargs(t0, t_retrieval, t_generation))
                log_store.add(dlog)
                logger.info("BDS decision=refuse reason_code=citation_failure")
                return AgentResult(
                    response=response_text,
                    sources=tool_results,
                    decision="refuse",
                    classify_result={"decision": "refuse", "reason_code": "citation_failure"},
                    decision_log=dlog.to_dict(),
                )

        # Grounding check
        if not self._check_grounding(final_response, tool_results):
            final_response = REFUSAL_MESSAGES["grounding_fail"]
            dlog = make_decision_log(query, classify_result, tool_results, final_response, citations, **self._build_log_kwargs(t0, t_retrieval, t_generation))
            log_store.add(dlog)
            logger.info("BDS decision=refuse reason_code=grounding_failure")
            return AgentResult(
                response=final_response,
                sources=tool_results,
                decision="refuse",
                classify_result={"decision": "refuse", "reason_code": "grounding_failure"},
                decision_log=dlog.to_dict(),
            )

        # Refuse detection — if LLM response contains refusal patterns, override to refuse
        REFUSAL_PATTERNS = [
            r"chưa thể xác nhận",
            r"không có thông tin",
            r"không đủ thông tin",
            r"không được cung cấp",
            r"không tìm thấy",
            r"không có dữ liệu",
        ]
        is_refusal = any(re.search(p, final_response, re.IGNORECASE) for p in REFUSAL_PATTERNS)
        if is_refusal and not citations:
            dlog = make_decision_log(query, classify_result, tool_results, final_response, [], **self._build_log_kwargs(t0, t_retrieval, t_generation))
            dlog.reason_code = "insufficient_evidence"
            log_store.add(dlog)
            logger.info("BDS decision=refuse reason_code=insufficient_evidence (LLM refusal detected)")
            return AgentResult(
                response=final_response,
                sources=tool_results,
                decision="refuse",
                classify_result={"decision": "refuse", "reason_code": "insufficient_evidence"},
                decision_log=dlog.to_dict(),
            )

        # Answer
        dlog = make_decision_log(query, classify_result, tool_results, final_response, citations, **self._build_log_kwargs(t0, t_retrieval, t_generation))
        log_store.add(dlog)
        logger.info("BDS decision=answer reason_code=%s latency=%.0fms", dlog.reason_code, dlog.latency_total_ms)
        return AgentResult(
            response=final_response,
            sources=tool_results,
            decision="answer",
            classify_result={"decision": "answer", "reason_code": dlog.reason_code, "assessment": assessment},
            decision_log=dlog.to_dict(),
        )

    async def run_stream(self, query: str, history: list[dict]):
        t0 = time.time()
        classify_result = self.classifier.classify(query, history)

        if classify_result.decision == "out_of_scope":
            oos_type = classify_result.intents[0] if classify_result.intents else "unknown"
            oos_msgs = get_oos_messages()
            response = oos_msgs.get(oos_type, oos_msgs.get("model_oos", ""))
            dlog = make_decision_log(query, classify_result, [], response, [], **self._build_log_kwargs(t0, 0, 0))
            log_store.add(dlog)
            yield {"type": "decision", "content": "out_of_scope"}
            yield {"type": "answer", "content": response}
            yield {"type": "done"}
            return

        yield {"type": "decision", "content": "answer"}
        yield {"type": "classify", "content": {"topic": classify_result.topic, "entities": classify_result.entities}}

        messages = await self._build_messages(query, history)
        tool_schemas = await build_tool_schemas()
        tool_results = []
        force_tool = classify_result.topic is not None

        t_retrieve_start = time.time()
        for i in range(self.MAX_ITERATIONS):
            try:
                resp = await self.llm.chat.completions.create(
                    model=settings.llm_model, messages=messages, tools=tool_schemas,
                    tool_choice="required" if force_tool and i == 0 else "auto", stream=False,
                )
            except Exception as e:
                t_retrieval = time.time() - t_retrieve_start
                dlog = make_decision_log(
                    query, classify_result, [], REFUSAL_MESSAGES["system_error"], [],
                    **self._build_log_kwargs(t0, t_retrieval, 0),
                    error_stage="retrieval", error_type=type(e).__name__, error_message=str(e)[:200],
                )
                log_store.add(dlog)
                yield {"type": "answer", "content": REFUSAL_MESSAGES["system_error"]}
                yield {"type": "done"}
                return

            choice = resp.choices[0]

            if not choice.message.tool_calls:
                # LLM answered directly
                final_response = choice.message.content or ""
                t_retrieval = time.time() - t_retrieve_start
                break

            results = await self._execute_tools_parallel(choice.message.tool_calls)
            tool_results.extend(results)

            # Check if LLM called ask_clarification → yield and return
            for tc, res in zip(choice.message.tool_calls, results):
                if tc.function.name == "ask_clarification" and res.get("success"):
                    clarify_result = res["result"]
                    response_text = clarify_result.get("message", "Bạn muốn tìm thông tin nào?")
                    dlog = make_decision_log(query, classify_result, tool_results, response_text, [], **self._build_log_kwargs(t0, time.time() - t_retrieve_start, 0))
                    dlog.reason_code = "missing_topic"
                    log_store.add(dlog)
                    yield {"type": "clarify", "content": response_text}
                    yield {"type": "sources", "content": []}
                    yield {"type": "done"}
                    return

            for r in results:
                yield {"type": "tool_call", "content": {"tool": r["tool"], "success": r["success"]}}

            messages.append(choice.message)
            for tc, res in zip(choice.message.tool_calls, results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res["result"], ensure_ascii=False)})
        else:
            # Loop exhausted — force final answer
            t_retrieval = time.time() - t_retrieve_start
            final_response = ""

        # If no final_response yet, stream final answer
        if not final_response:
            t_gen_start = time.time()
            messages.append({"role": "user", "content": "Dựa vào kết quả tool trên, trả lời câu hỏi gốc. Dẫn nguồn URL khi có."})
            stream = await self.llm.chat.completions.create(model=settings.llm_model, messages=messages, tools=tool_schemas, tool_choice="none", stream=True)

            final_response = ""
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    final_response += delta.content
                    yield {"type": "token", "content": delta.content}

            t_generation = time.time() - t_gen_start
        else:
            # LLM already answered — stream it token by token (simulate)
            t_generation = time.time() - t_retrieve_start
            yield {"type": "token", "content": final_response}

        # Evidence assessment
        assessment, valid_sources = assess_evidence(tool_results, query)

        if assessment == "insufficient":
            dlog = make_decision_log(query, classify_result, tool_results, REFUSAL_MESSAGES["insufficient_evidence"], [], **self._build_log_kwargs(t0, t_retrieval, 0))
            log_store.add(dlog)
            yield {"type": "answer", "content": REFUSAL_MESSAGES["insufficient_evidence"]}
            yield {"type": "sources", "content": []}
            yield {"type": "done"}
            return

        citations = validate_citations(valid_sources)

        if not self._check_grounding(final_response, tool_results):
            yield {"type": "token", "content": "\n\n" + REFUSAL_MESSAGES["grounding_fail"]}

        dlog = make_decision_log(query, classify_result, tool_results, final_response, citations, **self._build_log_kwargs(t0, t_retrieval, t_generation))
        log_store.add(dlog)

        yield {"type": "done"}
        if citations:
            seen = set()
            formatted = []
            sorted_citations = sorted(citations, key=lambda c: c.get("score", 0), reverse=True)
            for c in sorted_citations:
                url = c.get("source_url", "")
                if not url or not url.startswith("http") or url in seen:
                    continue
                seen.add(url)
                model = c.get("model_code", "")
                label = c.get("source_type", "")
                score = round(c.get("score", 0), 3)
                text = f"{model} — {label}" if model and label else (label or url)
                formatted.append({"text": text, "url": url, "type": label, "score": score})
                if len(formatted) >= 5:
                    break
            if formatted:
                yield {"type": "sources", "content": formatted}
