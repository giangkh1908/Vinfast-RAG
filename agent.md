# agent.md — Vai trò & cách làm việc của Agent trong dự án RAG Chatbot VinFast

Đây là file cấu hình cho AI coding agent khi được giao build dự án **RAG chatbot tư vấn xe VinFast**. Đọc cùng với `rules.md` (ràng buộc bắt buộc) và `skills.md` (kiến thức chuyên môn áp dụng).

---

## 1. Bối cảnh dự án

Agent đang hỗ trợ build một **Agentic RAG chatbot** trả lời câu hỏi khách hàng về xe VinFast (thông số kỹ thuật, giá, bảo hành, sạc pin, so sánh model), dựa trên dữ liệu nội bộ công ty, cần khả năng scale khi traffic tăng.

**Kiến trúc: Agentic RAG thuần (không LangGraph)**

```
Data Pipeline (Dev 2):                Agent Layer (Dev 1):
  Firecrawl → markdown → chunk          User query → Classify → Agent Loop
  → embed → Qdrant                            │
  → PostgreSQL (car_catalog,                   ├── LLM function calling
    car_pricing, promotion,                    ├── 6 tools (parallel)
    utility_link, maintenance_link)            ├── Evaluate → (retry nếu chưa đủ)
                                               ├── Synthesize (structured context)
Admin Portal (Dev 3):                         └── Groundedness check
  Admin UI → POST endpoints
  → INSERT/UPDATE PostgreSQL             Output: response + sources + needs_human
  Chat frontend (SSE streaming)
```

## 2. Phân công 3 Dev

| Dev | Scope | Files chính |
|---|---|---|
| **Dev 1** | Agent Layer — tools, classifier, agent loop, grounding, prompts, context builder | `app/agent/`, `app/api/chat.py` |
| **Dev 2** | Data Pipeline — Firecrawl, embed, populate PostgreSQL/Qdrant | `app/data/`, `scripts/migrate_*.py` |
| **Dev 3** | Admin Portal + Frontend — UI nhập data, chat frontend | `app/api/admin.py`, `app/static/` |

**Nguyên tắc tránh conflict:**
- Dev 1 KHÔNG đụng `app/data/`, `app/api/admin.py`
- Dev 2 KHÔNG đụng `app/agent/`, `app/api/chat.py`
- Dev 3 KHÔNG đụng `app/agent/`, `app/core/retrieval.py`
- DB schema đã define trong plan — cả 3 dev dùng đúng, đặc biệt cột `model_family` trong `car_catalog`

## 3. Cách tiếp cận một task

Với mỗi task được giao, agent nên theo trình tự:

1. **Xác nhận phạm vi** — task này thuộc Dev nào? Có phụ thuộc vào phần nào chưa hoàn thành không?
2. **Lên kế hoạch ngắn gọn** trước khi viết code — liệt kê file sẽ tạo/sửa
3. **Triển khai theo đơn vị nhỏ** — mỗi lần một thành phần, không gộp nhiều thay đổi cùng lúc
4. **Tự kiểm tra trước khi báo hoàn thành**: chạy thử với ít nhất vài input mẫu
5. **Báo cáo rõ ràng**: đã làm gì, giả định nào đã đặt ra, phần nào cần người review quyết định

## 4. Implementation Plan

Xem chi tiết tại `plan-agentic-rag.md` — chứa đầy đủ:
- Tasks cho cả 3 Dev (A1-A6, B1-B14, C1-C4)
- Full code cho Dev 1 (tools, schemas, agent_loop, classifier, context_builder, grounding, prompts, chat.py wiring, migration script)
- Hướng dẫn cho Dev 2 và Dev 3 (không conflict)
- Timeline 3 tuần
- Golden QA test cases

## 5. Definition of Done

Một task được coi là hoàn thành khi:

- Code chạy được với dữ liệu mẫu thực tế (không chỉ dữ liệu giả lập đơn giản)
- Có test tối thiểu (unit test cho tool functions, hoặc golden QA test cases)
- Không vi phạm điều nào trong `rules.md`
- Có ghi chú ngắn về giả định/giới hạn đã biết (không che giấu nhược điểm)

## 6. Khi nào agent PHẢI dừng lại và hỏi người

- Khi cần đổi lựa chọn kiến trúc cốt lõi (vector DB, embedding model, LLM provider)
- Khi phát hiện dữ liệu nhạy cảm (giá đại lý, chiết khấu nội bộ) có nguy cơ lộ ra qua câu trả lời chatbot
- Khi ước tính chi phí (token, hạ tầng) vượt ngưỡng hợp lý cho một demo/pilot
- Khi yêu cầu của người dùng mâu thuẫn với guardrail đã thống nhất (vd: "bỏ qua kiểm tra nguồn cho nhanh")
