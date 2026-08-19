# Observability Plan — Vivu Chatbot Backend

> Trạng thái: **Đang triển khai.** Plan này thay thế phần "Distributed tracing via Phoenix"
> trong đánh giá cũ — **Phoenix đã bị xoá** (app/tracing.py) vì không phải dependency,
> không được cài, và yêu cầu tự chạy server. Thay bằng Langfuse spans (SaaS, đã tích hợp).
>
> Nguyên tắc: 3 mục này **không làm bot nhanh hơn** — chúng là lớp để *đo được và cứu được*.
> Không phá hệ metrics REST/PG + admin dashboard đang hoạt động.

## Hiện trạng (trước plan)

| Khía cạnh | Hiện trạng | Đánh giá |
|---|---|---|
| Health check | `/healthz` (liveness) + `/ready` (readiness sâu: PG, Qdrant, Redis, LLM) | ✅ **Đã đủ và đúng** — không cần sửa |
| LLM tracing | Langfuse (`LangfuseAsyncOpenAI` trong `app/agent/llm.py`) | ✅ Đã có, auto-trace LLM calls |
| Metrics | `request_metrics` (PG) + REST `/api/admin/metrics/*` + Kafka → admin dashboard | ✅ Có (batch 2-5s, không realtime) |
| Distributed tracing | ~~Phoenix~~ (đã xoá) | ❌ Thiếu spans cho request lifecycle |
| Prometheus | Không có `/metrics`, không prometheus-client | ❌ Thiếu realtime/alerting |
| Structured logging | `logging.basicConfig` text thuần | ❌ Không parse được bởi ELK/Loki/Grafana |

## 3 hạng mục

### 1. Structured logging — ưu tiên #1, chi phí thấp, không thêm dep
- Module mới `app/core/logging_config.py`: custom JSON `Formatter`
- `request_id`/`session_id` qua `contextvars`, gán bởi ASGI middleware → mọi log trong 1 request cùng 1 id
- Đăng ký trong `app/main.py` bởi `setup_logging()`; `LOG_FORMAT=json|text` (mặc định text cho dev terminal)
- Lợi ích: ELK/Loki/Grafana parse được field, nối logs 1 request xuyên các node.

**Files:** `app/core/logging_config.py` (mới), `app/main.py`, `app/config.py`, `docs/GUIDE.md`

### 2. Prometheus metrics + Kafka consumer metrics
- Thêm `prometheus-client` + endpoint `/metrics`
- Export realtime: HTTP request count/duration, **LLM latency + cost**, cache hit/miss,
  embedding latency, **Kafka consumer** (buffer depth, batches flushed, flush failures)
- Đắp lên (không thay) hệ REST/PG hiện có.

**Files:** `app/core/telemetry/prometheus.py` (mới), `app/api/prometheus.py` (mới,
endpoint `/metrics`), `app/main.py` (middleware), `requirements.txt`, + hook nhẹ vào
`llm.py`, `retrieval.py`, `cache.py`, `kafka_worker.py`, `telemetry.py`.

### 3. Distributed tracing → Langfuse lifecycle spans
- Thay Phoenix: dùng Langfuse (SaaS, keys đã có) — **không cần chạy server**
- Giữ auto-trace LLM; thêm **trace + spans** cho request lifecycle trong `agent_loop`
  (classify → tools → generate), gắn `request_id`, query, decision, latency
- Guard vô hiệu (no-op) khi Langfuse tắt.

**Files:** `app/core/telemetry/langfuse_trace.py` (mới), `agent_loop.py`

## Ưu tiên & phụ thuộc backend

| # | Việc | Công sức | Backend cần |
|---|---|---|---|
| 1 | Structured logging | Nhỏ | Không |
| 2 | Prometheus `/metrics` + Kafka metrics | TB | Không (chỉ export format) |
| 3 | Langfuse lifecycle spans | TB | Langfuse cloud (đã có keys) |

## Validation sau triển khai
- Regression: `tests/unit/test_decision.py` + `eval/benchmark/run_benchmark.py` (không đổi)
- Log: 1 request → kiểm tra JSON line có `request_id` xuyên các node
- `/metrics`: `curl /metrics` trả `text/plain; version=0.0.4` đủ counter/histogram
- Langfuse: trace xuất hiện trong cloud, có span lifecycle

## Loại trừ / không làm
- **Không** đưa deep check vào `/healthz` (anti-pattern liveness → restart-loop); giữ `/ready` sâu
- **Không** xoá hệ metrics REST/PG (dashboard admin vẫn dùng)
- OTel → Grafana/Tempo chỉ là option xa khi có Grafana Cloud (ngoài scope hiện tại)
