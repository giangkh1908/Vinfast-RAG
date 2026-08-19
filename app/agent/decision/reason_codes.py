"""Reason codes — contract §5: enum + BDS classifier map + refusal messages."""

import logging
from enum import StrEnum

logger = logging.getLogger("bds.decision")


# ── Reason Code Enum (contract §5) ─────────────────────────────────────────
class ReasonCode(StrEnum):
    # answer
    SUFFICIENT_DIRECT_EVIDENCE = "sufficient_direct_evidence"
    PARTIAL_DIRECT_EVIDENCE = "partial_direct_evidence"
    # clarify
    MISSING_MODEL = "missing_model"
    MISSING_VERSION = "missing_version"
    MISSING_TOPIC = "missing_topic"
    AMBIGUOUS_CONTEXT = "ambiguous_context"
    # refuse
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INDIRECT_EVIDENCE = "indirect_evidence"
    INVALID_SOURCE = "invalid_source"
    SOURCE_CONFLICT = "source_conflict"
    CITATION_FAILURE = "citation_failure"
    SYSTEM_ERROR = "system_error"
    GROUNDING_FAILURE = "grounding_failure"
    # out_of_scope
    UNSUPPORTED_MODEL = "unsupported_model"
    UNSUPPORTED_COMPARISON = "unsupported_comparison"
    UNSUPPORTED_RECOMMENDATION = "unsupported_recommendation"
    UNSUPPORTED_PRICING_POLICY = "unsupported_pricing_policy"
    UNSUPPORTED_AFTER_SALES = "unsupported_after_sales"
    UNSUPPORTED_SAFETY_DIAGNOSIS = "unsupported_safety_diagnosis"
    UNSUPPORTED_CONTACT_WORKFLOW = "unsupported_contact_workflow"
    EXTERNAL_SOURCE_REQUESTED = "external_source_requested"
    PERSONAL_DATA_OR_TRANSACTION = "personal_data_or_transaction"


# Map classifier reason strings → ReasonCode
_REASON_MAP = {
    "BDS-01": ReasonCode.SUFFICIENT_DIRECT_EVIDENCE,
    "BDS-02": ReasonCode.MISSING_MODEL,
    "BDS-02A": ReasonCode.UNSUPPORTED_MODEL,
    "BDS-03": ReasonCode.MISSING_VERSION,
    "BDS-04": ReasonCode.SUFFICIENT_DIRECT_EVIDENCE,
    "BDS-05": ReasonCode.MISSING_TOPIC,
    "BDS-06": ReasonCode.INSUFFICIENT_EVIDENCE,
    "BDS-07A": ReasonCode.INDIRECT_EVIDENCE,
    "BDS-07B": ReasonCode.PARTIAL_DIRECT_EVIDENCE,
    "BDS-08": ReasonCode.INVALID_SOURCE,
    "BDS-09": ReasonCode.SOURCE_CONFLICT,
    "BDS-10": ReasonCode.AMBIGUOUS_CONTEXT,
    "BDS-11": ReasonCode.UNSUPPORTED_COMPARISON,
    "BDS-12": ReasonCode.UNSUPPORTED_RECOMMENDATION,
    "BDS-13": ReasonCode.UNSUPPORTED_PRICING_POLICY,
    "BDS-14": ReasonCode.UNSUPPORTED_AFTER_SALES,
    "BDS-15": ReasonCode.UNSUPPORTED_SAFETY_DIAGNOSIS,
    "BDS-16": ReasonCode.UNSUPPORTED_CONTACT_WORKFLOW,
    "BDS-17": ReasonCode.EXTERNAL_SOURCE_REQUESTED,
    "BDS-18": ReasonCode.CITATION_FAILURE,
    "BDS-19": ReasonCode.SYSTEM_ERROR,
    "insufficient_evidence": ReasonCode.INSUFFICIENT_EVIDENCE,
    "no_citation": ReasonCode.CITATION_FAILURE,
    "grounding_fail": ReasonCode.GROUNDING_FAILURE,
    "system_error": ReasonCode.SYSTEM_ERROR,
    "comparison": ReasonCode.UNSUPPORTED_COMPARISON,
    "recommendation": ReasonCode.UNSUPPORTED_RECOMMENDATION,
    "pricing": ReasonCode.UNSUPPORTED_PRICING_POLICY,
    "warranty_maintenance": ReasonCode.UNSUPPORTED_AFTER_SALES,
    "diagnostics": ReasonCode.UNSUPPORTED_SAFETY_DIAGNOSIS,
    "hotline_showroom": ReasonCode.UNSUPPORTED_CONTACT_WORKFLOW,
    "external_source": ReasonCode.EXTERNAL_SOURCE_REQUESTED,
    "personal_data": ReasonCode.PERSONAL_DATA_OR_TRANSACTION,
    "model_oos": ReasonCode.UNSUPPORTED_MODEL,
    "ambiguous_context": ReasonCode.AMBIGUOUS_CONTEXT,
    "missing_model": ReasonCode.MISSING_MODEL,
    "missing_version": ReasonCode.MISSING_VERSION,
    "missing_topic": ReasonCode.MISSING_TOPIC,
    "missing_context": ReasonCode.AMBIGUOUS_CONTEXT,
    "sufficient_direct": ReasonCode.SUFFICIENT_DIRECT_EVIDENCE,
}


def resolve_reason_code(reason: str) -> str:
    """Map classifier reason string → ReasonCode enum value."""
    for prefix, code in sorted(_REASON_MAP.items(), key=lambda x: -len(x[0])):
        if prefix in reason:
            return code.value
    logger.warning("Unmapped classifier reason: %r — defaulting to system_error for safety", reason)
    return ReasonCode.SYSTEM_ERROR.value


_DEFAULT_REPLY = "Xin lỗi, mình chưa có thông tin phù hợp. Bạn có thể hỏi lại bằng câu khác được không?"


# ── Response Messages ──────────────────────────────────────────────────────
REFUSAL_MESSAGES = {
    "insufficient_evidence": _DEFAULT_REPLY,
    "no_citation": _DEFAULT_REPLY,
    "grounding_fail": _DEFAULT_REPLY,
    "system_error": "Có lỗi xảy ra. Vui lòng thử lại.",
}


def get_clarify_messages() -> dict[str, str]:
    return {
        "model_code": _DEFAULT_REPLY,
        "topic": _DEFAULT_REPLY,
    }
