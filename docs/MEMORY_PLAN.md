# Kế hoạch: Multi-turn Memory (Session + Summary + Window)

> Trạng thái: **ĐÃ CHỐT thiết kế** — triển khai theo thứ tự tasks ở cuối.
> Các quyết định đã chốt: session-only (không user auth), messages ở localStorage,
> summary ở DB (Postgres/Neon), window <10 turn, token limits có sẵn.

## 1. Mục tiêu

- Hội thoại multi-turn ổn định, memory **có kiểm soát**: không phình vô hạn, không mất ngữ cảnh quan trọng.
- **Session-based** (không đăng nhập user): 1 session = 1 phiên chat, do client tạo UUID.
- Messages hiển thị: **localStorage client** (tắt web/quay lại vẫn còn, clear session mới mất).
- Summary (trí nhớ nén): **lưu DB server** — client không phải giữ, server chủ động kiểm soát.
- Bảo mật: **sanitize history** chống prompt injection (bắt buộc).

## 2. Kiến trúc tổng

```
┌─ CLIENT ──────────────────────────────────────────────┐
│ localStorage:                                         │
│   vivu_session_id = "uuid-v4"   (tạo 1 lần)            │
│   vivu_history    = [{role, content, ts}, ...]         │
│                                                       │
│ Mỗi turn: gửi {session_id, message, window ≤10 turn}   │
│ UI: hiển thị 7 turn, kéo lên load thêm (slice local)   │
│ "Chat mới" = xoá key + tạo session_id mới              │
└──────────────────────┬────────────────────────────────┘
                       │ POST /api/chat/stream
                       ▼
┌─ BACKEND ─────────────────────────────────────────────┐
│ ① Validate: session_id (uuid) + message ≤1000 token    │
│ ② Sanitize history (chống injection)                  │
│ ③ Đọc summary từ DB (chat_sessions)                    │
│ ④ Build input: system + [summary] + window + query     │
│ ⑤ Window vượt ngưỡng / đủ N turn → summarize → DB      │
│ ⑥ LLM stream (max output 4000) → client                │
│ ⑦ UPSERT DB: turn_count+1, summary mới, last_message   │
└───────────────────────────────────────────────────────┘
```

## 3. API contract

```
POST /api/chat/stream
{
  "session_id": "a1b2c3d4-...",        // bắt buộc, uuid v4 do client tạo
  "message": "giá VF8 bao nhiêu?",      // bắt buộc, ≤1000 token → 400
  "history": [                          // tùy chọn, TỐI ĐA 7 turn gần nhất
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
→ 200 SSE stream (decision, token, tool_call, sources, done)
→ 400: message quá dài / session_id sai format / history quá lớn
```

**Quy ước**: `history` = các turn **đã hoàn thành** (KHÔNG bao gồm `message` đang gửi),
client cắt `history.slice(-14)` (7 turn = 14 message).

## 4. Database — `chat_sessions` ✅ (đã tạo `app/core/session_store.py`)

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_count      INT NOT NULL DEFAULT 0,
    summary         TEXT,                    -- running summary (NULL = chưa có)
    summary_tokens  INT NOT NULL DEFAULT 0,  -- token của summary → tính budget
    last_message    TEXT,
    meta            JSONB
);
CREATE INDEX idx_chat_sessions_updated ON chat_sessions(updated_at);
```

Thao tác/request: `get_session()` (1 SELECT) + `touch_session()` (1 UPSERT) ≈ 1–3ms.

## 5. Pipeline xử lý request (chi tiết)

### ① Validate
- `session_id`: `uuid.UUID()` → sai format trả 400 (đã có `parse_session_id`)
- `message`: `estimate_tokens() > 1000` → 400 "Câu hỏi quá dài" (đã có ở `chat.py`)
- `history`: tổng token > 30.000 → 400 (defense in depth, tránh request khổng lồ)

### ② Sanitize history — `sanitize_history()` (module mới, BẮT BUỘC)
```
Input: [{role, content}, ...] từ client (KHÔNG TIN TƯỞNG)
- Lọc: chỉ giữ role ∈ {user, assistant}; bỏ role khác (system, tool, ...)
       → chặn prompt injection qua role="system"
- Ép xen kẽ: bắt đầu = user, kết thúc = assistant, user→assistant luân phiên
       → cắt assistant lẻ đầu, bỏ user trùng liên tiếp, cắt user cuối chưa có reply
- Cap từng message: content ≤ 4000 ký tự (cắt đuôi + đánh dấu)
- Cap tổng: ≤ 30.000 token (đã check ở ①, đây là lớp 2)
Output: list message hợp lệ, sẵn sàng đưa vào prompt
```

### ③ Đọc summary
```
summary, summary_tokens = get_session(session_id)  # {} nếu session mới
```

### ④ Build input
```
messages = [
  system: system_prompt + ("\n\n[Tóm tắt hội thoại trước]: " + summary nếu có)
  ...history đã sanitize (window = 7 turn)
  user: query  (context RAG được chèn ở node generate — phase sau)
]
→ truncate_messages(messages, INPUT_MAX_TOKENS=16000)  # backstop đã có
```

### ⑤ Summarize — node `summarize` (module mới)
```
Kích hoạt khi: (turn_count % 7 == 0) HOẶC window token > 6000
Input:  [summary cũ (nếu có)] + [toàn bộ window vừa nhận]
Prompt: "Tóm tắt/ghi tiếp hội thoại. Đặc biệt giữ: model xe đang quan tâm,
         phiên bản, tầm giá, câu hỏi chưa được trả lời."
Output: summary mới (max_tokens=256, dùng stream_chat_with_fallback với writer=None)
→ Lưu vào DB qua update_summary(summary, summary_tokens) — KHÔNG tăng turn_count
```
Vì client chỉ gửi window = 7 turn, và summarize chạy **đúng vào biên 7 turn**,
summary luôn "bắt kịp" phần history vừa rời khỏi window → **không mất thông tin tích lũy**.

### ⑥ LLM stream
- `max_tokens=4000` (đã có), tool call `max_tokens=1024` (đã có)

### ⑦ Write back
```
touch_session(session_id, turn_count+1, summary mới nếu có, last_message=message)
```

## 6. Token budget tổng (đã có, chỉ đọc lại)

| Thành phần | Budget |
|---|---|
| User message | ≤1000 (reject 400) |
| Summary | ~256 |
| Window (7 turn thực tế ~2.1K token) | ≤6000 |
| System prompt | ~970 |
| **Tổng input** | ≤16000 (backstop) |
| Output | ≤4000 |

## 7. Edge cases

| Case | Xử lý |
|---|---|
| Session mới (chưa có row) | `touch_session` INSERT tự tạo |
| History rỗng | Build không có window, vẫn chạy bình thường |
| Turn lẻ / xen kẽ sai | Sanitize cắt cho đúng user→assistant |
| Client gửi role="system" | Sanitize **bỏ** — chống injection |
| localStorage mất nhưng session còn | Gửi window rỗng → server vẫn có summary → trả lời được (không lỗi) |
| "Chat mới" | Client tạo UUID mới → DB row mới |
| Session chết | `cleanup_stale_sessions(30 ngày)` chạy định kỳ |
| 2 request cùng session song song | Hiếm (client disable nút); UPSERT atomic, LWW chấp nhận |

## 8. Trách nhiệm Frontend (phase sau — ghi rõ để không quên)

- localStorage: `vivu_session_id` + `vivu_history`
- Gửi window: `history.slice(-14)` (7 turn = 14 message)
- Pagination: hiển thị 7 turn, kéo lên load thêm từ mảng local (không gọi API)
- Race: `isLoadingOlder` lock, dedupe message id, không auto-scroll khi user đang đọc history cũ
- Clear chat: xoá 2 key + tạo session_id mới

## 9. Thứ tự triển khai

| # | Task | File | Phụ thuộc |
|---|------|------|-----------|
| 1 | ✅ `session_store.py` (DB + CRUD + cleanup) | `app/core/session_store.py` | — |
| 2 | ✅ `sanitize_history()` module | `app/agent/history.py` | — |
| 3 | ✅ Wire API: `ChatRequest.session_id` + validate + `get_session`/`touch_session` | `app/api/chat.py`, `app/agent/agent_loop.py` | 1, 2 |
| 4 | ✅ Memory builder: inject summary vào system + window | `app/agent/nodes/messages.py`, `app/agent/prompts.py` | 3 |
| 5 | ✅ Node summarize (biên 7 turn + ngưỡng 6000) | `app/agent/nodes/summarize.py` | 4 |
| 6 | ✅ Test E2E: 8 turn, injection, 400, stream — TẤT CẢ PASS | `tests/` + script tạm | 5 |
| 7 | ✅ Frontend: React+TS (localStorage session + SSE + StatusBar + markdown) | `frontend/` → build `app/static` | 6 |

## Ghi chú bug đã fix trong quá trình test

- **`touch_session` ghi đè `summary_tokens` về 0**: UPSERT dùng `COALESCE(EXCLUDED.summary_tokens, ...)` nhưng 0 không phải NULL → mỗi turn ghi đè. **Fix**: tách trách nhiệm — `touch_session` chỉ lo turn_count/last_message, `update_summary` độc quyền cột summary.
- **Pagination (task 7 cũ)**: history nằm localStorage nên UI hiện toàn bộ; "load thêm khi kéo lên" chỉ cần khi >50 message — để sau.

## 10. Câu hỏi mở (chờ bạn chốt khi code)

- `SUMMARY_EVERY = 7` turn và ngưỡng `6000` token — giữ hay chỉnh?
- Summary prompt: có cần giữ thêm "sở thích người dùng" ngoài 4 trường xe (model, phiên bản, giá, câu hỏi dở)?
