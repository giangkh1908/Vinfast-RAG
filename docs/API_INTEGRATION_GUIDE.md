# ViVu VinFast AI Assistant — API Integration Guide (Dành cho Frontend & Mobile)

Tài liệu này cung cấp chi tiết toàn bộ các Endpoint REST API, Server-Sent Events (SSE), kiểu dữ liệu Request/Response, mã lỗi, và mã mẫu tích hợp (TypeScript / React) cho đội ngũ Frontend.

---

## 1. Thông Tin Chung & Cấu Hình

- **Base URL (Development):** `http://localhost:8000`
- **Interactive Swagger UI:** `http://localhost:8000/docs`
- **ReDoc Interactive Docs:** `http://localhost:8000/redoc`
- **CORS:** Đã kích hoạt cho tất cả các domain (`allow_origins=["*"]`).
- **Rate Limit:** 30 requests/phút mỗi IP (cho Client chat).

---

## 2. Nhóm Endpoint Health & Readiness Probes

### 2.1. Fast Liveness Probe (`GET /healthz`)
- **Mục đích:** Dùng cho Load Balancer / Kubernetes / Cloudflare kiểm tra server còn sống (<1ms).
- **Response `200 OK`:**
```json
{
  "status": "alive"
}
```

### 2.2. Deep Readiness Probe (`GET /ready`)
- **Mục đích:** Kiểm tra toàn diện kết nối hạ tầng Cloud (PostgreSQL pool, Qdrant Cloud, Upstash Redis, LLM API Keys).
- **Response `200 OK`:**
```json
{
  "status": "ready",
  "app_version": "1.0.0",
  "checks": {
    "postgres_pool": { "status": "ok", "pool": { "size": 5, "free": 5 } },
    "qdrant_cloud": { "status": "ok", "collections": ["vivu_product_info", "vivu_policy"] },
    "redis_cache": { "status": "ok", "cache_enabled": true },
    "llm_credentials": { "status": "ok", "provider": "deepinfra" }
  }
}
```

---

## 3. Nhóm Endpoint Chatbot (Dành cho Người Dùng Cuối)

### 3.1. Chat Streaming (`POST /api/chat/stream`) — *Khuyên dùng cho Chat UI*

Nhận câu trả lời thời gian thực qua Server-Sent Events (SSE).

- **Request Headers:**
  - `Content-Type: application/json`
  - `Accept: text/event-stream`

- **Request Body (JSON):**
```json
{
  "message": "VF 8 Plus pin bao nhiêu kWh?",
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "message_id": "msg_001",
  "history": [
    { "role": "user", "content": "Xin chào" },
    { "role": "assistant", "content": "Xin chào Quý khách! ViVu có thể hỗ trợ gì ạ?" }
  ]
}
```

#### Cấu Trúc Các Sự Kiện SSE (Event Stream Chunks):

| SSE Event Type | Dữ liệu `event.content` | Ý nghĩa / Hướng dẫn FE render |
|---|---|---|
| `classify` | `{"intent": "specs", "entities": {"model_code": "VF 8", "version": "Plus"}}` | Phân loại intent và thông tin trích xuất. |
| `tool_call` | `{"tool": "get_specs", "args": {"model_code": "VF 8"}}` | Hiển thị trạng thái "Đang tra cứu dữ liệu...". |
| `token` | `"VF 8 Plus có dung lượng pin là "` | Từng từ/token sinh ra — FE append vào khung chat. |
| `decision` | `"answer"` \| `"clarify"` \| `"out_of_scope"` | Phân loại quyết định của Agent. |
| `done` | `{"status": "completed"}` | Kết thúc stream. |
| `error` | `{"error": "Chi tiết lỗi"}` | Báo lỗi khi xử lý. |

---

### 3.2. Chat Non-Streaming (`POST /api/chat`)

Dùng cho tích hợp nhanh (Webhook / Test API).

- **Request Body:** Giống `POST /api/chat/stream`.
- **Response `200 OK` (JSON):**
```json
{
  "response": "VF 8 Plus trang bị pin dung lượng khả dụng 87.7 kWh, cho quãng đường di chuyển khoảng 457 km sau một lần sạc đầy (chuẩn WLTP).",
  "needs_clarification": false,
  "decision": "answer",
  "classify": {
    "entities": { "model_code": "VF 8", "version": "Plus", "intent": "specs" }
  },
  "decision_log": {}
}
```

---

## 4. Nhóm Endpoint Admin Telemetry & Metrics (Dashboard Giám Sát Chi Phí & Latency)

> 💡 **Lưu ý:** Mặc định hệ thống mở trực tiếp cho Frontend gọi API lấy dữ liệu ngay. Nếu Backend cấu hình `ADMIN_API_KEY` trong `.env` thì mới cần truyền thêm Header `X-Admin-Key`.

### 4.1. Tổng quan KPI (`GET /api/admin/metrics/overview?hours=24`)
- **Header:** Không bắt buộc (hoặc truyền `X-Admin-Key` nếu có)
- **Query Params:** `hours` (mặc định: 24)
- **Response `200 OK`:**

```json
{
  "status": "success",
  "window_hours": 24,
  "total_requests": 1420,
  "successful_requests": 1410,
  "failed_requests": 10,
  "error_rate_pct": 0.7,
  "tokens": {
    "prompt_tokens": 1250000,
    "completion_tokens": 480000,
    "total_tokens": 1730000
  },
  "costs": {
    "total_cost_usd": 0.3094,
    "total_cost_vnd": 7858.76
  },
  "latency_ms": {
    "avg": 820,
    "p50": 650,
    "p95": 1450,
    "p99": 2100
  },
  "ttft_ms": {
    "avg": 240,
    "p50": 190,
    "p95": 420
  },
  "caching": {
    "cache_hits": 450,
    "cache_hit_rate_pct": 31.69
  }
}
```

---

### 4.2. Dữ liệu vẽ biểu đồ chuỗi thời gian (`GET /api/admin/metrics/timeseries?hours=24`)
- **Response `200 OK`:**
```json
{
  "status": "success",
  "points": [
    {
      "bucket": "2026-08-18T10:00:00+00:00",
      "requests": 85,
      "avg_latency_ms": 610,
      "avg_ttft_ms": 180,
      "total_tokens": 110500,
      "cost_vnd": 512.4,
      "cache_hits": 28
    }
  ]
}
```

---

### 4.3. Phân bổ Ý định người dùng (`GET /api/admin/metrics/intents?hours=168`)
- **Response `200 OK`:**
```json
{
  "status": "success",
  "intents": [
    { "intent": "specs", "count": 680, "percentage": 47.89 },
    { "intent": "price", "count": 390, "percentage": 27.46 },
    { "intent": "compare", "count": 180, "percentage": 12.68 },
    { "intent": "policy", "count": 110, "percentage": 7.75 },
    { "intent": "out_of_scope", "count": 60, "percentage": 4.22 }
  ]
}
```

---

### 4.4. Lịch sử Request Logs có phân trang (`GET /api/admin/metrics/logs`)
- **Query Params:** `limit=50&offset=0&intent=specs&cache_only=false`
- **Response `200 OK`:**
```json
{
  "total": 1420,
  "limit": 50,
  "offset": 0,
  "logs": [
    {
      "id": 1,
      "request_id": "req_abc123",
      "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "created_at": "2026-08-18T12:00:00Z",
      "query_text": "VF 8 Plus pin bao nhiêu kWh?",
      "intent": "specs",
      "decision": "answer",
      "model_used": "deepseek/deepseek-chat",
      "prompt_version": "v1.0.0",
      "prompt_tokens": 850,
      "completion_tokens": 120,
      "total_tokens": 970,
      "cost_usd": 0.000152,
      "cost_vnd": 3.86,
      "ttft_ms": 195,
      "total_latency_ms": 720,
      "cache_hit": false,
      "cache_type": "none",
      "tools_used": ["get_specs"],
      "status_code": 200,
      "error_message": null
    }
  ]
}
```

---

## 5. Nhóm Endpoint Admin Quản Lý Prompt (Prompt Registry & Live Versioning)

> 💡 **Lưu ý:** Mặc định mở trực tiếp cho Frontend gọi. Chỉ yêu cầu Header `X-Admin-Key` khi có cấu hình `ADMIN_API_KEY` trong `.env`.

### 5.1. Xem các phiên bản đang Active (`GET /api/admin/prompts/active`)

```json
{
  "status": "success",
  "active_versions": {
    "system": "v1.0.0",
    "synthesize": "v1.0.0",
    "classify": "v1.0.0",
    "summarize": "v1.0.0"
  }
}
```

### 5.2. Kích hoạt phiên bản mới Live tức thì (`POST /api/admin/prompts/{prompt_type}/{version}/activate`)
- **Ví dụ:** `POST /api/admin/prompts/system/v1.1.0/activate`
- **Response `200 OK`:**
```json
{
  "status": "activated",
  "message": "Successfully activated system -> v1.1.0"
}
```

### 5.3. Tạo phiên bản prompt mới (`POST /api/admin/prompts`)
```json
{
  "prompt_type": "system",
  "version": "v1.1.0",
  "template": "Bạn là ViVu, chuyên viên tư vấn cao cấp xe VinFast...\n{model_list}",
  "description": "Tối ưu hóa tone giọng ngắn gọn và chuyên nghiệp hơn",
  "author": "admin",
  "set_active": false
}
```

### 5.4. Thử nghiệm Render Template (`POST /api/admin/prompts/test-render`)
```json
{
  "prompt_type": "synthesize",
  "variables": {
    "context": "VF 8 Plus pin 87.7 kWh",
    "query": "VF 8 pin bao nhiêu?"
  }
}
```

---

## 6. Mã Mẫu Tích Hợp SSE Trên React / TypeScript

```typescript
// services/chatService.ts
export async function streamChat({
  message,
  sessionId,
  history,
  onToken,
  onClassify,
  onDone,
  onError,
}: {
  message: string;
  sessionId: string;
  history: Array<{ role: string; content: string }>;
  onToken: (token: string) => void;
  onClassify?: (classifyData: any) => void;
  onDone?: () => void;
  onError?: (err: any) => void;
}) {
  const response = await fetch("http://localhost:8000/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      history,
    }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`HTTP Error ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const event = JSON.parse(line.replace("data: ", ""));
          if (event.type === "token") onToken(event.content);
          else if (event.type === "classify" && onClassify) onClassify(event.content);
          else if (event.type === "done" && onDone) onDone();
          else if (event.type === "error" && onError) onError(event.content);
        } catch (e) {
          console.error("Error parsing SSE event:", e);
        }
      }
    }
  }
}
```
