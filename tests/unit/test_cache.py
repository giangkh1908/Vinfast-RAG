"""Unit tests for app.core.storage.cache module."""

import pytest

from app.core.storage.cache import (
    _is_valid_version,
    _rest_url_from,
    _sha1,
    _token_from_url,
    cache,
    data_version,
    make_answer_key,
    make_dedup_key,
    make_embed_key,
    make_exact_io_key,
    make_hs_key,
    make_tool_colors_key,
    make_tool_models_key,
    make_tool_price_key,
    make_tool_specs_key,
    normalize_query,
)


class TestQueryNormalizationAndHashing:
    """Test normalize_query and sha1 hashing."""

    def test_normalize_query_variations(self):
        q1 = normalize_query("VF  8 giá bao nhiêu?")
        q2 = normalize_query("vf-8 Giá")
        q3 = normalize_query("VF8  giá!!")
        assert q1 == "vf 8 giá bao nhiêu"
        assert q2 == "vf 8 giá"
        assert q3 == "vf 8 giá"

    def test_normalize_empty_query(self):
        assert normalize_query("") == ""

    def test_sha1_deterministic(self):
        h1 = _sha1("model_a", "version_b")
        h2 = _sha1("model_a", "version_b")
        h3 = _sha1("model_a", "version_c")
        assert len(h1) == 16
        assert h1 == h2
        assert h1 != h3


class TestDataVersionAndValidation:
    """Test data_version live query and validation."""

    def test_is_valid_version(self):
        assert _is_valid_version("v1.0_2026-08-19") is True
        assert _is_valid_version("v2.1") is True
        assert _is_valid_version("unknown") is False
        assert _is_valid_version(None) is False
        assert _is_valid_version("") is False

    @pytest.mark.asyncio
    async def test_data_version_success(self, mock_db_pool):
        from app.core.storage.cache import _ver_cache

        _ver_cache["value"] = None
        _ver_cache["at"] = 0.0
        ver = await data_version()
        assert ver is not None
        assert _is_valid_version(ver)


class TestKeyBuilders:
    """Test key generation functions."""

    @pytest.mark.asyncio
    async def test_make_hs_key(self, mock_db_pool):
        key = await make_hs_key("VF 8 pin bao nhiêu", model_id="VF8", top_k=5)
        assert key is not None
        assert key.startswith("hs:")
        assert "VF8" in key

    def test_make_embed_key(self):
        key = make_embed_key("Văn bản kiểm thử embedding")
        assert key.startswith("emb:")

    @pytest.mark.asyncio
    async def test_make_answer_key(self, mock_db_pool):
        key1 = await make_answer_key(
            entities={"model": "VF 8", "intent": "price"},
            query="VF 8 giá bao nhiêu?",
            prompt_hash="abcd1234efgh",
            llm_model="deepseek",
        )
        assert key1 is not None
        assert key1.startswith("ans:")

        key2 = await make_answer_key(
            entities={"model": "VF 8", "intent": "price"},
            query="VF 8 giá bao nhiêu?",
            prompt_hash="abcd1234efgh",
            llm_model="deepseek",
        )
        assert key1 == key2

    def test_make_dedup_key(self):
        key = make_dedup_key("session-123", "msg-456")
        assert key.startswith("dedup:")

    def test_make_exact_io_key(self):
        k1 = make_exact_io_key("VF 8 giá bao nhiêu?")
        k2 = make_exact_io_key("vf  8  Giá bao nhiêu?")
        assert k1 == k2
        assert k1.startswith("io:")

    @pytest.mark.asyncio
    async def test_make_tool_keys(self, mock_db_pool):
        p_key = await make_tool_price_key("VF 8", "Plus")
        s_key = await make_tool_specs_key("VF 8", "Plus", "battery", ["battery_kwh"])
        c_key = await make_tool_colors_key("VF 8", "Plus")
        m_key = await make_tool_models_key()

        assert p_key.startswith("tool:price:")
        assert s_key.startswith("tool:specs:")
        assert c_key.startswith("tool:colors:")
        assert m_key.startswith("tool:models:")


class TestUrlHelpers:
    """Test token and REST URL parsing."""

    def test_token_from_url(self):
        url = "rediss://default:my_secret_token_123@global-redis.upstash.io:6379"
        assert _token_from_url(url) == "my_secret_token_123"

        url_no_token = "redis://localhost:6379"
        assert _token_from_url(url_no_token) == ""

    def test_rest_url_from(self):
        url = "rediss://default:token@my-db.upstash.io:6379"
        assert _rest_url_from(url) == "https://my-db.upstash.io"

        https_url = "https://my-db.upstash.io/"
        assert _rest_url_from(https_url) == "https://my-db.upstash.io"


class TestRedisCacheMethods:
    """Test get_json, set_json, set_nx_json, get_or_set, and error handling."""

    @pytest.mark.asyncio
    async def test_get_and_set_json(self, mock_redis):
        ok = await cache.set_json("test:key1", {"status": "ok", "value": 42}, ttl=60)
        assert ok is True

        data = await cache.get_json("test:key1")
        assert data == {"status": "ok", "value": 42}

    @pytest.mark.asyncio
    async def test_set_nx_json_deduplication(self, mock_redis):
        res1 = await cache.set_nx_json("test:lock1", {"locked": True}, ttl=60)
        assert res1 is True

        # Second attempt should fail (key already exists)
        res2 = await cache.set_nx_json("test:lock1", {"locked": True}, ttl=60)
        assert res2 is False

    @pytest.mark.asyncio
    async def test_get_or_set_lock_pattern(self, mock_redis):
        call_count = 0

        async def compute_value(x):
            nonlocal call_count
            call_count += 1
            return {"result": x * 2}

        # First call: computes and sets
        val1, hit1 = await cache.get_or_set("test:computed", 60, compute_value, 21)
        assert val1 == {"result": 42}
        assert hit1 is False
        assert call_count == 1

        # Second call: cache hit, no compute
        val2, hit2 = await cache.get_or_set("test:computed", 60, compute_value, 21)
        assert val2 == {"result": 42}
        assert hit2 is True
        assert call_count == 1

    def test_sync_get_and_set_json(self, mock_redis):
        ok = cache.sync_set_json("test:sync_key", {"sync": True}, ttl=60)
        assert ok is True

        data = cache.sync_get_json("test:sync_key")
        assert data == {"sync": True}

    @pytest.mark.asyncio
    async def test_cooldown_error_circuit_breaker(self, mock_redis):
        cache._errors = 0
        cache._down_until = 0.0

        # Simulate 2 consecutive errors
        cache._mark_down(Exception("Simulated Redis Err 1"))
        assert not cache._in_cooldown()

        cache._mark_down(Exception("Simulated Redis Err 2"))
        assert cache._in_cooldown()

        # While in cooldown, get_json safely returns None without calling client
        val = await cache.get_json("test:any_key")
        assert val is None

        # Reset errors
        cache._reset_errors()
        cache._down_until = 0.0
