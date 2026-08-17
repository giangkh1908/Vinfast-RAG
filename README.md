# Vivu

Chatbot AI hỗ trợ tư vấn xe VinFast — FastAPI + LangGraph + hybrid intent + deterministic tool planning.

## Kiến trúc hiện tại

```
Client (React+TS, SSE) → /api/chat/stream
  → validate (session_id, token limits)
  → sanitize history (chống injection)
  → classify: hybrid intent (rule → LLM fallback strict-JSON)
  → build_tool_plan: deterministic tool calls (LLM không đoán tham số)
  → execute song song → generate (LLM tổng hợp) → respond (sources)
  → multi-turn memory: chat_sessions (summary) + window 7 turn
```

## Data pipeline

Luồng data end-to-end (raw → clean → chunk → embed → Qdrant + PostgreSQL), chạy
bằng 1 lệnh. Chi tiết: [`docs/DATA_PIPELINE.md`](docs/DATA_PIPELINE.md).
Schema 2 DB: [`docs/DATA_SCHEMA_SPEC.md`](docs/DATA_SCHEMA_SPEC.md).

```bash
pip install -r requirements.txt
cp .env.example .env   # điền OPENROUTER_API_KEY, QDRANT_*, PG_DSN
PYTHONUTF8=1 python scripts/run_pipeline.py --version v1 --recreate --promote
```

## Chạy app

```bash
# Backend (serve cả frontend đã build ở app/static):
PYTHONUTF8=1 .venv/Scripts/python -m uvicorn app.main:app --port 8000

# Frontend dev (nếu sửa UI — build lại khi xong):
cd frontend && npm run dev        # http://localhost:5173 (proxy /api → :8000)
cd frontend && npm run build      # build thẳng vào app/static
```

## Tài liệu

| Doc | Nội dung |
|---|---|
| [`docs/INTENT_PLANNING.md`](docs/INTENT_PLANNING.md) | Hybrid intent (12 intent) + deterministic tool plan — LLM không đoán tham số |
| [`docs/MEMORY_PLAN.md`](docs/MEMORY_PLAN.md) | Multi-turn memory: chat_sessions, summary mỗi 7 turn, window 7 turn, token limits |
| [`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md) | Frontend React+TS: SSE, StatusBar, markdown, localStorage session |
| [`docs/LATENCY.md`](docs/LATENCY.md) | Đo latency, feature check (context -40x), TTFT provider, hướng Redis |
| [`docs/architecture.md`](docs/architecture.md) | Kiến trúc tổng + module map |
| [`docs/GUIDE.md`](docs/GUIDE.md) | Hướng dẫn chung |
| [`docs/DATA_PIPELINE.md`](docs/DATA_PIPELINE.md) | Pipeline data |
| [`docs/DATA_SCHEMA_SPEC.md`](docs/DATA_SCHEMA_SPEC.md) | Schema DB (car_specs, price_list, chat_sessions...) |

## Hạn chế data đã biết

- **Bảo hành tổng quát**: ✅ CÓ — 28 chunks từ `data/raw/vn_vi_chinh-sach-bao-hanh-oto...txt` (model_id null) trong `vivu_policy` (thời hạn bảo hành từng dòng xe, phạm vi bảo hành...). Lưu ý: `data/05_chinh_sach_dich_vu/chinh_sach_bao_hanh.md` rỗng (0 byte) nhưng KHÔNG ảnh hưởng — pipeline ingest từ raw txt.
- **Bảo hành theo model (SVC PDF)**: chỉ có VF3/5/6/MPV7 — VF2/7/8/9 chưa có bản policy model-specific (nhưng general policy đã phủ).
- VF6 không có dòng `sunroof_type` trong car_specs → bot trả "chưa được ghi nhận" (đúng rule).
