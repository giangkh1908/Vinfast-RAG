"""Langfuse distributed tracing — lifecycle spans cho 1 request chat.

Thay thế Phoenix: Langfuse là SaaS (keys đã có trong .env), không cần chạy server.
LangfuseAsyncOpenAI (app/agent/llm.py) đã auto-trace từng LLM call; module này thêm
span "chain" cho lifecycle request (classify → tools → generate) để 2 LLM call trong
cùng 1 câu nằm dưới 1 trace duy nhất.

Mọi lỗi đều thoái hoá thành no-op — tracing KHÔNG được phép làm hỏng request chính.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger("bds.langfuse")

_client = None


def get_langfuse():
    """Singleton Langfuse client. Trả None khi tắt / lỗi cấu hình."""
    global _client
    if _client is not None:
        return _client
    try:
        from app.config import settings

        if not settings.langfuse_enabled:
            return None
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            flush_at=20,
            flush_interval=5,
        )
        return _client
    except Exception as e:  # noqa: BLE001
        logger.debug("Langfuse disabled: %s", e)
        return None


class _NoopSpan:
    """Stub khi Langfuse tắt — mọi method thành no-op."""

    def __bool__(self):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def update(self, *args, **kwargs):  # noqa: D401
        return None


@asynccontextmanager
async def langfuse_chain(name: str, *, input: object = None, **meta) -> AsyncIterator[object]:
    """Context manager mở 1 span 'chain' trong Langfuse (no-op nếu tắt).

    Mọi LLM call bên trong (qua LangfuseAsyncOpenAI) tự nest dưới span này.
    """
    lf = get_langfuse()
    if lf is None:
        yield _NoopSpan()
        return
    try:
        # start_as_current_observation chỉ hỗ trợ sync `with` (không phải async),
        # nhưng dùng được trong hàm async vì nó chỉ set span làm "current" trong
        # context — các await bên trong vẫn nest đúng theo event loop task.
        with lf.start_as_current_observation(
            name=name,
            as_type="chain",
            input=input,
            metadata=meta,
        ) as span:  # type: ignore
            yield span
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse span '%s' failed (no-op): %s", name, e)
        yield _NoopSpan()


async def flush() -> None:
    """Flush bất đồng bộ buffer lên Langfuse cloud."""
    try:
        lf = get_langfuse()
        if lf is not None:
            await lf.flush_async()
    except Exception:  # noqa: BLE001
        pass
