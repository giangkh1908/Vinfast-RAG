# Data Pipeline — End-to-end (dữ liệu hiện có)

Luồng chạy end-to-end cho **dữ liệu đã crawl sẵn** trong `data/raw/`:
raw text → clean → chunk → embed → ingest vào **Qdrant** (dense + sparse) và
**PostgreSQL**. Một lệnh duy nhất, idempotent, log từng bước.

> Schema chi tiết (collections, payload, DDL, CSV, manifest) xem
> [`DATA_SCHEMA_SPEC.md`](./DATA_SCHEMA_SPEC.md). File này chỉ nói cách chạy.

## 1. Yêu cầu môi trường

- **Python 3.11+**
- **Docker** (chạy Qdrant + PostgreSQL)
- **OpenRouter API key** (embed `openai/text-embedding-3-small` 1536-dim,
  rerank `cohere/rerank-v3.5` — rerank chỉ dùng ở retriever, không phải ingest)
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
python scripts/run_pipeline.py --version v1 --recreate --commit (git rev-parse --short HEAD)
```

```bash
# Linux/macOS:
python scripts/run_pipeline.py --version v1 --recreate --commit $(git rev-parse --short HEAD)
```

Orchestrator `scripts/run_pipeline.py` chạy theo thứ tự, **fail-fast** (bước nào
lỗi → dừng, không chạy bước sau):

| Bước | Script | Output |
|------|--------|--------|
| 1/5 clean | `scripts/clean_data/clean_to_jsonl.py` | `intermediate/{vector,hot}.jsonl` + `link_only.json` |
| 2/5 split | `scripts/clean_data/split_cold_hot.py` | `vector/*.jsonl` + `postgres/*.csv` + `_manifest.json` |
| 3/5 dense | `scripts/ingest/vector_ingest.py` | 4 collection Qdrant dense (embed OpenRouter) |
| 4/5 sparse | `scripts/ingest/sparse_ingest.py` | collection `sparse` (BM25) + `sparse_index.json` |
| 5/5 postgres | `scripts/ingest/postgres_ingest.py` | UPSERT `edition`, `price_list`, `ingest_version` |

### CLI flags

| Flag | Mặc định | Ý nghĩa |
|------|----------|---------|
| `--version` | `v1` | Folder version dưới `data/clean/` |
| `--recreate` | off | Xóa + tạo lại Qdrant collections (dense + sparse). Bỏ qua thì **idempotent** (skip collection đã đủ points) |
| `--no-sparse` | off | Bỏ BM25 sparse (chỉ dense + PostgreSQL) |
| `--commit` | `""` | Repo commit hash ghi vào `_manifest.json` / `ingest_version` (audit) |
| `--max-len` | `400` | Chunk max length (chars) |

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
# Qdrant: 5 collection, 2333 dense + 2333 sparse points
curl http://localhost:6333/collections
curl -s -X POST http://localhost:6333/collections/vivu_specs/points/count -d '{"exact":true}'

# PostgreSQL: edition ~14, price_list ~14, ingest_version 1 row
docker exec vivu_postgres psql -U vivu -d vivu \
  -c "SELECT count(*) FROM edition; SELECT count(*) FROM price_list; SELECT * FROM ingest_version;"
```

Kết quả tham chiếu (lần chạy đầu, version `v1`):

```
Qdrant:  vivu_specs=250  vivu_product_info=1447  vivu_policy=546
         vivu_maintenance=90  sparse=2333
Postgres: edition=14  price_list=14  ingest_version=1
Manifest: total_chunks=2333  total_rows_upserted=28
```

## 6. Idempotent / re-run

- Không có `--recreate` → `vector_ingest` **skip** collection đã đủ points,
  `postgres_ingest` `ON CONFLICT DO UPDATE`. Re-run không đổi count, không tốn
  token embed.
- Muốn build lại sạch (đổi model embed, đổi chunking, sửa clean logic): thêm
  `--recreate`. Sparse luôn rebuild toàn bộ (BM25 vocab/idf phụ thuộc toàn
  corpus).

## 7. Chạy từng bước (debug)

Orchestrator là cách dùng chính. Nếu cần debug 1 bước, gọi script trực tiếp
(cùng `run()` mà orchestrator gọi):

```bash
PYTHONUTF8=1 python scripts/clean_data/clean_to_jsonl.py --version v1
PYTHONUTF8=1 python scripts/clean_data/split_cold_hot.py --version v1 --commit $(git rev-parse --short HEAD)
PYTHONUTF8=1 python scripts/ingest/vector_ingest.py --version v1 --recreate
PYTHONUTF8=1 python scripts/ingest/sparse_ingest.py --version v1 --recreate
PYTHONUTF8=1 python scripts/ingest/postgres_ingest.py --version v1
```

## 8. Phase sau (chưa làm)

- **API endpoint**: user input file/URL → crawl→clean→chunk→embed tự động.
- Background job, per-file incremental sparse, re-ingest incremental (không
  rebuild toàn bộ corpus).
- Gắn `scripts/crawl.py` vào pipeline (hiện `data/raw/` đã crawl sẵn).