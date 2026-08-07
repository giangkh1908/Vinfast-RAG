# Prototype Plan — UC-01 Product Information (VF7 Only)

## Goal

Build a working prototype chatbot that answers questions about VinFast VF7 using data from 2 files + model_specs.json. No guardrails, no admin portal, no multi-model support. Just: clean data → store → agent loop → chat UI.

## Scope

- **1 model only:** VF 7 (Eco, Plus, Plus Trần kính toàn cảnh)
- **Data sources:** `vf7.md`, `vf7_specs.md`, `model_specs.json` (VF7 section), `chinh_sach_ban_hang.md`
- **No guardrails:** skip pre/post guardrails, injection check
- **No admin portal:** seed data via scripts only
- **No user memory:** single-session, no persistence
- **No clarification loop:** if query unclear, LLM handles gracefully
- **Frontend:** single HTML file, minimal CSS, SSE streaming

## Data Conflicts Found

| Spec | `vf7_specs.md` (2023) | `vf7.md` landing page | `model_specs.json` (API) |
|---|---|---|---|
| VF7 Plus power | 260 kW | 150 kW | 1 motor: 201 kW, 2 motor: 349 kW |
| VF7 Plus torque | 500 Nm | 310 Nm | 500 Nm |
| VF7 Plus range | 431 km WLTP | 500.5 km | 504 km |
| VF7 Plus battery | — | 70 kWh | 75.6 kWh |

**Resolution:** `model_specs.json` is authoritative (structured API data). `vf7.md` landing page is second priority. `vf7_specs.md` is oldest (2023 article) — **prose descriptions only, KHÔNG dùng số liệu**.

**Data separation rule (critical):**
- **PostgreSQL (car_specs, car_pricing):** ALL numbers — kW, Nm, km, kWh, mm, giá tiền, túi khí...
- **Qdrant (vinfast_kb):** Prose descriptions ONLY — thiết kế, tính năng, màu sắc, chính sách, trải nghiệm
- **KHÔNG put specs numbers into Qdrant chunks** — tránh LLM lấy số sai từ search_knowledge_base thay vì get_specs

---

## Step 1 — Data Processing

### 1a. Parse `model_specs.json` → PostgreSQL

Source: `data/02_thong_so_ky_thuat/model_specs.json` → `Products-Car-VF7` section

**Tables to populate:**

```sql
-- car_catalog (1 row)
INSERT INTO car_catalog (model_code, model_name, model_family, segment, status, versions, vehicle_usage_type)
VALUES ('VF 7', 'VF 7', 'VF7', 'CUV', 'active', '["2026","2025","2024","2023"]', 'personal');

-- car_pricing (3 rows: Eco, Plus, Plus Trần kính)
-- From vf7.md landing page (most current prices):
INSERT INTO car_pricing (model_code, version_name, version_code, price_vnd, promo_price_vnd) VALUES
('VF 7', 'Eco', 'GC15V', 740000000, 703000000),
('VF 7', 'Plus', 'GC12V', 830000000, 788500000),
('VF 7', 'Plus kính toàn cảnh', 'GC12V', 850000000, 807500000);

-- car_specs (dùng số từ model_specs.json, KHÔNG dùng 260kW từ vf7_specs.md)
-- NULL version_name = áp dụng chung mọi bản

-- Kích thước (chung mọi bản)
INSERT INTO car_specs (model_code, version_name, version_code, spec_category, spec_key, spec_value, spec_unit) VALUES
('VF 7', NULL,   NULL,    'dimension',  'length_mm',          '4545',    'mm'),
('VF 7', NULL,   NULL,    'dimension',  'width_mm',           '1890',    'mm'),
('VF 7', NULL,   NULL,    'dimension',  'height_mm',          '1635.75', 'mm'),
('VF 7', NULL,   NULL,    'dimension',  'wheelbase_mm',       '2840',    'mm'),
('VF 7', NULL,   NULL,    'dimension',  'ground_clearance_mm','190',     'mm'),

-- La-zăng (khác nhau giữa bản)
('VF 7', 'Eco',  'GC15V', 'dimension',  'wheel_size_inch',    '19',      'inch'),
('VF 7', 'Plus', 'GC12V', 'dimension',  'wheel_size_inch',    '20',      'inch'),

-- Powertrain (dùng 201kW từ model_specs.json, KHÔNG dùng 260kW)
('VF 7', 'Eco',  'GC15V', 'powertrain', 'power_kw',           '130',     'kW'),
('VF 7', 'Plus', 'GC12V', 'powertrain', 'power_kw',           '201',     'kW'),
('VF 7', 'Eco',  'GC15V', 'powertrain', 'torque_nm',          '250',     'Nm'),
('VF 7', 'Plus', 'GC12V', 'powertrain', 'torque_nm',          '500',     'Nm'),
('VF 7', 'Eco',  'GC15V', 'powertrain', 'range_km',           '498',     'km'),
('VF 7', 'Plus', 'GC12V', 'powertrain', 'range_km',           '504',     'km'),
('VF 7', 'Eco',  'GC15V', 'powertrain', 'battery_kwh',        '59.6',    'kWh'),
('VF 7', 'Plus', 'GC12V', 'powertrain', 'battery_kwh',        '75.6',    'kWh'),
('VF 7', 'Eco',  'GC15V', 'powertrain', 'drivetrain',         'FWD',     NULL),
('VF 7', 'Plus', 'GC12V', 'powertrain', 'drivetrain',         'AWD',     NULL),
('VF 7', 'Eco',  'GC15V', 'powertrain', 'top_speed_kmh',      '150',     'km/h'),
('VF 7', 'Plus', 'GC12V', 'powertrain', 'top_speed_kmh',      '175',     'km/h'),

-- Nội thất
('VF 7', 'Eco',  'GC15V', 'interior',   'screen_size_inch',   '12.9',    'inch'),
('VF 7', 'Plus', 'GC12V', 'interior',   'screen_size_inch',   '15',      'inch'),
('VF 7', NULL,   NULL,    'interior',   'seats',              '5',       ''),

-- An toàn (từ model_specs.json adas section)
('VF 7', 'Plus', 'GC12V', 'adas',       'forward_collision_warning', 'Có',  NULL),
('VF 7', 'Plus', 'GC12V', 'adas',       'front_emergency_braking',   'Có',  NULL),
('VF 7', 'Plus', 'GC12V', 'adas',       'blind_spot_warning',        'Có',  NULL),
('VF 7', 'Eco',  'GC15V', 'adas',       'blind_spot_warning',        'Có',  NULL),
('VF 7', 'Eco',  'GC15V', 'adas',       'forward_collision_warning', 'Không', NULL);

-- ... (flatten all specs from model_specs.json Products-Car-VF7 section)
```

**Script:** `scripts/seed_vf7.py`
- Read `model_specs.json`, filter `Products-Car-VF7`
- Flatten `specs.powertrain`, `specs.dimension`, `specs.safety`, `specs.interior`, `specs.exterior`, `specs.adas`
- Insert into `car_specs`
- Insert prices from hardcoded values (from `vf7.md`)
- Insert 1 row into `car_catalog`

### 1b. Clean & Chunk → Qdrant

**Source 1: `vf7.md`** (333 lines raw → ~150 lines clean)

Clean rules:
- Strip all `![...](url)` images
- Strip nav/footer/cookie/reCAPTCHA boilerplate (lines 1-8, 232-333)
- Strip price section (lines 24-49) — prices go to PostgreSQL only
- Strip "So sánh với xe động cơ đốt trong" calculator (lines 232-295)
- Keep: design description, exterior, interior, ADAS features, warranty, charging infrastructure

Chunks to create (pure prose, KHÔNG lẫn số specs):

| Chunk ID | model_id | edition_id | text | text_type | source_type |
|---|---|---|---|---|---|
| `vivu_product_info:vf7:overview` | VF7 | NULL | "VF 7 là mẫu C-SUV điện phân khúc hạng C. Thiết kế bởi Torino Design kết hợp VinFast. Triết lý thiết kế 'Vũ Trụ Phi Đối Xứng' — thể hiện sự tự do, cá tính, mạnh mẽ và thể thao." | prose | product_page |
| `vivu_product_info:vf7:exterior` | VF7 | NULL | "Đầu xe thon gọn lấy cảm hứng phi thuyền không gian. Dải đèn LED cánh chim chữ V đặc trưng. Đèn LED hình thang đặt dưới cản trước. Tay nắm cửa ẩn vào thân xe tối ưu khí động học. Gương chiếu hậu đặt trên cửa trước mở rộng tầm quan sát. Đường gân dập nổi nối liền hông xe, đuôi xe cơ bắp góc cạnh." | prose | product_page |
| `vivu_product_info:vf7:colors` | VF7 | NULL | "VF 7 có 5 màu ngoại thất: Solar Ruby, Zenith Grey, Urban Mint, Infinity Blanc, Jet Black." | list | product_page |
| `vivu_product_info:vf7:interior` | VF7 | NULL | "Nội thất hướng tới người lái, tất cả tiện nghi trong tầm tay. Tùy chọn trần kính toàn cảnh mở rộng không gian. Giảm thiểu nút bấm vật lý, tích hợp điều khiển và giải trí vào màn hình cảm ứng trung tâm." | prose | product_page |
| `vivu_product_info:vf7:warranty` | VF7 | NULL | "Bảo hành xe mới 7 năm hoặc 160.000 km (tùy điều kiện nào đến trước). Xưởng dịch vụ không ngày nghỉ, sửa chữa lưu động, cứu hộ 24/7. Bảo hành xe thương mại 3 năm hoặc 100.000 km." | prose | product_page |
| `vivu_product_info:vf7:charging_infra` | VF7 | NULL | "Hệ thống trạm sạc VinFast trải dài 34 tỉnh và thành phố. 106 tuyến quốc lộ quan trọng đều có trạm sạc. 80/85 thành phố đã được lắp đặt. Khoảng cách trung bình giữa 2 trạm sạc trong thành phố là 3.5 km." | prose | product_page |
| `vivu_product_info:vf7:design_prose` | VF7 | NULL | "VF 7 được chắp bút bởi Torino Design. Phần mui vuốt xuống thấp mang hơi hướng thể thao, đường nét táo bạo xuôi về đuôi xe tạo tổng thể hiện đại khỏe khoắn. Hông xe có đường cắt xẻ mạnh tạo cá tính." | prose | brochure |
| `vivu_product_info:vf7:smart_features` | VF7 | NULL | "Tính năng thông minh: trợ lái trên đường cao tốc level 2, trợ làn, hỗ trợ tự động chuyển làn, giám sát hành trình, cảnh báo va chạm, trợ lái khi nguy cơ va chạm, hỗ trợ đỗ xe, đèn pha tự động. Phần mềm cập nhật từ xa (OTA), chẩn đoán và thông báo lỗi qua máy chủ." | list | brochure |
| `vivu_product_info:vf7:driving_feel` | VF7 | NULL | "Cảm giác chắc chắn khi cầm lái nhờ khoảng cách tâm bánh trước-sau bố trí hợp lý, kiểm soát lực kéo tốt. Dễ dàng di chuyển, vào cua mượt mà, linh hoạt khi tăng giảm tốc. Hệ dẫn động AWD (bản Plus) cho khả năng bám đường cao trên đường trơn trượt." | prose | brochure |

**Source 3: `chinh_sach_ban_hang.md`** (249 lines, 30 FAQ Q&A pairs)

Clean rules:
- Strip YAML front-matter (lines 1-4)
- Strip note about full answers (line 7)
- Keep all Q&A pairs as-is

Chunks to create (1 Q&A = 1 chunk, model_id=NULL vì FAQ áp dụng chung):

| Chunk ID | model_id | edition_id | text | text_type | source_type |
|---|---|---|---|---|---|
| `vivu_faq:chinh_sach_ban_hang:01` | NULL | NULL | "Q: Lái thử có cam kết mua không?\nA: Không. Dịch vụ lái thử nhằm giúp Quý khách đưa ra quyết định mua xe một cách tự tin và thoải mái." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:02` | NULL | NULL | "Q: Lái thử tại nhà mất phí không?\nA: Dịch vụ hoàn toàn miễn phí." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:03` | NULL | NULL | "Q: Lái thử bao lâu, bao xa?\nA: Quãng đường 5-10 km. Thời gian tối đa 30 phút." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:04` | NULL | NULL | "Q: Cần chuẩn bị gì để lái thử?\nA: GPLX còn hạn (bản cứng/VNeID), sức khỏe đảm bảo, không rượu bia chất kích thích, ký cam kết trước khi lái." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:05` | NULL | NULL | "Q: Dòng xe nào lái thử được?\nA: VF 3, VF 5, VF 6, VF 7, VF 8, VF 9, Limo Green, Minio Green, EC Van." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:06` | NULL | NULL | "Q: Đăng ký lái thử bằng cách nào?\nA: Truy cập https://shop.vinfastauto.com/vn_vi/dang-ky-lai-thu, chọn lịch và đăng ký." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:07` | NULL | NULL | "Q: Thẩm định vay mua xe?\nA: Truy cập https://shop.vinfastauto.com/tham-dinh-vay-o-to/techcombank, làm theo 4 bước." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:08` | NULL | NULL | "Q: Đặt mua xe bằng cách nào?\nA: Mua trực tiếp tại Showroom VinFast." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:09` | NULL | NULL | "Q: Được huỷ cọc không?\nA: Cọc trước: được chuyển nhượng/huỷ. Cọc cam kết: không hoàn/huỷ, chỉ chuyển giao." | qa_pair | faq |
| `vivu_faq:chinh_sach_ban_hang:10` | NULL | NULL | "Q: Tính giá lăn bánh?\nA: Truy cập https://shop.vinfastauto.com/vn_vi/chi-phi-lan-banh." | qa_pair | faq |

> Chỉ ingest 10 Q&A đầu (liên quan đến mua xe ô tô điện). Bỏ Q&A về xe máy điện, phụ kiện, chuyển nhượng cọc VF8/VF9.

**Total chunks:** ~19 (9 product_info/prose + 10 FAQ)

**Script:** `scripts/ingest_vf7.py`
- Read `vf7.md` + `vf7_specs.md` + `chinh_sach_ban_hang.md`
- Apply clean rules (strip images, nav, prices, specs numbers, boilerplate)
- Split into chunks by section heading (vf7.md, vf7_specs.md) hoặc Q&A pair (chinh_sach_ban_hang.md)
- Embed each chunk (local model hoặc Google)
- Upsert into Qdrant `vinfast_kb` collection với payload: `model_id`, `edition_id`, `text_type`, `source_type`, `source_url`

---

## Step 2 — Database Setup

### 2a. PostgreSQL

**Script:** `scripts/setup_vf7_db.py`
- Create tables (from plan-agentic-rag.md A1): `car_catalog`, `car_pricing`, `car_specs`, `utility_link`
- Seed VF7 data (from Step 1a)
- Seed 6 utility links (hardcode)

### 2b. Qdrant

**Script:** `scripts/setup_vf7_qdrant.py`
- Create collection `vinfast_kb` (dense + sparse)
- Ingest chunks (from Step 1b)

**Payload schema per point:**
```json
{
  "text": "VF 7 là mẫu C-SUV điện...",
  "model_id": "VF7",           // normalized, không dấu cách
  "edition_id": null,           // null = chung mọi bản, "Eco"/"Plus" = bản-specific
  "text_type": "prose",         // prose | list | qa_pair
  "source_type": "product_page", // product_page | brochure | faq | policy
  "source_url": "https://...",
  "language": "vi"
}
```

---

## Step 3 — Agent (Minimal)

From `plan-agentic-rag.md`, apply ONLY:

| Component | Include? | Why |
|---|---|---|
| B1 Tools | ✅ Simplified: 4 tools only | get_price, get_specs, search_knowledge_base, list_available_models |
| B2 Tool Schemas | ✅ Static (no dynamic loading) | Hardcode VF7 model list |
| B3 Agent Loop | ✅ Core loop only | Max 3 iterations, no groundedness check |
| B4 Classify | ❌ Skip | LLM handles routing via function calling |
| B5 Parallel Execution | ✅ | asyncio.gather for multi-tool calls |
| B6 Context Builder | ✅ Simplified | Format tool results → text |
| B7 Groundedness | ❌ Skip | Prototype, no quality gate |
| B8 Memory | ❌ Skip | Single session |
| B9 Prompts | ✅ Minimal | System prompt with VF7 info only |
| B10 Chat API | ✅ | POST /api/chat/stream with SSE |

### 3a. Tools (`app/agent/tools.py`)

```python
# Only 4 tools for prototype:

async def get_price(model_code: str = "VF 7", version: str = None) -> dict:
    """Query car_pricing table. Return prices for VF7.
    Source: PostgreSQL (car_pricing). Returns: price_vnd, promo_price_vnd."""
    
async def get_specs(model_code: str = "VF 7", version: str = None, category: str = None) -> dict:
    """Query car_specs table. Return ALL specs numbers for VF7.
    Source: PostgreSQL (car_specs). 
    Filter: category (dimension|powertrain|interior|safety|adas), version (Eco|Plus|NULL=chung).
    Returns: spec_key, spec_value, spec_unit, spec_category."""

async def search_knowledge_base(query: str) -> dict:
    """Hybrid search Qdrant vinfast_kb. Return matching prose chunks.
    Source: Qdrant. Returns: text, model_id, edition_id, text_type, source_type.
    KHÔNG trả specs numbers — numbers come from get_specs."""

async def list_available_models() -> dict:
    """Return VF7 models only for prototype."""
```

### 3b. Tool Schemas (`app/agent/schemas.py`)

Static schemas, no dynamic loading. Hardcode `enum: ["VF 7"]` for model_code.

### 3c. Agent Loop (`app/agent/agent_loop.py`)

Simplified from B3:
- Skip pre-guardrails
- Skip classify/clarify
- Skip user memory
- Skip groundedness check
- Keep: agent loop (max 3 iterations) + parallel tool execution + synthesize

```python
class AgentLoop:
    MAX_ITERATIONS = 3

    async def run(self, query: str, history: list[dict]) -> AgentResult:
        messages = self._build_messages(query, history)
        tool_results = []

        for i in range(self.MAX_ITERATIONS):
            response = await self.llm.chat(messages, tools=TOOL_SCHEMAS)
            if not response.tool_calls:
                break
            results = await self._execute_tools_parallel(response.tool_calls)
            tool_results.extend(results)
            if self._is_satisfied(query, tool_results):
                break
            messages = self._append_tool_results(messages, response, results)

        context = self._build_structured_context(tool_results)
        final_response = await self._synthesize(query, context, history)
        return AgentResult(response=final_response, sources=tool_results)
```

### 3d. System Prompt (`app/agent/prompts.py`)

```python
SYSTEM_PROMPT = """Bạn là trợ lý tư vấn xe VinFast VF 7.

Phiên bản đang bán: VF 7 Eco, VF 7 Plus, VF 7 Plus Trần kính toàn cảnh.

Quy tắc:
1. Trả lời bằng tiếng Việt, ngắn gọn.
2. Hỏi giá → PHẢI dùng get_price tool. KHÔNG tự bịa số tiền.
3. Hỏi thông số (công suất, quãng đường, pin, kích thước) → PHẢI dùng get_specs tool.
4. Hỏi tính năng/mô tả/chính sách → dùng search_knowledge_base.
5. Không tự bịa số liệu. Không tư vấn xe khác.
6. Dẫn nguồn (URL) khi có.
"""
```

> **KHÔNG hardcode giá trong system prompt** — ép LLM phải gọi get_price tool để test function calling flow.

---

## Step 4 — Backend

### 4a. FastAPI app (`app/main.py`)

```python
from fastapi import FastAPI
from app.api.chat import router as chat_router

app = FastAPI()
app.include_router(chat_router)
app.mount("/", StaticFiles(directory="app/static", html=True))
```

### 4b. Chat endpoint (`app/api/chat.py`)

```python
@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    agent = get_agent_loop()
    async def generate():
        async for event in agent.run_stream(request.message, request.history):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 4c. Config (`app/config.py`)

Minimal config:
```python
class Settings:
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    postgres_url: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "vinfast_kb"
```

---

## Step 5 — Frontend

Single file: `app/static/index.html`

```
Features:
- Chat input + send button
- Message history (user/assistant)
- SSE streaming (tokens appear realtime)
- Sources display (collapsed, click to expand)
- Simple CSS (no framework)
```

No admin portal, no session management, no feedback buttons.

---

## File List (Prototype)

```
scripts/
├── seed_vf7.py              # Step 1a: parse model_specs.json → PostgreSQL
├── ingest_vf7.py            # Step 1b: clean + chunk + embed → Qdrant
├── setup_vf7_db.py          # Step 2a: create tables + seed
└── setup_vf7_qdrant.py      # Step 2b: create collection + ingest

app/
├── main.py                  # Step 4a: FastAPI app
├── config.py                # Step 4c: minimal config
├── api/
│   └── chat.py              # Step 4b: SSE streaming endpoint
├── agent/
│   ├── tools.py             # Step 3a: 4 tools
│   ├── schemas.py           # Step 3b: static schemas
│   ├── agent_loop.py        # Step 3c: simplified loop
│   ├── context_builder.py   # Step 3a: format results
│   └── prompts.py           # Step 3d: system prompt
├── core/
│   ├── retrieval.py         # HybridRetriever (reuse existing)
│   └── embedding.py         # EmbeddingProvider (reuse existing)
└── static/
    └── index.html           # Step 5: chat UI

docker-compose.yml           # PostgreSQL + Qdrant + App
requirements.txt
.env.example
```

---

## Execution Order

```
1. docker-compose up (PostgreSQL + Qdrant)
2. python scripts/setup_vf7_db.py (create tables + seed VF7 data)
3. python scripts/setup_vf7_qdrant.py (create collection + ingest chunks)
4. uvicorn app.main:app (start server)
5. Open http://localhost:8000 (chat UI)
```

## Validation

Test queries:
1. "VF 7 giá bao nhiêu?" → get_price → 3 versions with prices (LLM KHÔNG biết giá trước)
2. "VF 7 Plus công suất bao nhiêu?" → get_specs → 201kW (1 motor)
3. "VF 7 có mấy màu?" → search_knowledge_base → 5 colors
4. "VF 7 quãng đường đi được bao xa?" → get_specs → 498km Eco, 504km Plus
5. "VF 7 có tính năng gì?" → search_knowledge_base → ADAS list
6. "So sánh VF 7 Eco và Plus" → get_price×2 + get_specs×2 → comparison table
7. "Lái thử VF 7 có mất phí không?" → search_knowledge_base (FAQ) → "Miễn phí"
8. "Điều kiện bảo hành VF 7?" → search_knowledge_base (FAQ) → "7 năm/160.000 km"
9. "Tôi có được huỷ cọc không?" → search_knowledge_base (FAQ) → "Cọc trước: được. Cọc cam kết: không."
