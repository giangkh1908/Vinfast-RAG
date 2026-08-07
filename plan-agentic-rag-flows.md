# Agentic RAG — 11 Luồng hoạt động chính

>  Mỗi flow bao gồm: components tham gia, tool calls, số LLM interactions, và response format.

---

## Tổng quan kiến trúc

```
User query
    │
    ▼
┌──────────────────────────┐
│  Guardrails (pre-check)  │  ←  ContentGuardrail + InjectionGuardrail
│  content + injection     │
└──────────┬───────────────┘
           │ passed
           ▼
┌──────────────────────────┐
│  Agent Loop              │  ←  thay thế AdaptiveRetriever
│  LLM + 6 tools           │
│  max 5 iterations        │
│  support parallel calls  │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  Guardrails (post-check) │  ← ConfidenceGuardrail
└──────────┬───────────────┘
           │
           ▼
       Response (SSE stream hoặc JSON)
```

**6 tools sau khi merge:**

| # | Tool | Nguồn dữ liệu | Loại |
|---|---|---|---|
| 1 | `search_knowledge_base` | Qdrant (hybrid dense + native sparse IDF, rerank) | RAG |
| 2 | `list_available_models` | PostgreSQL `car_catalog` | DB lookup |
| 3 | `get_price` | PostgreSQL `car_pricing` | DB lookup |
| 4 | `get_active_promotions` | PostgreSQL `promotion` | DB lookup |
| 5 | `get_utility_link` | PostgreSQL `utility_link` | Static link |
| 6 | `get_maintenance_link` | PostgreSQL `maintenance_link` | DB lookup |

---

## Flow A — Giá bán (1 tool call)

**Query mẫu:** "VF8 Plus giá bao nhiêu?"

```
User: "VF8 Plus giá bao nhiêu?"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: giá + VF8 + Plus
  │    → tool_call: get_price({model_code: "VF8", version: "Plus"})
  │
│  Tool get_price:
│    SELECT * FROM car_pricing WHERE model_code='VF8' AND version_name='Plus'
│    → {price_vnd: 1199000000, effective_date: "2026-07-01",
│       source_url: "shop.vinfastauto.com/..."}
│    Check model_family → related: ["VF8_2026"]
│    → {prices: [...], related_models: ["VF8_2026"],
│       note: "Cùng họ VF8: VF8_2026"}
│
│  LLM iteration 2:
│    Tổng hợp từ tool result + system prompt rules
│    BẮT BUỘC kèm nguồn + ngày cập nhật
│    Thấy related_models → chủ động đề cập:
│    "Bạn có muốn xem giá VF8 The All-New 2026 không?"
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "VF8 Plus có giá niêm yết 1.199.000.000 VNĐ.
           Nguồn: shop.vinfastauto.com, cập nhật: 01/07/2026
           Ngoài ra còn có VF8 The All-New 2026, bạn có muốn xem giá không?"

LLM calls: 2 | Tool calls: 1
```

---

## Flow B — So sánh (4 tool calls song song)

**Query mẫu:** "So sánh VF8 và VF9, xe nào phù hợp gia đình hơn?"

```
User: "So sánh VF8 và VF9, xe nào phù hợp gia đình?"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: so sánh 2 model, cần giá + specs cả 2
  │    → 4 tool_calls PARALLEL trong 1 response:
  │
  │    ┌─ get_price({model_code: "VF8"})
  │    ├─ get_price({model_code: "VF9"})
  │    ├─ search_knowledge_base({query: "VF8 không gian gia đình chỗ ngồi cốp",
  │    │                          model_code: "VF8"})
  │    └─ search_knowledge_base({query: "VF9 không gian gia đình chỗ ngồi cốp",
  │                               model_code: "VF9"})
  │
  │  Agent execute PARALLEL (asyncio.gather):
  │    get_price VF8     → [{Eco: 1.059T}, {Plus: 1.199T}]
  │    get_price VF9     → [{Eco: 1.499T}, {Plus: 1.689T}]
  │    search VF8        → [chunk: "SUV 7 chỗ, cốp 423L..."]
  │    search VF9        → [chunk: "SUV 7 chỗ cỡ lớn, cốp 580L..."]
  │
  │  LLM iteration 2:
  │    Tổng hợp so sánh từ 4 kết quả
  │    Đưa gợi ý cụ thể dựa trên số liệu
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "So sánh VF8 vs VF9:
           VF8 Plus: 1.199 tỷ, SUV 7 chỗ, cốp 423L
           VF9 Plus: 1.689 tỷ, SUV 7 chỗ cỡ lớn, cốp 580L
           Với gia đình đông người, VF9 phù hợp hơn..."

LLM calls: 2 | Tool calls: 4 (song song)
Đặc biệt: LLM gọi nhiều tools trong 1 response → Agent execute parallel
```

---

## Flow C — Link tĩnh (1 tool call)

**Query mẫu:** "Tôi muốn xem chi phí lăn bánh VF8 ở Hà Nội"

```
User: "Tôi muốn xem chi phí lăn bánh VF8 ở Hà Nội"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: chi phí lăn bánh → trả link, KHÔNG tự tính
  │    → tool_call: get_utility_link({link_type: "onroad_cost"})
  │
  │  Tool get_utility_link:
  │    SELECT url FROM utility_link WHERE link_type='onroad_cost'
  │    → {url: "https://shop.vinfastauto.com/vn_vi/du-toan-chi-phi-lan-banh",
  │       label: "Dự toán chi phí lăn bánh VinFast"}
  │
  │  LLM iteration 2:
  │    Trả link cho user. KHÔNG tự tính toán.
  │    System prompt enforce: "KHÔNG tự implement công thức"
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "Để xem chi phí lăn bánh VF8 tại Hà Nội:
           🔗 https://shop.vinfastauto.com/vn_vi/du-toan-chi-phi-lan-banh
           Công cụ chính chủ sẽ tính thuế trước bạ, phí đăng ký theo tỉnh bạn chọn."

LLM calls: 2 | Tool calls: 1
Lưu ý: LLM KHÔNG tự tính — system prompt enforce điều này
```

---

## Flow D — Khuyến mãi (1 tool call)

**Query mẫu:** "VF3 đang có khuyến mãi gì không?"

```
User: "VF3 đang có khuyến mãi gì không?"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: khuyến mãi + VF3
  │    → tool_call: get_active_promotions({model_code: "VF3"})
  │
  │  Tool get_active_promotions:
  │    SELECT * FROM promotion
  │    WHERE (model_code='VF3' OR model_code IS NULL)
  │      AND end_date >= CURRENT_DATE
  │    → [
  │        {title: "Ưu đãi mùa hè 2026",
  │         description: "Giảm 30 triệu cho VF3 Plus",
  │         start_date: "2026-07-01", end_date: "2026-08-31"},
  │        {title: "Trợ giá xe cũ đổi mới",
  │         description: "Hỗ trợ 20 triệu khi đổi xe cũ lấy VF3",
  │         start_date: "2026-06-15", end_date: "2026-09-30"}
  │      ]
  │
  │  LLM iteration 2:
  │    Format kèm nguồn + ngày (BẮT BUỘC theo system prompt)
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "VF3 đang có 2 chương trình khuyến mãi:
           1. Ưu đãi mùa hè 2026 (01/07 - 31/08/2026)
              Giảm 30 triệu cho VF3 Plus. Nguồn: vinfastauto.com
           2. Trợ giá xe cũ đổi mới (15/06 - 30/09/2026)
              Hỗ trợ 20 triệu khi đổi xe cũ lấy VF3. Nguồn: vinfastauto.com
           Bạn quan tâm chương trình nào?"

LLM calls: 2 | Tool calls: 1
```

---

## Flow E — RAG thuần (1 tool call)

**Query mẫu:** "VF8 có mấy màu ngoại thất?"

```
User: "VF8 có mấy màu ngoại thất?"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: thông số sản phẩm → search RAG
  │    → tool_call: search_knowledge_base({
  │        query: "VF8 màu ngoại thất",
  │        model_code: "VF8"
  │      })
  │
  │  Tool search_knowledge_base:
│    HybridRetriever.hybrid_search()
│      → dense embedding + Qdrant native sparse (IDF)
│      → RRF fusion → 20 candidates
│      → rerank → top 5
  │    → [chunk: "VF8 có 8 màu ngoại thất: Đen, Trắng,
  │            Xanh dương, Xám, Đỏ, Bạc, Xanh lá, Nâu"]
  │
  │  LLM iteration 2:
  │    Tổng hợp từ retrieved context
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "VF8 có 8 tùy chọn màu ngoại thất:
           Đen, Trắng, Xanh dương, Xám, Đỏ, Bạc, Xanh lá, Nâu.
           Nguồn: vinfastauto.com"

LLM calls: 2 | Tool calls: 1
Đặc biệt: HybridRetriever: dense + Qdrant native sparse + rerank, chỉ wrap thành tool
```

---

## Flow F — Bảo dưỡng chi tiết → trả link (1 tool call)

**Query mẫu:** "Hướng dẫn thay dầu hộp số VF8"

```
User: "Hướng dẫn thay dầu hộp số VF8"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: bảo dưỡng chi tiết → trả link, KHÔNG trả nội dung
  │    → tool_call: get_maintenance_link({
  │        car_model: "VF8",
  │        section: "dau_mo_phu_tung"
  │      })
  │
  │  Tool get_maintenance_link:
  │    SELECT * FROM maintenance_link
  │    WHERE car_model='VF8' AND section_key='dau_mo_phu_tung'
  │    → {section_title: "Dầu mỡ, phụ tùng",
  │       source_url: "https://vinfastauto.com/.../dau-mo"}
  │
  │  LLM iteration 2:
  │    Trả link + tên mục. KHÔNG tóm tắt bước thao tác.
  │    System prompt: "Nội dung gắn chặt với ảnh → trả link gốc"
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "Xem hướng dẫn chi tiết tại:
           🔗 https://vinfastauto.com/.../dau-mo
           Mục: Dầu mỡ, phụ tùng bảo dưỡng
           Hướng dẫn kèm hình ảnh minh họa từng bước.
           Nếu không tự thực hiện, bạn có thể đặt lịch tại xưởng dịch vụ VinFast."

LLM calls: 2 | Tool calls: 1
Lưu ý: Trả LINK, KHÔNG trả nội dung chi tiết (system prompt enforce)
```

---

## Flow G — Bị chặn bởi Guardrails (0 LLM calls)

**Query mẫu:** "Tesla Model Y có tốt hơn VF8 không?"

```
User: "Tesla Model Y có tốt hơn VF8 không?"
  │
  ▼
Guardrails pre-check ─────────────────────────────────────────
  │  ContentGuardrail:
  │    Pattern: "tesla.*tốt hơn" → MATCH
  │    Reason: "Không hỗ trợ so sánh tiêu cực với hãng khác."
  │
  └────────────────────────────────────────────────────────────
  │
  ▼
Response: "Không hỗ trợ so sánh tiêu cực với hãng khác."
           needs_human = true

LLM calls: 0 | Tool calls: 0
Đặc biệt: Chặn TRƯỚC khi vào agent loop — không tốn LLM token
```

---

## Flow H — Ngoài phạm vi, LLM từ chối (1 LLM call, 0 tool calls)

**Query mẫu:** "Thời tiết hôm nay thế nào?"

```
User: "Thời tiết hôm nay thế nào?"
  │
  ▼
Guardrails pre-check → passed ✅ (không violate content rules)
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    Phân tích: câu hỏi không liên quan VinFast
  │    → KHÔNG gọi tool nào
  │    → Trả lời trực tiếp: từ chối lịch sự
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Post-check: no tools called + response chỉ là từ chối → pass ✅

Response: "Xin lỗi, tôi chỉ hỗ trợ tư vấn về xe điện VinFast.
           Bạn có câu hỏi nào về sản phẩm, giá cả, hoặc dịch vụ VinFast không?"

LLM calls: 1 | Tool calls: 0
```

---

## Flow I — Tool trả rỗng, LLM tự fallback chain (3 LLM calls)

**Query mẫu:** "VF10 giá bao nhiêu?" (model không tồn tại)

```
User: "VF10 giá bao nhiêu?"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  LLM iteration 1:
  │    → tool_call: get_price({model_code: "VF10"})
  │    Tool: SELECT ... WHERE model_code='VF10' → [] (empty)
  │    Tool trả: {prices: [], message: "Giá VF10 hiện chưa cập nhật"}
  │
  │  LLM iteration 2:
  │    Nhận thấy VF10 không có giá → TỰ quyết định gọi thêm tool
  │    → tool_call: list_available_models({})
  │    Tool: SELECT * FROM car_catalog
  │    → [{VF3, VF5, VF6, VF7, VF8, VF9}]
  │
  │  LLM iteration 3:
  │    Tổng hợp: VF10 không tồn tại, gợi ý các model có sẵn
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "Hiện tại VinFast chưa có thông tin về VF10.
           Các dòng xe điện hiện có:
           - VF3 (MiniCar)    - VF5 (Crossover)
           - VF6 (Crossover)  - VF7 (SUV)
           - VF8 (SUV)        - VF9 (SUV cao cấp)
           Bạn quan tâm dòng nào?"

LLM calls: 3 | Tool calls: 2
Đặc biệt: LLM TỰ quyết định fallback chain — không cần hardcode logic
```

---

## Flow J — Streaming SSE

**Query mẫu:** Mọi câu hỏi — realtime streaming

```
User: POST /api/chat/stream  "VF8 giá bao nhiêu?"
  │
  ▼
Agent Loop (chạy bình thường, nhưng stream intermediate status)
  │
  │  → event: status    {"message": "Đang tìm giá VF8..."}
  │     Frontend hiển thị loading state
  │
  │  → event: tool_call  {"tool": "get_price", "args": {"model_code": "VF8"}}
  │     Frontend hiển thị "Đang tra cứu giá..."
  │
  │  → event: token     {"token": "VF8 Plus: "}
  │  → event: token     {"token": "1.199.000.000 VNĐ..."}
  │     Streaming text realtime
  │
  │  → event: done      {"sources": [...], "needs_human": false,
  │                       "session_id": "..."}
  │     Stream kết thúc
  │
  ▼
Frontend render đầy đủ response

So với adaptive RAG:
  MỚI: event status    → user biết agent đang làm gì
  MỚI: event tool_call → transparency: tool nào đang được gọi
  GIỮ: event token     → streaming text như cũ
  GIỮ: event done      → final metadata
```

---

## Flow K — Multi-turn conversation (context từ history)

**Query mẫu:** Turn 2 — "Còn VF9 thì sao?" (sau khi đã hỏi giá VF8)

```
Context history:
  Turn 1 - User: "VF8 giá bao nhiêu?"
  Turn 1 - Agent: "VF8 Plus: 1.199 tỷ, Eco: 1.059 tỷ..."
  │
  ▼
User: "Còn VF9 thì sao?" (turn 2)
  │
  ▼
Agent Loop ──────────────────────────────────────────────────────
  │
  │  Agent build messages:
  │    [system_prompt]
  │    [history: User "VF8 giá bao nhiêu?"
  │             Agent "VF8 Plus: 1.199 tỷ..."]
  │    [User: "Còn VF9 thì sao?"]
  │
  │  LLM iteration 1:
  │    Từ context → hiểu "Còn VF9 thì sao?" = hỏi giá VF9
  │    → tool_call: get_price({model_code: "VF9"})
  │    Tool → [{Eco: 1.499T}, {Plus: 1.689T}]
  │
  │  LLM iteration 2:
  │    Tổng hợp, tự động so sánh với VF8 đã hỏi ở turn trước
  │
  └──────────────────────────────────────────────────────────────
  │
  ▼
Response: "VF9 có 2 phiên bản:
           - Eco: 1.499 tỷ
           - Plus: 1.689 tỷ
           So với VF8 Plus (1.199 tỷ), VF9 cao hơn khoảng 300-500 triệu
           tùy phiên bản."

LLM calls: 2 | Tool calls: 1
Đặc biệt: KHÔNG cần rewrite_query() regex — LLM context window xử lý tự nhiên hơn
```

---

## Bảng tổng hợp

| Flow | Query mẫu | LLM calls | Tool calls | Tools dùng | Ghi chú |
|---|---|---|---|---|---|
| **A** | "VF8 Plus giá bao nhiêu?" | 2 | 1 | `get_price` | Price + source + date |
| **B** | "So sánh VF8 và VF9" | 2 | 4 | `get_price` ×2 + `search_knowledge_base` ×2 | Parallel execution |
| **C** | "Chi phí lăn bánh VF8" | 2 | 1 | `get_utility_link` | Trả link, không tính |
| **D** | "VF3 khuyến mãi gì?" | 2 | 1 | `get_active_promotions` | Source + date bắt buộc |
| **E** | "VF8 có mấy màu?" | 2 | 1 | `search_knowledge_base` | RAG: dense+native sparse+rerank |
| **F** | "Thay dầu VF8 hướng dẫn" | 2 | 1 | `get_maintenance_link` | Trả link, không content |
| **G** | "Tesla tốt hơn VF8?" | 0 | 0 | — | Guardrail chặn |
| **H** | "Thời tiết hôm nay?" | 1 | 0 | — | LLM từ chối trực tiếp |
| **I** | "VF10 giá bao nhiêu?" | 3 | 2 | `get_price` → `list_available_models` | LLM tự fallback |
| **J** | Mọi câu (stream) | — | — | — | Thêm event: status, tool_call |
| **K** | "Còn VF9 thì sao?" | 2 | 1 | `get_price` | History context tự resolve |
| **L** | "Tôi muốn mua xe" | 1+1 | 0→1+ | clarify → `get_price` + `search_knowledge_base` | Clarification cycle |

---

## Flow L — Clarification Cycle (classify → clarify → user reply → classify lại)

**Query mẫu:** "Tôi muốn mua xe"

```
Turn 1:
User: "Tôi muốn mua xe"
  │
  ▼
Guardrails pre-check → passed ✅
  │
  ▼
Classify(query="Tôi muốn mua xe", history=[])
  │  Regex: không match pattern nào
  │  LLM fallback: intent=["general"], clarity_score=0.2
  │  missing_fields: ["model", "budget", "use_case"]
  │
  ▼
clarity_score=0.2 < 0.5 → ClarifyNode
  │
  │  LLM: "Bạn quan tâm dòng xe nào và ngân sách dự kiến khoảng bao nhiêu?"
  │
  ▼
Return: response="Bạn quan tâm dòng xe nào...", needs_clarification=true
  │
  ▼
⏸ Graph dừng. Chờ user trả lời.

═══════════════════════════════════════════

Turn 2 (user reply):
User: "VF8, khoảng 1.2 tỷ"
  │
  ▼
Classify(query="VF8, khoảng 1.2 tỷ", history=[turn 1])
  │  Regex: không match (nhưng có model "VF8")
  │  LLM: từ context turn 1 → intent=["price", "general"]
  │  clarity_score=0.8 (có model rõ ràng)
  │  missing_fields: []
  │
  ▼
clarity_score=0.8 >= 0.5 → Agent Loop
  │
  │  LLM iteration 1:
  │    → tool_call: get_price({model_code: "VF8"})
  │    → tool_call: search_knowledge_base({query: "VF8 thông tin tổng quan", model_code: "VF8"})
  │
  │  LLM iteration 2:
  │    Tổng hợp: giá VF8 + thông tin + gợi ý
  │
  ▼
Response: "VF8 có 2 phiên bản:
           - Eco: 1.059 tỷ
           - Plus: 1.199 tỷ
           Phù hợp ngân sách 1.2 tỷ của bạn. SUV 7 chỗ...
           Bạn muốn xem chi tiết phiên bản nào?"

Lần 1: LLM calls: 1 (classify + clarify) | Tool calls: 0
Lần 2: LLM calls: 2 (classify + synthesize) | Tool calls: 2
Tổng: 2 lần tương tác, 3 LLM calls, 2 tool calls
Đặc biệt: LangGraph interrupt + resume — state được preserve qua checkpoint
```

---


