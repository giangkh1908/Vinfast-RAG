import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from app.config import settings

logger = logging.getLogger("retrieval")

_reranker = None
_sparse_index = None
_embed_client = None


def _get_embed_client():
    """OpenAI-compatible client for embeddings with built-in retry + connection pooling."""
    global _embed_client
    if _embed_client is None:
        from openai import OpenAI
        _embed_client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            max_retries=3,
            timeout=60.0,
        )
    return _embed_client

# Collections to search. Override via QDRANT_DENSE_COLLECTIONS env var.
import os as _os
_dense_env = _os.environ.get("QDRANT_DENSE_COLLECTIONS", "")
DENSE_COLLECTIONS = [c.strip() for c in _dense_env.split(",") if c.strip()] if _dense_env else ["vivu_product_info", "vivu_policy", "vivu_maintenance"]
SPARSE_COLLECTION = "sparse"

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CLEAN_DIR = REPO_ROOT / "data" / "clean"

STOPWORDS = set("""
và của là đã đang sẽ được với cho từ đến tại cũng như hay hoặc nhưng nếu thì
khi mà nên vì thế nên để lại vẫn còn rất chỉ mỗi này kia nào đó đây những các
tất mọi người tôi bạn chúng ta họ nó ông bà anh chị em cùng thôi cần nếu đúng
xin quý""".split())

TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    return [t for t in TOKEN_RE.findall(text) if t not in STOPWORDS and len(t) > 1]


# ── Sparse index auto-detection ──────────────────────────────────────────────
def _find_latest_sparse_index() -> Path | None:
    """Scan data/clean/*/sparse_index.json, return path with highest version number."""
    global _sparse_index
    if not DATA_CLEAN_DIR.exists():
        return None
    best_num = -1
    best_path = None
    for p in DATA_CLEAN_DIR.glob("*/sparse_index.json"):
        try:
            raw = p.read_text(encoding="utf-8")
            idx = json.loads(raw)
            ver = idx.get("version", p.parent.name)
            num = int(ver.lstrip("v")) if ver.lstrip("v").isdigit() else 0
            if num > best_num:
                best_num = num
                best_path = p
                _sparse_index = idx
        except Exception:
            continue
    return best_path


def _load_sparse_index() -> dict:
    global _sparse_index
    if _sparse_index is None:
        path = _find_latest_sparse_index()
        if path is None:
            _sparse_index = {}
        else:
            logger.info("Loaded sparse index from %s (version=%s)", path, _sparse_index.get("version"))
    return _sparse_index or {}


def _query_to_sparse(query: str) -> dict | None:
    idx = _load_sparse_index()
    if not idx or "vocab" not in idx:
        return None

    vocab = idx["vocab"]
    idf_list = idx["idf"]
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
    return {"indices": [indices[i] for i in order], "values": [values[i] for i in order]}


def _openrouter_embed(texts: list[str]) -> list[list[float]]:
    """Embed texts using OpenAI SDK with built-in retry + connection pooling."""
    client = _get_embed_client()
    batch_size = 100
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model=settings.openrouter_embed_model,
            input=batch,
        )
        sorted_data = sorted(response.data, key=lambda x: x.index)
        all_embeddings.extend([d.embedding for d in sorted_data])
    return all_embeddings


# ── Qdrant REST API helper ─────────────────────────────────────────────────
class QdrantREST:
    """Thin wrapper around Qdrant REST API."""

    def __init__(self, url: str, api_key: str = ""):
        self.base = url.rstrip("/")
        self.session = requests.Session()
        if api_key:
            self.session.headers["api-key"] = api_key
        self.session.headers["Content-Type"] = "application/json"
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _build_filter(self, model_id: str = None) -> dict | None:
        if not model_id:
            return None
        return {"must": [{"key": "model_id", "match": {"value": model_id}}]}

    def search(self, collection: str, vector: list[float], model_id: str = None, limit: int = 10) -> list[dict]:
        body = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        f = self._build_filter(model_id)
        if f:
            body["filter"] = f

        try:
            r = self.session.post(
                f"{self.base}/collections/{collection}/points/search",
                json=body,
                timeout=30,
            )
            r.raise_for_status()
            return r.json().get("result", [])
        except Exception as e:
            if model_id and "Index required" in str(e):
                body.pop("filter", None)
                r = self.session.post(
                    f"{self.base}/collections/{collection}/points/search",
                    json=body,
                    timeout=30,
                )
                r.raise_for_status()
                return r.json().get("result", [])
            raise

    def search_sparse(self, collection: str, sparse: dict, model_id: str = None, limit: int = 10) -> list[dict]:
        body = {
            "vector": {
                "name": "sparse",
                "indices": sparse["indices"],
                "values": sparse["values"],
            },
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        f = self._build_filter(model_id)
        if f:
            body["filter"] = f

        try:
            r = self.session.post(
                f"{self.base}/collections/{collection}/points/search",
                json=body,
                timeout=30,
            )
            r.raise_for_status()
            return r.json().get("result", [])
        except Exception:
            return []

    def retrieve(self, collection: str, ids: list[str]) -> list[dict]:
        """Fetch points by IDs from a collection (with payload, no vectors)."""
        if not ids:
            return []
        try:
            r = self.session.post(
                f"{self.base}/collections/{collection}/points",
                json={"ids": ids, "with_payload": True, "with_vector": False},
                timeout=30,
            )
            r.raise_for_status()
            return r.json().get("result", [])
        except Exception as e:
            logger.warning("retrieve %s failed: %s", collection, e)
            return []


_qdrant: QdrantREST | None = None


def get_qdrant() -> QdrantREST:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantREST(settings.qdrant_url, settings.qdrant_api_key)
    return _qdrant


# ── Reranker ───────────────────────────────────────────────────────────────
class CohereReranker:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.cohere.ai/v1/rerank"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        query = pairs[0][0]
        documents = [doc for _, doc in pairs]
        try:
            r = self.session.post(
                self.base_url,
                json={"model": "rerank-multilingual-v3.0", "query": query, "documents": documents, "top_n": len(documents)},
                timeout=30,
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            scores = [0.0] * len(pairs)
            for item in results:
                scores[item.get("index", 0)] = item.get("relevance_score", 0.0)
            return scores
        except Exception as e:
            logger.warning("Cohere rerank failed: %s", e)
            return [0.0] * len(pairs)


def get_reranker():
    global _reranker
    if _reranker is None and settings.rerank_enabled:
        if settings.cohere_api_key:
            _reranker = CohereReranker(settings.cohere_api_key)
        else:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(settings.rerank_model)
    return _reranker


# ── Fusion ─────────────────────────────────────────────────────────────────
def _rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _rrf_fusion(result_lists: list[list], k: int = 60) -> list[tuple]:
    scores = {}
    hit_data = {}
    for results in result_lists:
        for rank, hit in enumerate(results):
            pid = hit.get("id", "")
            scores[pid] = scores.get(pid, 0) + _rrf_score(rank, k)
            if pid not in hit_data:
                hit_data[pid] = hit
    sorted_ids = sorted(scores.keys(), key=lambda pid: scores[pid], reverse=True)
    return [(hit_data[pid], scores[pid]) for pid in sorted_ids]


# ── Sparse text resolution ──────────────────────────────────────────────────
def _resolve_sparse_texts(qdrant: QdrantREST, sparse_results: list[dict]) -> list[dict]:
    """Resolve sparse results that lack 'text' by fetching from dense collections.

    Sparse v2+ stores reference-only payloads {collection, chunk_id, model_id}.
    Dense collections (via alias) contain the actual text. Point IDs are the same
    across sparse and dense (both derived from chunk_id via uuid5).
    """
    needs_text = []
    has_text = []
    for hit in sparse_results:
        payload = hit.get("payload", {})
        if payload.get("text", "").strip():
            has_text.append(hit)
        else:
            needs_text.append(hit)

    if not needs_text:
        return sparse_results

    # Group IDs by their source dense collection
    by_collection: dict[str, list[str]] = {}
    for hit in needs_text:
        col = hit.get("payload", {}).get("collection", "")
        if col:
            by_collection.setdefault(col, []).append(hit["id"])

    # Batch fetch from each dense collection
    text_map: dict[str, dict] = {}
    for col, ids in by_collection.items():
        records = qdrant.retrieve(col, ids)
        for rec in records:
            payload = rec.get("payload", {})
            text_map[rec["id"]] = {
                "text": payload.get("text", ""),
                "source_type": payload.get("source_type", ""),
                "source_url": payload.get("source_url", ""),
                "edition_id": payload.get("edition_id", ""),
                "text_type": payload.get("text_type", ""),
                "page": payload.get("page", ""),
            }

    # Inject text into sparse results
    resolved = []
    for hit in needs_text:
        extra = text_map.get(hit["id"], {})
        if extra.get("text"):
            hit.setdefault("payload", {}).update(extra)
            resolved.append(hit)
        else:
            logger.debug("Could not resolve text for sparse point %s", hit["id"])

    return has_text + resolved


# ── Main search ────────────────────────────────────────────────────────────
async def hybrid_search(query: str, model_id: str = None, top_k: int = 5) -> list[dict]:
    qdrant = get_qdrant()
    dense_vector = _openrouter_embed([query])[0]
    limit = top_k * 2

    # 1. Dense search across all collections (via aliases → active version)
    all_dense = []
    for col in DENSE_COLLECTIONS:
        try:
            results = qdrant.search(col, dense_vector, model_id=model_id, limit=limit)
            all_dense.extend(results)
        except Exception as e:
            logger.warning("search %s failed: %s", col, e)

    # 2. Sparse search (BM25) + resolve text from dense collections
    sparse_results = []
    sparse_vec = _query_to_sparse(query)
    if sparse_vec:
        try:
            sparse_results = qdrant.search_sparse(SPARSE_COLLECTION, sparse_vec, model_id=model_id, limit=limit)
            sparse_results = _resolve_sparse_texts(qdrant, sparse_results)
        except Exception as e:
            logger.warning("sparse search failed: %s", e)

    # 3. RRF fusion
    if sparse_results:
        fused = _rrf_fusion([all_dense, sparse_results])
    else:
        fused = [(hit, hit.get("score", 0)) for hit in all_dense]

    # 4. Rerank
    reranker = get_reranker()
    if reranker and len(fused) > 0:
        pairs = [(query, hit.get("payload", {}).get("text", "")) for hit, _ in fused]
        non_empty = [(i, q, d) for i, (q, d) in enumerate(pairs) if d.strip()]
        if non_empty:
            rerank_pairs = [(q, d) for _, q, d in non_empty]
            rerank_scores = reranker.predict(rerank_pairs)
            # Only apply rerank if at least one score is non-zero (rerank succeeded)
            if any(s > 0 for s in rerank_scores):
                scores = [0.0] * len(pairs)
                for j, (orig_idx, _, _) in enumerate(non_empty):
                    scores[orig_idx] = rerank_scores[j]
                fused = [(hit, float(score)) for (hit, _), score in zip(fused, scores)]
                fused.sort(key=lambda x: x[1], reverse=True)

    # 5. Return top_k (skip chunks without text)
    results = []
    for hit, score in fused:
        payload = hit.get("payload", {})
        text = payload.get("text", "")
        if not text or not text.strip():
            continue
        results.append({
            "text": text,
            "model_id": payload.get("model_id"),
            "edition_id": payload.get("edition_id"),
            "text_type": payload.get("text_type", ""),
            "source_type": payload.get("source_type", ""),
            "source_url": payload.get("source_url", ""),
            "page": payload.get("page", ""),
            "score": round(score, 4),
        })
        if len(results) >= top_k:
            break

    return results
