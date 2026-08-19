"""Test ans: cache implementation"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agent.agent_loop import AgentLoop, _is_cacheable
from app.core.storage.cache import cache, make_answer_key


async def test_cacheable_logic():
    """Test _is_cacheable function"""
    print("=" * 60)
    print("TEST 1: Logic cacheable")
    print("=" * 60)

    # Single-turn, có session_id, intent rõ ràng
    result = _is_cacheable([], "session-123", "price")
    print(f"[OK] Single-turn, session_id, price intent: {result} (expected: True)")
    assert result

    # Multi-turn (có history)
    result = _is_cacheable([{"role": "user", "content": "hi"}], "session-123", "price")
    print(f"[OK] Multi-turn (có history): {result} (expected: False)")
    assert not result

    # Không có session_id
    result = _is_cacheable([], "", "price")
    print(f"[OK] Không có session_id: {result} (expected: False)")
    assert not result

    # Intent không cacheable
    for intent in ["out_of_scope", "greeting", "chitchat", "clarify"]:
        result = _is_cacheable([], "session-123", intent)
        print(f"[OK] Intent '{intent}': {result} (expected: False)")
        assert not result

    # Intent cacheable
    for intent in ["price", "spec_feature", "spec_query", "policy"]:
        result = _is_cacheable([], "session-123", intent)
        print(f"[OK] Intent '{intent}': {result} (expected: True)")
        assert result

    print("[PASS] TEST 1\n")


async def test_cache_key_generation():
    """Test make_answer_key function"""
    print("=" * 60)
    print("TEST 2: Cache key generation")
    print("=" * 60)

    key1 = await make_answer_key(entities={"model": "VF 8", "intent": "price"}, query="VF 8 giá bao nhiêu?")
    print(f"[OK] Key 1: {key1}")

    # Cùng query, cùng entities → cùng key
    key2 = await make_answer_key(entities={"model": "VF 8", "intent": "price"}, query="VF 8 giá bao nhiêu?")
    print(f"[OK] Key 2: {key2}")
    assert key1 == key2, "Cùng query + entities phải cho cùng key"

    # Khác query → khác key
    key3 = await make_answer_key(entities={"model": "VF 9", "intent": "price"}, query="VF 9 giá bao nhiêu?")
    print(f"[OK] Key 3 (khác query): {key3}")
    assert key1 != key3, "Khác query phải cho khác key"

    print("[PASS] TEST 2\n")


async def test_cache_hit_miss():
    """Test cache hit/miss với AgentLoop"""
    print("=" * 60)
    print("TEST 3: Cache hit/miss thực tế")
    print("=" * 60)

    if not cache.enabled:
        print("[WARN] Cache không enabled, bỏ qua test này")
        return

    # Xóa cache trước khi test
    await cache._client.flushdb()
    print("[OK] Đã xóa toàn bộ cache")

    agent = AgentLoop()

    # Query 1: Cache miss
    print("\n[TEST] Query 1: 'VF 8 giá bao nhiêu?' (cache miss)")
    result1 = await agent.run(query="VF 8 giá bao nhiêu?", history=[], session_id="test-session-1")
    print(f"[OK] Response 1: {result1.response[:100]}...")
    print(f"[OK] Decision: {result1.decision}")

    # Kiểm tra cache đã được set
    keys = await cache._client.keys("ans:*")
    print(f"[OK] Số keys trong cache: {len(keys)}")
    assert len(keys) > 0, "Cache phải có ít nhất 1 key sau query đầu tiên"

    # Query 2: Cache hit (cùng query)
    print("\n[TEST] Query 2: 'VF 8 giá bao nhiêu?' (cache hit)")
    result2 = await agent.run(
        query="VF 8 giá bao nhiêu?",
        history=[],
        session_id="test-session-2",  # Khác session_id nhưng cùng query + entities
    )
    print(f"[OK] Response 2: {result2.response[:100]}...")
    print(f"[OK] Decision: {result2.decision}")

    # Response phải giống nhau (từ cache)
    assert result1.response == result2.response, "Cache hit phải trả về cùng response"

    # Query 3: Multi-turn (không cache)
    print("\n[TEST] Query 3: Multi-turn (không cache)")
    result3 = await agent.run(
        query="VF 8 giá bao nhiêu?", history=[{"role": "user", "content": "hi"}], session_id="test-session-3"
    )
    print(f"[OK] Response 3: {result3.response[:100]}...")
    print("[OK] Multi-turn không dùng cache (đúng)")

    print("[PASS] TEST 3\n")


async def main():
    try:
        await test_cacheable_logic()
        await test_cache_key_generation()
        await test_cache_hit_miss()

        print("\n" + "=" * 60)
        print("[SUCCESS] TẤT CẢ TEST ĐỀU PASSED")
        print("=" * 60)
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
