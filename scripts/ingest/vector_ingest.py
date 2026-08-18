#!/usr/bin/env python3
"""
vector_ingest.py — Ingest vector JSONL vào Qdrant (versioned + incremental).

Collection = `<stem>__<version>` (VD `vivu_product_info__v2`). Versioned → ingest v2
KHÔNG đè v1. Promote/rollback swap alias (xem scripts/version_manager.py).

Incremental embed: cache vector theo content-hash (lib/vector_cache.py).
Chunk nào content không đổi → cache hit → lấy vector, không gọi API. Miss →
embed + cache. Cuối cùng xóa orphan points (chunk bị bỏ ở version mới).

`--recreate` = drop collection + BỎ QUA cache (rebuild sạch, hiếm — đổi embed
model). Mặc định (không recreate) = incremental UPSERT + cache.

Embed bằng OpenRouter API (mặc định openai/text-embedding-3-small, 1536 chiều).
Đọc: data/clean/<version>/vector/*.jsonl  →  Qdrant collection `<stem>__<version>`

Usage:
    python scripts/ingest/vector_ingest.py --version v1            # incremental
    python scripts/ingest/vector_ingest.py --version v1 --recreate # rebuild sạch
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

# Chạy trực tiếp (`python scripts/ingest/vector_ingest.py`) → repo root vào sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.config import CLEAN_DIR, QDRANT_API_KEY, QDRANT_TIMEOUT, QDRANT_URL  # noqa: E402
from scripts.schemas import validate_chunk, make_dense_payload  # noqa: E402
from lib.openrouter import (API_KEY, EMBED_MODEL, embed_texts,  # noqa: E402
                            summarize_metrics)
from lib.vector_cache import VectorCache, content_hash  # noqa: E402

VECTOR_DIR = CLEAN_DIR / "{version}" / "vector"

DEFAULT_QDRANT_URL = QDRANT_URL
BATCH_SIZE = 64
UPSERT_BATCH = 100


def qdrant_id(chunk_id: str) -> str:
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(ns, chunk_id))


def make_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in chunk.items() if k not in {"id", "is_hot"}}


def validate_chunks_and_payload(chunks: list[dict[str, Any]], context: str = "") -> list[dict[str, Any]]:
    """Validate chunk schema + dense payload. Raise ValueError if invalid."""
    valid_chunks = []
    errors = []
    for i, c in enumerate(chunks):
        try:
            chunk_model = validate_chunk(c, context=f"{context}[{i}]")
            # Validate dense payload can be created
            make_dense_payload(chunk_model)
            valid_chunks.append(c)
        except ValueError as e:
            errors.append(str(e))
    if errors:
        msg = f"Payload validation failed {context}:\n" + "\n".join(errors[:5])
        if len(errors) > 5:
            msg += f"\n... and {len(errors) - 5} more errors"
        raise ValueError(msg)
    return valid_chunks


def probe_dimension() -> int:
    """Embed 1 text thử để biết chiều vector của model."""
    v = embed_texts(["VF thử nghiệm"], batch_size=1)[0]
    return len(v)


def collection_dim(client: QdrantClient, name: str) -> int | None:
    """Đọc dim từ collection đang có (nếu tồn tại)."""
    if not client.collection_exists(name):
        return None
    info = client.get_collection(name)
    cfg = info.config.params.vectors
    # Single vector config → .size; named config → dict
    if hasattr(cfg, "size"):
        return cfg.size
    return None


def existing_ids(client: QdrantClient, name: str) -> set[str]:
    """Scroll toàn bộ point id hiện có trong collection (để tìm orphan)."""
    ids: set[str] = set()
    offset = None
    while True:
        records, offset = client.scroll(name, limit=256, offset=offset,
                                        with_payload=False, with_vectors=False)
        ids.update(r.id for r in records)
        if offset is None:
            break
    return ids


def ingest_file(client: QdrantClient, path: Path, recreate: bool,
                version: str, cache: VectorCache) -> tuple[int, int, int, int]:
    """Trả (total_points, embedded_miss, cached_hit, deleted_orphans)."""
    collection_name = f"{path.stem}__{version}"
    print(f"[vector_ingest] processing {collection_name} ...")

    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not chunks:
        print("  empty file, skipping")
        return (0, 0, 0, 0)

    # Validate chunk schema + payload structure
    chunks = validate_chunks_and_payload(chunks, context=collection_name)
    print(f"  ✓ validated {len(chunks)} chunks")

    # Tạo/xóa collection
    if recreate and client.collection_exists(collection_name):
        client.delete_collection(collection_name)

    # Content-hash + tra cache (1 pass, đếm hit/miss đúng)
    hashes = [content_hash(c["text"], c.get("structured"), EMBED_MODEL) for c in chunks]
    vectors: list[list[float] | None] = [None] * len(chunks)
    miss_idx: list[int] = []
    cached_hit = 0
    first_hit_dim: int | None = None
    use_cache = not recreate
    for i, h in enumerate(hashes):
        v = cache.get(h) if use_cache else None
        if v is not None and (first_hit_dim is None or len(v) == first_hit_dim):
            if first_hit_dim is None:
                first_hit_dim = len(v)
            vectors[i] = v
            cached_hit += 1
        else:
            miss_idx.append(i)

    # Xác định dim: collection đang có → cache hit → probe API
    dim = collection_dim(client, collection_name)
    if dim is None:
        dim = first_hit_dim or probe_dimension()
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        # Payload indexes cho filter thường dùng (model_id, category, source_type)
        for field in ("model_id", "category", "source_type"):
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        print(f"  created {collection_name} (dim={dim})")

    # Embed miss qua OpenRouter
    embedded_miss = 0
    if miss_idx:
        print(f"  embedding {len(miss_idx)} chunks (cache miss) ...")
        miss_texts = [chunks[i]["text"] for i in miss_idx]
        embedded = embed_texts(miss_texts, batch_size=BATCH_SIZE)
        for i, vec in zip(miss_idx, embedded):
            if len(vec) != dim:
                print(f"  WARN: dim mismatch {len(vec)} != {dim}", file=sys.stderr)
            vectors[i] = vec
            if use_cache:
                cache.put(hashes[i], collection_name, EMBED_MODEL, vec)
            embedded_miss += 1
        if use_cache:
            cache.commit()

    # Upsert tất cả (hit + miss)
    points = [
        PointStruct(
            id=qdrant_id(c["id"]),
            vector=vectors[i],
            payload=make_payload(c),
        )
        for i, c in enumerate(chunks)
    ]
    for i in range(0, len(points), UPSERT_BATCH):
        client.upsert(collection_name=collection_name,
                      points=points[i:i + UPSERT_BATCH], wait=True)

    # Xóa orphan (chunk bị bỏ ở version này) — chỉ khi KHÔNG recreate
    deleted = 0
    if not recreate:
        wanted = {qdrant_id(c["id"]) for c in chunks}
        orphans = list(existing_ids(client, collection_name) - wanted)
        for i in range(0, len(orphans), UPSERT_BATCH):
            client.delete(collection_name=collection_name,
                           points_selector=orphans[i:i + UPSERT_BATCH], wait=True)
        deleted = len(orphans)

    print(f"  upserted {len(points)}  embedded={embedded_miss}  cached={cached_hit}  deleted_orphans={deleted}")
    return (len(points), embedded_miss, cached_hit, deleted)


def run(version: str = "v1", url: str = DEFAULT_QDRANT_URL, recreate: bool = False) -> int:
    """Embed + upsert Qdrant dense collections (versioned, incremental). Trả 0/1."""
    if not API_KEY:
        print("[vector_ingest] OPENROUTER_API_KEY chưa set trong .env", file=sys.stderr)
        return 1

    vector_dir = Path(str(VECTOR_DIR).format(version=version))
    if not vector_dir.exists():
        print(f"[vector_ingest] vector dir not found: {vector_dir}", file=sys.stderr)
        return 1

    client = QdrantClient(url=url, api_key=QDRANT_API_KEY or None,
                          timeout=QDRANT_TIMEOUT)
    try:
        client.get_collections()
    except Exception as e:
        print(f"[vector_ingest] cannot connect to Qdrant: {e}", file=sys.stderr)
        return 1

    cache = VectorCache()
    t0 = time.time()
    total_points = 0
    total_embedded = 0
    total_cached = 0
    total_deleted = 0
    try:
        for jsonl in sorted(vector_dir.glob("*.jsonl")):
            pts, emb, cached, deleted = ingest_file(
                client, jsonl, recreate, version, cache)
            total_points += pts
            total_embedded += emb
            total_cached += cached
            total_deleted += deleted
    finally:
        cache.close()

    sm = summarize_metrics()
    tot = sm["total"]
    print(f"[vector_ingest] done. points={total_points}  "
          f"embedded={total_embedded}  cached={total_cached}  "
          f"deleted_orphans={total_deleted}  time={time.time()-t0:.1f}s")
    print(f"  API: {tot['calls']} embed calls  {tot['latency_ms']/1000:.1f}s  "
          f"tokens in={tot['input_tokens']}  out={tot['output_tokens']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest vector JSONL into Qdrant (versioned + incremental).")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--url", default=DEFAULT_QDRANT_URL)
    ap.add_argument("--recreate", action="store_true",
                    help="Drop collection + ignore cache (rebuild sạch)")
    args = ap.parse_args()
    return run(args.version, args.url, args.recreate)


if __name__ == "__main__":
    sys.exit(main())
