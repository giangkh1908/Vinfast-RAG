"""
app/schemas/chat_schemas.py — Pydantic Schemas for Chat API Requests & Responses.
"""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    message_id: str | None = None  # UUID để chống gửi trùng


class ChatResponse(BaseModel):
    response: str
    needs_clarification: bool = False
    classify: dict[str, Any] = Field(default_factory=dict)
    decision: str = "answer"
    decision_log: dict[str, Any] = Field(default_factory=dict)
