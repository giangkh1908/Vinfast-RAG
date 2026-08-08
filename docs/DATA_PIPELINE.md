# Data Pipeline

Pipeline xử lý dữ liệu VinFast:

```text
data/raw/ -> clean/chunk -> split -> specs -> embedding -> Qdrant/PostgreSQL
```

Pipeline chạy fail-fast. Mỗi version được build riêng, sau đó mới promote để
retriever sử dụng.

## 1. Yêu cầu

- Python 3.11+
- OpenRouter API key trong `.env`
- Crawl4AI + Chromium cho brochure PDF
- Qdrant Cloud + Neon (Postgres) — cấu hình trong `.env`
- Docker chỉ cần khi chạy fallback local (xem `docker-compose.local.yml`)

## 2. Cài đặt

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
crawl4ai-doctor
```

Nếu `.venv` đã có sẵn:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\crawl4ai-doctor.exe
```

Tạo `.env` từ `.env.example` và điền:

```dotenv
OPENROUTER_API_KEY=...
OPENROUTER_CHAT_MODEL=openai/gpt-4o-mini
OPENROUTER_EMBED_MODEL=openai/text-embedding-3-small
QDRANT_URL=https://<cluster-id>.aws.cloud.qdrant.io
QDRANT_API_KEY=...
PG_DSN=postgresql://<user>:<password>@<host>.neon.tech/neondb?sslmode=require
```

Database mặc định chạy cloud (Qdrant Cloud + Neon), không cần Docker cho
production. Nếu cloud lỗi / muốn chạy local chỉ để test, xem mục dưới.

### 2.1. Fallback local bằng Docker (khi cloud lỗi / offline)

Docker chạy Qdrant + PostgreSQL local thay cho cloud. Chỉ cần đổi `.env` và bật
compose; code không phải sửa gì (mọi script đọc biến từ `.env`):

1. Khởi động DB local:
   ```powershell
   docker compose -f docker-compose.local.yml up -d
   docker compose -f docker-compose.local.yml ps
   ```
   (Kiểm tra: Qdrant `http://localhost:16333`, PostgreSQL `localhost:15432`.)

2. Đổi `.env` sang local (bỏ api_key, port dùng của compose):
   ```dotenv
   QDRANT_URL=http://localhost:16333
   QDRANT_API_KEY=
   PG_DSN=postgresql://vivu:vivu@localhost:15432/vivu
   ```

3. Chạy lại pipeline (lần đầu cần `--recreate` để tạo collection local):
   ```powershell
   .\.venv\Scripts\python.exe scripts/run_pipeline.py --version v1 --recreate --promote
   ```

4. Quay lại cloud: khôi phục `.env` về `QDRANT_URL`/`QDRANT_API_KEY`/`PG_DSN`
   cloud rồi chạy lại pipeline (`--recreate --promote` để đẩy data lên cloud).
   Có thể tắt compose local: `docker compose -f docker-compose.local.yml down`.

## 3. Crawl dữ liệu

Crawl HTML hoặc PDF vào `data/raw/`:

```powershell
.\.venv\Scripts\python.exe scripts/crawl.py `
  https://vinfastauto.com/vn_vi/dat-coc-xe-vf2
```

`crawl.py` dùng Crawl4AI cho HTML và PyMuPDF cho PDF. Brochure PDF dùng cho
spec được khai báo theo thứ tự VF2 -> VF9 trong:

```text
data/raw/link_brochure.md
```

Không cần crawl brochure PDF thủ công. Full pipeline tự đọc các URL này.

## 4. Chạy full pipeline

### 4.1. Một lệnh đầy đủ

Dùng cho dev hằng ngày. Lệnh này tự clean, chunk, crawl brochure PDF, vision
OCR khi cần, parse specs, embed, ingest và activate version:

```powershell
.\.venv\Scripts\python.exe scripts/run_pipeline.py `
  --version v1 `
  --recreate `
  --max-len 800 `
  --commit $(git rev-parse --short HEAD) `
  --promote
```

Đây là lệnh duy nhất cần dùng sau khi cài đặt. `--recreate` là tùy chọn an
toàn khi rebuild sạch; bỏ nó nếu chỉ muốn chạy incremental.

### 4.2. Chạy nhanh, bỏ qua brochure LLM

Dùng khi brochure không thay đổi và chỉ muốn cập nhật raw HTML:

```powershell
.\.venv\Scripts\python.exe scripts/run_pipeline.py `
  --version v1 `
  --no-crawl-brochures
```

Mặc định pipeline gọi LLM qua Crawl4AI cho 8 brochure PDF, vì vậy chạy lâu hơn
và tốn token. PDF có text layer dùng extraction thường; PDF image-only fallback
sang render ảnh + vision LLM OCR.

### 4.3. Chạy từng version nhưng chưa activate

```powershell
.\.venv\Scripts\python.exe scripts/run_pipeline.py `
  --version v1 `
  --recreate `
  --max-len 800 `
  --commit $(git rev-parse --short HEAD)
```

Nếu không dùng `--promote`, version chỉ được build, chưa active:

```powershell
.\.venv\Scripts\python.exe scripts/version_manager.py promote --version v1
```

## 5. Các bước pipeline

| Bước | Thành phần | Kết quả |
|---|---|---|
| 1 | `clean_to_jsonl.py` | Làm sạch raw, loại giá khỏi vector, chunk tối đa 800 ký tự |
| 2 | `split_cold_hot.py` | Chia vector collections và PostgreSQL CSV |
| 3 | `parse_specs.py` | Tạo `postgres/specs.csv`; có thể Crawl4AI + LLM brochure |
| 4 | `vector_ingest.py` | Embed và ingest Qdrant dense |
| 5 | `sparse_ingest.py` | Build BM25 sparse, có thể bỏ bằng `--no-sparse` |
| 6 | `postgres_ingest.py` | UPSERT edition, prices, specs và ingest version |

Spec số liệu không đi vào vector. Chúng được lưu ở `car_specs` để query chính
xác theo model/edition.

## 6. Output

```text
data/clean/v1/
|- _manifest.json
|- sparse_index.json
|- intermediate/
|  |- vector.jsonl
|  |- hot.jsonl
|  `- link_only.json
|- vector/
|  |- vivu_product_info.jsonl
|  |- vivu_policy.jsonl
|  `- vivu_maintenance.jsonl
`- postgres/
   |- edition.csv
   |- price_list.csv
   `- specs.csv
```

`vector.jsonl` không được chứa giá tiền. Giá chỉ nằm trong `hot.jsonl` và
`postgres/price_list.csv`. `specs.csv` theo contract ở
[`SPEC_SCHEMA.md`](./SPEC_SCHEMA.md).

## 7. Chạy từng bước

```powershell
.\.venv\Scripts\python.exe scripts/clean_data/clean_to_jsonl.py --version v1 --max-len 800
.\.venv\Scripts\python.exe scripts/clean_data/split_cold_hot.py --version v1 --commit $(git rev-parse --short HEAD)
.\.venv\Scripts\python.exe scripts/clean_data/parse_specs.py --version v1 --crawl-brochures
.\.venv\Scripts\python.exe scripts/ingest/vector_ingest.py --version v1 --recreate
.\.venv\Scripts\python.exe scripts/ingest/sparse_ingest.py --version v1 --recreate
.\.venv\Scripts\python.exe scripts/ingest/postgres_ingest.py --version v1
```

## 8. Kiểm tra sau khi chạy

```powershell
.\.venv\Scripts\python.exe scripts/version_manager.py status
.\.venv\Scripts\python.exe scripts/version_manager.py list
Get-Content data/clean/v1/_manifest.json
```

Kiểm tra specs (Neon):

```powershell
psql $env:PG_DSN -c `
  "SELECT model_code, version_name, spec_key, spec_value, spec_unit FROM car_specs ORDER BY model_code, version_name, spec_key;"
```

Kiểm tra Qdrant Cloud:

```powershell
curl -u ":$env:QDRANT_API_KEY" "$env:QDRANT_URL/collections"
```

## 9. Rerun và versioning

- `--recreate`: xoá collection Qdrant của version và embed lại toàn bộ.
- Không có `--recreate`: vector cache giúp tránh embed lại nội dung không đổi.
- `--prev`: chỉ định version trước để tính diff; mặc định tự tìm từ manifest.
- `--promote`: đổi alias active sau khi ingest thành công.
- Full pipeline mặc định chạy `--crawl-brochures`; dùng `--no-crawl-brochures`
  nếu chỉ muốn cập nhật raw HTML mà không gọi vision/LLM.

Chi tiết promote/rollback xem [`VERSIONING.md`](./VERSIONING.md).
