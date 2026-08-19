"""FastAPI Dependency Injection providers for Vivu VinFast AI Assistant.

Allows clean separation of concerns and effortless test overriding via
`app.dependency_overrides`.
"""

from app.agent.agent_loop import AgentLoop
from app.core.storage.cache import RedisCache
from app.core.storage.cache import cache as default_cache
from app.core.storage.db import get_pool as default_get_pool

_agent: AgentLoop | None = None


async def get_db_pool():
    """Dependency provider for PostgreSQL asyncpg connection pool."""
    return await default_get_pool()


def get_chat_agent() -> AgentLoop:
    """Dependency provider for the main AI AgentLoop instance."""
    global _agent
    if _agent is None:
        _agent = AgentLoop()
    return _agent


def get_redis_cache() -> RedisCache:
    """Dependency provider for multi-tier Redis cache singleton."""
    return default_cache
