#!/usr/bin/env python3
"""
spec_common.py — Dữ liệu + helper dùng chung cho các bước clean data.

Tránh duplicate giữa clean_to_jsonl.py và parse_specs.py:
  - MODEL_LABEL / MODEL_EDITIONS   mapping model → label / editions
  - no_diacritics                  bỏ dấu tiếng Việt (giữ nguyên hoa/thường)
  - parse_raw_file                 parse header crawl + body từ data/raw{,/_pdf}
  - infer_model                    rút model_id từ tên file

Lưu ý hành vi (đừng đổi nếu không có lý do — sẽ thay đổi output pipeline):
  - no_diacritics KHÔNG lowercase và chỉ xử lý 'đ' thường; caller muốn đổi cả
    'Đ' hoa phải tự .lower() trước (xem norm() trong parse_specs).
"""

import re
import unicodedata
from pathlib import Path
from typing import Any

MODEL_LABEL = {
    "VF2": "VF 2",
    "VF3": "VF 3",
    "VF5": "VF 5",
    "VF6": "VF 6",
    "VF7": "VF 7",
    "VF8": "VF 8",
    "VF8NEW": "VF 8 All New",
    "VF9": "VF 9",
    "VFMPV7": "VF MPV 7",
}

# Danh sách edition theo thứ tự giá tăng dần — dùng để gán edition khi
# dat-coc page không in rõ edition (block rẻ nhất = edition đầu).
MODEL_EDITIONS = {
    "VF2": ["TieuChuan"],
    "VF3": ["Eco", "Plus"],
    "VF5": ["Plus"],
    "VF6": ["Eco", "Plus"],
    "VF7": ["Eco", "Plus", "PlusCaptain", "Plus_AWD", "Plus_AWD_PanoramicRoof"],
    "VF8": ["Eco", "Plus"],
    "VF8NEW": ["The All New"],
    "VF9": ["Eco", "Plus", "PlusCaptain"],
    "VFMPV7": ["Eco", "Plus"],
}

# Alias edition từ nguồn spec sheet (model_data/*.csv) → edition chuẩn trong
# MODEL_EDITIONS — đồng bộ giữa car_specs (spec sheet) và edition/price_list
# (dat-coc page). VD: spec sheet "VF 7 Plus AWD" = variant GC12V_T023 trên
# trang dat-coc → edition chuẩn "Plus_AWD".
EDITION_ALIASES = {
    "VF7": {"Plus AWD": "Plus_AWD"},
}


def no_diacritics(s: str) -> str:
    """Bỏ dấu tiếng Việt → so khớp label/section không phân biệt dấu.

    Giữ nguyên hoa/thường, chỉ thay 'đ' thường → 'd' ('Đ' hoa giữ nguyên —
    caller muốn đổi cả 'Đ' thì .lower() trước).
    """
    return "".join(c for c in unicodedata.normalize("NFD", s)
                  if unicodedata.category(c) != "Mn").replace("đ", "d")


def parse_raw_file(path: Path) -> tuple[dict[str, Any], str]:
    """Parse file crawl output: header comments (# Nguồn / # Crawl lúc /
    # Loại / # Selector) + body sau dòng `====`."""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = {"source_url": "", "fetched_at": "", "source_type": "", "selector": ""}
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# Nguồn:"):
            meta["source_url"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Crawl lúc:"):
            meta["fetched_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Loại:"):
            meta["source_type"] = line.split(":", 1)[1].strip().lower()
        elif line.startswith("# Selector:"):
            meta["selector"] = line.split(":", 1)[1].strip()
        elif re.match(r"^={5,}$", line.strip()):
            body_start = i + 1
            break
    return meta, "\n".join(lines[body_start:])


def infer_model(path: Path) -> str | None:
    """Rút model_id từ tên file (vf3, vf5, vf8-the-all-new, mpv7...)."""
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    # Sắp xếp key dài → ngắn để tránh false match:
    # VD "vf206" match "vf2" trước "vf6" → sai; "vf8theallnew" match trước "vf8".
    _MODEL_KEYS = sorted([
        ("mpv7", "VFMPV7"),
        ("vf206", "VF6"), ("vf6", "VF6"),
        ("vf2", "VF2"), ("vf3", "VF3"), ("vf5", "VF5"),
        ("vf7", "VF7"), ("vf8theallnew", "VF8NEW"),
        ("vf8thenew", "VF8NEW"), ("vf8allnew", "VF8NEW"),
        ("vf8", "VF8"), ("vf9", "VF9"),
    ], key=lambda x: -len(x[0]))
    for key, model in _MODEL_KEYS:
        if key in name:
            return model
    return None
