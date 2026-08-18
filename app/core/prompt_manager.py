"""
app/core/prompt_manager.py — Enterprise Prompt Registry & Versioning Engine.

Quản lý toàn bộ prompt templates của Vivu:
- Lưu trữ và đánh version trong PostgreSQL (bảng prompt_registry)
- Hỗ trợ Dynamic Switching (A/B testing, rollback) mà không cần restart server
- In-memory caching với cơ chế invalidation tức thì khi activate version mới
- Seed tự động các default prompts (v1.0.0) khi khởi động hệ thống
"""
import asyncio
import hashlib
import logging
import time
from typing import Any, Optional

from app.core.db import get_pool, run_with_db_retry

logger = logging.getLogger("bds.prompts")

_DEFAULT_SYSTEM_PROMPT_V1 = """Bạn là trợ lý tư vấn xe VinFast tại Việt Nam.

## Danh sách xe đang bán (cập nhật từ hệ thống)
{model_list}

## Quy tắc
1. Trả lời bằng tiếng Việt, ngắn gọn, đi thẳng vào câu hỏi. Câu hỏi đơn giản → tối đa 3-5 câu. Chỉ dùng bảng khi so sánh nhiều model.
2. Kết thúc ngay sau khi trả lời xong. KHÔNG mời chào ("Bạn có muốn..."), KHÔNG hỏi lại khi đã đủ dữ liệu.
3. Nếu câu hỏi rút gọn (VD: "bản Plus thì sao?"), dựa vào lịch sử hội thoại để hiểu đang hỏi về xe/thông số nào.
4. Hỏi giá → PHẢI dùng get_price tool. KHÔNG tự bịa số tiền.
5. Hỏi thông số kỹ thuật (công suất, quãng đường, pin, kích thước, túi khí, ADAS, nội thất, ngoại thất, tính năng) → PHẢI dùng get_specs tool. BẮT BUỘC dùng parameter category để lọc:
   - Hỏi về sạc, pin, thời gian sạc → category="battery"
   - Hỏi về công suất, mô-men xoắn, tốc độ, tăng tốc → category="powertrain"
   - Hỏi về kích thước, chiều dài, rộng, cao, khoảng sáng gầm → category="dimension"
   - Hỏi về phạm vi di chuyển, quãng đường → category="battery"
   - Hỏi về túi khí, phanh, an toàn → category="safety"
   - Hỏi về nội thất, ghế, màn hình, loa, điều hòa → category="interior"
   - Hỏi về cửa sổ trời, kính trần, sunroof, panoramic roof → category="interior"
   - Hỏi về ngoại thất, đèn, mâm → category="exterior"
   - Hỏi về ADAS, cruise, lane → category="adas"
   - Hỏi về tiện nghi, giải trí, kết nối, trợ lý ảo → KHÔNG truyền category.
   - Nếu không chắc category nào → KHÔNG truyền category (lấy tất cả).
6. Hỏi về model, phiên bản, danh sách xe → dùng list_available_models hoặc get_specs.
7. So sánh, gợi ý, tư vấn → PHẢI gọi get_specs cho TỪNG model liên quan.
8. Hỏi về màu sắc, màu nội thất, tùy chọn màu → PHẢI dùng get_colors.
9. KHÔNG được trả lời từ kiến thức sẵn có. PHẢI gọi tool cho MỖI model riêng biệt. KHÔNG tự bịa số liệu.
10. Nếu tool không có dữ liệu → trả lời "Xin lỗi, mình chưa có thông tin phù hợp. Bạn có thể hỏi lại bằng câu khác được không?"
11. QUAN TRỌNG: Nếu tool results KHÔNG đề cập đến một tính năng/thông số cụ thể mà user hỏi (VD: ghế massage, cửa sổ trời, sưởi vô-lăng, số chỗ ngồi...), bạn PHẢI nói "Mình chưa có thông tin về [tính năng] này." KHÔNG được khẳng định "không có" hoặc "Không" — vì chưa có dữ liệu ≠ xác nhận không có.
12. QUY TẮC ƯU TIÊN NGUỒN DỮ LIỆU:
    - Spec DB (từ get_specs, get_price, get_colors) là nguồn CHÍNH THỨC, đáng tin cậy nhất.
    - KB (từ search_knowledge_base) là nguồn THAM KHẢO, có thể không chính xác hoặc mâu thuẫn với spec DB.
    - Khi spec DB và KB MÂU THUẪN → luôn ưu tiên spec DB.
13. GIỌNG VĂN TỰ NHIÊN: Trả lời trực tiếp như đang tư vấn. CẤM mở đầu "Theo dữ liệu", "Theo thông tin hiện có" hoặc dùng "được phê duyệt"/"được ghi nhận".
14. QUY TẮC PHIÊN BẢN MẶC ĐỊNH: Khi user KHÔNG nêu tên phiên bản, gọi tool KHÔNG kèm parameter version và trả lời theo bản Eco (hoặc bản rẻ nhất). Nêu rõ tên phiên bản và kết câu bằng gợi ý các phiên bản khác.

## Khi nào gọi ask_clarification
CHỈ gọi khi thiếu model (không biết người dùng hỏi xe nào). KHÔNG BAO GIỜ gọi ask_clarification để hỏi về phiên bản."""

_DEFAULT_SYNTHESIZE_PROMPT_V1 = """Bạn là trợ lý tư vấn xe VinFast. Tổng hợp thông tin dưới đây thành câu trả lời ngắn gọn, chính xác.

QUAN TRỌNG:
- Context đã có đủ thông tin. KHÔNG hỏi lại model, version hay topic.
- CHỈ dùng thông tin trong context. KHÔNG thêm thông tin ngoài context.
- KHÔNG dẫn URL/link trong câu trả lời (giao diện hiển thị tự động).
- KHÔNG tự bịa số liệu. KHÔNG dùng kiến thức sẵn có.
- KHI SO SÁNH: mỗi model có specs riêng. KHÔNG lấy specs model A gán cho model B.
- GIỌNG VĂN TỰ NHIÊN: trả lời trực tiếp như đang tư vấn. CẤM mở đầu "Theo dữ liệu", "Theo thông tin hiện có".
- Nếu context không có thông tin được hỏi → nói rõ: "Mình chưa có thông tin về [topic] cho [model]."

Context:
{context}

Câu hỏi: {query}"""

_DEFAULT_CLASSIFY_PROMPT_V1 = """Phân loại câu hỏi tư vấn xe VinFast. Chỉ trả về JSON:
{{"intent": "<intent>", "model": "<model>", "version": "<version>", "topic": "<topic>"}}

Câu hỏi: {query}"""

_DEFAULT_SUMMARIZE_PROMPT_V1 = """Tóm tắt hội thoại tư vấn xe VinFast dưới đây. {extend}
Giữ lại: Dòng xe user quan tâm, phiên bản, nhu cầu/ngân sách, các câu hỏi đã được giải đáp.
Độ dài tối đa 200 từ.

Lịch sử:
{history}"""

_INITIAL_PROMPTS = [
    {
        "prompt_type": "system",
        "version": "v1.0.0",
        "template": _DEFAULT_SYSTEM_PROMPT_V1,
        "description": "System prompt gốc: 14 quy tắc tư vấn xe VinFast, hybrid tool routing & default version rule",
        "author": "system",
        "is_active": True,
    },
    {
        "prompt_type": "synthesize",
        "version": "v1.0.0",
        "template": _DEFAULT_SYNTHESIZE_PROMPT_V1,
        "description": "Synthesize prompt gốc: Tổng hợp context và sinh câu trả lời tự nhiên",
        "author": "system",
        "is_active": True,
    },
    {
        "prompt_type": "classify",
        "version": "v1.0.0",
        "template": _DEFAULT_CLASSIFY_PROMPT_V1,
        "description": "Classify fallback prompt: Phân loại intent & entities",
        "author": "system",
        "is_active": True,
    },
    {
        "prompt_type": "summarize",
        "version": "v1.0.0",
        "template": _DEFAULT_SUMMARIZE_PROMPT_V1,
        "description": "Summarize prompt: Nén hội thoại multi-turn",
        "author": "system",
        "is_active": True,
    },
]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prompt_registry (
    id              SERIAL PRIMARY KEY,
    prompt_type     VARCHAR(64) NOT NULL,
    version         VARCHAR(32) NOT NULL,
    template        TEXT NOT NULL,
    description     TEXT DEFAULT '',
    author          VARCHAR(128) DEFAULT 'system',
    is_active       BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prompt_type, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_registry_type ON prompt_registry(prompt_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_active_unique ON prompt_registry(prompt_type) WHERE is_active = true;
"""

_schema_ready = False
_ensure_lock = asyncio.Lock()

# In-memory prompt cache: { prompt_type: { "template": str, "version": str, "hash": str, "cached_at": float } }
_active_cache: dict[str, dict[str, Any]] = {}
_CACHE_TTL = 300  # 5 phút


class PromptManager:
    """Quản lý và cấp phát prompts theo phiên bản."""

    @staticmethod
    async def ensure_schema() -> None:
        """Tạo bảng và nạp dữ liệu seed nếu chưa có (idempotent)."""
        global _schema_ready
        if _schema_ready:
            return
        async with _ensure_lock:
            if _schema_ready:
                return

            async def _init_db():
                pool = await get_pool()
                async with pool.acquire() as conn:
                    for stmt in _SCHEMA_SQL.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            await conn.execute(stmt)

                    # Kiểm tra và seed nếu bảng rỗng
                    count = await conn.fetchval("SELECT COUNT(*) FROM prompt_registry")
                    if count == 0:
                        for p in _INITIAL_PROMPTS:
                            await conn.execute(
                                """
                                INSERT INTO prompt_registry (prompt_type, version, template, description, author, is_active)
                                VALUES ($1, $2, $3, $4, $5, $6)
                                ON CONFLICT (prompt_type, version) DO NOTHING
                                """,
                                p["prompt_type"],
                                p["version"],
                                p["template"],
                                p["description"],
                                p["author"],
                                p["is_active"],
                            )
                        logger.info("Prompt registry initialized with %d default prompts", len(_INITIAL_PROMPTS))

            await run_with_db_retry(_init_db, label="ensure prompt_registry schema")
            _schema_ready = True

    @staticmethod
    def invalidate_cache(prompt_type: Optional[str] = None) -> None:
        """Xoá cache in-memory khi có cập nhật hoặc chuyển đổi version."""
        global _active_cache
        if prompt_type:
            _active_cache.pop(prompt_type, None)
        else:
            _active_cache.clear()

    @staticmethod
    async def get_active_prompt(prompt_type: str) -> tuple[str, str]:
        """Lấy prompt template đang active kèm version string. Trả về (template_text, version)."""
        now = time.time()
        cached = _active_cache.get(prompt_type)
        if cached and (now - cached["cached_at"]) < _CACHE_TTL:
            return cached["template"], cached["version"]

        try:
            await PromptManager.ensure_schema()

            async def _fetch():
                pool = await get_pool()
                return await pool.fetchrow(
                    """
                    SELECT template, version FROM prompt_registry
                    WHERE prompt_type = $1 AND is_active = true
                    LIMIT 1
                    """,
                    prompt_type,
                )

            row = await run_with_db_retry(_fetch, label=f"get_active_prompt({prompt_type})")
            if row:
                template = row["template"]
                version = row["version"]
                p_hash = hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]
                _active_cache[prompt_type] = {
                    "template": template,
                    "version": version,
                    "hash": p_hash,
                    "cached_at": now,
                }
                return template, version
        except Exception as e:
            logger.warning("Error fetching active prompt %s from DB: %s (using static fallback)", prompt_type, e)

        # Fallback to in-code default
        for p in _INITIAL_PROMPTS:
            if p["prompt_type"] == prompt_type:
                return p["template"], p["version"]
        return "", "v1.0.0"

    @staticmethod
    async def list_prompts(prompt_type: Optional[str] = None) -> list[dict[str, Any]]:
        """Liệt kê danh sách tất cả prompt và các phiên bản."""
        await PromptManager.ensure_schema()
        query = """
        SELECT id, prompt_type, version, description, author, is_active, created_at, updated_at,
               length(template) as char_count
        FROM prompt_registry
        """
        params = []
        if prompt_type:
            query += " WHERE prompt_type = $1"
            params.append(prompt_type)
        query += " ORDER BY prompt_type ASC, created_at DESC"

        async def _fetch():
            pool = await get_pool()
            return await pool.fetch(query, *params)

        rows = await run_with_db_retry(_fetch, label="list_prompts")
        return [
            {
                "id": r["id"],
                "prompt_type": r["prompt_type"],
                "version": r["version"],
                "description": r["description"],
                "author": r["author"],
                "is_active": r["is_active"],
                "char_count": r["char_count"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else "",
            }
            for r in rows
        ]

    @staticmethod
    async def get_prompt_detail(prompt_type: str, version: str) -> Optional[dict[str, Any]]:
        """Lấy chi tiết và toàn bộ template của một version cụ thể."""
        await PromptManager.ensure_schema()

        async def _fetch():
            pool = await get_pool()
            return await pool.fetchrow(
                """
                SELECT id, prompt_type, version, template, description, author, is_active, created_at, updated_at
                FROM prompt_registry
                WHERE prompt_type = $1 AND version = $2
                """,
                prompt_type,
                version,
            )

        row = await run_with_db_retry(_fetch, label="get_prompt_detail")
        if not row:
            return None
        return {
            "id": row["id"],
            "prompt_type": row["prompt_type"],
            "version": row["version"],
            "template": row["template"],
            "description": row["description"],
            "author": row["author"],
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
        }

    @staticmethod
    async def create_prompt_version(
        prompt_type: str,
        version: str,
        template: str,
        description: str = "",
        author: str = "admin",
        set_active: bool = False,
    ) -> dict[str, Any]:
        """Tạo mới một phiên bản prompt."""
        await PromptManager.ensure_schema()

        async def _create():
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if set_active:
                        await conn.execute(
                            "UPDATE prompt_registry SET is_active = false WHERE prompt_type = $1",
                            prompt_type,
                        )
                    row = await conn.fetchrow(
                        """
                        INSERT INTO prompt_registry (prompt_type, version, template, description, author, is_active)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING id, prompt_type, version, description, author, is_active, created_at
                        """,
                        prompt_type,
                        version,
                        template,
                        description,
                        author,
                        set_active,
                    )
                    return dict(row)

        res = await run_with_db_retry(_create, label="create_prompt_version")
        if set_active:
            PromptManager.invalidate_cache(prompt_type)
        return res

    @staticmethod
    async def activate_version(prompt_type: str, version: str) -> bool:
        """Kích hoạt một phiên bản prompt làm active version (atomic switch)."""
        await PromptManager.ensure_schema()

        async def _activate():
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Check existence
                    exists = await conn.fetchval(
                        "SELECT COUNT(*) FROM prompt_registry WHERE prompt_type = $1 AND version = $2",
                        prompt_type,
                        version,
                    )
                    if not exists:
                        return False

                    # Deactivate current
                    await conn.execute(
                        "UPDATE prompt_registry SET is_active = false WHERE prompt_type = $1",
                        prompt_type,
                    )
                    # Activate selected
                    await conn.execute(
                        "UPDATE prompt_registry SET is_active = true, updated_at = now() WHERE prompt_type = $1 AND version = $2",
                        prompt_type,
                        version,
                    )
                    return True

        success = await run_with_db_retry(_activate, label=f"activate_version({prompt_type}, {version})")
        if success:
            PromptManager.invalidate_cache(prompt_type)
        return success

    @staticmethod
    async def get_active_versions_map() -> dict[str, str]:
        """Trả về map tất cả active versions: {'system': 'v1.0.0', 'synthesize': 'v1.0.0', ...}"""
        await PromptManager.ensure_schema()

        async def _fetch():
            pool = await get_pool()
            return await pool.fetch("SELECT prompt_type, version FROM prompt_registry WHERE is_active = true")

        rows = await run_with_db_retry(_fetch, label="get_active_versions_map")
        return {r["prompt_type"]: r["version"] for r in rows}


prompt_manager = PromptManager()
