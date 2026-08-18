import logging
import re
import time
import asyncio
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from app.agent.decision import make_decision_log, log_store, get_clarify_messages
from app.agent.graph_state import AgentState
from app.agent.classifier import MODEL_RE, normalize_model

logger = logging.getLogger("bds.graph.respond")


# ── Rút nhãn ngắn cho link "Xem thêm" ────────────────────────────────────
def _source_link_label(url: str, model_code: str | None = None) -> str:
    """Rút nhãn ngắn dễ nhìn từ URL brochure (VD 'VF 6', 'VF 8 All New', 'VF MPV 7').

    Ưu tiên: model rút từ URL → model_code (entities) → hostname → URL gốc.
    """
    try:
        # unquote + thay '_' bằng khoảng trắng để khớp "VF_MPV 7" / "VF8_Brochure"
        unq = unquote(url).replace("_", " ")
    except Exception:
        unq = url
    m = MODEL_RE.search(unq)
    if m:
        return normalize_model(m.group(1))
    if model_code:
        return model_code
    try:
        host = urlparse(url).netloc
        return host if host else url
    except Exception:
        return url


def format_source_links(tool_results: list[dict], default_model: str | None = None) -> str:
    """Thu thập toàn bộ URL nguồn duy nhất từ các tool results, trả về chuỗi markdown link.

    Ví dụ: '[VF 5](url_1), [VF 8](url_2)'
    """
    seen_urls = set()
    links = []

    tool_priority = ['get_specs', 'get_price', 'get_colors', 'search_knowledge_base']

    # Ưu tiên các tool lấy dữ liệu theo model
    for priority_tool in tool_priority:
        for tr in tool_results:
            if tr.get("tool") != priority_tool or not tr.get("success"):
                continue
            res = tr.get("result")
            if not isinstance(res, dict):
                continue
            url = res.get("source_url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            model_code = res.get("model_code") or (tr.get("args") or {}).get("model_code")
            links.append(source_link_md(url, model_code or default_model))

    # Fallback các tool còn lại
    for tr in tool_results:
        if not tr.get("success"):
            continue
        res = tr.get("result")
        if not isinstance(res, dict):
            continue
        url = res.get("source_url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        model_code = res.get("model_code") or (tr.get("args") or {}).get("model_code")
        links.append(source_link_md(url, model_code or default_model))

    return ", ".join(links)


def source_link_md(url: str, model_code: str | None = None) -> str:
    """Trả markdown link click được với nhãn ngắn: '[VF 6](url)'."""
    return f"[{_source_link_label(url, model_code)}]({url})"

# Câu trả lời mặc định cho các case không trả lời được
_DEFAULT_REPLY = "Xin lỗi, mình chưa có thông tin phù hợp. Bạn có thể hỏi lại bằng câu khác được không?"


@dataclass
class AgentResult:
    response: str
    sources: list[dict] = field(default_factory=list)
    source_url: str = ""  # URL nguồn hoặc danh sách markdown link
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

    if response_text:
        answer = response_text
    elif decision == "clarify":
        answer = _DEFAULT_REPLY
    elif decision == "refuse":
        answer = _DEFAULT_REPLY
    elif decision == "out_of_scope":
        answer = "Xin lỗi, câu hỏi này nằm ngoài phạm vi tư vấn xe VinFast. Quý khách có thể hỏi về thông số kỹ thuật, giá bán hoặc chính sách của các dòng xe VinFast ạ! 😊"
    else:
        answer = final_response
    
    # Lấy toàn bộ link URL nguồn từ tool results (hỗ trợ nhiều model khi so sánh)
    source_links_str = ""
    if decision == "answer" and tool_results:
        source_links_str = format_source_links(tool_results, entities.get("model_code"))
    
    # Thêm link URL ở cuối câu trả lời (markdown link ngắn, click được)
    if source_links_str:
        answer = answer.rstrip() + "\n\n🔗 Xem thêm: " + source_links_str

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
            source_url=source_links_str,
            needs_clarification=(decision == "clarify"),
            classify_result=_build_classify_result(state),
            decision=decision,
            decision_log=decision_log,
        )
    }
