"""LLM streaming với fallback model.

Chính: settings.llm_model (gemini-3.1-flash-lite).
Dự phòng: settings.llm_fallback_model (claude-haiku-4-5) — tự kích hoạt khi
model chính lỗi TRƯỚC khi stream bất kỳ token nào.

Đã stream token ra client rồi mà lỗi → KHÔNG fallback (tránh duplicate token).
Lưu ý: follow-up sau tool call của Gemini trên DeepInfra luôn lỗi 400
(thiếu thought_signature) → fallback Haiku xử lý tiếp được loop đó.
"""

import logging

from openai import AsyncOpenAI

from app.config import llm_extra_kwargs, settings

logger = logging.getLogger("bds.llm")

_llm_client: "AsyncOpenAI | None" = None


def get_llm():
    """Client chat chính (DeepInfra, OpenAI-compatible) — dùng chung toàn app."""
    global _llm_client
    if _llm_client is None:
        if settings.langfuse_enabled:
            try:
                from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI

                _llm_client = LangfuseAsyncOpenAI(
                    api_key=settings.deepinfra_api_key,
                    base_url=settings.deepinfra_base_url,
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
                logger.info("Langfuse AsyncOpenAI wrapper enabled (host=%s)", settings.langfuse_host)
            except Exception as exc:
                logger.warning("Could not initialize Langfuse AsyncOpenAI (%s), fallback to native AsyncOpenAI", exc)
                _llm_client = AsyncOpenAI(api_key=settings.deepinfra_api_key, base_url=settings.deepinfra_base_url)
        else:
            _llm_client = AsyncOpenAI(api_key=settings.deepinfra_api_key, base_url=settings.deepinfra_base_url)
    return _llm_client


# ── Token limits (có thể override qua .env) ───────────────────────────────
# Output: cap độ dài câu trả lời/tool call → kiểm soát chi phí + latency,
# không phụ thuộc default của provider (DeepInfra thường cap thấp hơn).
OUTPUT_MAX_TOKENS: int = settings.llm_max_output_tokens  # câu trả lời chat cuối
TOOL_CALL_MAX_TOKENS: int = settings.llm_tool_call_max_tokens  # JSON tool call
USER_INPUT_MAX_TOKENS: int = settings.llm_user_input_max_tokens  # 1 message người dùng tối đa
# Input: tổng budget messages gửi lên model (system + history + query).
# Context retrieved chunks (RAG) tính riêng — xử lý sau ở tầng retrieval/top-k.
INPUT_MAX_TOKENS: int = settings.llm_input_max_tokens


def estimate_tokens(text: str) -> int:
    """Ước lượng token nhanh, không cần tokenizer (Vi/En ~4 ký tự/token)."""
    return max(1, len(text) // 4)


def truncate_text(text: str, max_tokens: int) -> str:
    """Cắt text còn tối đa max_tokens token (ước lượng ~4 ký tự/token)."""
    if not text or estimate_tokens(text) <= max_tokens:
        return text
    cut_at = max(0, max_tokens * 4)
    return text[:cut_at] + "\n…[bị cắt do vượt token budget]"


def truncate_messages(messages: list[dict], max_tokens: int = INPUT_MAX_TOKENS) -> list[dict]:
    """Cắt messages cho vừa budget token — giữ system (đầu) + user (cuối).

    1. Tổng token ≤ budget → trả nguyên.
    2. Quá → drop dần history cũ nhất (giữa) cho tới khi chỉ còn [system, user].
    3. Vẫn quá → cắt đuôi từng message còn lại (trừ system), ưu tiên cũ trước.
    """
    if not messages:
        return messages

    def _tok(m: dict) -> int:
        return estimate_tokens(m.get("content", "") or "")

    # Bước 2: giữ system[0] + user[-1], drop history cũ nhất ở index 1
    while len(messages) > 2 and sum(_tok(m) for m in messages) > max_tokens:
        messages.pop(1)

    if sum(_tok(m) for m in messages) <= max_tokens:
        return messages

    # Bước 3: cắt đuôi các message còn lại (thường là user query bị dán quá dài)
    used = sum(_tok(m) for m in messages)
    for m in messages[1:]:
        if used <= max_tokens:
            break
        content = m.get("content", "") or ""
        overflow_chars = (used - max_tokens) * 4
        cut_at = max(0, len(content) - overflow_chars)
        if cut_at <= 0 or cut_at >= len(content):
            continue
        new_content = content[:cut_at] + "\n…[bị cắt do vượt token budget]"
        used -= estimate_tokens(content) - estimate_tokens(new_content)
        m["content"] = new_content
    return messages


try:
    from langgraph.config import get_stream_writer as _lg_get_writer
except ImportError:
    _lg_get_writer = None


def get_writer():
    """Writer để stream token ra client (custom stream mode). None nếu không có."""
    if _lg_get_writer is None:
        return None
    try:
        return _lg_get_writer()
    except Exception:
        return None


class PartialStreamError(Exception):
    """Lỗi xảy ra SAU khi đã stream token → không được fallback/retry."""


def _models_chain() -> list[str]:
    chain = [settings.llm_model]
    fb = settings.llm_fallback_model
    if fb and fb != settings.llm_model:
        chain.append(fb)
    return chain


async def _stream_chat(llm, model: str, messages: list, writer, **kwargs) -> tuple[str, dict]:
    """Stream 1 call, accumulate content + tool-call deltas. Trả (content, acc)."""
    import time as _time

    _t0 = _time.perf_counter()
    content_parts: list[str] = []
    tool_calls_acc: dict[int, dict] = {}
    got_chunk = False
    word_buffer = ""
    try:
        stream = await llm.chat.completions.create(model=model, messages=messages, stream=True, **kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            got_chunk = True
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                if writer:
                    word_buffer += delta.content
                    # Tìm ranh giới từ cuối cùng (khoảng trắng hoặc xuống dòng)
                    last_break = max(
                        word_buffer.rfind(" "),
                        word_buffer.rfind("\n"),
                        word_buffer.rfind("\t"),
                    )
                    if last_break != -1:
                        to_emit = word_buffer[: last_break + 1]
                        word_buffer = word_buffer[last_break + 1 :]
                        if to_emit:
                            writer({"type": "token", "content": to_emit})
            if delta.tool_calls:
                if writer and word_buffer:
                    writer({"type": "token", "content": word_buffer})
                    word_buffer = ""
                for tc in delta.tool_calls:
                    acc = tool_calls_acc.setdefault(tc.index or 0, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            acc["name"] += tc.function.name
                        if tc.function.arguments:
                            acc["arguments"] += tc.function.arguments
        # Flush phần còn lại ở cuối câu
        if writer and word_buffer:
            writer({"type": "token", "content": word_buffer})
            word_buffer = ""
    except Exception as e:
        if got_chunk:
            raise PartialStreamError(str(e)) from e
        raise
    finally:
        try:
            from app.core.telemetry.prometheus import record_llm

            record_llm(model=model, duration_s=_time.perf_counter() - _t0)
        except Exception:
            pass
    return "".join(content_parts), tool_calls_acc


async def stream_chat_with_fallback(llm, messages: list, writer=None, **kwargs) -> tuple[str, dict, str]:
    """Thử lần lượt model chính → fallback.

    Trả (content, tool_calls_acc, model_used). Ném exception nếu cả chain lỗi
    (hoặc PartialStreamError nếu lỗi sau khi đã stream token).
    """
    if writer is None:
        writer = get_writer()
    last_err: Exception | None = None
    for model in _models_chain():
        kw = dict(kwargs)
        kw.update(llm_extra_kwargs(model))  # reasoning_effort theo từng model
        try:
            content, acc = await _stream_chat(llm, model, messages, writer, **kw)
            if model != settings.llm_model:
                logger.info("LLM fallback activated: %s", model)
            return content, acc, model
        except PartialStreamError:
            raise
        except Exception as e:
            logger.warning("LLM %s failed (%s) — thử model tiếp theo", model, type(e).__name__)
            last_err = e
    raise last_err
