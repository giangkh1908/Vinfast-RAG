# vivu
Chatbot AI hỗ trợ tư vấn xe cho Vinfast

## Data pipeline

Luồng data end-to-end (raw → clean → chunk → embed → Qdrant + PostgreSQL), chạy
bằng 1 lệnh. Chi tiết cách chạy + verify xem
[`docs/DATA_PIPELINE.md`](docs/DATA_PIPELINE.md). Schema của 2 DB (collections,
payload, DDL, CSV, manifest) xem [`docs/DATA_SCHEMA_SPEC.md`](docs/DATA_SCHEMA_SPEC.md).

Chạy nhanh (cần `.env` đã cấu hình cloud + OpenRouter key):

```bash
pip install -r requirements.txt
cp .env.example .env   # điền OPENROUTER_API_KEY, QDRANT_* cloud, PG_DSN Neon
PYTHONUTF8=1 python scripts/run_pipeline.py --version v1 --recreate --promote
```

DB mặc định dùng **cloud** (Qdrant Cloud + Neon). Nếu cloud lỗi / muốn chạy local
với Docker, đổi 3 biến DB trong `.env` về localhost rồi:
`docker compose -f docker-compose.local.yml up -d` — xem `docs/DATA_PIPELINE.md`
mục "Fallback local bằng Docker".
