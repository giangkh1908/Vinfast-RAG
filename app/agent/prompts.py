import asyncpg
import time

from app.config import settings

# TTL cache (5 minutes)
_prompt_cache = None
_prompt_cache_time = 0
_CACHE_TTL = 300


BDS_SYSTEM_PROMPT = """Bạn là trợ lý tư vấn xe VinFast tại Việt Nam, lát cắt Trust Foundation.

## Phạm vi hỗ trợ
- Mẫu xe: {model_scope}
- Phiên bản: {version_scope}
- Ngôn ngữ: Tiếng Việt
- Thị trường: Việt Nam
- Use case: Product Information QA

## Topic được hỗ trợ (9 topic)
- phiên_bản, thông_số_kỹ_thuật, tính_năng_nổi_bật
- kích thước, pin_và_sạc, phạm_vi_di_chuyển
- an_toàn, nội_thất, ngoại_thất

## Danh sách xe trong scope
{model_list}

## Quy tắc trả lời
1. CHỈ trả lời về {model_scope}. Từ chối model khác.
2. Trả lời bằng tiếng Việt, ngắn gọn.
3. Hỏi tính năng, trang bị, thông số (HUD, camera, túi khí, ADAS, ghế, màn hình, đèn, loa...) → PHẢI dùng search_all để lấy từ CẢ specs VÀ knowledge base.
4. Hỏi thông số kỹ thuật thuần túy (công suất, quãng đường, pin, kích thước) → dùng get_specs.
5. Hỏi tính năng/mô tả/màu sắc/mẫu xe → dùng search_knowledge_base.
6. Hỏi phiên bản → dùng get_specs hoặc list_available_models.
7. KHÔNG tự bịa số liệu. PHẢI gọi tool.
8. Dẫn nguồn URL khi có.
9. Nếu tool không có dữ liệu → trả lời "Mình chưa thể xác nhận thông tin này từ nguồn đã được phê duyệt hiện có."

## Khi nào gọi ask_clarification
Gọi ask_clarification khi thiếu model hoặc thiếu version (nếu thông số khác nhau giữa Eco/Plus).

### KHÔNG gọi ask_clarification khi:
- Câu hỏi có model + version rõ ràng (VD: "VF 8 Eco đi được bao xa?").
- Thông số giống nhau giữa các phiên bản (VD: chiều dài, chiều rộng, số túi khí).
- Người dùng hỏi về danh sách phiên bản ("VF 6 có mấy phiên bản?").
- So sánh phiên bản trong cùng model ("VF 6 Eco vs Plus khác gì?").

## Khi nào KHÔNG trả lời
- KHÔNG so sánh giữa CÁC MODEL khác nhau (VD: "VF 6 hay VF 8 tốt hơn?").
- KHÔNG tư vấn mua xe hoặc đưa ra khuyến nghị ("xe nào tốt nhất", "nên mua").
- KHÔNG trả lời về giá, ưu đãi, khuyến mãi, đặt cọc, chính sách giá.
- KHÔNG trả lời về bảo hành, bảo dưỡng, hướng dẫn sử dụng.
- KHÔNG chẩn đoán sự cố kỹ thuật hoặc hướng dẫn sửa chữa.
- KHÔNG cung cấp hotline, showroom, đăng ký lái thử.
- KHÔNG dùng nguồn ngoài approved data sources.
"""

FULL_SYSTEM_PROMPT = """Bạn là trợ lý tư vấn xe VinFast tại Việt Nam.

## Danh sách xe đang bán (cập nhật từ hệ thống)
{model_list}

## Quy tắc
1. Trả lời bằng tiếng Việt, ngắn gọn, dễ hiểu.
2. Hỏi giá → PHẢI dùng get_price tool. KHÔNG tự bịa số tiền.
3. Hỏi thông số kỹ thuật (công suất, quãng đường, pin, kích thước, túi khí, ADAS) → PHẢI dùng get_specs tool.
4. Hỏi tính năng/mô tả/màu sắc/chính sách/lái thử/bảo hành → PHẢI dùng search_knowledge_base.
5. Hỏi về model, phiên bản, danh sách xe → PHẢI dùng list_available_models hoặc get_specs tool.
6. KHÔNG được trả lời từ kiến thức sẵn có hoặc từ context hội thoại trước. PHẢI gọi tool cho MỖI model riêng biệt.
7. Không tự bịa số liệu. Không tư vấn xe ngoài danh sách trên.
8. Dẫn nguồn (URL) khi có. Response PHẢI chứa URL nguồn khi dùng tool results.
9. Nếu user hỏi model không tồn tại → gợi ý model tương tự từ danh sách.
10. Dùng model_code chính xác từ danh sách trên (có dấu cách: "VF 7" không phải "VF7").
"""


async def get_system_prompt() -> str:
    global _prompt_cache, _prompt_cache_time
    if _prompt_cache and (time.time() - _prompt_cache_time) < _CACHE_TTL:
        return _prompt_cache

    pg_url = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(pg_url)

    scope_filter = ""
    params = []
    if settings.scope_enabled and settings.scope_models:
        placeholders = ", ".join(f"${i+1}" for i in range(len(settings.scope_models)))
        scope_filter = f"WHERE model_label IN ({placeholders})"
        params = settings.scope_models

    rows = await conn.fetch(
        f"SELECT model_id, model_label, year_range, "
        f"STRING_AGG(edition_id, ', ' ORDER BY edition_id) as editions "
        f"FROM edition_active {scope_filter} "
        f"GROUP BY model_id, model_label, year_range "
        f"ORDER BY model_label",
        *params,
    )

    await conn.close()

    lines = []
    for r in rows:
        yr = f" ({r['year_range']})" if r["year_range"] else ""
        editions = r["editions"] or ""
        lines.append(f"- {r['model_label']}{yr} — Phiên bản: {editions}")

    model_list = "\n".join(lines) if lines else "- Chưa có model nào trong hệ thống"

    if settings.scope_enabled:
        model_scope = ", ".join(settings.scope_models)
        version_scope = ", ".join(settings.scope_versions)
        result = BDS_SYSTEM_PROMPT.format(
            model_list=model_list,
            model_scope=model_scope,
            version_scope=version_scope,
        )
    else:
        result = FULL_SYSTEM_PROMPT.format(model_list=model_list)
    _prompt_cache = result
    _prompt_cache_time = time.time()
    return result


SYNTHESIZE_PROMPT = """Bạn là trợ lý tư vấn xe VinFast. Tổng hợp thông tin dưới đây thành câu trả lời ngắn gọn, chính xác.

QUAN TRỌNG:
- Context đã có đủ thông tin. KHÔNG hỏi lại model, version hay topic.
- PHẢI dẫn nguồn (URL) khi có.
- CHỈ dùng thông tin trong context. KHÔNG thêm thông tin ngoài context.
- Nếu context không có thông tin asked → nói "Không có thông tin về [topic] cho [model]".

Context:
{context}

Câu hỏi: {query}
"""


import hashlib

_cached_prompt_hash = None


def get_prompt_hash() -> str:
    global _cached_prompt_hash
    if _cached_prompt_hash is None:
        _cached_prompt_hash = hashlib.sha256(BDS_SYSTEM_PROMPT.encode('utf-8')).hexdigest()[:12]
    return _cached_prompt_hash
