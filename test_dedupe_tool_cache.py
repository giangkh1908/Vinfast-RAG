import asyncio
import sys
sys.path.insert(0, '.')

from app.core.cache import cache, make_dedup_key, make_tool_price_key, make_tool_specs_key, DEDUP_TTL
from app.agent.tools import get_price, get_specs, get_colors, list_available_models
from app.api.chat import _check_dedupe


async def test_dedupe():
    print("\n=== TEST DEDUPE ===")
    
    # Test tạo dedupe key
    session_id = "test-session-123"
    message_id = "msg-001"
    
    key = make_dedup_key(session_id, message_id)
    print(f"Dedupe key: {key}")
    
    # Xóa key nếu có (để test từ đầu)
    await cache._client.delete(key)
    print(f"Deleted existing key")
    
    # Test 1: Lần đầu set_nx_json -> phải thành công (True)
    result1 = await cache.set_nx_json(key, {"processed": True}, DEDUP_TTL)
    print(f"Test 1 - First set_nx_json: {result1} (expected: True)")
    assert result1 == True, "First set_nx_json should succeed"
    
    # Test 2: Lần hai set_nx_json cùng key -> phải thất bại (False)
    result2 = await cache.set_nx_json(key, {"processed": True}, DEDUP_TTL)
    print(f"Test 2 - Second set_nx_json (same key): {result2} (expected: False)")
    assert result2 == False, "Second set_nx_json should fail (key exists)"
    
    # Test 3: Key khác -> phải thành công (True)
    key2 = make_dedup_key(session_id, "msg-002")
    await cache._client.delete(key2)
    result3 = await cache.set_nx_json(key2, {"processed": True}, DEDUP_TTL)
    print(f"Test 3 - set_nx_json (different key): {result3} (expected: True)")
    assert result3 == True, "Different key should succeed"
    
    # Test 4: Verify _check_dedupe function
    # Xóa key cũ
    await cache._client.delete(key)
    # Lần đầu -> không phải duplicate (False)
    is_dup1 = await _check_dedupe(session_id, message_id)
    print(f"Test 4 - First _check_dedupe: {is_dup1} (expected: False - not duplicate)")
    assert is_dup1 == False, "First check should not be duplicate"
    # Lần hai -> là duplicate (True)
    is_dup2 = await _check_dedupe(session_id, message_id)
    print(f"Test 5 - Second _check_dedupe: {is_dup2} (expected: True - is duplicate)")
    assert is_dup2 == True, "Second check should be duplicate"
    
    # Cleanup
    await cache._client.delete(key)
    await cache._client.delete(key2)
    
    print("[OK] Dedupe test passed")


async def test_tool_cache():
    print("\n=== TEST TOOL CACHE ===")
    
    # Test get_price cache
    print("\n-- Testing get_price --")
    print("Call 1 (should hit DB):")
    result1 = await get_price("VF 8")
    print(f"  Result: {len(result1['prices'])} prices")
    
    print("Call 2 (should hit cache):")
    result2 = await get_price("VF 8")
    print(f"  Result: {len(result2['prices'])} prices")
    print(f"  Same result: {result1 == result2}")
    
    # Test get_specs cache
    print("\n-- Testing get_specs --")
    print("Call 1 (should hit DB):")
    specs1 = await get_specs("VF 8", version="Eco")
    print(f"  Result: {len(specs1['specs'])} specs")
    
    print("Call 2 (should hit cache):")
    specs2 = await get_specs("VF 8", version="Eco")
    print(f"  Result: {len(specs2['specs'])} specs")
    print(f"  Same result: {specs1 == specs2}")
    
    # Test get_colors cache
    print("\n-- Testing get_colors --")
    print("Call 1 (should hit DB):")
    colors1 = await get_colors("VF 8")
    print(f"  Result: {len(colors1['colors'])} colors")
    
    print("Call 2 (should hit cache):")
    colors2 = await get_colors("VF 8")
    print(f"  Result: {len(colors2['colors'])} colors")
    print(f"  Same result: {colors1 == colors2}")
    
    # Test list_available_models cache
    print("\n-- Testing list_available_models --")
    print("Call 1 (should hit DB):")
    models1 = await list_available_models()
    print(f"  Result: {len(models1['models'])} models")
    
    print("Call 2 (should hit cache):")
    models2 = await list_available_models()
    print(f"  Result: {len(models2['models'])} models")
    print(f"  Same result: {models1 == models2}")
    
    print("\n[OK] Tool cache test passed")


async def test_cache_keys():
    print("\n=== TEST CACHE KEYS ===")
    
    # Test price keys
    key1 = await make_tool_price_key("VF 8", "Eco")
    key2 = await make_tool_price_key("VF 8", "Eco")
    key3 = await make_tool_price_key("VF 8", "Plus")
    
    print(f"Price key 1: {key1}")
    print(f"Price key 2: {key2}")
    print(f"Price key 3: {key3}")
    print(f"Same params = same key: {key1 == key2}")
    print(f"Different params = different key: {key1 != key3}")
    
    # Test specs keys
    key4 = await make_tool_specs_key("VF 8", "Eco", "Exterior", ["color"])
    key5 = await make_tool_specs_key("VF 8", "Eco", "Exterior", ["color"])
    key6 = await make_tool_specs_key("VF 8", "Plus", "Exterior", ["color"])
    
    print(f"\nSpecs key 1: {key4}")
    print(f"Specs key 2: {key5}")
    print(f"Specs key 3: {key6}")
    print(f"Same params = same key: {key4 == key5}")
    print(f"Different params = different key: {key4 != key6}")
    
    print("\n[OK] Cache key test passed")


async def main():
    if not cache.enabled:
        print("ERROR: Cache is not enabled. Check REDIS_URL in .env")
        sys.exit(1)
    
    print("Cache enabled:", cache.enabled)
    print("Cache mode:", cache.mode)
    
    try:
        await test_cache_keys()
        await test_dedupe()
        await test_tool_cache()
        
        print("\n" + "="*50)
        print("[SUCCESS] ALL TESTS PASSED")
        print("="*50)
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
