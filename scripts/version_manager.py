#!/usr/bin/env python3
"""
version_manager.py — Quản lý version cho data pipeline (Qdrant alias + PG active).

Model: collection vật lý = `<col>__<version>`; alias `<col>` → active version.
Promote/rollback = swap alias (atomic) + flip `ingest_version.is_current`.

Subcommands:
  list        — bảng versions từ ingest_version (version, created_at, is_current, diff, commit)
  status      — alias Qdrant `<col>` → `__<version>` + current version
  promote     — alias swap → `__<V>` + is_current=V (V đã ingest)
  rollback    — alias swap về `__<V>` + is_current=V (V vẫn còn data → instant)
  delete      — drop `__<V>` collections + DELETE rows PG version=V (refuse nếu đang active)
  migrate-v1  — (1 lần) chuyển v1 hiện có (collection unversioned) sang `__v1` + alias,
                PG versioned, is_current=v1. KHÔNG re-embed (copy points WITH vectors).
                Chạy sau khi deploy code versioned.

Usage:
    python scripts/version_manager.py list
    python scripts/version_manager.py promote --version v2
    python scripts/version_manager.py rollback --to v1
    python scripts/version_manager.py delete --version v2
    python scripts/version_manager.py migrate-v1
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

load_dotenv(REPO_ROOT / ".env")

from scripts.ingest import postgres_ingest  # noqa: E402

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:16333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
PG_DSN = os.environ.get("PG_DSN", "postgresql://vivu:vivu@localhost:15432/vivu")

SPARSE_ALIAS = "sparse"
DENSE_ALIASES = ["vivu_product_info", "vivu_policy", "vivu_maintenance"]

ALL_ALIASES = DENSE_ALIASES + [SPARSE_ALIAS]


# ── helpers ──────────────────────────────────────────────────────────────────

def _client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)


def _conn():
    return psycopg2.connect(PG_DSN)


def dense_stems_for_version(version: str) -> list[str]:
    """Tên collection dense của 1 version (từ vector/*.jsonl stems)."""
    vdir = REPO_ROOT / "data" / "clean" / version / "vector"
    if not vdir.exists():
        return list(DENSE_ALIASES)
    stems = sorted(p.stem for p in vdir.glob("*.jsonl"))
    return stems or list(DENSE_ALIASES)


def physical_collections(version: str, stems: list[str] | None = None) -> list[str]:
    """Tên collection vật lý của version (dense `__<v>` + sparse `__<v>`)."""
    stems = stems or dense_stems_for_version(version)
    return [f"{s}__{version}" for s in stems] + [f"{SPARSE_ALIAS}__{version}"]


def existing_aliases(client: QdrantClient) -> dict[str, str]:
    """Trả {alias_name: collection_name} đang có trong Qdrant."""
    out: dict[str, str] = {}
    try:
        resp = client.get_aliases()
        for a in resp.aliases:
            out[a.alias_name] = a.collection_name
    except Exception:  # noqa: BLE001
        pass
    return out


def swap_aliases(client: QdrantClient, version: str) -> list[str]:
    """Atomic swap: alias `<col>` → `<col>__<version>` cho mọi col. Trả list col đã swap."""
    stems = dense_stems_for_version(version)
    cols = stems + [SPARSE_ALIAS]
    # Chỉ delete alias đang tồn tại (Qdrant error 404 nếu delete alias không có)
    cur_aliases = existing_aliases(client)
    ops = []
    for col in cols:
        physical = f"{col}__{version}"
        if not client.collection_exists(physical):
            raise RuntimeError(f"collection vật lý chưa ingest: {physical} — chạy run_pipeline --version {version} trước")
        if col in cur_aliases:
            ops.append(models.DeleteAliasOperation(
                delete_alias=models.DeleteAlias(alias_name=col)))
        ops.append(models.CreateAliasOperation(
            create_alias=models.CreateAlias(alias_name=col, collection_name=physical)))
    if ops:
        client.update_collection_aliases(change_aliases_operations=ops)
    return cols


def current_version_pg() -> str | None:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT version FROM ingest_version WHERE is_current LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_list(args=None) -> int:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT version, created_at, prev_version, is_current,
                              vector_chunks_added, vector_chunks_modified,
                              vector_chunks_removed, pg_rows_upserted, repo_commit
                       FROM ingest_version ORDER BY created_at DESC""")
        rows = cur.fetchall()
    except psycopg2.Error as e:
        print(f"[list] lỗi PG: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    if not rows:
        print("(chưa có version nào trong ingest_version)")
        return 0
    print(f"{'version':<8} {'created_at':<22} {'current':<8} {'prev':<6} "
          f"{'added':>6} {'mod':>5} {'rem':>5} {'pg':>4}  commit")
    for r in rows:
        v, ca, prev, cur, add, mod, rem, pg, commit = r
        ca_s = ca.strftime("%Y-%m-%d %H:%M:%S")[:19] if ca else ""
        print(f"{v:<8} {ca_s:<22} {'★' if cur else '':<8} {(prev or '-'):<6} "
              f"{(add or 0):>6} {(mod or 0):>5} {(rem or 0):>5} {(pg or 0):>4}  {commit or ''}")
    return 0


def cmd_status(args=None) -> int:
    client = _client()
    cur_pg = current_version_pg()
    print(f"Active version (PG): {cur_pg or '(none)'}")
    print(f"{'alias':<22} → collection")
    aliases = existing_aliases(client)
    for col in ALL_ALIASES:
        print(f"  {col:<22} → {aliases.get(col, '(no alias)')}")
    # list all physical collections
    cols = [c.name for c in client.get_collections().collections]
    versioned = sorted(c for c in cols if "__" in c)
    print(f"\nPhysical collections ({len(versioned)}):")
    for c in versioned:
        cnt = client.count(collection_name=c).count
        print(f"  {c:<32} {cnt:>6} points")
    return 0


def _activate(version: str, rollback: bool) -> int:
    client = _client()
    conn = _conn()
    try:
        # 1) alias swap (atomic). Nếu fail → PG không đụng (active cũ giữ)
        cols = swap_aliases(client, version)
        # 2) flip is_current
        postgres_ingest.set_current(conn, version, rollback=rollback)
    except Exception as e:  # noqa: BLE001
        print(f"[{'rollback' if rollback else 'promote'}] FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    action = "ROLLBACK" if rollback else "PROMOTED"
    print(f"{action} → active={version}")
    print(f"  alias swap: {', '.join(cols)} → __{version}")
    print(f"  is_current = {version}")
    return 0


def cmd_promote(args) -> int:
    return _activate(args.version, rollback=False)


def cmd_rollback(args) -> int:
    return _activate(args.to, rollback=True)


def cmd_delete(args) -> int:
    version = args.version
    cur = current_version_pg()
    if version == cur:
        print(f"[delete] REFUSE: {version} đang active — rollback trước khi delete.", file=sys.stderr)
        return 1
    client = _client()
    stems = dense_stems_for_version(version)
    cols = physical_collections(version, stems)
    dropped = []
    for c in cols:
        if client.collection_exists(c):
            client.delete_collection(c)
            dropped.append(c)
    # xóa alias trỏ tới version này (nếu có)
    aliases = existing_aliases(client)
    dangling = [a for a, target in aliases.items() if target in cols]
    if dangling:
        client.update_collection_aliases(change_aliases_operations=[
            models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=a)) for a in dangling
        ])
    # PG rows
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM price_list WHERE version = %s", (version,))
        cur.execute("DELETE FROM edition WHERE version = %s", (version,))
        cur.execute("DELETE FROM car_specs WHERE ingest_version = %s", (version,))
        cur.execute("DELETE FROM ingest_version WHERE version = %s", (version,))
        conn.commit()
    finally:
        conn.close()
    print(f"[delete] version={version}")
    print(f"  dropped collections: {dropped}")
    print(f"  removed dangling aliases: {dangling}")
    print(f"  deleted PG rows (edition/price_list/car_specs/ingest_version) for version={version}")
    print(f"  (folder data/clean/{version}/ giữ nguyên — audit)")
    return 0


def _copy_collection(client: QdrantClient, src: str, dst: str) -> int:
    """Copy points (with vectors + payload) src → dst. Trả số points copied. NO re-embed."""
    info = client.get_collection(src)
    params = info.config.params
    vectors_config = None
    sparse_vectors_config = None
    if params.vectors is not None:
        if isinstance(params.vectors, dict):
            vectors_config = params.vectors
        else:
            vc = params.vectors
            vectors_config = models.VectorParams(size=vc.size, distance=vc.distance)
    if getattr(params, "sparse_vectors", None):
        sparse_vectors_config = params.sparse_vectors
    client.create_collection(dst, vectors_config=vectors_config,
                             sparse_vectors_config=sparse_vectors_config)

    n = 0
    offset = None
    while True:
        records, offset = client.scroll(src, limit=500, offset=offset,
                                        with_payload=True, with_vectors=True)
        if not records:
            break
        points = [models.PointStruct(id=r.id, vector=r.vector, payload=r.payload)
                  for r in records]
        for i in range(0, len(points), 100):
            client.upsert(dst, points=points[i:i + 100], wait=True)
        n += len(points)
        if offset is None:
            break
    return n


def _backfill_cache(client: QdrantClient, version: str) -> int:
    """Populate vector cache từ v1 jsonl (text) + Qdrant __v1 vectors (không re-embed).

    Để v1 cũng hưởng cache: re-ingest v1 sau migrate = 100% hit (0 token).
    """
    import json as _json
    import uuid as _uuid
    from lib.vector_cache import VectorCache, content_hash
    from lib.openrouter import EMBED_MODEL

    cache = VectorCache()
    ns = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    vdir = REPO_ROOT / "data" / "clean" / version / "vector"
    n = 0
    for f in sorted(vdir.glob("*.jsonl")):
        col = f.stem
        collection = f"{col}__{version}"
        if not client.collection_exists(collection):
            continue
        chunks = [_json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not chunks:
            continue
        ids = [str(_uuid.uuid5(ns, c["id"])) for c in chunks]
        # retrieve vectors theo id (batch 100), put cache theo content_hash
        for i in range(0, len(ids), 100):
            batch_ids = ids[i:i + 100]
            batch_chunks = chunks[i:i + 100]
            records = client.retrieve(collection, ids=batch_ids, with_payload=False, with_vectors=True)
            vmap = {str(r.id): r.vector for r in records}
            for c, qid in zip(batch_chunks, batch_ids):
                vec = vmap.get(qid)
                if vec is None:
                    continue
                h = content_hash(c["text"], c.get("structured"), EMBED_MODEL)
                cache.put(h, col, EMBED_MODEL, vec)
                n += 1
        cache.commit()
    cache.close()
    return n


def cmd_migrate_v1(args=None) -> int:
    """1 lần: chuyển v1 hiện có (unversioned) sang `__v1` + alias + PG versioned."""
    client = _client()
    version = "v1"

    # 1) Copy từng collection unversioned → `__v1` (giữ vector, không re-embed)
    stems = DENSE_ALIASES  # mặc định
    # phát hiện stems thật từ collection đang có (unversioned)
    existing = {c.name for c in client.get_collections().collections}
    aliases = existing_aliases(client)
    print(f"[migrate-v1] existing collections: {sorted(existing)}")
    migrated = []
    for col in DENSE_ALIASES + [SPARSE_ALIAS]:
        src = col
        dst = f"{col}__{version}"
        if not client.collection_exists(src):
            print(f"  skip {src} (không có) — collection gốc chưa ingest?")
            continue
        if client.collection_exists(dst):
            print(f"  skip {dst} (đã có)")
            migrated.append(dst)
            continue
        print(f"  copy {src} → {dst} (giữ vector, không re-embed) ...")
        n = _copy_collection(client, src, dst)
        print(f"    {n} points copied")
        migrated.append(dst)

    # 2) Xóa collection unversioned gốc (giải phóng tên alias) + tạo alias `<col>` → `<col>__v1`
    cur_aliases = existing_aliases(client)
    for col in DENSE_ALIASES + [SPARSE_ALIAS]:
        if col in cur_aliases:
            continue  # đã là alias → không phải collection gốc, skip
        if client.collection_exists(col):
            client.delete_collection(col)
            print(f"  dropped original {col} (giải phóng tên alias)")
    ops = []
    for dst in migrated:
        col = dst.rsplit("__", 1)[0]
        if col in existing_aliases(client):
            ops.append(models.DeleteAliasOperation(
                delete_alias=models.DeleteAlias(alias_name=col)))
        ops.append(models.CreateAliasOperation(
            create_alias=models.CreateAlias(alias_name=col, collection_name=dst)))
    if ops:
        client.update_collection_aliases(change_aliases_operations=ops)
        print(f"  alias tạo: {[o.create_alias.alias_name for o in ops if isinstance(o, models.CreateAliasOperation)]}")

    # 2.5) Backfill vector cache từ v1 (để v1 cũng cache-hit, không re-embed)
    try:
        n = _backfill_cache(client, version)
        print(f"  backfilled cache: {n} vectors (v1 giờ re-ingest = 0 token)")
    except Exception as e:  # noqa: BLE001
        print(f"  WARN backfill cache fail (không chặn): {e}", file=sys.stderr)

    # 3) PG: rebuild schema versioned từ v1 CSV, tag version='v1', is_current=v1
    conn = _conn()
    try:
        cur = conn.cursor()
        # drop bảng unversioned cũ (nếu schema cũ) rồi tạo lại versioned
        cur.execute("DROP VIEW IF EXISTS edition_active; DROP VIEW IF EXISTS price_list_active;")
        cur.execute("DROP TABLE IF EXISTS price_list; DROP TABLE IF EXISTS edition;")
        cur.execute("DROP TABLE IF EXISTS maintenance_schedule;")  # schema cũ, đã bỏ per spec
        # ingest_version: thêm cột mới (is_current/activated_at/rolled_back_at) nếu thiếu,
        # giữ rows audit cũ. Không ALTER edition/price_list (vừa drop ở trên).
        cur.execute(postgres_ingest._MIGRATE_INGEST_VERSION_DDL)
        cur.execute(postgres_ingest.DDL)
        conn.commit()
        # ingest v1 CSV với version tag
        version_dir = REPO_ROOT / "data" / "clean" / version
        pg_dir = version_dir / "postgres"
        if pg_dir.exists():
            edition_rows = postgres_ingest.load_csv(pg_dir / "edition.csv")
            price_rows = postgres_ingest.load_csv(pg_dir / "price_list.csv")
            postgres_ingest.upsert_edition(conn, version, edition_rows)
            postgres_ingest.upsert_price_list(conn, version, price_rows)
            postgres_ingest.record_manifest(conn, version, version_dir)
        postgres_ingest.set_current(conn, version, rollback=False)
    finally:
        conn.close()

    print(f"[migrate-v1] XONG. active=v1, alias `<col>` → `<col>__v1`.")
    print(f"  Consumer query VIEW edition_active / price_list_active (= v1).")
    print(f"  Giờ ingest v2: run_pipeline --version v2 --recreate --commit ${{...}}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Version manager cho data pipeline.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Liệt kê versions trong ingest_version").set_defaults(func=cmd_list)
    sub.add_parser("status", help="Alias Qdrant + current version").set_defaults(func=cmd_status)

    p_promote = sub.add_parser("promote", help="Activate version (alias swap + is_current)")
    p_promote.add_argument("--version", required=True)
    p_promote.set_defaults(func=cmd_promote)

    p_rb = sub.add_parser("rollback", help="Activate version cũ (instant, không re-ingest)")
    p_rb.add_argument("--to", required=True)
    p_rb.set_defaults(func=cmd_rollback)

    p_del = sub.add_parser("delete", help="Drop collection __V + xóa rows PG (refuse nếu active)")
    p_del.add_argument("--version", required=True)
    p_del.set_defaults(func=cmd_delete)

    sub.add_parser("migrate-v1", help="(1 lần) chuyển v1 unversioned → __v1 + alias, không re-embed").set_defaults(func=cmd_migrate_v1)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())