"""Central configuration management using Pydantic BaseSettings.

Provides type-safety, automatic environment variable loading, and validation.
"""

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# DeepInfra là OpenAI-compatible → dùng chung OpenAI SDK với base_url này.
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Chat LLM (DeepInfra — OpenAI-compatible) ───────────────────────────
    deepinfra_api_key: str = Field(default="", validation_alias=AliasChoices("DEEPINFRA_API_KEY", "deepinfra_api_key"))
    deepinfra_base_url: str = Field(
        default=DEEPINFRA_BASE_URL, validation_alias=AliasChoices("DEEPINFRA_BASE_URL", "deepinfra_base_url")
    )
    llm_model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash",
        validation_alias=AliasChoices("DEEPINFRA_CHAT_MODEL", "LLM_MODEL", "llm_model"),
    )
    llm_fallback_model: str = Field(
        default="anthropic/claude-haiku-4-5",
        validation_alias=AliasChoices("DEEPINFRA_FALLBACK_MODEL", "LLM_FALLBACK_MODEL", "llm_fallback_model"),
    )

    # ── Embedding & Rerank ───────────────────────────────────────────────────
    openrouter_api_key: str = Field(
        default="", validation_alias=AliasChoices("OPENROUTER_API_KEY", "openrouter_api_key")
    )
    openrouter_embed_model: str = Field(
        default="openai/text-embedding-3-small",
        validation_alias=AliasChoices("OPENROUTER_EMBED_MODEL", "openrouter_embed_model"),
    )
    rerank_enabled: bool = Field(default=True, validation_alias=AliasChoices("RERANK_ENABLED", "rerank_enabled"))
    rerank_model: str = Field(
        default="Qwen/Qwen3-Reranker-0.6B", validation_alias=AliasChoices("DEEPINFRA_RERANK_MODEL", "rerank_model")
    )

    # ── Database & Cache ─────────────────────────────────────────────────────
    postgres_url: str = Field(
        default="postgresql://vivu:vivu@localhost:5432/vivu",
        validation_alias=AliasChoices("POSTGRES_URL", "PG_DSN", "postgres_url"),
    )
    qdrant_url: str = Field(default="http://localhost:6333", validation_alias=AliasChoices("QDRANT_URL", "qdrant_url"))
    qdrant_api_key: str = Field(default="", validation_alias=AliasChoices("QDRANT_API_KEY", "qdrant_api_key"))
    redis_url: str = Field(default="", validation_alias=AliasChoices("REDIS_URL", "redis_url"))
    redis_token: str = Field(default="", validation_alias=AliasChoices("REDIS_TOKEN", "redis_token"))
    cache_enabled: bool = Field(default=True, validation_alias=AliasChoices("CACHE_ENABLED", "cache_enabled"))

    # ── Rate Limiting & Backpressure ─────────────────────────────────────────
    rate_limit_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("RATE_LIMIT_ENABLED", "rate_limit_enabled")
    )
    rate_limit_rpm: int = Field(default=30, ge=1, validation_alias=AliasChoices("RATE_LIMIT_RPM", "rate_limit_rpm"))
    rate_limit_burst: int = Field(
        default=5, ge=1, validation_alias=AliasChoices("RATE_LIMIT_BURST", "rate_limit_burst")
    )
    backpressure_max: int = Field(
        default=50, ge=1, validation_alias=AliasChoices("BACKPRESSURE_MAX", "backpressure_max")
    )

    # ── Token limits ─────────────────────────────────────────────────────────
    llm_max_output_tokens: int = Field(
        default=4000, ge=1, validation_alias=AliasChoices("LLM_MAX_OUTPUT_TOKENS", "llm_max_output_tokens")
    )
    llm_tool_call_max_tokens: int = Field(
        default=1024, ge=1, validation_alias=AliasChoices("LLM_TOOL_CALL_MAX_TOKENS", "llm_tool_call_max_tokens")
    )
    llm_input_max_tokens: int = Field(
        default=16000, ge=1, validation_alias=AliasChoices("LLM_INPUT_MAX_TOKENS", "llm_input_max_tokens")
    )
    llm_user_input_max_tokens: int = Field(
        default=1000, ge=1, validation_alias=AliasChoices("LLM_USER_INPUT_MAX_TOKENS", "llm_user_input_max_tokens")
    )

    # ── Admin & Metrics ──────────────────────────────────────────────────────
    admin_api_key: str = Field(default="", validation_alias=AliasChoices("ADMIN_API_KEY", "admin_api_key"))
    metrics_enabled: bool = Field(default=True, validation_alias=AliasChoices("METRICS_ENABLED", "metrics_enabled"))
    usd_vnd_rate: float = Field(
        default=25400.0, gt=0, validation_alias=AliasChoices("USD_VND_EXCHANGE_RATE", "usd_vnd_rate")
    )
    app_version: str = Field(default="v1.0.0", validation_alias=AliasChoices("APP_VERSION", "app_version"))

    # ── Observability ───────────────────────────────────────────────────────
    # structured logging: json | text (JSON parse được bởi ELK/Loki/Grafana)
    log_format: str = Field(default="text", validation_alias=AliasChoices("LOG_FORMAT", "log_format"))
    # Prometheus /metrics export endpoint
    prometheus_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("PROMETHEUS_ENABLED", "prometheus_enabled")
    )

    # ── Langfuse Observability ───────────────────────────────────────────────
    langfuse_public_key: str = Field(
        default="", validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY", "langfuse_public_key")
    )
    langfuse_secret_key: str = Field(
        default="", validation_alias=AliasChoices("LANGFUSE_SECRET_KEY", "langfuse_secret_key")
    )
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com", validation_alias=AliasChoices("LANGFUSE_HOST", "langfuse_host")
    )
    langfuse_enabled: bool = Field(default=True, validation_alias=AliasChoices("LANGFUSE_ENABLED", "langfuse_enabled"))

    # ── Upstash Kafka Cloud Settings ─────────────────────────────────────────
    kafka_bootstrap_servers: str = Field(
        default="", validation_alias=AliasChoices("KAFKA_BOOTSTRAP_SERVERS", "kafka_bootstrap_servers")
    )
    kafka_sasl_username: str = Field(
        default="", validation_alias=AliasChoices("KAFKA_SASL_USERNAME", "kafka_sasl_username")
    )
    kafka_sasl_password: str = Field(
        default="", validation_alias=AliasChoices("KAFKA_SASL_PASSWORD", "kafka_sasl_password")
    )
    kafka_telemetry_topic: str = Field(
        default="vinfast.telemetry", validation_alias=AliasChoices("KAFKA_TELEMETRY_TOPIC", "kafka_telemetry_topic")
    )
    kafka_alerts_topic: str = Field(
        default="vinfast.alerts", validation_alias=AliasChoices("KAFKA_ALERTS_TOPIC", "kafka_alerts_topic")
    )
    kafka_enabled: bool = Field(default=True, validation_alias=AliasChoices("KAFKA_ENABLED", "kafka_enabled"))

    # ── Email SMTP & Alerting Settings ───────────────────────────────────────
    smtp_host: str = Field(default="smtp.gmail.com", validation_alias=AliasChoices("SMTP_HOST", "smtp_host"))
    smtp_port: int = Field(default=587, ge=1, le=65535, validation_alias=AliasChoices("SMTP_PORT", "smtp_port"))
    smtp_user: str = Field(default="", validation_alias=AliasChoices("SMTP_USER", "smtp_user"))
    smtp_password: str = Field(default="", validation_alias=AliasChoices("SMTP_PASSWORD", "smtp_password"))
    smtp_from_name: str = Field(
        default="VinFast AI Alerts", validation_alias=AliasChoices("SMTP_FROM_NAME", "smtp_from_name")
    )
    alert_email_recipient: str = Field(
        default="", validation_alias=AliasChoices("ALERT_EMAIL_RECIPIENT", "alert_email_recipient")
    )
    alert_email_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("ALERT_EMAIL_ENABLED", "alert_email_enabled")
    )
    alert_spam_critical_threshold: int = Field(
        default=15,
        ge=1,
        validation_alias=AliasChoices("ALERT_SPAM_CRITICAL_THRESHOLD", "alert_spam_critical_threshold"),
    )
    alert_cost_critical_threshold_vnd: float = Field(
        default=100000.0,
        ge=0,
        validation_alias=AliasChoices("ALERT_COST_CRITICAL_THRESHOLD_VND", "alert_cost_critical_threshold_vnd"),
    )

    @model_validator(mode="after")
    def _validate_composite_flags(self) -> "Settings":
        """Auto-adjust boolean flags if required credentials are missing."""
        if self.langfuse_enabled and not (self.langfuse_public_key and self.langfuse_secret_key):
            object.__setattr__(self, "langfuse_enabled", False)

        if self.kafka_enabled and not (
            self.kafka_bootstrap_servers and self.kafka_sasl_username and self.kafka_sasl_password
        ):
            object.__setattr__(self, "kafka_enabled", False)

        if self.alert_email_enabled and not (
            self.smtp_host and self.smtp_user and self.smtp_password and self.alert_email_recipient
        ):
            object.__setattr__(self, "alert_email_enabled", False)

        return self


def llm_extra_kwargs(model: str) -> dict:
    """Reasoning models cần giảm thinking tokens để không tốn latency.

    - gpt-oss: chỉ nhận "low" ("none" bị bỏ qua, vẫn nghĩ 16s như thường)
    - qwen/gemini/luna/o1/o3: nhận "none"
    """
    m = model.lower()
    if "gpt-oss" in m:
        return {"reasoning_effort": "low"}
    if any(k in m for k in ("qwen", "luna", "o1", "o3", "gemini", "deepseek")):
        return {"reasoning_effort": "none"}
    return {}


settings = Settings()
