"""Redis cache layer (Upstash) — fail-safe, disabled khi không có REDIS_URL.

Nguyên tắc:
- Không có REDIS_URL / CACHE_ENABLED=false → mọi method no-op (miss pass-through).
- Redis lỗi → dead-cooldown 30s (trong cooldown bỏ qua, không spam error), sau đó thử lại.
- Không cache gì không tái tạo được từ nguồn gốc.
- Key version-aware: `data_version()` đọc LIVE từ PG `ingest_version.is_current`
  (cache in-memory 60s) — promote version → key tự đổi, không restart.
"""

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata

import redis.asyncio as aioredis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from app.config import settings

logger = logging.getLogger("bds.cache")


def _cache_metric(kind: str, hit: bool) -> None:
    """Ghi Prometheus cache hit/miss (no-op khi Prometheus tắt/chưa cài)."""
    try:
        from app.core.telemetry.prometheus import record_cache

        record_cache(kind=kind, hit=hit)
    except Exception:
        pass


# ── Data version (chống stale-data) ────────────────────────────────────────
_ver_cache: dict = {"value": None, "at": 0.0}
_VER_TTL = 60.0  # promote lan toả ≤60s
_ver_lock = threading.Lock()

# ── TTL constants ──────────────────────────────────────────────────────────
ANS_TTL = 1800  # 30 phút cho answer cache (single-turn)
TOOL_PRICE_TTL = 900  # 15 phút cho price (biến động)
TOOL_DATA_TTL = 14400  # 4 giờ cho specs/colors/models (version-aware key, stale tự invalidate khi promote)
DEDUP_TTL = 3600  # 1 giờ cho dedupe message_id


# Versions không hợp lệ (PG unreachable) → skip cache để tránh stale data
_VALID_VERSIONS = frozenset({"unknown"})


def _is_valid_version(ver: str | None) -> bool:
    """True nếu version đủ tin cậy để làm cache key."""
    return bool(ver) and ver not in _VALID_VERSIONS


async def data_version() -> str | None:
    """SELECT version FROM ingest_version WHERE is_current LIMIT 1.

    Cache in-memory 60s. Trả None khi PG unreachable -> key builders
    skip cache (miss pass-through), tránh stale data từ version cũ.
    """
    now = time.time()
    with _ver_lock:
        if _ver_cache["value"] is not None and now - _ver_cache["at"] < _VER_TTL:
            return _ver_cache["value"]
    try:
        from app.core.storage.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT version FROM ingest_version WHERE is_current LIMIT 1")
        ver = row["version"] if row else None
    except Exception as e:  # noqa: BLE001
        logger.warning("data_version: PG unreachable -> skip cache: %s", e)
        ver = None
    with _ver_lock:
        _ver_cache["value"] = ver
        _ver_cache["at"] = now
    return ver


# ── Chuẩn hoá query (key ổn định giữa các cách diễn đạt) ───────────────────
_MODEL_NORM_RE = re.compile(r"vf[\s\-_]*(\d+)", re.IGNORECASE)


def normalize_query(query: str) -> str:
    """NFC → lowercase → gộp whitespace → bỏ punctuation đầu/cuối → chuẩn hoá model.

    "VF  8 giá bao nhiêu?" và "vf-8 Giá" → cùng chuẩn "vf 8 giá".
    """
    if not query:
        return ""
    q = unicodedata.normalize("NFC", query).strip().lower()
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[^\w\sà-ỹđ]", "", q, flags=re.UNICODE).strip()

    def _norm_model(m: re.Match) -> str:
        return f"vf {m.group(1)}"

    return _MODEL_NORM_RE.sub(_norm_model, q)


def _sha1(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ── Key builders ───────────────────────────────────────────────────────────
async def make_hs_key(query: str, model_id: str | None = None, top_k: int = 5, skip_rerank: bool = False) -> str | None:
    ver = await data_version()
    if not _is_valid_version(ver):
        return None
    mid = model_id or "-"
    return f"hs:{ver}:{_sha1(normalize_query(query))}:{mid}:{top_k}:{int(skip_rerank)}"


def make_embed_key(text: str) -> str:
    # Dùng text THÔ (không chuẩn hoá): vector nhạy chữ — cùng text thô = cùng vector
    # deterministic tuyệt đối; text khác (dù gần giống) → key khác → embed lại cho đúng.
    return f"emb:{settings.openrouter_embed_model}:{_sha1(text)}"


async def make_answer_key(entities: dict, query: str, prompt_hash: str = "", llm_model: str = "") -> str | None:
    """Key cho ans: cache — gồm data_version + prompt_hash + llm_model + entities + query.

    Trả None khi PG unreachable (data_version=None) → skip cache để tránh stale.
    entities: {model: 'VF 8', version: 'Plus', intent: 'price'}
    """
    ver = await data_version()
    if not _is_valid_version(ver):
        return None
    if not prompt_hash:
        from app.agent.prompts import get_prompt_hash

        prompt_hash = get_prompt_hash()
    if not llm_model:
        llm_model = settings.llm_model.split("/")[-1]  # lấy tên model ngắn gọn
    # Entities sort để ổn định
    ent_str = "|".join(f"{k}={v}" for k, v in sorted(entities.items()) if v)
    return f"ans:{ver}:{prompt_hash}:{llm_model}:{_sha1(ent_str, normalize_query(query))}"


def make_dedup_key(session_id: str, message_id: str) -> str:
    """Key cho dedupe - chống gửi trùng message.

    Args:
        session_id: UUID của session
        message_id: UUID của message (client sinh)

    Returns:
        Key dạng 'dedup:{sha1(session_id|message_id)}'
    """
    return f"dedup:{_sha1(session_id, message_id)}"


def make_exact_io_key(query: str) -> str:
    """Key cho exact I/O cache — thuần câu hỏi chuẩn hoá (không phụ thuộc session/history).

    Args:
        query: Câu hỏi người dùng

    Returns:
        Key dạng 'io:{sha1(normalized_query)}'
    """
    return f"io:{_sha1(normalize_query(query))}"


async def make_tool_price_key(model_code: str, version: str = None) -> str | None:
    """Key cho cache get_price.

    Args:
        model_code: Mã model (VD: 'VF 8')
        version: Phiên bản (VD: 'Plus') - optional

    Returns:
        Key dạng 'tool:price:{data_version}:{model}:{version}' hoặc None nếu PG unreachable
    """
    ver = await data_version()
    if not _is_valid_version(ver):
        return None
    v = version or "-"
    return f"tool:price:{ver}:{_sha1(model_code, v)}"


async def make_tool_specs_key(
    model_code: str, version: str = None, category: str = None, keys: list[str] = None
) -> str | None:
    """Key cho cache get_specs.

    Args:
        model_code: Mã model
        version: Phiên bản - optional
        category: Danh mục spec - optional
        keys: List các spec keys - optional

    Returns:
        Key dạng 'tool:specs:{data_version}:{sha1(model|version|category|keys)}' hoặc None
    """
    ver = await data_version()
    if not _is_valid_version(ver):
        return None
    v = version or "-"
    c = category or "-"
    k = "|".join(sorted(keys)) if keys else "-"
    return f"tool:specs:{ver}:{_sha1(model_code, v, c, k)}"


async def make_tool_colors_key(model_code: str, version: str = None) -> str | None:
    """Key cho cache get_colors.

    Args:
        model_code: Mã model
        version: Phiên bản - optional

    Returns:
        Key dạng 'tool:colors:{data_version}:{sha1(model|version)}' hoặc None
    """
    ver = await data_version()
    if not _is_valid_version(ver):
        return None
    v = version or "-"
    return f"tool:colors:{ver}:{_sha1(model_code, v)}"


async def make_tool_models_key() -> str | None:
    """Key cho cache list_available_models.

    Returns:
        Key dạng 'tool:models:{data_version}' hoặc None
    """
    ver = await data_version()
    if not _is_valid_version(ver):
        return None
    return f"tool:models:{ver}"


# ── RedisCache wrapper ─────────────────────────────────────────────────────
def _token_from_url(url: str) -> str:
    """Parse token từ URL dạng rediss://default:<token>@host:6379."""
    if "://" not in url or "@" not in url:
        return ""
    auth = url.split("://", 1)[1].split("@", 1)[0]
    if ":" in auth:
        return auth.split(":", 1)[1]
    return ""


def _rest_url_from(url: str) -> str:
    """rediss://host:6379 → https://host (Upstash REST)."""
    if url.startswith("https://"):
        return url.rstrip("/")
    host = url.split("@", 1)[-1].split(":", 1)[0]
    return f"https://{host}"


class RedisCache:
    """Async wrapper quanh Redis. Mọi lỗi → miss pass-through (không crash).

    Mode REST (Upstash REST API — https://<db>.upstash.io + Bearer token):
    dùng khi có REDIS_TOKEN (hoặc parse được từ URL). Không TCP → không lo
    connection đóng sau idle như serverless TCP.
    Mode TCP (redis-py): fallback khi không có token (redis:// / rediss://).
    """

    def __init__(self) -> None:
        self._client = None  # async client (get/set giống nhau ở cả 2 mode)
        self._sync_client = None  # sync client (dùng trong executor thread)
        self._enabled = bool(settings.redis_url) and settings.cache_enabled
        self._down_until: float = 0.0
        self._errors: int = 0
        self._lock = threading.Lock()
        self._rest_mode = False
        if self._enabled:
            try:
                token = settings.redis_token or _token_from_url(settings.redis_url)
                if token:
                    # REST mode — Upstash REST API, khỏi TCP
                    from upstash_redis import Redis as SyncRedis
                    from upstash_redis.asyncio import Redis as AsyncRedis

                    rest_url = _rest_url_from(settings.redis_url)
                    self._client = AsyncRedis(url=rest_url, token=token)
                    self._sync_client = SyncRedis(url=rest_url, token=token)
                    self._rest_mode = True
                else:
                    # TCP mode — redis-py (Upstash serverless: timeout rộng + retry)
                    import redis as sync_redis

                    self._client = aioredis.from_url(
                        settings.redis_url,
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                        health_check_interval=30,
                        retry_on_timeout=True,
                        retry=Retry(ExponentialBackoff(base=0.1, cap=1.0), retries=2),
                    )
                    self._sync_client = sync_redis.Redis.from_url(
                        settings.redis_url,
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                        health_check_interval=30,
                        retry_on_timeout=True,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("Redis init fail → cache disabled: %s", e)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def mode(self) -> str:
        return "rest" if self._rest_mode else "tcp"

    def _in_cooldown(self) -> bool:
        return time.time() < self._down_until

    def _mark_down(self, exc: Exception) -> None:
        # Chỉ cooldown sau 2 lỗi LIÊN TIẾP (1 lỗi rời rạc có thể là hiccup mạng)
        with self._lock:
            self._errors += 1
            if self._errors < 2:
                logger.warning("Redis error (retry tiếp): %s", exc)
                return
            now = time.time()
            if now >= self._down_until:
                logger.warning("Redis down (cooldown 30s): %s", exc)
            self._down_until = now + 30.0

    def _reset_errors(self) -> None:
        with self._lock:
            self._errors = 0

    async def get_json(self, key: str):
        if not self._enabled or self._in_cooldown():
            return None
        try:
            raw = await self._client.get(key)  # type: ignore[union-attr]
            if raw is None:
                _cache_metric(kind="redis", hit=False)
                return None
            self._reset_errors()
            _cache_metric(kind="redis", hit=True)
            return json.loads(raw)
        except Exception as e:  # noqa: BLE001
            self._mark_down(e)
            return None

    async def set_json(self, key: str, value, ttl: int) -> bool:
        if not self._enabled or self._in_cooldown():
            return False
        try:
            await self._client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)  # type: ignore[union-attr]
            self._reset_errors()
            return True
        except Exception as e:  # noqa: BLE001
            self._mark_down(e)
            return False

    async def set_nx_json(self, key: str, value, ttl: int) -> bool:
        """SET if Not eXists. Trả về True nếu set thành công (key chưa tồn tại), False nếu key đã tồn tại.
        Dùng cho dedupe: chỉ cho phép set 1 lần, các lần sau sẽ fail.

        Lưu ý: Redis down → KHÔNG cho qua (trả False) để dedup vẫn chặn
        duplicate trong suốt outage. Chỉ bypass khi cache bị disable hoàn toàn.
        """
        if not self._enabled:
            return True  # Cache disabled hoàn toàn → cho qua
        if self._in_cooldown():
            return False  # Redis down → chặn duplicate (an toàn hơn cho qua)
        try:
            result = await self._client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl, nx=True)  # type: ignore[union-attr]
            self._reset_errors()
            # Upstash Redis trả về bool: True nếu set thành công, False nếu NX fail
            return bool(result)
        except Exception as e:  # noqa: BLE001
            self._mark_down(e)
            return False  # Lỗi → chặn duplicate (an toàn hơn cho qua)

    async def get_or_set(self, key: str, ttl: int, factory, *args, **kwargs):
        """GET; miss → SET NX (lock) → factory(*args, **kwargs) → SET value.

        Tránh race condition:2 concurrent requests cùng miss → cả 2 compute factory.
        Dùng SET NX với lock_ttl ngắn làm mutex — request đầu set thành công,
        request sau thấy key đã có →等待 rồi retry GET.

        Returns: (value, hit: bool) — hit=True nếu cache hit, False nếu compute.
        """
        hit = await self.get_json(key)
        if hit is not None:
            return hit, True

        # Lock pattern: SET lock_key NX với TTL ngắn
        lock_key = f"lock:{key}"
        lock_ttl = min(10, ttl)  # lock tối đa 10s hoặc TTL (nếu ngắn hơn)
        got_lock = await self.set_nx_json(lock_key, 1, lock_ttl)

        if got_lock:
            # Request đầu: compute + set value + delete lock
            try:
                value = await factory(*args, **kwargs)
                await self.set_json(key, value, ttl)
                return value, False
            finally:
                # Delete lock (cho request sau biết giá trị đã có)
                try:
                    if self._client:
                        await self._client.delete(lock_key)  # type: ignore[union-attr]
                except Exception:
                    pass
        else:
            # Request sau: chờ request đầu compute xong, rồi retry GET
            import asyncio as _aio

            for _ in range(5):  # retry max5 lần, mỗi lần2s = max10s
                await _aio.sleep(2)
                hit = await self.get_json(key)
                if hit is not None:
                    return hit, True
            # Hết retry → compute zelf (fallback, không block forever)
            value = await factory(*args, **kwargs)
            await self.set_json(key, value, ttl)
            return value, False

    # ── Sync helpers (dùng trong executor thread — embed/tool sync) ────────
    def sync_get_json(self, key: str):
        if not self._enabled or self._in_cooldown():
            return None
        try:
            raw = self._sync_client.get(key)  # type: ignore[union-attr]
            if raw is None:
                _cache_metric(kind="redis", hit=False)
                return None
            self._reset_errors()
            _cache_metric(kind="redis", hit=True)
            return json.loads(raw)
        except Exception as e:  # noqa: BLE001
            self._mark_down(e)
            return None

    def sync_set_json(self, key: str, value, ttl: int) -> bool:
        if not self._enabled or self._in_cooldown():
            return False
        try:
            self._sync_client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)  # type: ignore[union-attr]
            self._reset_errors()
            return True
        except Exception as e:  # noqa: BLE001
            self._mark_down(e)
            return False


# Singleton dùng chung
cache = RedisCache()
