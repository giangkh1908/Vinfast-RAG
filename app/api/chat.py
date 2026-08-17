import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent.agent_loop import AgentLoop
from app.agent.history import MAX_HISTORY_TOKENS, sanitize_history
from app.agent.llm import USER_INPUT_MAX_TOKENS, estimate_tokens
from app.agent.nodes.summarize import SUMMARY_EVERY, summarize_conversation
from app.core.session_store import get_session, touch_session, update_summary
from app.core.cache import cache, make_dedup_key, make_answer_key, DEDUP_TTL, ANS_TTL
from app.agent.classifier import get_classifier
from app.agent.intent import classify_intent

logger = logging.getLogger("bds.api")

router = APIRouter()

_agent = None


def get_agent() -> AgentLoop:
    global _agent
    if _agent is None:
        _agent = AgentLoop()
    return _agent


class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list[dict] = []
    message_id: str | None = None  # UUID để chống gửi trùng


class ChatResponse(BaseModel):
    response: str
    needs_clarification: bool = False
    classify: dict = {}
    decision: str = "answer"
    decision_log: dict = {}


_INPUT_TOO_LONG_MSG = (
    f"Câu hỏi quá dài (tối đa {USER_INPUT_MAX_TOKENS} token ~ "
    f"{USER_INPUT_MAX_TOKENS * 4} ký tự). Vui lòng rút gọn câu hỏi rồi thử lại."
)


def _reject_if_too_long(message: str) -> None:
    """Từ chối request nếu input người dùng vượt token budget (không cắt ngầm)."""
    if estimate_tokens(message) > USER_INPUT_MAX_TOKENS:
        raise HTTPException(status_code=400, detail=_INPUT_TOO_LONG_MSG)


def _parse_session_id(session_id: str) -> str:
    """Validate session_id là UUID v4 — sai format trả 400."""
    try:
        return str(uuid.UUID(session_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="session_id không hợp lệ")


def _check_history_size(history: list[dict]) -> None:
    """Defense in depth: từ chối request có history quá lớn (trước khi sanitize)."""
    total = sum(
        estimate_tokens(str(m.get("content", "")))
        for m in history
        if isinstance(m, dict)
    )
    if total > MAX_HISTORY_TOKENS:
        raise HTTPException(
            status_code=400,
            detail="Lịch sử hội thoại quá dài, vui lòng bắt đầu hội thoại mới.",
        )


async def _prepare_request(request: ChatRequest) -> tuple[list[dict], str | None, dict]:
    """Validate + sanitize + đọc session. Trả (history_sanitized, summary, session)."""
    _reject_if_too_long(request.message)
    _parse_session_id(request.session_id)
    _check_history_size(request.history)
    history = sanitize_history(request.history)
    session = await get_session(request.session_id)
    return history, session.get("summary"), session


async def _finish_turn(
    session_id: str,
    message: str,
    history: list[dict],
    summary: str | None,
    session: dict,
    decision: str = "answer",
) -> None:
    """Sau 1 turn: ghi nhận turn + summarize nếu tới biên (không block câu trả lời).

    Chỉ tính turn khi decision='answer' — refuse/clarify/out_of_scope không được
    lưu vào memory (turn_count không tăng, summary không thay đổi).
    """
    # Không tính turn cho các case không trả lời được
    if decision != "answer":
        return
    
    await touch_session(session_id, last_message=message)
    new_turn = (session.get("turn_count") or 0) + 1
    if new_turn % SUMMARY_EVERY == 0:
        try:
            new_summary = await summarize_conversation(summary, history, message)
            if new_summary:
                await update_summary(
                    session_id, new_summary, estimate_tokens(new_summary)
                )
                logger.info("session %s summarized at turn %d", session_id[:8], new_turn)
        except Exception:
            logger.exception("summarize failed (session %s)", session_id[:8])


async def _check_dedupe(session_id: str, message_id: str | None) -> bool:
    """Kiểm tra message đã được xử lý chưa. Trả True nếu là trùng lặp."""
    if not message_id or not cache.enabled:
        return False
    
    dedup_key = make_dedup_key(session_id, message_id)
    # Thử SET NX (chỉ set nếu key chưa tồn tại)
    # Trả về True nếu set thành công (key chưa tồn tại) -> không phải duplicate
    # Trả về False nếu set thất bại (key đã tồn tại) -> là duplicate
    set_success = await cache.set_nx_json(dedup_key, {"processed": True}, DEDUP_TTL)
    return not set_success


@router.post("/api/chat")
async def chat(request: ChatRequest):
    # Check dedupe nếu có message_id
    if await _check_dedupe(request.session_id, request.message_id):
        return JSONResponse(
            status_code=409,
            content={"error": "Tin nhắn trùng lặp", "message_id": request.message_id}
        )
    
    history, summary, session = await _prepare_request(request)
    agent = get_agent()
    result = await agent.run(
        request.message, history, summary=summary, session_id=request.session_id
    )
    await _finish_turn(request.session_id, request.message, history, summary, session, decision=result.decision)
    return ChatResponse(
        response=result.response,
        needs_clarification=result.needs_clarification,
        classify=result.classify_result,
        decision=result.decision,
        decision_log=result.decision_log,
    )


@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    # Check dedupe nếu có message_id
    if await _check_dedupe(request.session_id, request.message_id):
        return JSONResponse(
            status_code=409,
            content={"error": "Tin nhắn trùng lặp", "message_id": request.message_id}
        )
    
    history, summary, session = await _prepare_request(request)
    agent = get_agent()

    async def generate():
        decision = "answer"  # default, sẽ được cập nhật từ SSE event
        try:
            async for event in agent.run_stream(
                request.message, history, summary=summary, session_id=request.session_id
            ):
                # Capture decision từ SSE event để biết có nên ghi turn không
                if event.get("type") == "decision":
                    decision = event.get("content", "answer")
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await _finish_turn(request.session_id, request.message, history, summary, session, decision=decision)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx hay buffer SSE → phải tắt, không client nhận cả cục cuối stream
            "X-Accel-Buffering": "no",
        },
    )


from app.agent.decision import log_store


@router.get("/api/logs")
async def get_logs(run_id: str = None):
    if run_id:
        logs = log_store.get_by_run(run_id)
    else:
        logs = log_store.get_all()
    return JSONResponse(content={"count": len(logs), "run_id": run_id, "logs": logs})


@router.get("/api/logs/export")
async def export_logs(run_id: str = None):
    if run_id:
        logs = log_store.get_by_run(run_id)
    else:
        logs = log_store.get_all()
    lines = [json.dumps(l, ensure_ascii=False) for l in logs]
    content = "\n".join(lines) + "\n" if lines else ""
    fname = "logs_" + (run_id or "all") + ".jsonl"
    return StreamingResponse(
        content=iter([content]),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=" + fname},
    )
