"""P0 decision log builder — make_decision_log (schema §4)."""

import logging
import uuid
from datetime import UTC, datetime

from app.agent.decision.chunks import build_displayed_citations, build_retrieved_chunks
from app.agent.decision.evidence import assess_evidence
from app.agent.decision.models import DecisionLog
from app.agent.decision.reason_codes import resolve_reason_code
from app.agent.decision.version_utils import _get_build_version, _get_data_snapshot_id, _get_prompt_hash

logger = logging.getLogger("bds.decision")


def make_decision_log(
    query: str,
    classify_result,
    tool_results: list[dict],
    response: str,
    citations: list[dict],
    *,
    conversation_id: str = "",
    turn_index: int = 0,
    previous_request_id: str = "",
    latency_ms: float = 0.0,
    latency_retrieval_ms: float = 0.0,
    latency_generation_ms: float = 0.0,
    prompt_hash: str = "",
    error_stage: str = "",
    error_type: str = "",
    error_message: str = "",
    topic: str = "",
    history: list[dict] | None = None,
) -> DecisionLog:
    model = classify_result.entities.get("model_code", "unknown")
    version = classify_result.entities.get("version", "all_versions")
    detected_topic = topic or getattr(classify_result, "specificity", "unknown")

    # Build context-aware scoring query for multi-turn follow-ups
    # "plus" → "VF8 đi được bao nhiêu km? Bản Plus" → better keyword matching
    scoring_query = query
    if history:
        history_queries = [m["content"] for m in history if m.get("role") == "user"]
        if history_queries:
            scoring_query = " ".join(history_queries) + " " + query

    assessment, _ = assess_evidence(tool_results, scoring_query) if tool_results else ("not_run", [])

    reason_code = resolve_reason_code(classify_result.reason)
    retrieval_status = (
        "success"
        if tool_results
        else ("not_run" if classify_result.decision in ("clarify", "out_of_scope") else "no_result")
    )

    retrieved_chunks = build_retrieved_chunks(tool_results, scoring_query, topic=detected_topic)

    return DecisionLog(
        request_id=f"req_{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(UTC).isoformat(),
        build_version=_get_build_version(),
        prompt_version=prompt_hash or _get_prompt_hash(""),
        data_snapshot_id=_get_data_snapshot_id(),
        environment="production",
        conversation_id=conversation_id or uuid.uuid4().hex[:12],
        turn_index=turn_index,
        previous_request_id=previous_request_id or None,
        user_query=query,
        detected_vehicle_model=model,
        detected_vehicle_version=version,
        detected_topic=detected_topic,
        decision=classify_result.decision,
        reason_code=reason_code,
        retrieval_status=retrieval_status,
        retrieved_chunks=retrieved_chunks,
        retrieval_query=query,
        requested_top_k=5,
        evidence_assessment=assessment,
        displayed_answer=response[:2000],
        displayed_citations=build_displayed_citations(citations, retrieved_chunks),
        error_stage=error_stage or None,
        error_type=error_type or None,
        error_message=error_message or None,
        latency_total_ms=round(latency_ms, 1),
        latency_retrieval_ms=round(latency_retrieval_ms, 1),
        latency_generation_ms=round(latency_generation_ms, 1),
    )
