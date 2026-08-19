"""Summarize node — nén các turn cũ thành running summary (multi-turn memory).

Kích hoạt ở biên turn (turn_count % SUMMARY_EVERY == 0): lấy window vừa nhận
+ summary cũ → summary mới, lưu DB qua `update_summary` (không tăng turn_count).

KHÔNG phải node trong graph — được gọi từ `chat.py` SAU khi response đã xong
(finally), nên không làm tăng latency của câu trả lời.
"""

import logging

from app.agent.history import WINDOW_TURNS
from app.agent.llm import get_llm, stream_chat_with_fallback

logger = logging.getLogger("bds.summarize")

# Mỗi 7 turn summarize 1 lần (khớp window 7 turn — summary "bắt kịp" phần
# history vừa rời khỏi window, xem docs/MEMORY_PLAN.md mục ⑤)
SUMMARY_EVERY = WINDOW_TURNS
SUMMARY_MAX_TOKENS = 256

_SUMMARIZE_SYSTEM = "Bạn là trợ lý tóm tắt hội thoại tư vấn xe VinFast, chính xác và ngắn gọn."

_SUMMARIZE_PROMPT = """Tóm tắt hội thoại tư vấn xe VinFast dưới đây. {extend}

ĐẶC BIỆT GIỮ các thông tin:
- Model xe / phiên bản người dùng đang quan tâm
- Tầm giá, màu sắc, tùy chọn đã đề cập
- Câu hỏi CHƯA được trả lời / chưa đủ dữ liệu
- Quyết định / sở thích của người dùng

Viết bằng tiếng Việt, dạng gạch đầu dòng ngắn gọn, tối đa {max_tokens} token.
Chỉ giữ thông tin CÓ GIÁ TRỊ cho các turn sau, bỏ chào hỏi/rác."""


async def summarize_conversation(
    prev_summary: str | None,
    window: list[dict],
    query: str,
) -> str | None:
    """Tóm tắt window + summary cũ → summary mới. Trả None nếu không summarize được."""
    if not window and not prev_summary and not query:
        return None

    lines = [f"{m['role']}: {m['content']}" for m in window]
    if query:
        lines.append(f"user: {query}")
    convo = "\n".join(lines)

    extend = (
        f"Đây là tóm tắt cũ, hãy GHI TIẾP (giữ nguyên phần cũ, bổ sung phần mới):\n{prev_summary}\n"
        if prev_summary
        else "Đây là lần tóm tắt đầu tiên:"
    )

    messages = [
        {"role": "system", "content": _SUMMARIZE_SYSTEM},
        {
            "role": "user",
            "content": _SUMMARIZE_PROMPT.format(extend=extend, max_tokens=SUMMARY_MAX_TOKENS)
            + f"\n\nHội thoại:\n{convo}",
        },
    ]

    try:
        content, _, _ = await stream_chat_with_fallback(get_llm(), messages, max_tokens=SUMMARY_MAX_TOKENS)
        summary = (content or "").strip()
        return summary or None
    except Exception as e:
        logger.warning("summarize failed: %s", e)
        return None
