"""Sanitize history từ client — CHỐNG prompt injection.

History là dữ liệu KHÔNG TIN TƯỞNG (client tự do khai báo). Hàm này biến nó
thành danh sách message hợp lệ, sẵn sàng đưa vào prompt:
- Chỉ giữ role ∈ {user, assistant} — bỏ role system/tool/khác (chống injection)
- Ép xen kẽ user → assistant; bỏ assistant lẻ đầu, bỏ user cuối chưa có reply
- Cap độ dài từng message theo role (khớp token limits: user 1000 / assistant 4000)
- Giữ tối đa WINDOW_TURNS turn gần nhất (mặc định 7)
- Cap tổng token (lớp phòng thủ thứ 2 sau check ở API)
"""

from app.agent.llm import estimate_tokens

# Window mặc định: số turn gần nhất được giữ (1 turn = 1 cặp user + assistant)
WINDOW_TURNS = 7

# Cap từng message theo role (chars) — khớp token limits đã chốt:
#   user: 1000 token (~4000 ký tự) — khớp LLM_USER_INPUT_MAX_TOKENS
#   assistant: 4000 token (~16000 ký tự) — khớp LLM_MAX_OUTPUT_TOKENS
_MAX_MSG_CHARS = {"user": 4000, "assistant": 16000}

# Cap tổng history (token) — phòng client gửi request khổng lồ
MAX_HISTORY_TOKENS = 30000

_TRUNCATED = "\n…[bị cắt do vượt giới hạn]"

_ALLOWED_ROLES = {"user", "assistant"}


def _cap_message(role: str, content: str) -> str:
    """Cắt content về tối đa số ký tự cho phép theo role."""
    if isinstance(content, str) and len(content) > _MAX_MSG_CHARS[role]:
        return content[: _MAX_MSG_CHARS[role]] + _TRUNCATED
    return content


def sanitize_history(
    history: list[dict],
    window_turns: int = WINDOW_TURNS,
    max_tokens: int = MAX_HISTORY_TOKENS,
) -> list[dict]:
    """Lọc + chuẩn hoá history client gửi lên → list message hợp lệ.

    Không bao giờ raise — history rác bị bỏ im lặng (fail-closed, an toàn).
    Output: [{role: "user"|"assistant", content: str}, ...] xen kẽ, turn đã hoàn thành.
    """
    if not history:
        return []

    # 1) Chỉ giữ role hợp lệ (bỏ system/tool/khác → chặn injection)
    cleaned = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", ""))
        if role in _ALLOWED_ROLES:
            cleaned.append({"role": role, "content": m.get("content") or ""})

    # 2) Ép xen kẽ user → assistant:
    #    - bỏ assistant lẻ đầu (không có user trước)
    #    - user/assistant trùng liên tiếp → giữ message MỚI hơn
    merged: list[dict] = []
    for m in cleaned:
        role = m["role"]
        if not merged:
            if role == "assistant":
                continue
            merged.append(m)
            continue
        if merged[-1]["role"] == role:
            merged[-1] = m  # trùng role → thay bằng message mới nhất
            continue
        merged.append(m)

    # Nếu kết thúc bằng user → turn chưa hoàn thành, bỏ
    # (quy ước: history chỉ chứa turn ĐÃ xong, tin đang gửi nằm ở `message`)
    if merged and merged[-1]["role"] == "user":
        merged.pop()

    # 3) Cap từng message theo role
    merged = [{"role": m["role"], "content": _cap_message(m["role"], m["content"])} for m in merged]

    # 4) Chỉ giữ window_turns turn gần nhất (cắt theo cặp 2 message, từ đầu)
    max_msgs = window_turns * 2
    if len(merged) > max_msgs:
        merged = merged[-max_msgs:]

    # 5) Cap tổng token: drop dần turn cũ nhất (từ đầu) — luôn giữ trọn cặp
    while len(merged) >= 2 and sum(estimate_tokens(m["content"]) for m in merged) > max_tokens:
        merged = merged[2:]

    return merged
