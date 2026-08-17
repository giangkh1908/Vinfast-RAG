# skills.md — Kiến thức kỹ thuật agent cần áp dụng khi build RAG Chatbot VinFast

File này là tham chiếu kỹ thuật để agent biết **cách** triển khai từng thành phần trong kiến trúc, không chỉ biết pipeline gồm những gì. Cập nhật file này khi có quyết định kỹ thuật mới thay vì để kiến thức nằm rải rác trong hội thoại.

---

## 1. Kiến trúc tổng quan — Agentic RAG

```
User query → Pre-guardrails → Classify → Agent Loop → Synthesize → Post-guardrails → Response
                                    │
                                    ├── Clarify (nếu ambiguous) → chờ user → Classify lại
                                    │
                                    └── LLM function calling → Tools parallel → Evaluate → (loop nếu chưa đủ)
                                                                              │
                                                                              ├── get_price (PostgreSQL)
                                                                              ├── get_active_promotions (PostgreSQL)
                                                                              ├── list_available_models (PostgreSQL)
                                                                              ├── get_utility_link (PostgreSQL)
                                                                              ├── get_maintenance_link (PostgreSQL)
                                                                              └── search_knowledge_base (Qdrant hybrid)
```

**Phân loại dữ liệu — Embed vs Tool:**

| Loại dữ liệu | Lưu trữ | Truy vấn |
|---|---|---|
| Giá bán, phiên bản | PostgreSQL `car_pricing` | Tool `get_price` |
| Khuyến mãi | PostgreSQL `promotion` | Tool `get_active_promotions` |
| Danh mục model | PostgreSQL `car_catalog` | Tool `list_available_models` |
| Link dịch vụ | PostgreSQL `utility_link` | Tool `get_utility_link` |
| Bảo dưỡng links | PostgreSQL `maintenance_link` | Tool `get_maintenance_link` |
| Mô tả sản phẩm, specs brochure | Qdrant `vinfast_kb` (chunk + embed) | Tool `search_knowledge_base` |
| Chính sách, FAQ, hướng dẫn | Qdrant `vinfast_kb` (chunk + embed) | Tool `search_knowledge_base` |

## 2. Embedding

- **Model hiện tại: `paraphrase-multilingual-MiniLM-L12-v2`** (sentence-transformers, chạy local) — 384 dims, hỗ trợ đa ngôn ngữ tốt, tiếng Việt hoạt động ổn, không cần API key.
- Nếu cần chất lượng embedding cao hơn → nâng cấp lên `BGE-M3` (cũng chạy local qua sentence-transformers, nhưng nặng hơn ~2GB RAM).
- Chuẩn hóa văn bản trước khi embed: loại bỏ ký tự thừa, Unicode NFC, không embed cả markdown/HTML tag thô.

## 3. Vector Store — Qdrant

- **Qdrant** với dense + **native sparse vectors** (SparseVectorParams + Modifier.IDF).
- Qdrant tự tính IDF server-side — không cần BM25 index riêng (`sparse.py` đã xóa).
- Dense + sparse chung 1 point, Qdrant tự lo incremental update.
- **Payload schema:**
  ```
  text: string
  source_type: "product_page" | "brochure" | "policy" | "booking_guide" | "maintenance_section"
  model_code: string | null
  section: string | null
  source_url: string
  last_updated: date
  ```
- Hybrid search: `Prefetch(dense) + Prefetch(sparse)` → `FusionQuery(RRF)` → rerank → top-K.

## 4. Tool Functions — Chi tiết

### `search_knowledge_base(query, model_code?, source_type?)`
- Wraps `HybridRetriever.hybrid_search()`
- Optional `source_type` filter → narrower search, less noise
- Max 5 results after rerank
- Confidence threshold: `max(score) >= 0.7` mới coi là đủ

### `get_price(model_code, version?)`
- Query `car_pricing` table
- **BẮT BUỘC** check `model_family` → trả `related_models` (VF8 → VF8_2026)
- Nếu model không có giá → gợi ý `list_available_models`

### `get_active_promotions(model_code?)`
- Query `promotion` WHERE `end_date >= CURRENT_DATE`
- Include cả model-specific AND general (`model_code IS NULL`)

### `get_utility_link(link_type)`
- Query `utility_link` table
- Returns `{url, label}`
- 6 types: onroad_cost, loan_estimate, loan_appraisal, showroom_charging, maintenance_booking, test_drive_booking

### `get_maintenance_link(car_model, year?, section?)`
- Query `maintenance_link` table
- Returns link + section title, KHÔNG trả nội dung chi tiết

### `list_available_models(segment?)`
- Query `car_catalog` table
- Group theo `model_family` → trả `families` dict

## 5. Agent Loop

- **OpenAI function calling** + while loop, max 5 iterations
- Parallel tool execution bằng `asyncio.gather()`
- Luôn gửi full 6 TOOL_SCHEMAS — KHÔNG filter theo intent
- `_is_satisfied()`: check confidence score cho search_knowledge_base, check non-empty cho other tools
- Session context: lưu `model_code` đang trao đổi, inject vào messages

## 6. Classify

- **Regex** cho 8 intent patterns (price, promotion, comparison, link, maintenance, booking)
- Multi-intent: trả `list[str]` — "VF8 giá và khuyến mãi" → `["price", "promotion"]`
- Intent chỉ dùng làm **soft hint** trong prompt, KHÔNG filter tools
- **KHÔNG query DB** — entity disambiguation do tool-level xử lý
- LLM fallback cho ambiguous cases (không regex match)

## 7. Groundedness Check

- **Citation check** (regex): price/promo response phải có URL hoặc ngày
- **Number cross-check**: extract số trong response, so với tool_results ±1% tolerance
- Optional: LLM self-check (config toggle, tốn 1 LLM call)

## 8. Structured Context Builder

- Transform `tool_results` → formatted text cho LLM synthesize
- **MỌI field** trong tool result phải được format (related_models, note, families...)
- Nếu field bị bỏ sót trong context → LLM không biết field tồn tại

## 9. Prompt Structure

```
[System] Vai trò, quy tắc an toàn, giọng văn, tool usage rules
[Session Context] model_code đang quan tâm (nếu có)
[Intent Hints] gợi ý sơ bộ từ classifier (soft hint)
[History] vài lượt hội thoại gần nhất
[Question] câu hỏi hiện tại
```

- `SYNTHESIZE_PROMPT`: "Nếu context có related_models → chủ động đề cập"
- `CLARIFY_PROMPT`: "Tối đa 2 câu hỏi, chỉ hỏi phần thiếu"
- Không dùng few-shot có số liệu cụ thể

## 10. Guardrails

- **Content guardrail:** chặn so sánh tiêu cực, tư vấn tài chính, thông tin nội bộ
- **Injection guardrail:** chặn prompt injection patterns
- **Confidence guardrail:** similarity score < threshold → "không tìm thấy"
- **Groundedness check:** number cross-check cho giá/khuyến mãi

## 11. Evaluation

- **Golden QA set** 30+ cases: single-turn + multi-turn (ellipsis, coreference, negation, multi-intent, clarification)
- Đo: routing accuracy (tool nào được gọi), retrieval accuracy, faithfulness
- Chạy eval lại mỗi khi đổi tool logic, prompt, hoặc embedding model

## 12. Tech stack

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Agent | Agentic RAG thuần (OpenAI function calling + loop) | Không dùng LangGraph |
| Backend | Python + FastAPI | Hệ sinh thái RAG mạnh nhất |
| Embedding | sentence-transformers (local) | paraphrase-multilingual-MiniLM-L12-v2, 384 dims |
| LLM | openai/gpt-4o-mini qua TokenRouter | API key riêng, base URL tùy chỉnh |
| Vector DB | Qdrant | Dense + native sparse (SparseVectorParams + IDF) |
| Reranker | FlashRank (ms-marco-MultiBERT-L-12) | Lightweight ONNX, multilingual |
| Crawl/Parse | Firecrawl | HTML → markdown, PDF → markdown, structured extraction |
| DB | PostgreSQL (Supabase) | car_catalog, car_pricing, promotion, utility_link, maintenance_link |
| Cache | Redis | Cache câu hỏi phổ biến |

*Stack này là điểm khởi đầu — mọi thay đổi (đổi vector DB, đổi LLM provider) phải cập nhật lại file này để agent không dùng thông tin cũ.*
