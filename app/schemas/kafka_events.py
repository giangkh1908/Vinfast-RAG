"""
app/schemas/kafka_events.py — Pydantic Event Schemas for Kafka Broker & Dispatchers.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AlertSeverity(StrEnum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class TelemetryEventPayload(BaseModel):
    request_id: str
    session_id: str | None = None
    client_ip: str = "unknown"
    query_text: str = ""
    intent: str = "general"
    decision: str = "answer"
    model_used: str = ""
    prompt_version: str = "v1.0.0"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_vnd: float = 0.0
    ttft_ms: int = 0
    total_latency_ms: int = 0
    cache_hit: bool = False
    cache_type: str = "none"
    tools_used: list[str] = Field(default_factory=list)
    status_code: int = 200
    error_message: str | None = None


class IncidentAlertPayload(BaseModel):
    alert_type: str
    severity: AlertSeverity = AlertSeverity.WARNING
    title: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
