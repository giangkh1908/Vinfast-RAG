"""Decision module — package split từ decision.py (1170 dòng) thành các module nhỏ.

Giữ NGUYÊN public API: mọi `from app.agent.decision import X` vẫn hoạt động
(respond.py, validate.py, chat.py, tests...). Các khối:

- reason_codes.py  — ReasonCode enum, BDS map, resolve_reason_code, REFUSAL_MESSAGES
- version_utils.py — build version / prompt hash / data snapshot id (git, PG, manifest)
- models.py        — RetrievedChunk, DisplayedCitation, DecisionLog, LogStore
- evidence.py      — keyword maps + assess_evidence (LRU memoize) + validate_citations
- chunks.py        — build_retrieved_chunks, build_displayed_citations
- log_builder.py   — make_decision_log (P0 log schema)
"""

from app.agent.decision.chunks import build_displayed_citations, build_retrieved_chunks
from app.agent.decision.evidence import (
    _MODEL_RE,
    _SPEC_QUERY_KEYWORDS,
    _TOKEN_RE,
    _assess_evidence_impl,
    _price_relevance_score,
    _query_models,
    _query_tokens,
    _score_specs_rerank,
    _spec_relevance_score,
    assess_evidence,
    validate_citations,
)
from app.agent.decision.log_builder import make_decision_log
from app.agent.decision.models import (
    DecisionLog,
    DisplayedCitation,
    LogStore,
    RetrievedChunk,
    log_store,
)
from app.agent.decision.reason_codes import (
    _DEFAULT_REPLY,
    REFUSAL_MESSAGES,
    ReasonCode,
    get_clarify_messages,
    resolve_reason_code,
)
from app.agent.decision.version_utils import (
    _get_build_version,
    _get_data_snapshot_id,
    _get_prompt_hash,
    _warm_snapshot_cache,
)

# Warm cache nền cho data_snapshot_id (PG round-trip ~15s từ VN → Neon) — chạy
# một lần lúc import, request đầu không bị block.
_warm_snapshot_cache()

__all__ = [
    # reason_codes
    "ReasonCode",
    "resolve_reason_code",
    "REFUSAL_MESSAGES",
    "get_clarify_messages",
    "_DEFAULT_REPLY",
    # version_utils
    "_get_build_version",
    "_get_prompt_hash",
    "_get_data_snapshot_id",
    "_warm_snapshot_cache",
    # models
    "RetrievedChunk",
    "DisplayedCitation",
    "DecisionLog",
    "LogStore",
    "log_store",
    # evidence
    "_SPEC_QUERY_KEYWORDS",
    "_TOKEN_RE",
    "_MODEL_RE",
    "_query_tokens",
    "_query_models",
    "_spec_relevance_score",
    "_price_relevance_score",
    "_score_specs_rerank",
    "assess_evidence",
    "_assess_evidence_impl",
    "validate_citations",
    # chunks
    "build_retrieved_chunks",
    "build_displayed_citations",
    # log_builder
    "make_decision_log",
]
