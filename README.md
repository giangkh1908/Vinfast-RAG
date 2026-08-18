# ViVu — Trợ Lý Ảo Tư Vấn Xe Điện VinFast (Production Agentic RAG)

[![CI/CD Pipeline](https://github.com/giangkh1908/Vinfast-RAG/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](Dockerfile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ViVu là hệ thống Chatbot AI Agentic RAG thông minh hỗ trợ tư vấn xe ô tô điện VinFast (VF 2, VF 3, VF 5, VF 6, VF 7, VF 8, VF 9, VF MPV 7), giá bán, thông số kỹ thuật, so sánh xe, đặt cọc và chính sách bảo hành. Hệ thống được xây dựng trên kiến trúc Hybrid Intent + Deterministic Tool Planning nhằm đảm bảo **tốc độ phản hồi cực nhanh** và **triệt tiêu 100% ảo giác số liệu (Zero-Hallucination)**.

---

## 🏗️ Kiến Trúc Hệ Thống (Cloud-Native Architecture)

```mermaid
graph TD
    Client[Web UI / React App / Mobile] -->|SSE Stream / REST| API[FastAPI Backend :8000]
    
    subgraph "Backend Core Engine"
        API --> RateLimit[Rate Limiter 30 RPM & Backpressure]
        RateLimit --> Agent[Agentic RAG Engine]
        Agent --> Intent[Hybrid Intent Classifier]
        Intent --> DeterministicTools[Deterministic Tools: get_specs, get_price, get_colors]
        DeterministicTools --> DB[(Neon Serverless PostgreSQL)]
        Intent --> VectorSearch[Semantic Hybrid Search]
        VectorSearch --> Qdrant[(Qdrant Cloud Cluster)]
    end
    
    subgraph "Operations, Prompting & Telemetry"
        Agent --> PromptRegistry[(PostgreSQL: prompt_registry)]
        Agent --> Telemetry[(PostgreSQL: request_metrics)]
        Admin[Admin Dashboard] -->|X-Admin-Key| AdminAPI[/api/admin/*]
        AdminAPI --> Telemetry
        AdminAPI --> PromptRegistry
    end
```

---

## ⚡ Tính Năng Nổi Bật

1. **Deterministic Spec & Price Resolution:** Tra cứu chính xác 100% bảng giá niêm yết, công suất, mô-men xoắn, dung lượng pin, kích thước từ PostgreSQL (không để LLM bịa số liệu).
2. **Dynamic Prompt Registry & Live Versioning:** Quản lý phiên bản Prompt (`system`, `synthesize`, `classify`, `summarize`) trên Database, hỗ trợ đổi Prompt trên Live không cần build lại container.
3. **Telemetry & Cost Engine:** Đo lường chi tiết Token, chi phí (USD & VNĐ), Time-to-First-Token (TTFT), Latency P50/P95, và tỷ lệ Cache Hit/Miss.
4. **Healthcheck Probes Chuẩn Cloud:** Cung cấp `/healthz` (liveness <1ms) và `/ready` (kiểm tra sâu Neon PG, Qdrant Cloud, Upstash Redis).
5. **AI Quality CI Gates:** Tự động kiểm tra chất lượng AI trên mỗi PR, yêu cầu Intent Accuracy $\ge 95\%$ và Zero-Hallucination $100\%$.

---

## 🚀 Khởi Động Dự Án (Quickstart)

### 1. Chạy Trực Tiếp Bằng Python (Development)

```bash
# 1. Clone repository & tạo môi trường ảo
git clone https://github.com/giangkh1908/Vinfast-RAG.git
cd Vinfast-RAG
python -m venv .venv
source .venv/bin/activate  # Hoặc .venv\Scripts\activate trên Windows

# 2. Cài đặt dependencies
pip install -r requirements.txt

# 3. Cấu hình biến môi trường
cp .env.example .env
# Mở file .env và điền các API Key (DeepInfra/OpenRouter, Qdrant Cloud, Neon PostgreSQL...)

# 4. Khởi chạy Server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- **API Documentation (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Interactive Docs:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

### 2. Chạy Bằng Production Docker

Toàn bộ dịch vụ cơ sở dữ liệu (PostgreSQL, Qdrant, Redis) được kết nối trực tiếp đến Managed Cloud:

```bash
# Build và chạy container
docker compose -f docker-compose.prod.yml up -d --build

# Kiểm tra logs container
docker compose -f docker-compose.prod.yml logs -f api
```

---

## 📖 Danh Mục Tài Liệu Kỹ Thuật (Documentation)

| Tài liệu | Mục đích |
|---|---|
| 📘 [**API Integration Guide**](docs/API_INTEGRATION_GUIDE.md) | **Dành cho Frontend / Mobile**: Chi tiết request/response SSE, REST API, mã mẫu TypeScript/React. |
| 🛠️ [**DevOps & Monitoring Plan**](walkthrough.md) | Báo cáo chi tiết hạ tầng Docker, Healthcheck, Telemetry, Prompt Registry và CI/CD. |
| 🧠 [**Intent & Planning Spec**](docs/INTENT_PLANNING.md) | Kiến trúc Hybrid Intent và bảng quy tắc ánh xạ công cụ xác định. |
| 💾 [**Data Pipeline & Ingestion**](docs/DATA_PIPELINE.md) | Quy trình ETL, làm sạch dữ liệu xe VinFast, tạo embeddings và nạp vào Qdrant + PostgreSQL. |
| 🗄️ [**Database Schema Specification**](docs/DATA_SCHEMA_SPEC.md) | Chi tiết thiết kế các bảng: `car_specs`, `price_list_active`, `chat_sessions`, `request_metrics`, `prompt_registry`. |
| ⚡ [**Caching & Latency Optimization**](docs/LATENCY.md) | Chiến lược tối ưu TTFT, Exact-IO caching và Upstash Redis. |

---

## 🧪 Kiểm Thử Tự Động (Testing & Quality Gates)

Dự án tích hợp 3 bộ kiểm thử tự động toàn diện:

```bash
# 1. Kiểm tra Healthcheck, Cost Engine & Prompt Admin APIs
python tests/test_devops_and_metrics.py

# 2. Kiểm tra 48 tiêu chuẩn Decision Log Schema
python tests/test_log_schema.py

# 3. AI Quality & Zero-Hallucination Smoke Benchmark (AI CI Gate)
python tests/test_ai_smoke_eval.py
```

---

## 🤝 Liên Hệ & Đóng Góp

- **Maintainer:** ViVu Engineering Team
- **Repository:** [giangkh1908/Vinfast-RAG](https://github.com/giangkh1908/Vinfast-RAG)
- **License:** MIT License
