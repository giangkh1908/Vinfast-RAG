"""Session store cho multi-turn — DB lưu summary + metadata theo session_id.

Phân vai:
- Messages: KHÔNG lưu DB — client giữ trong localStorage, gửi window (≤10 turn) mỗi request.
- DB (chat_sessions): chỉ giữ running summary + thống kê phiên (turn_count, timestamps)
  → đủ để build context (system + summary + window + query) mà client không cần gửi summary,
    và phục vụ analytics + cleanup session chết.

Mỗi request tốn 2 thao tác nhỏ:
  1 SELECT (đọc summary) + 1 UPSERT (tăng turn_count, cập nhật summary nếu có)
→ ~1-3ms trên Neon, không đáng kể so với 1 LLM call.
"""

import asyncio
import logging
import uuid
from typing import Any

from app.core.storage.db import (
    RETRYABLE_DB_ERRORS,
    get_pool,
    run_with_db_retry,
)
from app.schemas import CHAT_SESSIONS_SCHEMA_SQL

logger = logging.getLogger("bds.session_store")

_SCHEMA_SQL = CHAT_SESSIONS_SCHEMA_SQL

_ensure_lock = asyncio.Lock()
_schema_ready = False


async def ensure_schema() -> None:
    """Tạo bảng + index nếu chưa có (idempotent, tự chạy lần dùng đầu)."""
    global _schema_ready
    if _schema_ready:
        return
    async with _ensure_lock:
        if _schema_ready:
            return

        async def _create_schema() -> None:
            pool = await get_pool()
            async with pool.acquire() as conn:
                for stmt in _SCHEMA_SQL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await conn.execute(stmt)

        await run_with_db_retry(_create_schema, label="ensure chat_sessions schema")
        _schema_ready = True


def parse_session_id(session_id: str) -> uuid.UUID:
    """Validate session_id — ném ValueError nếu sai format (API bắt → 400)."""
    return uuid.UUID(session_id)


async def get_session(session_id: str) -> dict[str, Any]:
    """Đọc summary + thống kê của session. Trả {} nếu session chưa tồn tại.

    Session metadata không được phép làm hỏng chat chính khi Neon chập chờn.
    """
    try:
        await ensure_schema()

        async def _fetch_session():
            pool = await get_pool()
            return await pool.fetchrow(
                """SELECT session_id, summary, summary_tokens, turn_count, created_at, updated_at, last_message
                   FROM chat_sessions WHERE session_id = $1""",
                parse_session_id(session_id),
            )

        row = await run_with_db_retry(_fetch_session, label="get_session")
        return dict(row) if row else {}
    except RETRYABLE_DB_ERRORS as exc:
        # Fail-open: history summary chỉ là metadata; không được biến request
        # chat thành HTTP 500 khi network tới Neon vừa bị reset.
        logger.warning("get_session unavailable, continuing without session: %s", exc)
        return {}


async def touch_session(session_id: str, *, last_message: str = "") -> None:
    """Ghi nhận 1 turn: tăng turn_count + cập nhật last_message.

    UPSERT — session mới được tạo tự động ở turn đầu.
    KHÔNG đụng cột summary/summary_tokens — chúng thuộc quyền `update_summary`
    (tránh ghi đè nhầm 0/NULL vào summary_tokens ở các turn không summarize).
    """
    try:
        await ensure_schema()

        async def _touch() -> None:
            pool = await get_pool()
            await pool.execute(
                """INSERT INTO chat_sessions (session_id, turn_count, last_message)
                   VALUES ($1, 1, $2)
                   ON CONFLICT (session_id) DO UPDATE SET
                       turn_count   = chat_sessions.turn_count + 1,
                       last_message = EXCLUDED.last_message,
                       updated_at   = now()""",
                parse_session_id(session_id),
                last_message,
            )

        await run_with_db_retry(_touch, label="touch_session")
    except RETRYABLE_DB_ERRORS as exc:
        logger.warning("touch_session skipped (PG unavailable): %s", exc)


async def cleanup_stale_sessions(max_age_days: int = 30) -> int:
    """Xoá session không hoạt động quá N ngày (chạy định kỳ). Trả số dòng đã xoá."""
    await ensure_schema()
    pool = await get_pool()
    status = await pool.execute(
        "DELETE FROM chat_sessions WHERE updated_at < now() - $1::interval",
        f"{max_age_days} days",
    )
    # status dạng "DELETE <n>"
    return int(status.split()[-1])


async def update_summary(session_id: str, summary: str | None, summary_tokens: int = 0) -> None:
    """Cập nhật summary KHÔNG tăng turn_count (gọi từ summarize node — Task 5)."""
    try:
        await ensure_schema()

        async def _update() -> None:
            pool = await get_pool()
            await pool.execute(
                "UPDATE chat_sessions SET summary = $2, summary_tokens = $3, updated_at = now() WHERE session_id = $1",
                parse_session_id(session_id),
                summary,
                summary_tokens,
            )

        await run_with_db_retry(_update, label="update_summary")
    except RETRYABLE_DB_ERRORS as exc:
        logger.warning("update_summary skipped (PG unavailable): %s", exc)
