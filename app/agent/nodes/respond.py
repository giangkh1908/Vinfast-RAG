import logging
import time
from dataclasses import dataclass, field

from app.agent.decision import make_decision_log, log_store, get_clarify_messages
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.respond")


@dataclass
class AgentResult:
    response: str
    sources: list[dict] = field(default_factory=list)
    needs_clarification: bool = False
    classify_result: dict = field(default_factory=dict)
    decision: str = "answer"
    decision_log: dict = field(default_factory=dict)


def _build_classify_result(state: AgentState) -> dict:
    return {
        "decision": state.get("decision", "answer"),
        "reason_code": state.get("reason_code", ""),
        "entities": state.get("entities", {}),
        "assessment": state.get("assessment", ""),
    }


async def respond_node(state: AgentState) -> dict:
    decision = state.get("decision", "answer")
    reason_code = state.get("reason_code", "")
    final_response = state.get("final_response", "")
    response_text = state.get("response_text", "")
    tool_results = state.get("tool_results", [])
    citations = state.get("citations", [])
    entities = state.get("entities", {})
    assessment = state.get("assessment", "")

    logger.info("RESPOND: decision=%s reason=%s assessment=%s tools=%s",
                decision, reason_code, assessment,
                [t.get("tool") for t in tool_results if t.get("success")])

    if decision == "clarify":
        answer = response_text or "Bạn muốn tìm thông tin nào?"
    elif decision == "refuse":
        answer = response_text or final_response or "Mình chưa thể xác nhận thông tin này."
    elif decision == "out_of_scope":
        answer = response_text or "Ngoài phạm vi hỗ trợ."
    else:
        answer = final_response

    t0 = state.get("t0", time.time())
    latency_ms = (time.time() - t0) * 1000

    t_retrieve_start = state.get("t_retrieve_start", 0)
    t_retrieve_end = state.get("t_retrieve_end", 0)
    latency_retrieval_ms = (t_retrieve_end - t_retrieve_start) * 1000 if t_retrieve_start and t_retrieve_end else 0

    t_generate_start = state.get("t_generate_start", 0)
    t_generate_end = state.get("t_generate_end", 0)
    if t_generate_start and t_generate_end:
        latency_generation_ms = (t_generate_end - t_generate_start) * 1000
    elif t_generate_start:
        latency_generation_ms = (time.time() - t_generate_start) * 1000
    else:
        latency_generation_ms = 0

    try:
        from app.agent.classifier import ClassifyResult
        cr = ClassifyResult(
            decision=decision,
            reason=reason_code,
            entities=entities,
            specificity=state.get("specificity", "unknown"),
        )
        dlog = make_decision_log(
            state["query"], cr, tool_results, answer, citations,
            latency_ms=latency_ms,
            latency_retrieval_ms=latency_retrieval_ms,
            latency_generation_ms=latency_generation_ms,
            topic=state.get("category", ""),
            history=state.get("history", []),
        )
        dlog.decision = decision
        dlog.reason_code = reason_code
        log_store.add(dlog)
        decision_log = dlog.to_dict()
    except Exception as e:
        logger.warning("Failed to create decision log: %s", e)
        decision_log = {}

    sources = citations if citations else tool_results
    if decision != "answer":
        sources = []

    return {
        "result": AgentResult(
            response=answer,
            sources=sources,
            needs_clarification=(decision == "clarify"),
            classify_result=_build_classify_result(state),
            decision=decision,
            decision_log=decision_log,
        )
    }
