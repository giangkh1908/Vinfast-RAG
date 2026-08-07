import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import settings
from app.agent.schemas import build_tool_schemas
from app.agent.tools import TOOL_REGISTRY
from app.agent.prompts import get_system_prompt, SYNTHESIZE_PROMPT
from app.agent.context_builder import build_structured_context
from app.agent.classifier import get_classifier
from app.agent.decision import (
    assess_evidence,
    validate_citations,
    make_decision_log,
    REFUSAL_MESSAGES,
    get_oos_messages,
    get_clarify_messages,
    DecisionLog,
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

        has_factual = any(
            tr.get("success") and tr["tool"] in ("get_specs", "search_knowledge_base", "get_price")
            for tr in tool_results
        )
        if not has_factual:
            return True

        def _extract_numbers(text: str) -> set[float]:
            nums = set()
            cleaned = re.sub(r"\d+[-–]\d+", "", text)
            for m in re.findall(r"\d[\d.,]*\d|\d+", cleaned):
                clean = m.replace(",", "").replace(".", "")
                try:
                    nums.add(float(clean))
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
            if num < 10:
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

    async def run(self, query: str, history: list[dict]) -> AgentResult:
        classify_result = self.classifier.classify(query, history)

        # Decision Order Step 1: Out-of-scope check
        if classify_result.decision == "out_of_scope":
            oos_type = classify_result.intents[0] if classify_result.intents else "unknown"
            oos_msgs = get_oos_messages()
            response = oos_msgs.get(oos_type, oos_msgs.get("model_oos", ""))
            dlog = make_decision_log(query, classify_result, [], response, [])
            logger.info("BDS decision=%s reason=%s", "out_of_scope", classify_result.reason)
            return AgentResult(
                response=response,
                decision="out_of_scope",
                classify_result={"decision": "out_of_scope", "reason": classify_result.reason, "entities": classify_result.entities},
                decision_log=dlog.to_dict(),
            )

        # Decision Order Step 2-4: Clarify checks
        if classify_result.decision == "clarify":
            response = self._generate_clarification(classify_result)
            dlog = make_decision_log(query, classify_result, [], response, [])
            logger.info("BDS decision=%s reason=%s", "clarify", classify_result.reason)
            return AgentResult(
                response=response,
                needs_clarification=True,
                decision="clarify",
                classify_result={"decision": "clarify", "reason": classify_result.reason, "entities": classify_result.entities},
                decision_log=dlog.to_dict(),
            )

        # Decision Order Step 5: Retrieve evidence
        messages = await self._build_messages(query, history)
        tool_schemas = await build_tool_schemas()
        tool_results = []
        force_tool = classify_result.topic is not None

        for i in range(self.MAX_ITERATIONS):
            response = await self.llm.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=tool_schemas,
                tool_choice="required" if force_tool and i == 0 else "auto",
            )

            choice = response.choices[0]
            if not choice.message.tool_calls:
                break

            results = await self._execute_tools_parallel(choice.message.tool_calls)
            tool_results.extend(results)

            messages.append(choice.message)
            for tc, res in zip(choice.message.tool_calls, results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res["result"], ensure_ascii=False)})

        # Decision Order Step 5-6: Evidence assessment
        assessment, valid_sources = assess_evidence(tool_results, query)

        if assessment == "insufficient":
            response_text = REFUSAL_MESSAGES["insufficient_evidence"]
            dlog = make_decision_log(query, classify_result, tool_results, response_text, [])
            dlog.evidence_assessment = "insufficient"
            logger.info("BDS decision=refuse reason=insufficient_evidence")
            return AgentResult(
                response=response_text,
                sources=tool_results,
                decision="refuse",
                classify_result={"decision": "refuse", "reason": "insufficient_evidence", "assessment": assessment},
                decision_log=dlog.to_dict(),
            )

        # Decision Order Step 7: Validity check — filter citations
        citations = validate_citations(valid_sources)

        # Synthesize response
        context = build_structured_context(tool_results)
        system_prompt = await get_system_prompt()
        synth_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": SYNTHESIZE_PROMPT.format(context=context, query=query)},
        ]
        synth_response = await self.llm.chat.completions.create(model=settings.llm_model, messages=synth_messages)
        final_response = synth_response.choices[0].message.content or ""

        # Decision Order Step 8: Citation check
        if not citations and final_response:
            has_numbers = bool(re.search(r"\d[\d.,]+", final_response))
            if has_numbers:
                response_text = REFUSAL_MESSAGES["no_citation"]
                dlog = make_decision_log(query, classify_result, tool_results, response_text, [])
                dlog.evidence_assessment = "no_citation"
                logger.info("BDS decision=refuse reason=no_citation")
                return AgentResult(
                    response=response_text,
                    sources=tool_results,
                    decision="refuse",
                    classify_result={"decision": "refuse", "reason": "no_citation"},
                    decision_log=dlog.to_dict(),
                )

        # Decision Order Step 9: Grounding check
        if not self._check_grounding(final_response, tool_results):
            final_response = REFUSAL_MESSAGES["grounding_fail"]
            dlog = make_decision_log(query, classify_result, tool_results, final_response, citations)
            dlog.evidence_assessment = "grounding_fail"
            logger.info("BDS decision=refuse reason=grounding_fail")
            return AgentResult(
                response=final_response,
                sources=tool_results,
                decision="refuse",
                classify_result={"decision": "refuse", "reason": "grounding_fail"},
                decision_log=dlog.to_dict(),
            )

        # Decision Order Step 9: Answer
        dlog = make_decision_log(query, classify_result, tool_results, final_response, citations)
        logger.info("BDS decision=answer assessment=%s citations=%d", assessment, len(citations))
        return AgentResult(
            response=final_response,
            sources=tool_results,
            decision="answer",
            classify_result={"decision": "answer", "reason": classify_result.reason, "assessment": assessment},
            decision_log=dlog.to_dict(),
        )

    async def run_stream(self, query: str, history: list[dict]):
        classify_result = self.classifier.classify(query, history)

        if classify_result.decision == "out_of_scope":
            oos_type = classify_result.intents[0] if classify_result.intents else "unknown"
            oos_msgs = get_oos_messages()
            yield {"type": "decision", "content": "out_of_scope"}
            yield {"type": "answer", "content": oos_msgs.get(oos_type, oos_msgs.get("model_oos", ""))}
            yield {"type": "done"}
            return

        if classify_result.decision == "clarify":
            yield {"type": "decision", "content": "clarify"}
            yield {"type": "clarify", "content": self._generate_clarification(classify_result)}
            yield {"type": "done"}
            return

        yield {"type": "decision", "content": "answer"}
        yield {"type": "classify", "content": {"topic": classify_result.topic, "entities": classify_result.entities}}

        messages = await self._build_messages(query, history)
        tool_schemas = await build_tool_schemas()
        tool_results = []
        force_tool = classify_result.topic is not None

        for i in range(self.MAX_ITERATIONS):
            response = await self.llm.chat.completions.create(
                model=settings.llm_model, messages=messages, tools=tool_schemas,
                tool_choice="required" if force_tool and i == 0 else "auto", stream=False,
            )

            choice = response.choices[0]
            if not choice.message.tool_calls:
                break

            results = await self._execute_tools_parallel(choice.message.tool_calls)
            tool_results.extend(results)

            for r in results:
                yield {"type": "tool_call", "content": {"tool": r["tool"], "success": r["success"]}}

            messages.append(choice.message)
            for tc, res in zip(choice.message.tool_calls, results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res["result"], ensure_ascii=False)})

        assessment, valid_sources = assess_evidence(tool_results, query)

        if assessment == "insufficient":
            yield {"type": "answer", "content": REFUSAL_MESSAGES["insufficient_evidence"]}
            yield {"type": "sources", "content": []}
            yield {"type": "done"}
            return

        citations = validate_citations(valid_sources)

        context = build_structured_context(tool_results)
        system_prompt = await get_system_prompt()
        synth_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": SYNTHESIZE_PROMPT.format(context=context, query=query)},
        ]

        stream = await self.llm.chat.completions.create(model=settings.llm_model, messages=synth_messages, stream=True)

        final_response = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                final_response += delta.content
                yield {"type": "token", "content": delta.content}

        if not self._check_grounding(final_response, tool_results):
            yield {"type": "token", "content": "\n\n" + REFUSAL_MESSAGES["grounding_fail"]}

        yield {"type": "done"}
        if citations:
            seen = set()
            formatted = []
            for c in citations:
                url = c.get("source_url", "")
                if not url or not url.startswith("http") or url in seen:
                    continue
                seen.add(url)
                model = c.get("model_code", "")
                label = c.get("source_type", "")
                text = f"{model} — {label}" if model and label else (label or url)
                formatted.append({"text": text, "url": url, "type": label})
            if formatted:
                yield {"type": "sources", "content": formatted}
