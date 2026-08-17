# Cache System Documentation

## Tổng quan

Hệ thống cache Redis được implement để giảm latency và chi phí API calls cho Vivu chatbot. Sử dụng **Upstash Redis** (REST mode) - serverless, không lo connection bị đóng.

## Kiến trúc

```
┌─────────────────────────────────────────────────────────────┐
│                      User Request                            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Dedupe Check (message_id)                        │
│         - Kiểm tra message đã được xử lý chưa                │
│         - Nếu trùng → trả về 409 hoặc replay cache           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Answer Cache Check (ans:)                        │
│         - Chỉ check nếu history rỗng (single-turn)          │
│         - Nếu hit → replay SSE ngay (50ms)                   │
│         - Nếu miss → tiếp tục xuống dưới                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Tool Execution (có cache riêng)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ get_price    │  │ get_specs    │  │ get_colors   │       │
│  │ (15 phút)    │  │ (24 giờ)     │  │ (24 giờ)     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Hybrid Search (hs: cache - 2 giờ)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Dense Search │  │ Sparse Search│  │   Rerank     │       │
│  │   (Qdrant)   │  │   (Qdrant)   │  │  (DeepInfra) │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Embedding (emb: cache - 7 ngày)                  │
│         - Cache vector embeddings từ OpenRouter              │
│         - Giảm chi phí API calls                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              LLM Generation                                   │
│         - DeepSeek-V3 hoặc Claude-3.5-Haiku                  │
│         - Response được cache vào ans: (nếu single-turn)     │
└─────────────────────────────────────────────────────────────┘
```

## Các tầng Cache

### 1. Answer Cache (ans:)

**Mục đích**: Cache câu trả lời cuối cùng, giảm chi phí LLM calls

**TTL**: 30 phút

**Điều kiện cache**:
- ✅ `history == []` (single-turn only)
- ✅ `session_id` không rỗng
- ✅ `intent` rõ ràng (không phải greeting, clarify, out_of_scope)

**Cache key structure**:
```
ans:{data_version}:{prompt_hash}:{llm_model}:{sha1(entities|normalized_query)}
```

**Ví dụ**:
```
ans:v2:a1b2c3d4e5f6:deepseek-v3:9f8e7d6c5b4a3f2e
```

**Cache value**:
```json
{
  "response": "VF 8 có giá từ 1.2 tỷ VNĐ...",
  "sources": [...],
  "decision": "answer"
}
```

**Tại sao chỉ cache single-turn?**
- Multi-turn có summary do LLM sinh ra → không deterministic
- Context thay đổi theo lịch sử hội thoại
- Tránh trả lời sai ngữ cảnh

### 2. Embedding Cache (emb:)

**Mục đích**: Cache vector embeddings, giảm chi phí OpenRouter API

**TTL**: 7 ngày

**Cache key structure**:
```
emb:{embed_model}:{sha1(text)}
```

**Ví dụ**:
```
emb:openai/text-embedding-3-small:1a2b3c4d5e6f7g8h
```

**Cache value**: Vector embedding (list[float])

**Tại sao cache lâu?**
- Embedding là deterministic (cùng text = cùng vector)
- Ít thay đổi theo thời gian
- Tiết kiệm chi phí đáng kể

### 3. Hybrid Search Cache (hs:)

**Mục đích**: Cache kết quả tìm kiếm từ Qdrant (dense + sparse + rerank)

**TTL**: 2 giờ

**Cache key structure**:
```
hs:{data_version}:{sha1(normalized_query)}:{model_id}:{top_k}:{skip_rerank}
```

**Ví dụ**:
```
hs:v2:abc123def456:VF 8:5:0
```

**Cache value**:
```json
[
  {
    "id": "chunk_id",
    "text": "...",
    "model_id": "VF 8",
    "score": 0.95,
    "source_url": "..."
  }
]
```

**Tại sao cache?**
- Giảm latency đáng kể (dense + sparse + rerank mất ~1-2s)
- Nhiều user hỏi câu tương tự

### 4. Tool Cache (tool:*)

**Mục đích**: Cache kết quả query PostgreSQL

**TTL theo loại**:
- `tool:price:` - **15 phút** (giá biến động)
- `tool:specs:` - **24 giờ**
- `tool:colors:` - **24 giờ**
- `tool:models:` - **24 giờ**

**Cache key structure**:
```
tool:{tool_name}:{data_version}:{sha1(params)}
```

**Ví dụ**:
```
tool:price:v2:abc123 (get_price cho VF 8)
tool:specs:v2:def456 (get_specs cho VF 8, version Eco)
```

**Tại sao giá cache ngắn?**
- Giá có thể thay đổi theo khuyến mãi
- 15 phút là cân bằng giữa freshness và performance

### 5. Dedupe Cache (dedup:)

**Mục đích**: Chống gửi trùng message (double-click, retry)

**TTL**: 1 giờ

**Cache key structure**:
```
dedup:{sha1(session_id|message_id)}
```

**Ví dụ**:
```
dedup:abc123def456ghi789
```

**Cơ chế**:
- Client sinh `message_id` (UUID) cho mỗi message
- Server dùng Redis `SET NX` (atomic) để check
- Nếu key đã tồn tại → trả về 409 "Tin nhắn trùng lặp"
- Nếu key chưa tồn tại → xử lý bình thường

**Ví dụ sử dụng**:
```python
# Frontend
const messageId = crypto.randomUUID();
await fetch('/api/chat', {
  method: 'POST',
  body: JSON.stringify({
    session_id: sessionId,
    message: 'Xin chào',
    message_id: messageId,
    history: []
  })
});

# Backend
if await cache.set_nx_json(dedup_key, {'processed': True}, DEDUP_TTL):
  # Xử lý bình thường
else:
  # Trả về 409 - Tin nhắn trùng lặp
```

## Data Version

**Mục đích**: Đảm bảo cache không trả về data cũ khi data mới được ingest

**Cơ chế**:
- Đọc từ bảng `ingest_version` trong PostgreSQL
- Cache in-memory 60 giây
- Khi promote version mới → cache keys tự động đổi

**Ví dụ**:
```python
# app/core/cache.py
async def data_version() -> str:
    """Đọc version hiện tại từ PostgreSQL"""
    query = "SELECT version FROM ingest_version WHERE is_current = true LIMIT 1"
    # Cache in-memory 60s
    if time.time() - _version_cache_time < 60:
        return _version_cache
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query)
        version = row['version']
        _version_cache = version
        _version_cache_time = time.time()
        return version
```

## Cấu hình

### Biến môi trường (.env)

```bash
# Upstash Redis (REST mode)
REDIS_URL=https://your-instance.upstash.io
REDIS_TOKEN=your-token
CACHE_ENABLED=true
RATE_LIMIT_ENABLED=true
```

### RedisCache Configuration

```python
# app/core/cache.py
class RedisCache:
    def __init__(self):
        # REST mode (Upstash)
        if settings.redis_url and settings.redis_url.startswith('https://'):
            self._client = redis.asyncio.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=5,
                retry_on_timeout=True
            )
        # TCP mode (fallback)
        else:
            self._client = redis.asyncio.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
```

## Monitoring & Troubleshooting

### Log cache hit/miss

```python
# Trong agent_loop.py
logger.info(f"Cache {'hit' if cached else 'miss'} for key: {cache_key}")
```

### Kiểm tra Redis connection

```python
python -c "
from app.core.cache import cache
import asyncio

async def check():
    print(f'Cache enabled: {cache.enabled}')
    print(f'Cache mode: {cache.mode}')
    # Test ping
    await cache._client.ping()
    print('Redis connection OK')

asyncio.run(check())
"
```

### Xem cache keys

```python
# Đếm keys theo prefix
async def count_keys(prefix):
    count = 0
    async for key in cache._client.scan_iter(match=f"{prefix}:*"):
        count += 1
    return count

# Ví dụ
print(f"Answer cache: {await count_keys('ans')} keys")
print(f"Embedding cache: {await count_keys('emb')} keys")
print(f"Hybrid search cache: {await count_keys('hs')} keys")
```

### Xóa cache

```python
# Xóa tất cả keys theo prefix
async def clear_cache(prefix):
    count = 0
    async for key in cache._client.scan_iter(match=f"{prefix}:*"):
        await cache._client.delete(key)
        count += 1
    return count

# Ví dụ: xóa answer cache
deleted = await clear_cache('ans')
print(f"Đã xóa {deleted} answer cache keys")
```

### Troubleshooting

#### Cache không hoạt động

1. Kiểm tra `CACHE_ENABLED=true` trong `.env`
2. Kiểm tra `REDIS_URL` và `REDIS_TOKEN` đúng
3. Test connection:
   ```python
   await cache._client.ping()  # Phải trả về True
   ```

#### Cache hit nhưng trả về data cũ

1. Kiểm tra `data_version()` có trả về version mới không
2. Xóa cache cũ:
   ```python
   await clear_cache('ans')
   await clear_cache('hs')
   ```

#### Redis down → ứng dụng crash

- Hệ thống có fail-safe: nếu Redis error → fallback về no-cache
- Check log: `Redis error (cooldown 30s): ...`
- Ứng dụng vẫn hoạt động bình thường, chỉ không có cache

## Performance Metrics

### Latency (ước tính)

| Tầng cache | Miss (giây) | Hit (giây) | Tiết kiệm |
|------------|-------------|------------|-----------|
| `emb:`     | 0.3         | 0.05       | 83%       |
| `hs:`      | 1.5         | 0.05       | 97%       |
| `tool:price` | 0.1       | 0.05       | 50%       |
| `ans:`     | 6-10        | 0.05       | 99%       |

### Chi phí (ước tính)

Giả sử 1000 requests/ngày, 30% cache hit rate:

| Tầng cache | Chi phí không cache | Chi phí có cache | Tiết kiệm |
|------------|---------------------|------------------|-----------|
| Embedding  | $3/ngày            | $2.1/ngày        | 30%       |
| LLM        | $10/ngày           | $7/ngày          | 30%       |
| **Tổng**   | **$13/ngày**       | **$9.1/ngày**    | **30%**   |

## Best Practices

### ✅ Nên làm

1. **Luôn check cache trước khi gọi API đắt tiền**
   ```python
   cached = await cache.get_json(cache_key)
   if cached:
       return cached
   # Gọi API...
   await cache.set_json(cache_key, result, TTL)
   ```

2. **Dùng data_version trong cache key**
   - Đảm bảo cache không trả về data cũ

3. **Set TTL hợp lý**
   - Price: 15 phút (biến động)
   - Specs/Colors: 24 giờ (ổn định)
   - Embeddings: 7 ngày (rất ổn định)

4. **Handle Redis errors gracefully**
   - Fallback về no-cache khi Redis down
   - Không để cache error làm crash ứng dụng

### ❌ Không nên làm

1. **Không cache multi-turn answers**
   - Context thay đổi theo lịch sử
   - Dễ trả lời sai ngữ cảnh

2. **Không dùng cache key quá dài**
   - Tốn bộ nhớ Redis
   - Dùng hash (sha1) cho params phức tạp

3. **Không cache khi không có session_id**
   - Không thể phân biệt user
   - Dễ cache nhầm data

4. **Không quên cleanup cache cũ**
   - Khi data structure thay đổi
   - Khi migrate version

## Future Enhancements

### Semantic Cache (Phase 2)

- Cache theo ngữ nghĩa thay vì exact match
- Dùng cosine similarity để tìm câu hỏi tương tự
- Giảm cache miss rate cho các câu hỏi tương tự

### Rate Limiting

- Giới hạn số request theo session/IP
- Chống spam và abuse
- Dùng Redis sliding window

### Cache Warming

- Pre-load cache cho các câu hỏi phổ biến
- Giảm latency cho user đầu tiên

### Distributed Cache

- Dùng Redis Cluster cho high availability
- Shard cache theo region/user

---

**Cập nhật lần cuối**: 2026-03-17  
**Version**: 1.0  
**Author**: Vivu Team
