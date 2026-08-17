import logging
import re
import time
import asyncio
from dataclasses import dataclass, field

from app.agent.decision import make_decision_log, log_store, get_clarify_messages
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.respond")

# Câu trả lời refuse thuần (không chứa dữ liệu thật) → KHÔNG hiện nguồn.
# Tránh trường hợp hỏi bảo hành mà data không có → hiện nguồn specs không liên quan.
_REFUSAL_PHRASES = (
    "chưa được ghi nhận",
    "chưa thể xác nhận",
    "không có dữ liệu",
    "không tìm thấy",
    "chưa có thông tin",
)
_HAS_DATA_RE = re.compile(r"(triệu|tỷ|kW|km|Nm|kWh|giây|%)")
# Dấu hiệu câu trả lời CÓ dữ liệu/kết luận thật (bullets, in đậm, "có...", ": ") —
# nếu có → không phải refuse thuần, giữ nguồn (tránh mất nguồn cho câu trả lời
# kiểu "VF 8 Plus có cửa sổ trời... còn lại chưa ghi nhận")
_HAS_FINDING_RE = re.compile(r"(có |gồm |bao gồm|\*\*|^\s*[-•]|: )", re.MULTILINE)


def _is_pure_refusal(text: str) -> bool:
    """Câu trả lời là refuse thuần (không có dữ liệu/kết luận thật) hay không."""
    t = (text or "").strip()
    if not t:
        return True
    if not any(p in t for p in _REFUSAL_PHRASES):
        return False
    return not (_HAS_DATA_RE.search(t) or _HAS_FINDING_RE.search(t))


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
        # make_decision_log gọi assess_evidence + build_retrieved_chunks
        # (cả 2 đều sync + có thể gọi _openrouter_embed → block event loop)
        # Wrap trong run_in_executor để không block stream.
        loop = asyncio.get_running_loop()
        dlog = await loop.run_in_executor(
            None,
            lambda: make_decision_log(
                state["query"], cr, tool_results, answer, citations,
                latency_ms=latency_ms,
                latency_retrieval_ms=latency_retrieval_ms,
                latency_generation_ms=latency_generation_ms,
                topic=state.get("category", ""),
                history=state.get("history", []),
            ),
        )
        dlog.decision = decision
        dlog.reason_code = reason_code
        log_store.add(dlog)
        decision_log = dlog.to_dict()
    except Exception as e:
        logger.warning("Failed to create decision log: %s", e)
        decision_log = {}

    sources = citations if citations else tool_results
    # Nguồn CHỈ hiển thị khi câu trả lời thực sự có dữ liệu.
    # Refuse thuần ("chưa được ghi nhận...") → bỏ nguồn, tránh hiện nguồn lạc đề.
    if decision != "answer" or _is_pure_refusal(answer):
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
