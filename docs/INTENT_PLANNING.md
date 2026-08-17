# Intent Classification & Deterministic Tool Planning

> Kiến trúc quyết định tool: **LLM KHÔNG bao giờ chọn tool / đoán tham số**.
> Lớp rule (regex/keyword) quyết định intent + category/version từ MAP; LLM chỉ
> làm **synthesis** (generate) và **classify fallback** cho case hiếm (strict JSON).

## 1. Vì sao đổi

Lỗi thực tế gặp phải khi để LLM chọn tool:
- `get_specs(category="exterior")` cho "cửa sổ trời" — nhưng `sunroof_type` nằm ở **interior** → miss → "chưa được ghi nhận" dù data có.
- "cửa sổ trời của những xe nào?" → LLM không gọi đủ model → kết luận sai "các xe còn lại chưa có".

**Nguyên tắc mới**: category/version/keys luôn từ **bảng map** (deterministic), không bao giờ do LLM suy đoán.

## 2. Luồng quyết định (hybrid)

```
query
  │
  ▼
classify_node
  ├─ ① Rule intent: classify_intent(query, topic)  → 12 intent (regex/keyword)
  ├─ ② spec_category: extract_spec_category(query) → bảng keyword→category (12 category)
  ├─ ③ spec_key:      extract_spec_key(query)      → bảng keyword→spec_key (feature check)
  ├─ ④ LLM fallback: CHỈ khi intent == "general" và query là câu hỏi thật
  │      → 1 call strict-JSON {intent enum, model, version, category} → VALIDATE → dùng
  └─ ⑤ Thiếu model cần thiết (price/spec/colors) → clarify (KHÔNG chạy tool bừa)
  │
  ▼
build_tool_plan(state)  → [(tool, args)] CHÍNH XÁC   (không có LLM loop chọn tool)
  │
  ▼
direct_fetch_node → chạy plan song song (asyncio.gather) → tool_results
  │
  ▼
generate_node → LLM tổng hợp câu trả lời (vai trò DUY NHẤT của LLM)
```

## 3. Intent taxonomy (12 intent)

| Intent | Pattern (VN) | Plan |
|---|---|---|
| `price` | giá, niêm yết, bao nhiêu tiền | `get_price(model, version)` |
| `spec_query` | công suất, pin, kích thước... (topic/category) | `get_specs(model, version, category)` |
| `feature_presence` | "**có X không/ko?**" | `get_specs(model, version=None, category, keys=[spec_key])` — trả đủ TẤT CẢ phiên bản |
| `cross_model_feature` | "**xe nào có X**" | `get_specs(m, None, category, keys=[spec_key])` × **9 model chính** |
| `compare` | so sánh, vs, hơn kém, hay hơn | `get_specs` × các model trong query (+ get_price nếu hỏi giá) |
| `versions_list` | có mấy phiên bản | `get_price(model)` (trả đủ phiên bản + giá) |
| `models_list` | danh sách xe | `list_available_models()` |
| `colors` | màu sắc | `get_colors(model, version)` |
| `utility` | link, đặt lịch, showroom, trả góp... | link tool theo subtype (7 pattern) |
| `policy` | bảo hành, bảo dưỡng, chính sách, đặt cọc | `search_knowledge_base(query, model)` |
| `general` | còn lại | `search_knowledge_base(query)` (+ LLM fallback classify) |
| `out_of_scope` | chào hỏi, không liên quan | plan rỗng → respond |

## 4. Bảng map spec_category (deterministic)

Trong `app/agent/intent.py` — `_SPEC_CATEGORY_PATTERNS` (~60 pattern, thứ tự ưu tiên pattern cụ thể trước):

| category | keyword ví dụ |
|---|---|
| `battery` | sạc nhanh, dung lượng pin, quãng đường, đi được, range, kwh, 10–70 |
| `powertrain` | công suất, mã lực, mô-men, torque, tăng tốc, 0-100, dẫn động, awd/fwd/rwd |
| `dimension` | kích thước, dài/rộng/cao, khoảng sáng gầm, trục cơ sở, trọng lượng, chỗ ngồi |
| `safety` | túi khí, airbag, phanh, abs, esc, an toàn, camera 360 |
| `interior` | **cửa sổ trời**, kính trần, sunroof, nội thất, ghế, màn hình, loa, điều hòa, HUD |
| `exterior` | ngoại thất, đèn, mâm, la-zăng, gương, kiểu dáng |
| `adas` | adas, cruise, giữ làn, va chạm, aeb, điểm mù, cao tốc |
| `security` | chống trộm, immobilizer, định vị |
| `chassis` | hệ thống treo, khung gầm, đánh lái |
| `None` (không lọc) | tiện nghi, giải trí, kết nối, trợ lý ảo (trải nhiều category — theo prompt rule 5) |

## 5. Bảng map spec_key (feature check)

`_SPEC_KEY_KEYWORDS` — map keyword → **đúng 1 field** cần cho feature_presence/cross_model
(`"cửa sổ trời"→sunroof_type`, `"túi khí"→airbags`, `"công suất"→power_kw`, `"quãng đường"→range_km`, `"ghế da"→leatherette_seats`...).

**Lợi ích**: cross-model context **~40x nhỏ hơn** (380 dòng → ~18 dòng) → giảm cost token + giảm context-rot (chi tiết: docs/LATENCY.md).

⚠️ Lưu ý Python: pattern 1 phần tử phải là tuple `(r"...",)` — thiếu dấu phẩy sẽ iterate từng ký tự (bug đã gặp).

## 6. LLM fallback (hybrid) — khi nào + validate

- **Kích hoạt**: rule intent == "general" VÀ (có model hoặc query ≥ 4 từ)
- **Gọi**: `llm_classify_fallback(query, history)` — 1 call `chat.completions.create` với `response_format={"type":"json_object"}`, max_tokens=150, temperature=0
- **Validate** (`_validate_llm_result`): intent ∈ enum; model_code khớp `MODEL_RE`; category ∈ danh sách — **sai format → bỏ, coi như general** (fail-closed)

## 7. Routing trong graph

- `route_after_classify`: `build_direct_plan(state)` trả plan → `direct_fetch`; None → `build_messages` (LLM loop — **chỉ còn là fallback cuối**, thực tế hiếm chạy)
- `execute_tools` (LLM loop) giữ lại làm safety net, chưa xoá (Phase 4: chặn hẳn khi plan coverage đạt 100% + golden test)

## 8. File

| File | Vai trò |
|---|---|
| `app/agent/intent.py` | intent rules, spec_category/spec_key maps, `classify_intent`, `extract_spec_category`, `extract_spec_key`, `llm_classify_fallback`, `_validate_llm_result` |
| `app/agent/direct_plan.py` | `build_tool_plan(state)` (intent→tool calls), `build_direct_plan` (alias), `needs_kb` |
| `app/agent/nodes/classify.py` | gọi hybrid intent; clarify chỉ khi intent thật sự cần; `spec_category`/`spec_key` vào entities |
| `app/agent/nodes/direct.py` | plan executor (song song) + bỏ qua KB inject khi feature check |
