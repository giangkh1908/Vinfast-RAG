import asyncio
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, SparseVector

from app.config import settings

_reranker = None
_sparse_index = None

DENSE_COLLECTIONS = ["vivu_product_info", "vivu_policy", "vivu_maintenance"]
SPARSE_COLLECTION = "sparse"
SPARSE_INDEX_PATH = Path(__file__).resolve().parents[2] / "data" / "clean" / "v1" / "sparse_index.json"

# Vietnamese stopwords
STOPWORDS = set("""
và của là đã đang sẽ được với cho từ đến tại cũng như hay hoặc nhưng nếu thì
khi mà nên vì thế nên để lại vẫn còn rất chỉ mỗi này kia nào đó đây những các
tất mọi người tôi bạn chúng ta họ nó ông bà anh chị em cùng thôi cần nếu đúng
xin quý""".split())

TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    return [t for t in TOKEN_RE.findall(text) if t not in STOPWORDS and len(t) > 1]


def _load_sparse_index() -> dict:
    global _sparse_index
    if _sparse_index is None:
        if SPARSE_INDEX_PATH.exists():
            with open(SPARSE_INDEX_PATH, "r", encoding="utf-8") as f:
                _sparse_index = json.load(f)
        else:
            _sparse_index = {}
    return _sparse_index


def _query_to_sparse(query: str) -> SparseVector | None:
    idx = _load_sparse_index()
    if not idx or "vocab" not in idx:
        return None

    vocab = idx["vocab"]
    idf_list = idx["idf"]
    n_docs = idx.get("n_docs", 2212)
    k1 = idx.get("k1", 1.5)
    b = idx.get("b", 0.75)
    avgdl = idx.get("avgdl", 47.5)

    tokens = tokenize(query)
    if not tokens:
        return None

    tf = Counter(tokens)
    indices = []
    values = []
    for t, f in tf.items():
        if t not in vocab:
            continue
        vocab_idx = vocab[t]
        idf_val = idf_list[vocab_idx] if isinstance(idf_list, list) and vocab_idx < len(idf_list) else 1.0
        w = idf_val * f * (k1 + 1) / (f + k1 * (1 - b + b * 1.0 / avgdl))
        indices.append(vocab_idx)
        values.append(round(w, 6))

    if not indices:
        return None

    order = sorted(range(len(indices)), key=lambda i: indices[i])
    indices = [indices[i] for i in order]
    values = [values[i] for i in order]
    return SparseVector(indices=indices, values=values)


def _openrouter_embed(texts: list[str]) -> list[list[float]]:
    r = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"},
        json={"model": settings.openrouter_embed_model, "input": texts},
        timeout=120,
    )
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda x: x["index"])
    return [x["embedding"] for x in data]


def get_reranker():
    global _reranker
    if _reranker is None and settings.rerank_enabled:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(settings.rerank_model)
    return _reranker


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, prefer_grpc=False)


def _rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _rrf_fusion(result_lists: list[list], k: int = 60) -> list[tuple]:
    scores = {}
    hit_data = {}
    for results in result_lists:
        for rank, hit in enumerate(results):
            pid = str(hit.id)
            scores[pid] = scores.get(pid, 0) + _rrf_score(rank, k)
            if pid not in hit_data:
                hit_data[pid] = hit
    sorted_ids = sorted(scores.keys(), key=lambda pid: scores[pid], reverse=True)
    return [(hit_data[pid], scores[pid]) for pid in sorted_ids]


async def _search_dense_collection(col: str, client, dense_vector, search_filter, limit):
    return client.search(
        collection_name=col,
        query_vector=dense_vector,
        query_filter=search_filter,
        limit=limit,
        with_payload=True,
    )


async def hybrid_search(query: str, model_id: str = None, top_k: int = 5) -> list[dict]:
    client = get_qdrant_client()
    dense_vector = _openrouter_embed([query])[0]

    search_filter = None
    if model_id:
        search_filter = Filter(must=[FieldCondition(key="model_id", match=MatchValue(value=model_id))])

    # 1. Parallel dense search across 4 collections
    limit = top_k * 2
    tasks = [
        _search_dense_collection(col, client, dense_vector, search_filter, limit)
        for col in DENSE_COLLECTIONS
    ]
    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    all_dense = []
    for i, result in enumerate(results_lists):
        if isinstance(result, Exception):
            import logging
            logging.getLogger("retrieval").warning("search %s failed: %s", DENSE_COLLECTIONS[i], result)
        else:
            all_dense.extend(result)

    # 2. Sparse search (BM25)
    sparse_results = []
    sparse_vec = _query_to_sparse(query)
    if sparse_vec:
        try:
            sparse_results = client.search(
                collection_name=SPARSE_COLLECTION,
                query_vector=("sparse", sparse_vec),
                query_filter=search_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception:
            pass

    # 3. RRF fusion
    if sparse_results:
        fused = _rrf_fusion([all_dense, sparse_results])
    else:
        fused = [(hit, hit.score) for hit in all_dense]

    # 4. Rerank
    reranker = get_reranker()
    if reranker and len(fused) > 0:
        pairs = [(query, hit.payload.get("text", "")) for hit, _ in fused]
        scores = reranker.predict(pairs)
        fused = [(hit, float(score)) for (hit, _), score in zip(fused, scores)]
        fused.sort(key=lambda x: x[1], reverse=True)

    # 5. Return top_k
    results = []
    for hit, score in fused[:top_k]:
        results.append({
            "text": hit.payload.get("text", ""),
            "model_id": hit.payload.get("model_id"),
            "edition_id": hit.payload.get("edition_id"),
            "text_type": hit.payload.get("text_type", ""),
            "source_type": hit.payload.get("source_type", ""),
            "source_url": hit.payload.get("source_url", ""),
            "score": round(score, 4),
        })

    return results
