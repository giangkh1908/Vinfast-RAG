
# Vivu  — Hướng dẫn chạy

## Yêu cầu

- Python 3.11+
- Docker Desktop
- API key TokenRouter (hoặc OpenAI)

---

## 1. Clone & Install

```bash
cd C:\Users\admin\Documents\GitHub\vivu
pip install -r requirements.txt
```

## 2. Tạo file .env

```bash
copy .env.example .env
```

Sửa `.env`:

```
OPENAI_API_KEY=sk-xxx-your-key
OPENAI_BASE_URL=https://api.tokenrouter.com/v1
LLM_MODEL=openai/gpt-4o-mini

POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vivu

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=vinfast_kb

EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_DIM=384
```

## 3. Docker — Start

```bash
docker-compose up -d
```

Verify:

```bash
docker ps
```

Phải thấy 3 containers:

| Container       | Port | URL                             |
| --------------- | ---- | ------------------------------- |
| vivu-postgres-1 | 5432 | —                              |
| vivu-qdrant-1   | 6333 | http://localhost:6333/dashboard |
| vivu-pgadmin-1  | 5050 | http://localhost:5050           |

## 4. Seed Data (PostgreSQL + Qdrant)

docker compose up -d
python scripts/run_pipeline.py --version v1 --recreate --promote
uvicorn app.main:app --reload --port 8000

Output mong đợi:

```
[1/4] Parsing source data...
  Specs: 108 rows | Pricing: 3 rows
  Product chunks: 9 | FAQ chunks: 10

[2/4] Seeding PostgreSQL...
[PG] Tables created
[PG] car_catalog: VF 7 seeded
[PG] car_pricing: 3 rows
[PG] car_specs: 108 rows
[PG] utility_link: 6 rows

[3/4] Ingesting Qdrant...
[QD] Collection 'vinfast_kb' created (384d)
[QD] Loading embedding model...
[QD] Upserted 19 chunks (total: 19)

[4/4] Validating...
  car_specs:    108 rows
  Qdrant 'vinfast_kb': 19 points

DONE. Run: uvicorn app.main:app
```

## 5. Start Server

```bash
uvicorn app.main:app --reload --port 8000
```

Mở http://localhost:8000

## 6. Test Queries

| Query                  | Tool được gọi             | Mong đợi                                                             |
| ---------------------- | ----------------------------- | ---------------------------------------------------------------------- |
| VF 7 giá bao nhiêu?  | get_price                     | 3 versions: Eco 703M, Plus 788.5M, Plus kính 807.5M                   |
| VF 7 Plus công suất? | get_specs                     | 150 kW (1-motor), 260 kW (AWD)                                         |
| VF 7 có mấy màu?    | search_knowledge_base         | 5 màu: Solar Ruby, Zenith Grey, Urban Mint, Infinity Blanc, Jet Black |
| So sánh Eco và Plus  | get_price + get_specs         | Bảng so sánh                                                         |
| Lái thử mất phí?   | search_knowledge_base (FAQ)   | Miễn phí                                                             |
| Nội thất VF 7 Eco    | get_specs (category=interior) | Màn hình 12.9", 6 loa, HUD tùy chọn                                |

---

## Docker — Quản lý

### Dừng containers (giữ data)

```bash
docker-compose stop
```

### Start lại

```bash
docker-compose start
```

### Dừng và xóa containers (GIỮ data qua volumes)

```bash
docker-compose down
```

### Dừng và xóa CẢ data (reset hoàn toàn)

```bash
docker-compose down -v
```

Sau đó chạy lại từ bước 3:

```bash
docker-compose up -d
python scripts/setup_vf7.py
```

### Xem logs

```bash
docker logs vivu-postgres-1
docker logs vivu-qdrant-1
docker logs vivu-pgadmin-1
```

---

## Xem Data

### PostgreSQL — pgAdmin

1. Mở http://localhost:5050
2. Login: `admin@vivu.com` / `admin`
3. Add Server:
   - Name: `vivu`
   - Host: `postgres`
   - Port: `5432`
   - Database: `vivu`
   - Username: `postgres`
   - Password: `postgres`
4. Browse: Servers → vivu → Schemas → public → Tables

### PostgreSQL — Docker CLI

```bash
docker exec vivu-postgres-1 psql -U postgres -d vivu -c "SELECT * FROM car_pricing;"
docker exec vivu-postgres-1 psql -U postgres -d vivu -c "SELECT version_name, spec_key, spec_value FROM car_specs WHERE spec_key='power_kw';"
```

### Qdrant Dashboard

Mở http://localhost:6333/dashboard → Collection `vinfast_kb`

---

## Re-seed Data

Chạy lại khi thay đổi source files hoặc muốn reset data:
python scripts/run_pipeline.py --version v1 --recreate --promote

Script tự `DELETE + INSERT` (PostgreSQL) và `upsert` (Qdrant). Không cần xóa data trước.

---

## Cấu trúc thư mục

```
vivu/
├── .env                          # Config (API key, DB URL)
├── .env.example                  # Template
├── requirements.txt              # Python dependencies
├── docker-compose.yml            # PostgreSQL + Qdrant + pgAdmin
│
├── scripts/
│   └── setup_vf7.py              # End-to-end: parse → seed PG + Qdrant
│
├── app/
│   ├── config.py                 # Settings (load từ .env)
│   ├── main.py                   # FastAPI app
│   ├── agent/
│   │   ├── tools.py              # 4 tools: get_price, get_specs, search_kb, list_models
│   │   ├── schemas.py            # Dynamic tool schemas (query DB)
│   │   ├── agent_loop.py         # Agent loop (max 3 iter) + SSE streaming
│   │   ├── context_builder.py    # Format tool results → text
│   │   └── prompts.py            # System prompt (dynamic từ DB)
│   ├── api/
│   │   └── chat.py               # POST /api/chat/stream
│   ├── core/
│   │   └── retrieval.py          # Hybrid search Qdrant
│   └── static/
│       └── index.html            # Chat UI
│
└── data/                          # Raw source files
    ├── 01_thong_tin_san_pham/     # Landing pages (vf7.md, vf8.md...)
    ├── 02_thong_so_ky_thuat/      # model_specs.json + brochures
    ├── 04_ho_tro_mua_xe/          # FAQ (chinh_sach_ban_hang.md)
    └── ...
```

---

## Lỗi thường gặp

| Lỗi                              | Nguyên nhân                                | Fix                                        |
| --------------------------------- | -------------------------------------------- | ------------------------------------------ |
| `ModuleNotFoundError: asyncpg`  | Chưa install                                | `pip install -r requirements.txt`        |
| `Connection refused` PostgreSQL | Docker chưa start                           | `docker-compose up -d`                   |
| `403 Forbidden` OpenAI          | Sai API key/model                            | Check`.env` OPENAI_API_KEY + LLM_MODEL   |
| `ValidationError: Extra inputs` | .env có field lạ                           | Đã fix:`extra = "ignore"` trong config |
| `not a valid point ID`          | Qdrant cần UUID                             | Đã fix:`deterministic_uuid()`          |
| `gpt-4o-mini not accessible`    | TokenRouter key không có quyền model đó | Đổi LLM_MODEL trong .env                 |
