"""Structured logging — JSON formatter + request context (request_id/session_id).

- 1 request → cùng request_id trên mọi log node (classify → tools → generate → validate)
  nhờ `contextvars` được gán bởi ASGI middleware.
- `LOG_FORMAT=json` → JSON lines, parse được bởi ELK/Loki/Grafana.
  `LOG_FORMAT=text` (mặc định) → giữ format quen thuộc cho terminal/dev.
"""

import contextvars
import json
import logging
import uuid

# Context vars: set per-request bởi middleware (main.py) / chat handler.
current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)

_EXTRA_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }
)


def set_request_context(request_id: str | None = None, session_id: str | None = None) -> str:
    """Gán request context cho request hiện tại; trả request_id đã dùng."""
    rid = request_id or uuid.uuid4().hex[:12]
    current_request_id.set(rid)
    if session_id is not None:
        current_session_id.set(session_id)
    return rid


def clear_request_context() -> None:
    """Reset context sau request (tránh rò rỉ giữa các request trong thread pool)."""
    current_request_id.set(None)
    current_session_id.set(None)


class JsonFormatter(logging.Formatter):
    """JSON-lines formatter: ts/level/logger/message + request_id/session_id + extra."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = current_request_id.get()
        sid = current_session_id.get()
        if rid:
            data["request_id"] = rid
        if sid:
            data["session_id"] = sid
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        # Merge any `extra` fields the caller passed (except reserved attrs)
        for key, value in record.__dict__.items():
            if key not in _EXTRA_ATTRS and not key.startswith("_"):
                try:
                    json.dumps({key: value})
                    data[key] = value
                except (TypeError, ValueError):
                    data[key] = str(value)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(log_format: str | None = None) -> None:
    """Cấu hình root logger. `log_format` override env LOG_FORMAT nếu truyền.

    - json: lắng nghe cả warning/error từ library vào terminal dưới dạng JSON.
    - text: giữ `%(asctime)s %(levelname)s %(name)s: %(message)s` như cũ.
    """
    fmt = (log_format or "text").lower()
    level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Xoá handler sẵn có (basicConfig đã chạy / môi trường có sẵn) để không trùng log.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(handler)

    logging.getLogger("bds").setLevel(level)
