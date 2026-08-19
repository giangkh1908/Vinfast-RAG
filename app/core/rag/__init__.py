"""
app/core/rag — Knowledge Base Hybrid Retrieval and Dynamic Prompt Registry.
"""

from app.core.rag.prompt_manager import (
    PromptManager,
)
from app.core.rag.retrieval import (
    get_qdrant,
    get_reranker,
    hybrid_search,
)

__all__ = [
    "hybrid_search",
    "get_qdrant",
    "get_reranker",
    "PromptManager",
]
