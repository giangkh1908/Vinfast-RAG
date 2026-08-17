import logging
import re
import time
import asyncio
from dataclasses import dataclass, field

from app.agent.decision import make_decision_log, log_store, get_clarify_messages
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.respond")

# Câu trả lời mặc định cho các case không trả lời được
_DEFAULT_REPLY = "Xin lỗi, mình chưa có thông tin phù hợp. Bạn có thể hỏi lại bằng câu khác được không?"


@dataclass
class AgentResult:
    response: str
    sources: list[dict] = field(default_factory=list)
    source_url: str = ""  # URL nguồn (hiển thị ở cuối câu trả lời)
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

    logger.info("RESPOND: decision=%s reason=%s assessment=%s tools=%d",
                decision, reason_code, assessment, len(tool_results))
    
    # Debug: check tool_results for source_url
    for i, tr in enumerate(tool_results):
        if tr.get("success") and isinstance(tr.get("result"), dict):
            url = tr["result"].get("source_url", "")
            logger.info("RESPOND: tool[%d]=%s source_url=%s", i, tr.get("tool"), url or "EMPTY")

    if decision == "clarify":
        answer = _DEFAULT_REPLY
    elif decision == "refuse":
        answer = _DEFAULT_REPLY
    elif decision == "out_of_scope":
        answer = _DEFAULT_REPLY
    else:
        answer = final_response
    
    # Lấy URL nguồn từ tool results (nếu có)
    source_url = ""
    if decision == "answer" and tool_results:
        # Ưu tiên get_specs → get_price → get_colors → khác
        # (tránh lấy URL từ search_knowledge_base - có thể là brochure xe khác)
        tool_priority = ['get_specs', 'get_price', 'get_colors']
        
        # Ưu tiên theo tool name
        for tool_name in tool_priority:
            for tr in tool_results:
                if tr.get("tool") != tool_name:
                    continue
                if tr.get("success") and isinstance(tr.get("result"), dict):
                    url = tr["result"].get("source_url", "")
                    if url:
                        source_url = url
                        break
            if source_url:
                break
        
        # Fallback: lấy từ bất kỳ tool nào có source_url
        if not source_url:
            for tr in tool_results:
                if tr.get("success") and isinstance(tr.get("result"), dict):
                    url = tr["result"].get("source_url", "")
                    if url:
                        source_url = url
                        break
    
    # Thêm link URL ở cuối câu trả lời (markdown link ngắn, click được)
    if source_url:
        answer = answer.rstrip() + f"\n\n🔗 Xem thêm: {source_url}"

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
        # (cả 2 đều sync + có thể gọi _openrouter_embed → block event loop 2-3s).
        # KHÔNG await để response trả ngay — log chạy nền (fire-and-forget).
        loop = asyncio.get_running_loop()

        async def _background_log():
            try:
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
            except Exception as e:
                logger.warning("Background decision log failed: %s", e)

        asyncio.ensure_future(_background_log())
        decision_log = {}
    except Exception as e:
        logger.warning("Failed to create decision log: %s", e)
        decision_log = {}

    sources = citations if citations else tool_results
    # KHÔNG gửi sources cho frontend — chỉ giữ nội dung câu trả lời.
    sources = []

    return {
        "result": AgentResult(
            response=answer,
            sources=sources,
            source_url=source_url,
            needs_clarification=(decision == "clarify"),
            classify_result=_build_classify_result(state),
            decision=decision,
            decision_log=decision_log,
        )
    }
