# vivu
Chatbot AI hỗ trợ tư vấn xe cho Vinfast

## Data pipeline

Luồng data end-to-end (raw → clean → chunk → embed → Qdrant + PostgreSQL), chạy
bằng 1 lệnh. Chi tiết cách chạy + verify xem
[`docs/DATA_PIPELINE.md`](docs/DATA_PIPELINE.md). Schema của 2 DB (collections,
payload, DDL, CSV, manifest) xem [`docs/DATA_SCHEMA_SPEC.md`](docs/DATA_SCHEMA_SPEC.md).

```bash
docker compose up -d
pip install -r requirements.txt
cp .env.example .env   # điền OPENROUTER_API_KEY
PYTHONUTF8=1 python scripts/run_pipeline.py --version v1 --recreate
```
