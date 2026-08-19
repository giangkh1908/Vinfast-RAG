"""
app/core/storage — Database Connection Pooling, Chat Sessions, and Multi-tier Caching.
"""

from app.core.storage.cache import (
    ANS_TTL,
    DEDUP_TTL,
    cache,
    make_answer_key,
    make_dedup_key,
    make_embed_key,
    make_exact_io_key,
    make_hs_key,
)
from app.core.storage.db import (
    RETRYABLE_DB_ERRORS,
    TimedAcquire,
    get_pool,
    pool_stats,
    reset_pool,
    run_with_db_retry,
)
from app.core.storage.session_store import (
    ensure_schema as ensure_session_schema,
)
from app.core.storage.session_store import (
    get_session,
    parse_session_id,
    touch_session,
    update_summary,
)

__all__ = [
    "get_pool",
    "reset_pool",
    "run_with_db_retry",
    "pool_stats",
    "RETRYABLE_DB_ERRORS",
    "TimedAcquire",
    "get_session",
    "touch_session",
    "update_summary",
    "parse_session_id",
    "ensure_session_schema",
    "cache",
    "make_dedup_key",
    "make_exact_io_key",
    "make_answer_key",
    "make_embed_key",
    "make_hs_key",
    "DEDUP_TTL",
    "ANS_TTL",
]
