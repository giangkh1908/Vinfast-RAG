# Kế hoạch: Frontend Chat (React + TypeScript) + Fix trạng thái "đang chờ"

> Quyết định: **giữ SSE** (backend không đổi), build lại frontend bằng **React + TS + Vite**,
> serve qua FastAPI (mount thư mục build). Phần "action khi chờ trả lời" được thiết kế lại theo
> research dưới đây.

## 1. Research: UX "đang chờ trả lời" các bên làm thế nào

| Nguồn | Cách làm |
|---|---|
| **ChatGPT / Claude.ai** | Stream text **ngay khi token đầu tiên chảy** → user thấy câu trả lời đang sinh (không có dots giả). Có nút **"Stop generating"** khi đang stream. Lỗi hiện rõ + nút retry |
| **Vercel AI SDK** (`useChat`) | State machine rõ: `isLoading`, `stop()`, `error`. Typing indicator chỉ hiển thị **trước token đầu**, khi có token thì thay bằng text stream |
| **Agent UIs (LangGraph/OpenAI Agents)** | Hiện **status theo bước agent**: "Đang tra cứu dữ liệu…", "Đang gọi tool…" — không để user nhìn dots mù |
| **Intercom / Crisp** | Typing indicator + trạng thái rõ, chống gửi trùng, giữ scroll khi đọc history cũ |

**Kết luận rút ra**:
1. Typing dots chỉ dùng **trước token đầu tiên** — khi stream chảy thì hiện text
2. Hiển thị **status thật từ server** (server đã gửi `{"type":"status","content":"Đang tra cứu dữ liệu…"}` mà frontend cũ **bỏ qua**)
3. Có nút **Stop/Cancel** (AbortController)
4. **Xử lý lỗi đủ 3 tầng**: HTTP 4xx (detail từ server), network error, `error` event giữa stream
5. Chống **double-submit** (Enter spam) — frontend cũ bị
6. **Auto-scroll có điều kiện** — chỉ khi user ở gần đáy
7. Lưu session + history vào localStorage (đã chốt), không mất khi reload

## 2. Lỗi cụ thể của `index.html` hiện tại

| # | Lỗi | Hậu quả |
|---|-----|---------|
| 1 | **Không check `res.ok`** — 400/422 bị nuốt, mất detail | Message quá dài / thiếu session_id → lỗi mơ hồ |
| 2 | **`btn.disabled` nhưng Enter vẫn gọi `send()`** | Spam Enter → nhiều request song song → race |
| 3 | **Bỏ qua event `status`** ("Đang tra cứu dữ liệu…") | User thấy dots 10–20s vô nghĩa khi tool chạy |
| 4 | **Bỏ qua event `error`** (lỗi giữa stream) | Graph lỗi → chat im lặng, không báo |
| 5 | **`tool_call` hiện thành dòng "🔧 tên_tool"** | Rác UI cho user cuối |
| 6 | **Không có nút Stop** | Không huỷ được request dài |
| 7 | **Không gửi `session_id`** | ❌ Backend mới BẮT BUỘC → frontend hiện tại **sẽ 422** |
| 8 | **Không localStorage** | Reload mất hết history |
| 9 | **Scroll luôn xuống đáy** | User đọc history cũ bị giật |
| 10 | **Không markdown** | Bảng so sánh hiện text thô |

## 3. Kiến trúc đề xuất

```
frontend/                          # React + TS + Vite (node 22 có sẵn)
├── package.json  vite.config.ts  tsconfig.json
├── index.html                     # entry Vite
└── src/
    ├── main.tsx  App.tsx
    ├── types.ts                   # ChatRequest, StreamEvent (union), Message, Source
    ├── api.ts                     # streamChat(): fetch SSE + AbortController + res.ok
    ├── session.ts                 # session_id + history (localStorage)
    ├── hooks/useChat.ts           # state machine: idle→sending→streaming→done|error
    └── components/
        ├── ChatPanel.tsx  MessageBubble.tsx  TypingIndicator.tsx
        ├── StatusBar.tsx          # "Đang tra cứu dữ liệu…" / "Đang soạn câu trả lời…"
        ├── StopButton.tsx  SourcesBox.tsx  InputBar.tsx

Build → dist/ → FastAPI mount (thay StaticFiles dir = frontend/dist)
```

### State machine (useChat)

```
idle ──send──▶ sending ──token đầu──▶ streaming ──done──▶ idle
 │                │  (dots + status)    │  (hiện text)   │
 │                ▼                     ▼                ▼
 │           lỗi 4xx/network ──▶ error ◀──stop (Abort)──┘
 │                │                     │
 └──retry/clear───┘                     └── show error + "Thử lại"
```

### Message client-side

```ts
interface Message {
  id: string;                          // uuid — dedupe/render (React key)
  role: 'user' | 'assistant';
  content: string;
  status: 'sending' | 'streaming' | 'done' | 'error';
  error?: string;
  sources?: Source[];
  toolCalls?: string[];                // debug (ẩn mặc định)
}
```

### Xử lý event stream (types.ts)

```ts
type StreamEvent =
  | { type: 'decision'; content: string }
  | { type: 'classify';  content: unknown }
  | { type: 'status';    content: string }        // ← dùng cho StatusBar
  | { type: 'tool_call'; content: { tool: string; success: boolean } }
  | { type: 'token';     content: string }
  | { type: 'answer' | 'clarify'; content: string }
  | { type: 'sources';   content: Source[] }
  | { type: 'error';     content: string }        // ← hiện rõ, không bỏ qua
  | { type: 'ping' } | { type: 'done' };
```

### Session + history (đã chốt ở MEMORY_PLAN)

```ts
session.ts:
  getSessionId()  // vivu_session_id — tạo uuid nếu chưa có
  pushMessage(role, content)   // vivu_history
  getWindow()     // history.slice(-14) = 7 turn
  clearSession()  // "Chat mới": xoá + tạo session_id mới
```

## 4. Hành vi "đang chờ" sau khi fix (chi tiết)

```
User gửi câu hỏi
  → Input disabled (Enter cũng chặn), hiện typing dots + "Đang phân tích câu hỏi…"
  → Server gửi {status: "Đang tra cứu dữ liệu…"} → StatusBar đổi text (thay dots)
  → tool_call → StatusBar đổi text theo BẢN ĐỒ THÂN THIỆN (KHÔNG bao giờ hiện tên tool)
  → token đầu tiên → bỏ dots/status, stream text hiện dần
  → done → dừng, hiện SourcesBox, input bật lại
  → Có nút ⏹ Stop suốt quá trình → abort request (server vẫn hoàn tất turn — vô hại)
  → Lỗi: 400 → hiện detail server; network → "Mất kết nối" + nút Thử lại; error event → hiện content
```

### Tool call → StatusBar thân thiện (KHÔNG hiện tên tool)

Nguyên tắc: user chỉ quan tâm TIẾN ĐỘ, không quan tâm tên kỹ thuật.
Frontend map `tool` → label dễ hiểu (1 nơi duy nhất, backend không đổi):

```ts
const TOOL_LABELS: Record<string, string> = {
  get_price:             "Đang tra cứu giá xe…",
  get_specs:             "Đang tra cứu thông số kỹ thuật…",
  get_colors:            "Đang tra cứu màu sắc…",
  list_available_models: "Đang tải danh sách xe…",
  search_knowledge_base: "Đang tra cứu dữ liệu…",
  ask_clarification:     "Đang làm rõ câu hỏi…",
};
// fallback: "Đang tra cứu dữ liệu…" — không hiện tên tool lạ
```

StatusBar hiển thị: `🔍 {label}` — nhỏ, không phải message, tự biến mất khi token chảy.

## 5. Thứ tự triển khai

| # | Task | Trạng thái |
|---|------|-----------|
| 1 | Scaffold `frontend/` (Vite + React + TS + react-markdown) | ✅ |
| 2 | `types.ts` + `session.ts` (localStorage) | ✅ |
| 3 | `api.ts`: streamChat với `res.ok` check, AbortController, parse SSE | ✅ |
| 4 | `useChat.ts`: state machine + chặn Enter spam + Stop + retry | ✅ |
| 5 | Components: StatusBar (label thân thiện), StopButton, MessageBubble, SourcesBox | ✅ |
| 6 | Markdown render (react-markdown + rehype-sanitize) | ✅ |
| 7 | Scroll có điều kiện (chỉ auto khi ở gần đáy) | ✅ |
| 8 | Clear chat + "Chat mới" + localStorage | ✅ |
| 9 | Pagination: hiển thị 7 turn, kéo lên load thêm (slice local) | ⏳ (xem ghi chú) |
| 10 | Build + mount vào FastAPI + E2E test | ✅ (serve + API OK; UI cần mở browser verify) |

> Ghi chú task 9: history toàn bộ nằm localStorage — UI hiện toàn bộ (không giới hạn 7 turn hiển thị).
> "Load thêm khi kéo lên" chỉ thực sự cần khi render hơn ~50 message; để sau khi widget hoàn thiện.

## 6. Chạy thử

```bash
# Dev (cần backend chạy cùng — đổi port proxy trong vite.config.ts nếu cần):
cd frontend && npm run dev        # http://localhost:5173

# Production: build thẳng vào app/static (FastAPI serve sẵn):
cd frontend && npm run build
PYTHONUTF8=1 .venv/Scripts/python -m uvicorn app.main:app --port 8000
# mở http://localhost:8000
```

## 7. Bug đã fix sau khi build

- **Duplicate "..."**: assistant bubble + StatusBar cùng hiện dots → bỏ dots khỏi bubble, StatusBar là nơi duy nhất.
- **Stream "dừng giữa chừng"**: `busy` check dùng closure stale → Enter+click cùng tick gửi 2 request, token chia 2 bubble → thêm `busyRef` (guard đồng bộ).
- **Assistant không lưu localStorage**: `updateLastAssistant` chỉ update nếu đã có assistant trong storage → dùng `contentRef` + push đúng 1 lần ở done/stop; `pushMessage` nhận id khớp state để retry xoá đúng.
- **Side-effect trong setState updater** (StrictMode dev double-invoke) → đưa mọi localStorage write ra ngoài updater.

## 6. Câu hỏi mở (đã chốt)

- ✅ Tool call: StatusBar hiện label thân thiện, không tên tool
- ✅ Markdown: **render đầy đủ** (react-markdown + rehype-sanitize)
- ✅ message_id / dedupe retry: **để phase Redis** (frontend chưa gửi, contract bổ sung sau)
