"""Test ans: cache functionality"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.agent.agent_loop import AgentLoop
from app.core.storage.cache import cache


async def test_cache():
    print("=" * 60)
    print("TEST: ans: cache với single-turn query")
    print("=" * 60)

    # Clean cache trước khi test
    if cache.enabled:
        # Xóa tất cả keys ans:*
        keys = await cache._client.keys("ans:*")
        if keys:
            await cache._client.delete(*keys)
            print(f"✓ Đã xóa {len(keys)} keys cache")
        else:
            print("✓ Cache trống")

    agent = AgentLoop()
    query = "VF 8 giá bao nhiêu?"
    session_id = "test-session-123"

    print(f"\nQuery: {query}")
    print(f"Session: {session_id}")
    print("History: [] (single-turn)")
    print()

    # Lần 1: Cache miss - phải chạy graph
    print("🔄 Lần 1: Chạy query (cache miss)...")
    start = __import__("time").time()
    response1 = await agent.run(query, history=[], session_id=session_id)
    time1 = __import__("time").time() - start
    print(f"✓ Hoàn tất trong {time1:.2f}s")
    print(f"  Response: {response1.response[:100]}...")

    # Kiểm tra cache đã được set chưa
    if cache.enabled:
        keys = await cache._client.keys("ans:*")
        print(f"  Cache keys: {len(keys)}")

    print()

    # Lần 2: Cache hit - phải trả về ngay
    print("🔄 Lần 2: Chạy lại query (cache hit)...")
    start = __import__("time").time()
    response2 = await agent.run(query, history=[], session_id=session_id)
    time2 = __import__("time").time() - start
    print(f"✓ Hoàn tất trong {time2:.2f}s")
    print(f"  Response: {response2.response[:100]}...")

    print()
    print("=" * 60)
    print(f"⏱️  Thời gian: {time1:.2f}s → {time2:.2f}s")
    if time2 < time1 * 0.5:
        print("✅ CACHE HIT: Nhanh hơn nhiều!")
    else:
        print("⚠️  Cache có thể không hoạt động")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_cache())
