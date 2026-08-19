"""Custom application exception hierarchy for Vivu VinFast Assistant.

Enables structured error classification, consistent API responses, and clean tracing.
"""

from typing import Any


class AppError(Exception):
    """Base exception for all domain and infrastructure errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "error": self.message,
            "code": self.code,
            "status_code": self.status_code,
        }
        if self.details:
            result["details"] = self.details
        return result


class DBConnectionError(AppError):
    """Lỗi kết nối cơ sở dữ liệu PostgreSQL / Neon."""

    def __init__(
        self, message: str = "Không thể kết nối cơ sở dữ liệu PostgreSQL", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, code="DB_CONNECTION_ERROR", status_code=503, details=details)


class LLMProviderError(AppError):
    """Lỗi gọi mô hình ngôn ngữ lớn (OpenAI / DeepInfra)."""

    def __init__(self, message: str = "Lỗi kết nối nhà cung cấp mô hình AI", details: dict[str, Any] | None = None):
        super().__init__(message=message, code="LLM_PROVIDER_ERROR", status_code=502, details=details)


class RAGRetrievalError(AppError):
    """Lỗi truy vấn Vector DB Qdrant / Hybrid search."""

    def __init__(self, message: str = "Lỗi truy vấn hệ thống tri thức RAG", details: dict[str, Any] | None = None):
        super().__init__(message=message, code="RAG_RETRIEVAL_ERROR", status_code=502, details=details)


class InvalidSessionIdError(AppError):
    """Session ID không đúng định dạng UUID."""

    def __init__(
        self, message: str = "session_id không hợp lệ (cần định dạng UUID)", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, code="INVALID_SESSION_ID", status_code=400, details=details)


class MessageTooLongError(AppError):
    """Câu hỏi vượt quá giới hạn token cho phép."""

    def __init__(
        self,
        message: str = "Câu hỏi quá dài. Vui lòng rút gọn nội dung câu hỏi.",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code="MESSAGE_TOO_LONG", status_code=400, details=details)


class HistoryTooLongError(AppError):
    """Lịch sử hội thoại vượt quá giới hạn token cho phép."""

    def __init__(
        self,
        message: str = "Lịch sử hội thoại quá dài. Vui lòng bấm 'Cuộc trò chuyện mới' để tiếp tục.",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code="HISTORY_TOO_LONG", status_code=400, details=details)


class DuplicateMessageError(AppError):
    """Tin nhắn bị trùng lặp (Idempotency deduplication)."""

    def __init__(
        self, message: str = "Tin nhắn trùng lặp. Đang xử lý hoặc đã hoàn thành.", details: dict[str, Any] | None = None
    ):
        super().__init__(message=message, code="DUPLICATE_MESSAGE", status_code=409, details=details)


class RateLimitExceededError(AppError):
    """Vượt quá giới hạn tần suất gọi API."""

    def __init__(
        self,
        message: str = "Bạn đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau.",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code="RATE_LIMIT_EXCEEDED", status_code=429, details=details)
