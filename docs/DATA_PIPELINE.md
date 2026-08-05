# Data Pipeline — End-to-end (dữ liệu hiện có)

Luồng chạy end-to-end cho **dữ liệu đã crawl sẵn** trong `data/raw/`:
raw text → clean → chunk → embed → ingest vào **Qdrant** (dense + sparse) và
**PostgreSQL**. Một lệnh duy nhất, incremental (content-hash cache), log từng bước.

> Schema chi tiết (collections, payload, DDL, CSV, manifest) xem
> [`DATA_SCHEMA_SPEC.md`](./DATA_SCHEMA_SPEC.md). Quản lý version (promote /
> rollback / migrate) xem [`VERSIONING.md`](./VERSIONING.md). File này chỉ nói
> cách chạy.
>
> **Lưu ý versioning**: ingest chỉ **build** version (`<col>__<ver>`), KHÔNG tự
> active. Sau ingest phải **promote** (hoặc thêm `--promote`) thì retriever mới
> thấy — xem §3.1.

## 1. Yêu cầu môi trường

- **Python 3.11+**
- **Docker** (chạy Qdrant + PostgreSQL)
- **OpenRouter API key** (embed `openai/text-embedding-3-small` 1536-dim, qua OpenRouter)
- **Windows**: phải set `PYTHONUTF8=1` để stdout in tiếng Việt không bị
  `cp1252 UnicodeEncodeError`.

## 2. Cài đặt

```bash
pip install -r requirements.txt
cp .env.example .env          # rồi điền OPENROUTER_API_KEY=...
docker compose up -d          # Qdrant :6333/:6334, Postgres16 :5432
```

Kiểm tra 2 DB đã lên:

```bash
curl http://localhost:6333/collections        # []  (rỗng là OK lần đầu)
docker exec vivu_postgres psql -U vivu -d vivu -c '\dt'
```

## 3. Chạy end-to-end

```bash
# Windows PowerShell (đặt PYTHONUTF8 cho tiếng Việt):
$env:PYTHONUTF8=1
python scripts/run_pipeline.py --version v1 --recreate --commit $(git rev-parse --short HEAD)
```

```bash
# Linux/macOS:
python scripts/run_pipeline.py --version v1 --recreate --commit $(git rev-parse --short HEAD)
```

### 3.1. Activate version (promote)

Ingest xong version **chưa active** — retriever query alias `<col>` chưa thấy gì
cho đến khi promote. Hai cách:

```bash
# Cách 1: ingest + activate liền (1 lệnh):
python scripts/run_pipeline.py --version v1 --recreate --promote --commit $(git rev-parse --short HEAD)

# Cách 2: tách 2 bước (ingest trước, kiểm tra, rồi mới active):
python scripts/run_pipeline.py --version v1 --recreate --commit $(git rev-parse --short HEAD)
python scripts/version_manager.py promote --version v1
```

Promote = atomic alias swap (`<col>` → `<col>__<ver>`) + flip `ingest_version.is_current`.
Rollback/dọn version cũ xem [`VERSIONING.md`](./VERSIONING.md).

Orchestrator `scripts/run_pipeline.py` chạy theo thứ tự, **fail-fast** (bước nào
lỗi → dừng, không chạy bước sau):

| Bước | Script | Output |
|------|--------|--------|
| 1/5 clean | `scripts/clean_data/clean_to_jsonl.py` | `intermediate/{vector,hot}.jsonl` + `link_only.json` |
| 2/5 split | `scripts/clean_data/split_cold_hot.py` | `vector/*.jsonl` + `postgres/*.csv` + `_manifest.json` |
| 3/5 dense | `scripts/ingest/vector_ingest.py` | 4 collection Qdrant dense `<col>__<ver>` (embed incremental, content-hash cache) |
| 4/5 sparse | `scripts/ingest/sparse_ingest.py` | collection `sparse__<ver>` (BM25) + `sparse_index.json` |
| 5/5 postgres | `scripts/ingest/postgres_ingest.py` | UPSERT `edition`, `price_list` (versioned) + `ingest_version` (is_current=false) |

### CLI flags

| Flag | Mặc định | Ý nghĩa |
|------|----------|---------|
| `--version` | `v1` | Folder version dưới `data/clean/` |
| `--recreate` | off | Drop collection `<col>__<ver>` + **bỏ qua cache** (rebuild sạch — chỉ khi đổi embed model / sửa bug embed). Mặc định = incremental UPSERT + cache |
| `--no-sparse` | off | Bỏ BM25 sparse (chỉ dense + PostgreSQL) |
| `--commit` | `""` | Repo commit hash ghi vào `_manifest.json` / `ingest_version` (audit) |
| `--max-len` | `400` | Chunk max length (chars) |
| `--prev` | auto | Version trước để diff chunk (mặc định: auto-detect từ `_manifest.json` của version trước) |
| `--promote` | off | Sau khi ingest xong, tự **activate** version (alias swap + is_current) |

### Preflight

Trước khi chạy, orchestrator kiểm tra: `data/raw/` không rỗng,
`OPENROUTER_API_KEY` đã set, Qdrant & Postgres reachable. Nếu thiếu → in gợi ý
`docker compose up -d` và thoát.

## 4. Output `data/clean/v1/`

```
data/clean/v1/
├── _manifest.json          # audit: total_chunks, rows_upserted, link_only, repo_commit
├── sparse_index.json       # vocab + idf + avgdl — retriever BM25 dùng chung
├── intermediate/           # (debug/audit) jsonl trước khi split
│   ├── vector.jsonl
│   ├── hot.jsonl
│   └── link_only.json
├── vector/                 # cold — ingest Qdrant dense (text KHÔNG chứa giá)
│   ├── vivu_specs.jsonl
│   ├── vivu_product_info.jsonl
│   ├── vivu_policy.jsonl
│   └── vivu_maintenance.jsonl
└── postgres/               # hot — COPY INTO PostgreSQL (giá, edition)
    ├── edition.csv
    └── price_list.csv
```

- **Chunking 1 lần, phân nhiều thùng**: cắt chunk chỉ ở bước clean (1 file gộp
  `intermediate/vector.jsonl`, 2333 dòng). Bước split KHÔNG cắt lại — chỉ chia
  dòng theo `collection` thành 4 file `vector/<collection>.jsonl` (1 file = 1
  Qdrant collection). 2333 = 250 + 1447 + 546 + 90.
- **Stable chunk id**: `<collection>:<model_lower>:<edition_lower>:<section_slug>:<seq>`
  → Qdrant point id = `uuid5` từ chunk id (deterministic, re-run không trùng lặp).
- **Vector text** phải KHÔNG chứa số tiền (`has_money` check) — chunk nào dính
  giá sẽ bị drop, tránh leak giá cũ. Giá chỉ nằm trong `postgres/price_list.csv`.
- **Bảo dưỡng**: KHÔNG lưu DB, chỉ trả link (`maintenance_url` trong
  `link_only`/`get_maintenance_info` tool) — xem spec §5.4.

## 5. Verify sau khi chạy

```bash
# Version management: alias → __v1, is_current=v1
PYTHONUTF8=1 python scripts/version_manager.py status
PYTHONUTF8=1 python scripts/version_manager.py list

# Qdrant: collection vật lý __v1 (alias <col> trỏ tới). Count qua alias OK.
curl http://localhost:6333/collections          # vivu_specs__v1, sparse__v1 ...
curl -s -X POST http://localhost:6333/collections/vivu_specs/points/count -d '{"exact":true}'

# PostgreSQL: query VIEW active (= v1), KHÔNG query base table (chứa nhiều version)
docker exec vivu_postgres psql -U vivu -d vivu \
  -c "SELECT count(*) FROM edition_active; SELECT count(*) FROM price_list_active; \
      SELECT version,is_current FROM ingest_version;"
```

Kết quả tham chiếu (lần chạy đầu, version `v1`, đã promote):

```
version_manager status:  vivu_specs → vivu_specs__v1, sparse → sparse__v1, active=v1
Qdrant:   vivu_specs__v1=250  vivu_product_info__v1=1447  vivu_policy__v1=546
          vivu_maintenance__v1=90  sparse__v1=2333
Postgres: edition_active=14  price_list_active=14  ingest_version: v1 is_current=t
Manifest: total_chunks=2333  total_rows_upserted=28
```

> Nếu chưa promote: `status` in "active=(none)" và VIEW active rỗng. Chạy
> `version_manager.py promote --version v1` (hoặc thêm `--promote` lúc ingest).

## 6. Idempotent / incremental / re-run

- **Incremental embed (content-hash cache)**: `vector_ingest` tra
  `data/.vector_cache/cache.sqlite` (key = `sha1(embed_model + text + structured)`).
  Chunk content KHÔNG đổi → cache hit → **0 API call, 0 token**. Đổi 1 file →
  chỉ embed chunk thực sự đổi (+ seq-shift trong cùng section, bounded). Re-run
  cùng version (data không đổi) = 100% hit = 0 token. Log in `embedded=X (miss)
  cached=Y (hit)`.
- `postgres_ingest` `ON CONFLICT DO UPDATE` theo PK versioned. `split_cold_hot`
  dọn file collection không còn + tính diff `added/modified/removed` so
  `prev_version` (ghi vào `_manifest.json` + `ingest_version`).
- Muốn rebuild sạch (đổi embed model, sửa bug embed): thêm `--recreate` (drop
  collection `__<ver>` + bỏ qua cache). Sparse luôn rebuild toàn bộ (BM25
  vocab/idf phụ thuộc toàn corpus, CPU-only ~1s, 0 token).

## 7. Chạy từng bước (debug)

Orchestrator là cách dùng chính. Nếu cần debug 1 bước, gọi script trực tiếp
(cùng `run()` mà orchestrator gọi):

```bash
PYTHONUTF8=1 python scripts/clean_data/clean_to_jsonl.py --version v1
PYTHONUTF8=1 python scripts/clean_data/split_cold_hot.py --version v1 --commit $(git rev-parse --short HEAD)
PYTHONUTF8=1 python scripts/ingest/vector_ingest.py --version v1 --recreate
PYTHONUTF8=1 python scripts/ingest/sparse_ingest.py --version v1 --recreate
PYTHONUTF8=1 python scripts/ingest/postgres_ingest.py --version v1
PYTHONUTF8=1 python scripts/version_manager.py promote --version v1   # activate (bước riêng)
```

## 8. Phase sau (chưa làm)

- **API endpoint**: user input file/URL → crawl→clean→chunk→embed tự động.
- Background job, per-file incremental sparse (BM25 incremental — hiện rebuild
  toàn bộ, nhưng CPU-only ~1s, 0 token).
- Chunk id theo content-hash (fix over-count `modified` khi chèn giữa — cache
  content-hash đã giảm embed đúng, chỉ số diff có thể cao hơn thực).
- Recovery command cho promote đứt giữa chừng (Qdrant alias + PG is_current
  best-effort 2-store). Gắn `scripts/crawl.py` vào pipeline (hiện `data/raw/` đã crawl sẵn).