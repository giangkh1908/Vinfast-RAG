import asyncpg
import hashlib
import time

from app.config import settings

# TTL cache (5 minutes)
_prompt_cache = None
_prompt_cache_time = 0
_prompt_hash = None
_CACHE_TTL = 300


SYSTEM_PROMPT = """Bạn là trợ lý tư vấn xe VinFast tại Việt Nam.

## Danh sách xe đang bán (cập nhật từ hệ thống)
{model_list}

## Quy tắc
1. Trả lời bằng tiếng Việt, ngắn gọn, dễ hiểu.
2. Hỏi giá → PHẢI dùng get_price tool. KHÔNG tự bịa số tiền.
3. Hỏi thông số kỹ thuật (công suất, quãng đường, pin, kích thước, túi khí, ADAS) → PHẢI dùng get_specs tool. BẮT BUỘC dùng parameter category để lọc:
   - Hỏi về sạc, pin, thời gian sạc → category="battery"
   - Hỏi về công suất, mô-men xoắn, tốc độ, tăng tốc → category="powertrain"
   - Hỏi về kích thước, chiều dài, rộng, cao, khoảng sáng gầm → category="dimension"
   - Hỏi về phạm vi di chuyển, quãng đường → category="battery"
   - Hỏi về túi khí, phanh, an toàn → category="safety"
   - Hỏi về nội thất, ghế, màn hình → category="interior"
   - Hỏi về ngoại thất, đèn, mâm → category="exterior"
   - Hỏi về ADAS, cruise, lane → category="adas"
   - Nếu không chắc category nào → KHÔNG truyền category (lấy tất cả).
4. Hỏi tính năng/trang bị (HUD, camera, loa, đèn, gương...) → dùng search_all để lấy từ CẢ specs VÀ knowledge base.
5. So sánh, gợi ý, tư vấn ("nên mua", "khác nhau", "xe nào tốt", "phù hợp") → PHẢI dùng search_all cho TỪNG model liên quan. Cần cả specs (số liệu) lẫn knowledge base (mô tả tính năng).
6. Hỏi về màu sắc, màu nội thất, tùy chọn màu → PHẢI dùng get_colors. KHÔNG dùng search_knowledge_base cho câu hỏi về màu.
7. Hỏi tính năng/mô tả/màu sắc/chính sách → dùng search_knowledge_base.
6. Hỏi về model, phiên bản, danh sách xe → dùng list_available_models hoặc get_specs.
7. KHÔNG được trả lời từ kiến thức sẵn có. PHẢI gọi tool cho MỖI model riêng biệt.
8. Không tự bịa số liệu.
9. Dẫn nguồn (URL) khi có.
10. Nếu tool không có dữ liệu → trả lời "Mình chưa thể xác nhận thông tin này từ nguồn đã được phê duyệt hiện có."
11. Khi model đã rõ → PHẢI gọi get_specs hoặc search_all. KHÔNG gọi ask_clarification khi model đã rõ.

## Khi nào gọi ask_clarification
Chỉ gọi khi thiếu model (không biết người dùng hỏi xe nào).

### KHÔNG gọi ask_clarification khi:
- Câu hỏi đã có model rõ ràng.
- Thông số giống nhau giữa các phiên bản.
- Người dùng hỏi về danh sách phiên bản.
"""


SYNTHESIZE_PROMPT = """Bạn là trợ lý tư vấn xe VinFast. Tổng hợp thông tin dưới đây thành câu trả lời ngắn gọn, chính xác.

QUAN TRỌNG:
- Context đã có đủ thông tin. KHÔNG hỏi lại model, version hay topic.
- PHẢI dẫn nguồn (URL) khi có.
- CHỈ dùng thông tin trong context. KHÔNG thêm thông tin ngoài context.
- KHÔNG tự bịa số liệu. KHÔNG dùng kiến thức sẵn có.
- KHI SO SÁNH: mỗi model có specs riêng. KHÔNG lấy specs model A gán cho model B.
- Nếu context không có thông tin được hỏi → nói rõ: "Thông tin về [topic] hiện chưa có trong dữ liệu đã được phê duyệt cho [model]."
- Nếu context chỉ có một phần thông tin → trả lời phần có, nói rõ phần chưa có.
- Nếu context có specs cho model A nhưng không có cho model B → chỉ trả lời cho model A, nói rõ model B chưa có dữ liệu.

Context:
{context}

Câu hỏi: {query}
"""


async def get_system_prompt() -> str:
    global _prompt_cache, _prompt_cache_time
    if _prompt_cache and (time.time() - _prompt_cache_time) < _CACHE_TTL:
        return _prompt_cache

    pg_url = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(pg_url)

    rows = await conn.fetch(
        "SELECT model_id, model_label, year_range, "
        "STRING_AGG(edition_id, ', ' ORDER BY edition_id) as editions "
        "FROM edition_active "
        "GROUP BY model_id, model_label, year_range "
        "UNION "
        "SELECT '' as model_id, model_code AS model_label, '' as year_range, "
        "STRING_AGG(DISTINCT version_name, ', ' ORDER BY version_name) as editions "
        "FROM car_specs "
        "WHERE model_code NOT IN (SELECT DISTINCT model_label FROM edition_active) "
        "AND model_code IS NOT NULL AND version_name IS NOT NULL "
        "GROUP BY model_code "
        "ORDER BY model_label"
    )

    await conn.close()

    lines = []
    for r in rows:
        yr = f" ({r['year_range']})" if r["year_range"] else ""
        editions = r["editions"] or ""
        lines.append(f"- {r['model_label']}{yr} — Phiên bản: {editions}")

    model_list = "\n".join(lines) if lines else "- Chưa có model nào trong hệ thống"

    result = SYSTEM_PROMPT.format(model_list=model_list)
    _prompt_cache = result
    _prompt_cache_time = time.time()
    return result


def get_prompt_hash() -> str:
    global _prompt_hash
    if _prompt_hash is None:
        _prompt_hash = hashlib.sha256(SYSTEM_PROMPT.encode('utf-8')).hexdigest()[:12]
    return _prompt_hash
