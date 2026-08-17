from pathlib import Path

from dotenv import dotenv_values

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

# DeepInfra là OpenAI-compatible → dùng chung OpenAI SDK với base_url này.
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


class Settings:
    def __init__(self):
        # Chat LLM (DeepInfra — OpenAI-compatible)
        self.deepinfra_api_key: str = _env.get("DEEPINFRA_API_KEY", "")
        self.deepinfra_base_url: str = _env.get("DEEPINFRA_BASE_URL", DEEPINFRA_BASE_URL)
        self.llm_model: str = _env.get("DEEPINFRA_CHAT_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
        # Fallback khi model chính lỗi (chưa stream gì ra client)
        self.llm_fallback_model: str = _env.get("DEEPINFRA_FALLBACK_MODEL", "anthropic/claude-haiku-4-5")
        # Embedding (OpenRouter — DeepInfra không host openai/text-embedding-3-small)
        self.openrouter_api_key: str = _env.get("OPENROUTER_API_KEY", "")
        self.openrouter_embed_model: str = _env.get("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small")
        # Rerank (DeepInfra)
        self.rerank_enabled: bool = _env.get("RERANK_ENABLED", "true").lower() == "true"
        # DeepInfra chỉ host: Qwen/Qwen3-Reranker-{0.6B,4B,8B}, nvidia/llama-nemotron-rerank-vl-1b-v2
        self.rerank_model: str = _env.get("DEEPINFRA_RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B")
        # DB
        self.postgres_url: str = _env.get("POSTGRES_URL") or _env.get("PG_DSN", "postgresql://vivu:vivu@localhost:5432/vivu")
        self.qdrant_url: str = _env.get("QDRANT_URL", "http://localhost:6333")
        self.qdrant_api_key: str = _env.get("QDRANT_API_KEY", "")
        # Redis cache (Upstash) — không có REDIS_URL → cache disabled (no-op, fail-safe)
        self.redis_url: str = _env.get("REDIS_URL", "")
        # REST token: set → dùng Upstash REST API (https://<db>.upstash.io + Bearer),
        # không dùng TCP. Nếu trống → tự parse từ REDIS_URL dạng rediss://default:token@
        self.redis_token: str = _env.get("REDIS_TOKEN", "")
        self.cache_enabled: bool = _env.get("CACHE_ENABLED", "true").lower() == "true"
        self.rate_limit_enabled: bool = _env.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
        self.rate_limit_rpm: int = int(_env.get("RATE_LIMIT_RPM", "30"))  # requests per minute per IP
        self.rate_limit_burst: int = int(_env.get("RATE_LIMIT_BURST", "5"))  # burst capacity
        self.backpressure_max: int = int(_env.get("BACKPRESSURE_MAX", "50"))  # max concurrent in-flight
        # Token limits (multi-turn safety: cap input + output)
        self.llm_max_output_tokens: int = int(_env.get("LLM_MAX_OUTPUT_TOKENS", "4000"))
        self.llm_tool_call_max_tokens: int = int(_env.get("LLM_TOOL_CALL_MAX_TOKENS", "1024"))
        self.llm_input_max_tokens: int = int(_env.get("LLM_INPUT_MAX_TOKENS", "16000"))
        self.llm_user_input_max_tokens: int = int(_env.get("LLM_USER_INPUT_MAX_TOKENS", "1000"))


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
