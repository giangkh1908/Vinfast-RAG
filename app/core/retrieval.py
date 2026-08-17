import json
import logging
import re
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from app.config import settings
from app.core.cache import cache, make_embed_key, make_hs_key

logger = logging.getLogger("retrieval")

# TTL cache
EMB_CACHE_TTL = 7 * 86400      # embedding: deterministic theo (model, text)
HS_CACHE_TTL = 2 * 3600        # hybrid_search: data_version key đã tự invalidate

_reranker = None
_sparse_index = None
_sparse_index_loaded_at = 0.0
_SPARSE_INDEX_TTL = 300  # re-check disk mỗi 5 phút để nhận version mới sau promote
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
    """Load sparse index, reload mỗi _SPARSE_INDEX_TTL giây.

    Quan trọng: sau khi pipeline promote version mới, file sparse_index.json
    mới xuất hiện trên disk. Nếu cache vĩnh viễn (check `is None`), process
    đang chạy sẽ kẹt vocab version cũ → sparse vector sai lệch âm thầm.
    """
    global _sparse_index, _sparse_index_loaded_at
    now = time.time()
    if _sparse_index is not None and (now - _sparse_index_loaded_at) <= _SPARSE_INDEX_TTL:
        return _sparse_index or {}

    old_ver = (_sparse_index or {}).get("version")
    path = _find_latest_sparse_index()
    if path is None and _sparse_index is None:
        _sparse_index = {}
    elif path is not None:
        logger.info("Loaded sparse index from %s (version=%s)", path, _sparse_index.get("version"))
    if (_sparse_index or {}).get("version") != old_ver:
        logger.info("Sparse index version change: %s -> %s", old_ver, (_sparse_index or {}).get("version"))
    _sparse_index_loaded_at = now
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
    """Embed texts using OpenAI SDK with built-in retry + connection pooling.

    Cache theo (model, text thô) — TTL 7 ngày, deterministic nên zero-risk.
    Chạy trong executor thread → dùng sync redis client.
    """
    client = _get_embed_client()
    batch_size = 100
    all_embeddings: dict[int, list[float]] = {}
    to_embed: list[int] = []
    for i, t in enumerate(texts):
        key = make_embed_key(t)
        hit = cache.sync_get_json(key)
        if hit is not None:
            all_embeddings[i] = hit
        else:
            to_embed.append(i)

    if to_embed:
        for j in range(0, len(to_embed), batch_size):
            batch_idx = to_embed[j:j + batch_size]
            batch_texts = [texts[i] for i in batch_idx]
            response = client.embeddings.create(
                model=settings.openrouter_embed_model,
                input=batch_texts,
            )
            sorted_data = sorted(response.data, key=lambda x: x.index)
            for k, d in zip(batch_idx, sorted_data):
                emb = d.embedding
                all_embeddings[k] = emb
                cache.sync_set_json(make_embed_key(texts[k]), emb, EMB_CACHE_TTL)

    # Giữ thứ tự gốc
    return [all_embeddings[i] for i in range(len(texts))]


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
        # QUAN TRỌNG: chunks GENERAL (model_id null — chính sách bảo hành, bảo dưỡng,
        # kiến thức chung) phải áp dụng cho MỌI model. Filter cũ (match chính xác)
        # loại chúng → "bảo hành VF 2" không bao giờ thấy policy chung → refuse.
        # Fix: (model_id = X OR model_id IS NULL)
        return {
            "min_should": {
                "conditions": [
                    {"key": "model_id", "match": {"value": model_id}},
                    {"key": "model_id", "is_null": True},
                ],
                "min_count": 1,
            }
        }

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
        # NamedVectorStruct: sparse vector phải lồng trong "vector", không đặt
        # indices/values ngang hàng với "name" (Qdrant sẽ trả 400).
        body = {
            "vector": {
                "name": "sparse",
                "vector": {
                    "indices": sparse["indices"],
                    "values": sparse["values"],
                },
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
        except Exception as e:
            logger.warning("sparse search %s failed: %s", collection, e)
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

# Thread pool cho các blocking call (requests) trong async context
_pool = ThreadPoolExecutor(max_workers=8)


def get_qdrant() -> QdrantREST:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantREST(settings.qdrant_url, settings.qdrant_api_key)
    return _qdrant


# ── Reranker ───────────────────────────────────────────────────────────────
class DeepInfraReranker:
    """Rerank qua DeepInfra. Trả scores theo thứ tự documents.

    Lưu ý: các reranker đang host (Qwen3-Reranker, nemotron) nhận field
    "queries" (số nhiều), KHÔNG phải "query" như ví dụ docs cũ (cross-encoder).
    Response: {"scores": [0..1], ...} cùng thứ tự với documents.
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.base_url = f"https://api.deepinfra.com/v1/inference/{model}"
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
        last_err = None
        # DeepInfra thỉnh thoảng drop connection (RemoteDisconnected) dù endpoint
        # nhanh (~1s/batch) → retry 1 lần thay vì fallback ngay.
        for attempt in range(2):
            try:
                r = self.session.post(
                    self.base_url,
                    json={"queries": query, "documents": documents},
                    timeout=(5, 25),
                )
                r.raise_for_status()
                scores = r.json().get("scores", [])
                if len(scores) != len(pairs):
                    logger.warning("DeepInfra rerank returned %d scores for %d docs", len(scores), len(pairs))
                    return [0.0] * len(pairs)
                return [float(s) for s in scores]
            except Exception as e:
                last_err = e
                logger.warning("DeepInfra rerank attempt %d failed: %s", attempt + 1, e)
        logger.warning("DeepInfra rerank gave up after retries: %s", last_err)
        return [0.0] * len(pairs)


def get_reranker():
    global _reranker
    if _reranker is None and settings.rerank_enabled and settings.deepinfra_api_key:
        _reranker = DeepInfraReranker(settings.deepinfra_api_key, settings.rerank_model)
    return _reranker


# ── Fusion ─────────────────────────────────────────────────────────────────
def _rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _rrf_fusion(result_lists: list[list], k: int = 60) -> list[tuple]:
    scores = {}
    hit_data = {}
    for results in result_lists:
        for rank, hit in enumerate(results, start=1):  # rank bắt đầu từ 1 (chuẩn RRF)
            pid = hit.get("id", "")
            scores[pid] = scores.get(pid, 0) + _rrf_score(rank, k)
            if pid not in hit_data:
                hit_data[pid] = hit
    sorted_ids = sorted(scores.keys(), key=lambda pid: scores[pid], reverse=True)
    return [(hit_data[pid], scores[pid]) for pid in sorted_ids]


def _dedup_fused(fused: list[tuple]) -> list[tuple]:
    """Bỏ chunk trùng text (cùng 1 chunk có thể nằm ở nhiều collection)."""
    seen = set()
    out = []
    for hit, score in fused:
        text = re.sub(r"\s+", " ", (hit.get("payload", {}).get("text") or "").strip().lower())
        if not text or text in seen:
            continue
        seen.add(text)
        out.append((hit, score))
    return out


def _embed_cosine_scores(query: str, texts: list[str]) -> list[float] | None:
    """Fallback relevance score (0..1) bằng embedding cosine — dùng khi reranker
    không khả dụng, để score luôn cùng thang [0,1] với ngưỡng evidence (0.3/0.5)."""
    if not texts:
        return []
    try:
        embeddings = _openrouter_embed([query] + texts)
        if len(embeddings) < len(texts) + 1:
            return None
        import numpy as np
        q = np.array(embeddings[0])
        qn = np.linalg.norm(q)
        if qn == 0:
            return None
        scores = []
        for emb in embeddings[1:]:
            d = np.array(emb)
            dn = np.linalg.norm(d)
            sim = float(np.dot(q, d) / (qn * dn)) if dn else 0.0
            scores.append(max(0.0, min(1.0, sim)))
        return scores
    except Exception as e:
        logger.warning("embed cosine scoring failed: %s", e)
        return None


# ── Sparse text resolution ──────────────────────────────────────────────────
def _resolve_sparse_texts(qdrant: QdrantREST, sparse_results: list[dict]) -> list[dict]:
    """Làm giàu sparse hits từ dense collections.

    Sparse payload thiếu text (bản reference-only) và LUÔN thiếu metadata
    citation (source_url, source_type, page...). Dense point có cùng id
    (đều sinh từ chunk_id qua uuid5) → fetch về để điền chỗ thiếu.
    """
    needs = []
    complete = []
    for hit in sparse_results:
        payload = hit.get("payload", {})
        if payload.get("text", "").strip() and payload.get("source_url"):
            complete.append(hit)
        else:
            needs.append(hit)

    if not needs:
        return sparse_results

    # Group IDs by their source dense collection
    by_collection: dict[str, list[str]] = {}
    for hit in needs:
        col = hit.get("payload", {}).get("collection", "")
        if col:
            by_collection.setdefault(col, []).append(hit["id"])

    # Batch fetch from each dense collection
    extra_map: dict[str, dict] = {}
    for col, ids in by_collection.items():
        records = qdrant.retrieve(col, ids)
        for rec in records:
            payload = rec.get("payload", {})
            extra_map[rec["id"]] = {
                "text": payload.get("text", ""),
                "source_type": payload.get("source_type", ""),
                "source_url": payload.get("source_url", ""),
                "edition_id": payload.get("edition_id", ""),
                "text_type": payload.get("text_type", ""),
                "page": payload.get("page", ""),
                "section_path": payload.get("section_path", ""),
            }

    # Merge: chỉ điền field còn thiếu, giữ text sparse nếu có
    resolved = []
    for hit in needs:
        extra = extra_map.get(hit["id"], {})
        p = hit.setdefault("payload", {})
        for k, v in extra.items():
            if v and not p.get(k):
                p[k] = v
        if p.get("text", "").strip():
            resolved.append(hit)
        else:
            logger.debug("Could not resolve text for sparse point %s", hit["id"])

    return complete + resolved


# ── Main search ────────────────────────────────────────────────────────────
async def hybrid_search(query: str, model_id: str = None, top_k: int = 5, skip_rerank: bool = False) -> list[dict]:
    # hs: cache theo (data_version, query chuẩn hoá, model, top_k, skip_rerank)
    # hs_key=None khi PG unreachable → skip cache (miss pass-through)
    hs_key = await make_hs_key(query, model_id, top_k, skip_rerank)
    if hs_key is not None:
        hit = await cache.get_json(hs_key)
        if hit is not None:
            return hit

    import asyncio
    loop = asyncio.get_running_loop()
    qdrant = get_qdrant()
    limit = top_k * 2

    # 1. Song song: embed query (OpenRouter ~2-3s) + sparse BM25 (local + Qdrant ~0.3s)
    sparse_vec = _query_to_sparse(query)
    embed_fut = loop.run_in_executor(_pool, _openrouter_embed, [query])
    sparse_fut = (
        loop.run_in_executor(_pool, qdrant.search_sparse, SPARSE_COLLECTION, sparse_vec, model_id, limit)
        if sparse_vec else None
    )

    dense_vector = (await embed_fut)[0]

    # 2. Dense search SONG SONG across all collections (via aliases → active version)
    dense_futs = [
        loop.run_in_executor(_pool, qdrant.search, col, dense_vector, model_id, limit)
        for col in DENSE_COLLECTIONS
    ]
    dense_results = await asyncio.gather(*dense_futs, return_exceptions=True)
    all_dense = []
    for col, res in zip(DENSE_COLLECTIONS, dense_results):
        if isinstance(res, Exception):
            logger.warning("search %s failed: %s", col, res)
        else:
            all_dense.extend(res)

    # 3. Sparse results + resolve metadata từ dense collections
    sparse_results = []
    if sparse_fut is not None:
        try:
            sparse_results = await sparse_fut
            if sparse_results:
                sparse_results = await loop.run_in_executor(_pool, _resolve_sparse_texts, qdrant, sparse_results)
        except Exception as e:
            logger.warning("sparse search failed: %s", e)

    # 4. RRF fusion + dedup trùng text
    if sparse_results:
        fused = _rrf_fusion([all_dense, sparse_results])
    else:
        fused = [(hit, hit.get("score", 0)) for hit in all_dense]
    fused = _dedup_fused(fused)

    # 5. Rescore về thang [0,1]. Ưu tiên DeepInfra reranker; nếu không có
    # (chưa set key / lỗi) thì fallback embedding cosine. Bắt buộc vì
    # ngưỡng evidence trong assess_evidence là 0.3/0.5 — score RRF thô
    # (~0.016) sẽ khiến mọi kết quả KB bị coi là insufficient.
    scored = False
    reranker = get_reranker()
    if not skip_rerank and reranker and len(fused) > 0:
        # Chỉ rerank top 10 từ RRF fusion để giảm thời gian
        rerank_candidates = fused[:10]
        pairs = [(query, hit.get("payload", {}).get("text", "")) for hit, _ in rerank_candidates]
        non_empty = [(i, q, d) for i, (q, d) in enumerate(pairs) if d.strip()]
        if non_empty:
            rerank_pairs = [(q, d) for _, q, d in non_empty]
            rerank_scores = reranker.predict(rerank_pairs)
            # Chỉ áp rerank nếu có ít nhất 1 score > 0 (rerank thành công)
            if any(s > 0 for s in rerank_scores):
                # Gán rerank scores cho top 10
                scores = [0.0] * len(pairs)
                for j, (orig_idx, _, _) in enumerate(non_empty):
                    scores[orig_idx] = rerank_scores[j]
                # Cập nhật fused: top 10 có rerank scores, phần còn lại giữ RRF score
                fused_top = [(hit, float(score)) for (hit, _), score in zip(rerank_candidates, scores)]
                fused_rest = fused[10:]  # giữ nguyên RRF scores
                fused = fused_top + fused_rest
                fused.sort(key=lambda x: x[1], reverse=True)
                scored = True

    if not scored and fused:
        texts = [hit.get("payload", {}).get("text", "") for hit, _ in fused]
        cos_scores = _embed_cosine_scores(query, texts)
        if cos_scores is not None and len(cos_scores) == len(fused):
            fused = [(hit, s) for (hit, _), s in zip(fused, cos_scores)]
            fused.sort(key=lambda x: x[1], reverse=True)
        elif sparse_results:
            # Không embed được: chuẩn hóa RRF về (0,1] theo max để giữ thứ tự
            mx = max(s for _, s in fused) or 1.0
            fused = [(hit, s / mx) for hit, s in fused]

    # 6. Return top_k (skip chunks without text)
    results = []
    for hit, score in fused:
        payload = hit.get("payload", {})
        text = payload.get("text", "")
        if not text or not text.strip():
            continue
        results.append({
            "id": hit.get("id", ""),
            "text": text,
            "model_id": payload.get("model_id"),
            "edition_id": payload.get("edition_id"),
            "text_type": payload.get("text_type", ""),
            "source_type": payload.get("source_type", ""),
            "source_url": payload.get("source_url", ""),
            "page": payload.get("page", ""),
            "section": payload.get("section_path", ""),
            "score": round(score, 4),
        })
        if len(results) >= top_k:
            break

    # Set sau khi có kết quả (miss → đã tính xong). Skip nếu hs_key=None (PG down)
    if hs_key is not None:
        await cache.set_json(hs_key, results, HS_CACHE_TTL)
    return results
