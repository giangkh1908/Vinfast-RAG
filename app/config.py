import os
from pathlib import Path

from dotenv import load_dotenv

# Tải .env nếu có (dành cho chạy local)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _get_env(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return val if val is not None else default


# DeepInfra là OpenAI-compatible → dùng chung OpenAI SDK với base_url này.
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


class Settings:
    def __init__(self):
        # Chat LLM (DeepInfra — OpenAI-compatible)
        self.deepinfra_api_key: str = _get_env("DEEPINFRA_API_KEY", "")
        self.deepinfra_base_url: str = _get_env("DEEPINFRA_BASE_URL", DEEPINFRA_BASE_URL)
        self.llm_model: str = _get_env("DEEPINFRA_CHAT_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
        # Fallback khi model chính lỗi (chưa stream gì ra client)
        self.llm_fallback_model: str = _get_env("DEEPINFRA_FALLBACK_MODEL", "anthropic/claude-haiku-4-5")
        # Embedding (OpenRouter — DeepInfra không host openai/text-embedding-3-small)
        self.openrouter_api_key: str = _get_env("OPENROUTER_API_KEY", "")
        self.openrouter_embed_model: str = _get_env("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small")
        # Rerank (DeepInfra)
        self.rerank_enabled: bool = _get_env("RERANK_ENABLED", "true").lower() == "true"
        # DeepInfra chỉ host: Qwen/Qwen3-Reranker-{0.6B,4B,8B}, nvidia/llama-nemotron-rerank-vl-1b-v2
        self.rerank_model: str = _get_env("DEEPINFRA_RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B")
        # DB
        self.postgres_url: str = _get_env("POSTGRES_URL") or _get_env("PG_DSN", "postgresql://vivu:vivu@localhost:5432/vivu")
        self.qdrant_url: str = _get_env("QDRANT_URL", "http://localhost:6333")
        self.qdrant_api_key: str = _get_env("QDRANT_API_KEY", "")
        # Redis cache (Upstash) — không có REDIS_URL → cache disabled (no-op, fail-safe)
        self.redis_url: str = _get_env("REDIS_URL", "")
        # REST token: set → dùng Upstash REST API (https://<db>.upstash.io + Bearer),
        # không dùng TCP. Nếu trống → tự parse từ REDIS_URL dạng rediss://default:token@
        self.redis_token: str = _get_env("REDIS_TOKEN", "")
        self.cache_enabled: bool = _get_env("CACHE_ENABLED", "true").lower() == "true"
        self.rate_limit_enabled: bool = _get_env("RATE_LIMIT_ENABLED", "true").lower() == "true"
        self.rate_limit_rpm: int = int(_get_env("RATE_LIMIT_RPM", "30"))  # requests per minute per IP
        self.rate_limit_burst: int = int(_get_env("RATE_LIMIT_BURST", "5"))  # burst capacity
        self.backpressure_max: int = int(_get_env("BACKPRESSURE_MAX", "50"))  # max concurrent in-flight
        # Token limits (multi-turn safety: cap input + output)
        self.llm_max_output_tokens: int = int(_get_env("LLM_MAX_OUTPUT_TOKENS", "4000"))
        self.llm_tool_call_max_tokens: int = int(_get_env("LLM_TOOL_CALL_MAX_TOKENS", "1024"))
        self.llm_input_max_tokens: int = int(_get_env("LLM_INPUT_MAX_TOKENS", "16000"))
        self.llm_user_input_max_tokens: int = int(_get_env("LLM_USER_INPUT_MAX_TOKENS", "1000"))
        # Admin & Metrics Telemetry (Mặc định để trống để FE gọi API trực tiếp)
        self.admin_api_key: str = _get_env("ADMIN_API_KEY", "")
        self.metrics_enabled: bool = _get_env("METRICS_ENABLED", "true").lower() == "true"
        self.usd_vnd_rate: float = float(_get_env("USD_VND_EXCHANGE_RATE", "25400.0"))
        self.app_version: str = _get_env("APP_VERSION", "v1.0.0")
        # Langfuse Observability
        self.langfuse_public_key: str = _get_env("LANGFUSE_PUBLIC_KEY", "")
        self.langfuse_secret_key: str = _get_env("LANGFUSE_SECRET_KEY", "")
        self.langfuse_host: str = _get_env("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self.langfuse_enabled: bool = _get_env("LANGFUSE_ENABLED", "true").lower() == "true" and bool(self.langfuse_public_key and self.langfuse_secret_key)



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
