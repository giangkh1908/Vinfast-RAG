from dotenv import dotenv_values

_env = dotenv_values(".env")


class Settings:
    def __init__(self):
        # Scope (BDS Trust Foundation)
        self.scope_enabled: bool = _env.get("SCOPE_ENABLED", "true").lower() == "true"
        self.scope_models: list[str] = _env.get("SCOPE_MODELS", "VF 6,VF 8").split(",")
        self.scope_versions: list[str] = _env.get("SCOPE_VERSIONS", "Eco,Plus").split(",")
        # LLM (TokenRouter)
        self.openai_api_key: str = _env.get("OPENAI_API_KEY", "")
        self.openai_base_url: str = _env.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.llm_model: str = _env.get("LLM_MODEL", "openai/gpt-4o-mini")
        # Embedding + Rerank (OpenRouter)
        self.openrouter_api_key: str = _env.get("OPENROUTER_API_KEY", "")
        self.openrouter_embed_model: str = _env.get("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small")
        # DB
        self.postgres_url: str = _env.get("POSTGRES_URL", "postgresql+asyncpg://vivu:vivu@localhost:5432/vivu")
        self.qdrant_url: str = _env.get("QDRANT_URL", "http://localhost:6333")
        self.qdrant_api_key: str = _env.get("QDRANT_API_KEY", "")
        self.qdrant_collection: str = _env.get("QDRANT_COLLECTION", "vivu_specs")
        self.embedding_model: str = _env.get("EMBEDDING_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
        self.embedding_dim: int = int(_env.get("EMBEDDING_DIM", "2048"))
        self.rerank_enabled: bool = _env.get("RERANK_ENABLED", "true").lower() == "true"
        self.rerank_model: str = _env.get("RERANK_MODEL", "nvidia/llama-nemotron-rerank-vl-1b-v2:free")
        self.rerank_top_k: int = int(_env.get("RERANK_TOP_K", "20"))


settings = Settings()
