# Thiết kế Cache Redis — BẢN CHỐT (Upstash)

> Trạng thái: provider **CHỐT = Upstash Redis**. Phương án **A (exact-key) ĐÃ CHỐT** — đang implement.
> Phương án **B (semantic cache) = PHASE SAU** — ghi ở mục 13, code sau khi A chạy ổn.

---

## 1. Provider: Upstash Redis (ĐÃ CHỐT)

| Mục | Giá trị |
|---|---|
| Service | Upstash Redis (serverless, TLS) |
| Region | Singapore (~60ms từ VN, hợp stack Neon/Qdrant Cloud) |
| Free tier | 10.000 commands/ngày, 256MB |
| Env | `REDIS_URL=rediss://default:<token>@<region>.upstash.io:6379` |
| Client | `redis` (redis-py) — async: `redis.asyncio.Redis.from_url(REDIS_URL)` |

**Ước lượng command/request** (~10):

```
rl (2: INCR+EXPIRE hoặc 1 Lua) + emb (2: GET+SET) + hs (2: GET/SET)
+ ans (2: GET/SET) + tool:* (1–2) ≈ 10 cmd/request
→ Free 10K/ngày ≈ ~1000 request/ngày — đủ dev/demo.
Nếu cạn: tắt tool:* trước, rồi hs:. (Cần scale → Redis Cloud free 30MB, không giới hạn cmd.)
```

---

## 2. Nguyên tắc bất biến

1. **Version trong key đọc LIVE từ PG** (`ingest_version.is_current`) — không tin env,
   không cần restart khi promote. Bảng này CÓ (`scripts/version_manager.py:112`).
2. Không cache gì không tái tạo được từ nguồn gốc.
3. **Redis down → miss pass-through** (try/except + dead-cooldown 30s), không crash.
4. **TTL phân tầng**: càng gần tiền/giá → TTL càng ngắn.
5. LLM không bao giờ sinh cache key — key từ input có cấu trúc (query chuẩn hoá +
   entities deterministic từ classifier + model + data_version).

---

## 3. Data version (chống stale)

```python
# app/core/cache.py
async def data_version() -> str:
    """SELECT version FROM ingest_version WHERE is_current LIMIT 1.
    Cache in-memory 60s (promote lan toả ≤60s, không restart).
    Fallback: "unknown" (PG unreachable → miss cache, thà chậm hơn stale)."""
```

Promote v3 → ≤60s mọi key sinh `...:v3:...`, key v2 mồ côi chết theo TTL. ✅
Sửa DB tay không bump version → TTL backstop + `cache_admin.py clear` (mục 8).

---

## 4. Cache key

```
ans:  {data_version}:{prompt_hash}:{llm_model}:{sha1(norm_query|entities)}
hs:   {data_version}:{sha1(norm_query)}:{model_id|-}:{top_k}:{skip_rerank}
emb:  {embed_model}:{sha1(normalized_text)}
tool: price:{data_version}:{model|-}:{version|-}
tool: specs:{data_version}:{model}:{version|-}:{keys_hash}
tool: models:{data_version} / colors:{data_version}:{model}
dedup:{sha1(session_id|message_id)}
rl:   s:{session_id}:{window} / ip:{ip}:{window}
```

- `norm_query`: NFC → lowercase → gộp whitespace → bỏ punctuation đầu/cuối →
  chuẩn hoá model "vf8"/"vf-8"/"VF  8" → "vf 8" (tái dùng `classifier.MODEL_RE`).
- `entities`: model_code + version từ `classifier._detect_model`, sort, nối vào key.
- `prompt_hash`: `prompts.get_prompt_hash()` (sha256(SYSTEM_PROMPT)[:12], đã có).
- `llm_model`: từ `llm.get_active_model()` — đổi DeepSeek ↔ Haiku = key mới.

### 4.1. ✅ QUYẾT ĐỊNH: answer cache CHỈ single-turn (history rỗng)

- Summary là LLM-sinh (`summarize_conversation`) → **nondeterministic** → hist_hash không đáng tin.
- **`ans:` chỉ cache khi `history == []`**. Multi-turn → miss, LLM làm việc bình thường.
- Đơn giản, đúng, không bug stale. (Mở rộng hist_hash sau nếu cần — KHÔNG làm bây giờ.)

---

## 5. TTL phân tầng (✅ đề xuất)

| Tầng | Prefix | TTL |
|---|---|---|
| Câu trả lời cuối (single-turn) | `ans:` | 30 phút |
| hybrid_search | `hs:` | 2 giờ |
| Embedding | `emb:` | 7 ngày |
| Giá / khuyến mãi | `tool:price:` | 15 phút |
| Specs / colors / models | `tool:*:` | 24 giờ |
| Dedupe | `dedup:` | 1 giờ |
| Rate limit | `rl:` | theo cửa sổ |

---

## 6. Điểm móc cache vào code thật

| Tầng | Hook | File:function |
|---|---|---|
| `emb:` | đầu `_openrouter_embed(texts)` — pipeline GET từng text, miss SET | `app/core/retrieval.py::_openrouter_embed` |
| `hs:` | đầu `hybrid_search` — hook TRONG hàm để cả tool lẫn direct_fetch ăn | `app/core/retrieval.py::hybrid_search` |
| `ans:` | đầu `run_stream` (nếu history==[]) — hit replay, miss chạy graph, cuối SET | `app/agent/agent_loop.py::run_stream` |
| `tool:*:` | từng tool | `app/agent/tools.py` (get_price/get_specs/get_colors/list_available_models) |
| Rate limit | đầu endpoint | `app/api/chat.py` |
| Dedupe | đầu endpoint | `app/api/chat.py` |

### 6.1. SSE replay khi ans-hit (shape khớp run_stream hiện tại)

```
{"type":"status","content":"Đang tìm câu trả lời…"}
{"type":"answer","content": <response>}
{"type":"sources","content": <formatted sources>}
{"type":"done"}
```

Client chỉ cần `answer + sources + done` → UI y hệt luồng thật. Không phát `tool_call` khi hit.

---

## 7. Rate limit — 2 lớp (không có user auth) ✅

| Lớp | Key | Ngưỡng |
|---|---|---|
| Session | `rl:s:{session_id}:{window}` | 10 msg / 10s |
| IP | `rl:ip:{ip}:{window}` | 30 msg / 60s |

- Token bucket Lua script (1 command/check) — tiết kiệm command Redis.
- Trả **429** + tiếng Việt thân thiện ("Bạn gửi hơi nhanh, chờ vài giây rồi thử lại.").
- IP từ `request.client.host`. Redis down → fail-open (dev tool).

---

## 8. Dedupe message_id ✅

- `ChatRequest` thêm `message_id: str` (uuid, client sinh — frontend `api.ts`).
- `SET dedup:{sha1(session_id|message_id)} 1 NX EX 3600`:
  - OK → request mới, xử lý bình thường.
  - Thất bại → **replay câu cũ** nếu còn trong `ans:` cache, ngược lại **409** "request trùng lặp".
- Bổ sung cho `busyRef` client (chống double-click + retry mạng).

---

## 9. Manual invalidation

`scripts/cache_admin.py` — SCAN + UNLINK (KHÔNG dùng KEYS):

```bash
python scripts/cache_admin.py clear                # xoá toàn bộ ns vivu:*
python scripts/cache_admin.py clear --prefix ans:  # chỉ answer cache
python scripts/cache_admin.py stats                # đếm key theo prefix
```

(Hook vào `version_manager promote` — belt & suspenders, dù version key đã tự xử lý.)

---

## 10. Cấu hình mới

### `.env` (thêm)
```
REDIS_URL=rediss://default:<token>@<region>.upstash.io:6379
CACHE_ENABLED=true
RATE_LIMIT_ENABLED=true
```

### `requirements.txt` (thêm)
```
redis>=5.0
```

---

## 11. Thứ tự implement (ROI ↓)

| # | Nội dung | File |
|---|---|---|
| 1 | `RedisCache` wrapper (get/set/get_or_set, dead-cooldown 30s, safe errors) + `data_version()` + `normalize_query()` + `make_*_key()` | `app/core/cache.py` (mới) |
| 2 | `emb:` | `retrieval.py::_openrouter_embed` |
| 3 | `hs:` | `retrieval.py::hybrid_search` |
| 4 | `ans:` single-turn + SSE replay | `agent_loop.py::run_stream` |
| 5 | Rate limit 2 lớp | `api/chat.py` |
| 6 | Dedupe message_id | `chat.py` + frontend `api.ts` |
| 7 | `tool:*` | `tools.py` |
| 8 | `cache_admin.py` | `scripts/` |
| 9 | Test: hit/miss từng tầng, Redis down, promote → key đổi, 429, dedupe 409 | — |

---

## 13. PHASE SAU: Semantic cache (B) — KHÔNG code bây giờ

Ý tưởng: embed câu hỏi user → so similarity với câu đã cache → cos_sim ≥ ngưỡng → trả output cũ.

**RỦI RO trong domain xe** (embedding gần chữ ≠ cùng nghĩa):
- "VF 8 giá bao nhiêu" vs "VF 8 có cửa sổ trời không" → sim ~0.9 nhưng answer khác hẳn
- "giá VF 8" vs "giá VF 9" / "giá bản Plus" → sim cao nhưng khác giá

**Bắt buộc guard cứng trước khi hit**: entities (model+version) khớp TUYỆT ĐỐI + intent khớp
+ feature keywords khớp + data_version/prompt_hash/llm_model khớp, RỒI MỚI cos_sim ≥ 0.97.
Vector lưu Qdrant collection riêng `vivu_cache` (không brute-force trong Redis — Upstash free
10K cmd/ngày không chịu nổi O(n) scan). Qdrant không TTL native → script dọn entry cũ.

**Khi nào làm**: sau khi A chạy ổn + test ngưỡng/guard trên bộ eval.

---

## 12. Trạng thái quyết định

| Mục | Trạng thái |
|---|---|
| Provider Upstash | ✅ **ĐÃ CHỐT** |
| Phương án A (exact-key) | ✅ **ĐÃ CHỐT** — đang implement |
| Answer cache single-turn | ✅ **ĐÃ CHỐT** |
| TTL (30m/2h/15m/24h/7d) | ✅ **ĐÃ CHỐT** |
| Rate limit (10/10s + 30/60s, 429 fail-open) | ✅ đề xuất — cần OK |
| Dedupe (replay nếu còn cache, ngược lại 409) | ✅ đề xuất — cần OK |
| SSE replay nén (không tool_call khi hit) | ✅ đề xuất — cần OK |
| Semantic cache (B) | ⏸ PHASE SAU |

**Việc của bạn**: tạo Upstash account → tạo database region **Singapore** → dán `REDIS_URL` vào `.env`. Xong OK mấy mục ✅ là tôi code.
