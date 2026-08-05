#!/usr/bin/env python3
"""
vector_ingest.py — Ingest vector JSONL vào local Qdrant.

Embed bằng OpenRouter API (mặc định openai/text-embedding-3-small, 1536 chiều)
— KHÔNG dùng model local. Key đọc từ .env (xem scripts/lib/openrouter.py).

For each line in data/clean/<version>/vector/*.jsonl:
  - embed text qua OpenRouter /embeddings
  - upsert vào Qdrant collection (kích thước = dim từ API, tự detect)

Usage:
    python scripts/ingest/vector_ingest.py --version v1 --recreate
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from lib.openrouter import (API_KEY, EMBED_MODEL, embed_texts,  # noqa: E402
                            summarize_metrics)

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_DIR = REPO_ROOT / "data" / "clean" / "{version}" / "vector"

DEFAULT_QDRANT_URL = "http://localhost:6333"
BATCH_SIZE = 64


def qdrant_id(chunk_id: str) -> str:
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(ns, chunk_id))


def make_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in chunk.items() if k not in {"id", "text", "is_hot"}}


def probe_dimension() -> int:
    """Embed 1 text thử để biết chiều vector của model."""
    v = embed_texts(["VF thử nghiệm"], batch_size=1)[0]
    return len(v)


def ingest_file(client: QdrantClient, path: Path, vector_size: int, recreate: bool) -> int:
    collection_name = path.stem
    print(f"[vector_ingest] processing {collection_name} ...")

    if recreate and client.collection_exists(collection_name):
        client.delete_collection(collection_name)

    # Idempotent: nếu collection đã đủ points (lần chạy trước xong) thì skip
    if client.collection_exists(collection_name) and not recreate:
        info = client.get_collection(collection_name)
        expected = sum(1 for _ in path.open(encoding="utf-8") if _.strip())
        if info.points_count >= expected:
            print(f"  skip (already {info.points_count} points)")
            return info.points_count

    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"  created collection {collection_name} (dim={vector_size})")

    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not chunks:
        print(f"  empty file, skipping")
        return 0

    texts = [c["text"] for c in chunks]
    print(f"  embedding {len(texts)} chunks ...")
    embeddings = embed_texts(texts, batch_size=BATCH_SIZE)

    points = [
        PointStruct(
            id=qdrant_id(c["id"]),
            vector=emb.tolist() if hasattr(emb, "tolist") else emb,
            payload=make_payload(c),
        )
        for c, emb in zip(chunks, embeddings)
    ]
    # Upsert theo lô nhỏ (100 points) — payload 1536-dim rất lớn, 1 request khổng lồ
    # dễ bị rớt connection (WinError 10053)
    UPSERT_BATCH = 100
    for i in range(0, len(points), UPSERT_BATCH):
        client.upsert(collection_name=collection_name,
                      points=points[i:i + UPSERT_BATCH], wait=True)
    print(f"  upserted {len(points)} points into {collection_name}")
    return len(points)


def run(version: str = "v1", url: str = DEFAULT_QDRANT_URL, recreate: bool = False) -> int:
    """Embed + upsert Qdrant dense collections. Trả 0 nếu OK, 1 nếu lỗi."""
    if not API_KEY:
        print("[vector_ingest] OPENROUTER_API_KEY chưa set trong .env", file=sys.stderr)
        return 1

    vector_dir = Path(str(VECTOR_DIR).format(version=version))
    if not vector_dir.exists():
        print(f"[vector_ingest] vector dir not found: {vector_dir}", file=sys.stderr)
        return 1

    client = QdrantClient(url=url)
    try:
        client.get_collections()
    except Exception as e:
        print(f"[vector_ingest] cannot connect to Qdrant: {e}", file=sys.stderr)
        return 1

    t0 = time.time()

    print(f"[vector_ingest] probing embedding dim (model: {EMBED_MODEL}) ...")
    try:
        vector_size = probe_dimension()
    except Exception as e:
        print(f"[vector_ingest] embed probe failed: {e}", file=sys.stderr)
        return 1
    print(f"  embedding dim = {vector_size}")

    total = 0
    for jsonl in sorted(vector_dir.glob("*.jsonl")):
        total += ingest_file(client, jsonl, vector_size, recreate)

    sm = summarize_metrics()
    tot = sm["total"]
    print(f"[vector_ingest] done. total points: {total}  time: {time.time()-t0:.1f}s")
    print(f"  API: {tot['calls']} embed calls  {tot['latency_ms']/1000:.1f}s  "
          f"tokens in={tot['input_tokens']}  out={tot['output_tokens']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest vector JSONL into local Qdrant (OpenRouter embed).")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--url", default=DEFAULT_QDRANT_URL)
    ap.add_argument("--recreate", action="store_true", help="Drop and recreate collections")
    args = ap.parse_args()
    return run(args.version, args.url, args.recreate)


if __name__ == "__main__":
    sys.exit(main())
