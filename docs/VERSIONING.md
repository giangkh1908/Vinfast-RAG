# Version Management — Data Pipeline

Quản lý version thật cho pipeline: ingest version mới KHÔNG đè version cũ,
promote/rollback atomic, biết version mới đổi gì so cũ, incremental embed (đổi
1 file = chỉ embed chunk đổi). Schema chi tiết xem
[`DATA_SCHEMA_SPEC.md`](./DATA_SCHEMA_SPEC.md); file này nói **cách dùng + lifecycle**.

## Mô hình

- Mỗi **version** = 1 folder `data/clean/<version>/` (đã có) + 5 collection Qdrant
  vật lý `<col>__<version>` + rows PG tag `version=<version>`.
- **Active** = `ingest_version.is_current=true` (đúng 1 row) + alias Qdrant
  `<col>` → `<col>__<active>`.
- **Ingest** (`run_pipeline`) = BUILD version mới, KHÔNG tự activate (trừ `--promote`).
  **Promote** = swap alias + `is_current`. **Rollback** = swap alias về version cũ
  + `is_current` (instant — version cũ vẫn còn data).
- **Consumer** (retriever / team khác): query **alias** `<col>` (Qdrant, tên ổn
  định) + VIEW `edition_active` / `price_list_active` (PG, không filter version).
  KHÔNG query collection vật lý `__<version>` hay base table trực tiếp.

## Lifecycle

```
ingest v2 (build, không active)         run_pipeline --version v2 --recreate
   ↓                                    → vivu_specs__v2 (+ sparse__v2), v1 nguyên
   ↓                                       PG rows version='v2' (is_current=false)
promote v2 (activate)                    version_manager.py promote --version v2
   ↓                                        (hoặc run_pipeline --version v2 --promote)
   ↓                                    → alias <col>→__v2, is_current=v2 (atomic)
rollback v1 (instant)                    version_manager.py rollback --to v1
   ↓                                    → alias <col>→__v1, is_current=v1
delete v2 (dọn, nếu không active)        version_manager.py delete --version v2
                                        → drop __v2, DELETE rows version=v2; folder giữ (audit)
```

## Lệnh

```bash
# 0) (1 lần) khi deploy code versioned — chuyển v1 hiện có sang __v1, KHÔNG re-embed:
PYTHONUTF8=1 python scripts/version_manager.py migrate-v1

# 1) ingest version mới (song song, không đè active):
PYTHONUTF8=1 python scripts/run_pipeline.py --version v2 --recreate --commit $(git rev-parse --short HEAD)

# 2) activate (1 lệnh nếu muốn ingest+activate liền):
PYTHONUTF8=1 python scripts/run_pipeline.py --version v2 --recreate --promote
#    hoặc tách:  run_pipeline ... --version v2   rồi   version_manager.py promote --version v2

# 3) xem trạng thái / liệt kê:
PYTHONUTF8=1 python scripts/version_manager.py status   # alias → collection + active
PYTHONUTF8=1 python scripts/version_manager.py list     # bảng versions (is_current, diff, commit)

# 4) rollback (instant):
PYTHONUTF8=1 python scripts/version_manager.py rollback --to v1

# 5) dọn version cũ (refuse nếu đang active — rollback trước):
PYTHONUTF8=1 python scripts/version_manager.py delete --version v2
```

## Incremental embed (content-hash cache)

- Vector cache theo **content-hash** (`backend/lib/vector_cache.py`, SQLite ở
  `data/.vector_cache/cache.sqlite`, gitignored). Key = `sha1(embed_model + text +
  structured)`.
- Chunk content KHÔNG đổi → **cache hit → 0 API call, 0 token**. Đổi 1 chunk →
  **cache miss → embed 1 chunk**. Đổi 1 raw file → chỉ embed chunk đổi (+ seq-shift
  trong cùng section, bounded).
- `--recreate` = drop collection + BỎ QUA cache (rebuild sạch — chỉ khi đổi embed
  model / sửa bug embed). Mặc định KHÔNG recreate = incremental UPSERT + cache.
- Thực tế (đã verify): re-run cùng version = `embedded=0 cached=2333` (5s, 0
  token); đổi 1 chunk = `embedded=1 cached=2332`.
- Sparse BM25 rebuild toàn bộ mỗi lần (CPU-only, ~1s, không tốn token) —
  incremental sparse là phase sau.

## Chunk diff (added/modified/removed)

`split_cold_hot` so sánh chunk_id + content-hash với `prev_version` (auto-detect
từ `_manifest.json` của version trước, hoặc `--prev`):
- `added` = chunk_id có ở version mới, không có ở prev
- `removed` = chunk_id có ở prev, không có ở version mới
- `modified` = có ở cả 2, content-hash khác

→ ghi vào `_manifest.json` (`vector.{added,modified,removed}`) + `ingest_version`.
Version đầu (không prev) = tất cả `added`.

> Caveat: `seq` trong chunk_id có thể shift khi chèn giữa → over-count `modified`
> (cache content-hash vẫn giảm embed đúng, chỉ số diff có thể cao hơn thực).
> Fix bằng chunk_id theo content-hash = phase sau.

## migrate-v1 (1 lần)

Khi deploy code versioned lên hệ thống đang chạy v1 (collection unversioned
`vivu_specs`...):
- Copy Qdrant `vivu_specs` → `vivu_specs__v1` (×4 dense + sparse, **giữ vector,
  không re-embed**) → drop gốc → tạo alias `<col>` → `__v1`.
- Backfill vector cache từ v1 (re-ingest v1 sau đó = 0 token).
- PG: drop bảng unversioned cũ, tạo schema versioned, ingest v1 CSV tag
  `version='v1'`, `is_current=v1` + VIEW active.

## Caveats

- **2-store atomicity best-effort**: promote/rollback swap alias Qdrant + flip
  `is_current` PG. Qdrant swap trước, PG sau. Nếu Qdrant fail → PG không đụng
  (active cũ giữ). Nếu PG fail sau Qdrant OK → Qdrant đã active mới, PG chưa →
  chạy lại `set_current` (recovery manual). Phase sau: recovery command.
- **Không rename Qdrant**: Qdrant không có rename collection → migrate dùng copy
  (giữ vector). Migrate chỉ chạy 1 lần.
- **Retention**: không tự dọn version cũ — dùng `delete` thủ công.