#!/usr/bin/env python3
"""
format_brochure_specs.py — Preprocess brochure PDF text extracts: detect spec
sheet pages (bảng thông số so sánh Eco/Plus) và format lại thành feature→value
pairs dễ đọc, trước khi đưa vào clean_to_jsonl.py.

Input:  data/brochure/*.txt          (raw crawl output — header comments + body)
Output: data/raw/<same_name>.txt     (spec sheet pages đã format, sẵn cho pipeline)

Usage:
    python scripts/clean_data/format_brochure_specs.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BROCHURE_DIR = REPO_ROOT / "data" / "brochure"
RAW_DIR = REPO_ROOT / "data" / "raw"

PAGE_MARKER_RE = re.compile(r"---\s*Trang\s*(\d+)\s*---")

# ── Helpers ───────────────────────────────────────────────────────────────


def _is_val(l: str) -> bool:
    """True nếu dòng là giá trị (số, Có/Không)."""
    s = l.strip()
    if not s:
        return False
    if re.match(r'^[\d.,]', s):
        return True
    if s.rstrip(',').strip() in ('Có', 'Không'):
        return True
    return False


def _is_disclaimer(l: str) -> bool:
    """True nếu dòng thuộc disclaimer (pháp lý, mô tả chung)."""
    kw = ('thông số kỹ thuật', 'tính năng', 'quãng đường', 'hình ảnh',
          'tham khảo', 'để đảm bảo', 'thông tin sản phẩm', 'có thể thay đổi',
          'sẽ chưa có sẵn', 'sử dụng pin', 'mang tính chất')
    low = l.lower().strip('* ')
    return any(k in low for k in kw)


def _is_sec_header(l: str) -> bool:
    """True nếu là section header thật (ALL-CAPS, >2 ký tự, ko phải giá trị)."""
    return l.isupper() and len(l) > 2 and not _is_val(l)


def _split_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split lines thành alternating feature/value blocks dùng _is_val."""
    if not lines:
        return []
    blocks: list[tuple[str, list[str]]] = []
    cur_type = 'val' if _is_val(lines[0]) else 'feat'
    cur: list[str] = []
    for l in lines:
        lt = 'val' if _is_val(l) else 'feat'
        if lt != cur_type and len(cur) >= 2:
            blocks.append((cur_type, cur))
            cur = []
            cur_type = lt
        cur.append(l)
    if cur:
        blocks.append((cur_type, cur))
    return blocks


# ── Spec sheet formatting ─────────────────────────────────────────────────


def _format_spec(lines: list[str]) -> str:
    """Format spec sheet từ lines → structured feature→value pairs."""
    # Bỏ disclaimer đầu tiên
    while lines and (lines[0].startswith('*') or _is_disclaimer(lines[0])
                     or len(lines[0]) < 4):
        lines.pop(0)

    if not lines:
        return '\n'.join(lines)

    # Check VF8 pattern: có marker VF x ECO / VF x PLUS trong 50% đầu trang
    eco_idx = plus_idx = None
    half = len(lines) // 2
    for i, l in enumerate(lines):
        if re.match(r'^VF\s+\w+\s+ECO$', l, re.I):
            eco_idx = i
        if re.match(r'^VF\s+\w+\s+PLUS$', l, re.I):
            plus_idx = i
    if (eco_idx is not None and plus_idx is not None
            and plus_idx > eco_idx and eco_idx < half):
        return _do_pair(lines[:eco_idx],
                        lines[eco_idx + 1:plus_idx],
                        lines[plus_idx + 1:])

    # Strategy B — VF6: tìm dòng first value → boundary
    first_val = next((i for i, l in enumerate(lines) if _is_val(l)), None)
    if first_val is None or first_val < 3:
        return '\n'.join(lines)
    features = lines[:first_val]
    values = lines[first_val:]
    mid = len(values) // 2
    return _do_pair(features, values[:mid], values[mid:])


def _do_pair(features: list[str], eco_vals: list[str],
             plus_vals: list[str]) -> str:
    """Pair features với giá trị Eco/Plus."""
    parts: list[str] = []

    # Ghép feature bị clean_line/xuống dòng
    merged: list[str] = []
    for f in features:
        if (merged and not f.isupper() and len(f) < 30
                and len(merged[-1]) > 40 and not f.startswith('*')):
            merged[-1] = merged[-1] + ' ' + f
        else:
            merged.append(f)

    # Dedup trùng
    seen: set[str] = set()
    uniq = []
    for f in merged:
        k = f.strip().lower()
        if k not in seen:
            seen.add(k)
            uniq.append(f)

    # Dùng ALL lines từ value blocks (ko filter = mất giá trị text như "Giả da")
    eco_clean = [v for v in eco_vals if not _is_sec_header(v)]
    plus_clean = [v for v in plus_vals if not _is_sec_header(v)]

    i_f = i_e = i_p = 0
    nf, ne, np = len(uniq), len(eco_clean), len(plus_clean)

    # Pair feature ↔ eco[i] | plus[i]
    while i_f < nf and i_e < ne and i_p < np:
        f = uniq[i_f]
        if _is_sec_header(f):
            parts.append(f'▌ {f}')
            i_f += 1
            continue
        parts.append(f'  → {f}:  {eco_clean[i_e]}  |  {plus_clean[i_p]}')
        i_f += 1
        i_e += 1
        i_p += 1

    while i_f < nf:
        f = uniq[i_f]
        parts.append(f'▌ {f}' if _is_sec_header(f) else f'  → {f}')
        i_f += 1

    return '\n'.join(parts)


# ── Page-level ────────────────────────────────────────────────────────────


def _is_spec_sheet_page(text: str) -> bool:
    """Heuristics: page có phải spec sheet không.

    Nhận diện spec sheet qua:
    - Có title "thông số kỹ thuật"
    - Có marker VF x ECO / VF x PLUS
    - Hoặc mật độ dòng giá trị cao."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 8:
        return False
    has_title = any('thông số kỹ thuật' in l.lower() for l in lines[:5])
    has_markers = any(re.match(r'^VF\s+\w+\s+(ECO|PLUS)$', l, re.I) for l in lines)
    val_cnt = sum(1 for l in lines if _is_val(l))
    if has_title or has_markers:
        return val_cnt >= 6
    return val_cnt >= max(12, len(lines) * 0.30)


def format_spec_sheet(text: str) -> str:
    """Detect + format spec sheet page. Return text gốc nếu không phải."""
    if not _is_spec_sheet_page(text):
        return text
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = _format_spec(lines)
    return result if result else text


def split_pages(body: str) -> list[tuple[int | None, str]]:
    """Split body text by ``--- Trang N ---`` markers."""
    raw_parts = PAGE_MARKER_RE.split(body)
    pages: list[tuple[int | None, str]] = []
    if raw_parts[0].strip():
        pages.append((None, raw_parts[0].strip()))
    for i in range(1, len(raw_parts) - 1, 2):
        page_num = int(raw_parts[i])
        content = raw_parts[i + 1].strip()
        if content:
            pages.append((page_num, content))
    return pages


def format_brochure_file(in_path: Path) -> str:
    """Read 1 raw brochure → format spec sheet pages → output string."""
    text = in_path.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()

    # Tách header comments khỏi body
    header_lines: list[str] = []
    body_start = 0
    in_header = True
    for i, line in enumerate(lines):
        if in_header:
            if (line.startswith('#')
                    or re.match(r'^={5,}$', line.strip())
                    or not line.strip()):
                header_lines.append(line)
            else:
                body_start = i
                in_header = False

    raw_body = '\n'.join(lines[body_start:])

    # Format từng page
    pages = split_pages(raw_body)
    out_parts: list[str] = []
    for page_num, content in pages:
        formatted = format_spec_sheet(content)
        if page_num is not None:
            out_parts.append(f'--- Trang {page_num} ---')
        out_parts.append(formatted)

    return '\n'.join(header_lines) + '\n' + '\n'.join(out_parts)


# ── CLI ───────────────────────────────────────────────────────────────────

def run() -> int:
    if not BROCHURE_DIR.exists():
        print(f'[format_brochure_specs] input dir not found: {BROCHURE_DIR}',
              file=sys.stderr)
        return 1
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for path in sorted(BROCHURE_DIR.iterdir()):
        if not path.is_file() or path.suffix not in ('.txt',):
            continue
        print(f'[format_brochure_specs] {path.name} ...', end=' ')
        try:
            formatted = format_brochure_file(path)
            out_path = RAW_DIR / path.name
            out_path.write_text(formatted, encoding='utf-8')
            print(f'→ {len(formatted)} bytes → {out_path.name}')
            n_ok += 1
        except Exception as e:
            print(f'ERROR: {e}', file=sys.stderr)
    print(f'[format_brochure_specs] done. {n_ok} files written.')
    return 0


def main() -> int:
    return run()


if __name__ == '__main__':
    sys.exit(main())
