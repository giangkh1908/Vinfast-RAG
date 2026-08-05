#!/usr/bin/env python3
"""
sparse_ingest.py — Generate BM25 (TF-IDF) sparse vectors cho mọi chunk và
upsert vào collection `sparse` của Qdrant (KHÔNG chạm dense collections,
KHÔNG cần re-embed).

Dense (OpenRouter embed) giữ nguyên trong 4 collection hiện có; sparse index nằm
riêng trong collection `sparse`. Retriever (`scripts/retriever/hybrid_retriever.py`)
merge 2 nguồn bằng RRF.

Đọc:   data/clean/<version>/vector/*.jsonl
Tạo:   collection `sparse` (Qdrant)  ← SparseVector mỗi chunk
Lưu:   data/clean/<version>/sparse_index.json  (vocab + idf — retriever dùng chung)

Usage:
    python scripts/ingest/sparse_ingest.py --version v1
"""

import argparse
import json
import math
import re
import sys
import unicodedata
import uuid
from collections import Counter
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, PointStruct, SparseIndexParams,
                                  SparseVector, SparseVectorParams)

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_DIR = REPO_ROOT / "data" / "clean" / "{version}" / "vector"
SPARSE_INDEX_PATH = REPO_ROOT / "data" / "clean" / "{version}" / "sparse_index.json"

SPARSE_COLLECTION = "sparse"
DEFAULT_QDRANT_URL = "http://localhost:6333"

# BM25 params
K1 = 1.5
B = 0.75

# Stopword tiếng Việt cơ bản
STOPWORDS = set("""
của và có là trong với cho khi từ không những các một được sẽ đã đang này đó thì
để về ra theo tại cũng như nên vào đến nhưng bởi vì hay hoặc gì rất hơn hết cả đều
sau trước mới lại còn phải bị do qua lên xuống ngay chỉ mà nữa đây ấy nào bao nhiêu
mình bạn tôi nó họ chúng ta ông bà anh chị em cùng thôi cần nếu đúng xin quý
""".split())

TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    return [t for t in TOKEN_RE.findall(text) if t not in STOPWORDS and len(t) > 1]


def qdrant_id(chunk_id: str) -> str:
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(ns, chunk_id))


def load_chunks(version: str) -> list[tuple[str, dict]]:
    """(collection, chunk dict) cho mọi chunk."""
    vdir = Path(str(VECTOR_DIR).format(version=version))
    chunks: list[tuple[str, dict]] = []
    for f in sorted(vdir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            chunks.append((f.stem, c))
    return chunks


def run(version: str = "v1", url: str = DEFAULT_QDRANT_URL, recreate: bool = False) -> int:
    """Build BM25 sparse vectors → Qdrant 'sparse' + sparse_index.json. Trả 0/1."""
    chunks = load_chunks(version)
    if not chunks:
        print(f"[sparse_ingest] no chunks in {VECTOR_DIR.format(version=version)}", file=sys.stderr)
        return 1
    print(f"[sparse_ingest] {len(chunks)} chunks")

    # 1. Tokenize + document frequency
    doc_tokens = [tokenize(c["text"]) for _, c in chunks]
    N = len(doc_tokens)
    df: Counter[str] = Counter()
    for toks in doc_tokens:
        df.update(set(toks))

    vocab = {t: i for i, t in enumerate(sorted(df))}
    idf = {t: math.log((N - df[t] + 0.5) / (df[t] + 0.5) + 1.0) for t in df}
    avgdl = sum(len(t) for t in doc_tokens) / N if N else 1.0
    print(f"  vocab={len(vocab)}  avgdl={avgdl:.1f}")

    # 2. Client
    client = QdrantClient(url=url)
    if recreate and client.collection_exists(SPARSE_COLLECTION):
        client.delete_collection(SPARSE_COLLECTION)
    if not client.collection_exists(SPARSE_COLLECTION):
        client.create_collection(
            collection_name=SPARSE_COLLECTION,
            sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
        )
        print(f"  created collection {SPARSE_COLLECTION}")

    # 3. BM25 sparse vector từng chunk + upsert
    points: list[PointStruct] = []
    for (col, c), toks in zip(chunks, doc_tokens):
        cid = c["id"]
        dl = len(toks)
        tf = Counter(toks)
        indices: list[int] = []
        values: list[float] = []
        for t, f in tf.items():
            if t not in vocab:
                continue
            w = idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / avgdl))
            indices.append(vocab[t])
            values.append(round(w, 6))
        # sắp theo index (Qdrant yêu cầu indices tăng dần)
        order = sorted(range(len(indices)), key=lambda i: indices[i])
        indices = [indices[i] for i in order]
        values = [values[i] for i in order]
        points.append(PointStruct(
            id=qdrant_id(cid),
            vector={"sparse": SparseVector(indices=indices, values=values)},
            payload={"collection": col, "chunk_id": cid, "model_id": c.get("model_id")},
        ))
        if len(points) >= 256:
            client.upsert(collection_name=SPARSE_COLLECTION, points=points, wait=True)
            points = []
    if points:
        client.upsert(collection_name=SPARSE_COLLECTION, points=points, wait=True)

    # 4. Lưu index cho retriever
    index_path = Path(str(SPARSE_INDEX_PATH).format(version=version))
    index_path.parent.mkdir(parents=True, exist_ok=True)
    # idf lưu dạng list aligned theo vocab index cho gọn
    idf_list = [idf[t] for t, i in sorted(idf.items(), key=lambda kv: vocab[kv[0]])]
    index_path.write_text(json.dumps({
        "version": version,
        "vocab": vocab,
        "idf": idf_list,
        "avgdl": avgdl,
        "n_docs": N,
        "k1": K1,
        "b": B,
    }, ensure_ascii=False), encoding="utf-8")

    total = client.count(collection_name=SPARSE_COLLECTION).count
    print(f"[sparse_ingest] done. sparse points: {total}")
    print(f"  index saved: {index_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build BM25 sparse vectors into Qdrant 'sparse' collection.")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--url", default=DEFAULT_QDRANT_URL)
    ap.add_argument("--recreate", action="store_true", help="Xóa và tạo lại collection sparse")
    args = ap.parse_args()
    return run(args.version, args.url, args.recreate)


if __name__ == "__main__":
    sys.exit(main())
