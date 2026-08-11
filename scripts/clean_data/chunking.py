#!/usr/bin/env python3
"""
chunking.py — Chunking theo câu (sentence-aware) cho chunks quá dài.

Tách từ clean_to_jsonl.py. Quy tắc:
  - max_len=800 (mặc định), cắt ở biên câu, overlap = câu cuối hoàn chỉnh
    của mảnh trước (khớp cửa sổ embedding ~128 token).
  - bảng markdown → lặp lại header ở mỗi mảnh (split_table).
  - câu đơn quá dài (không có biên câu / "; ") → cắt theo ký tự
    (split_long_line).
"""

import re
from typing import Any


def split_sentences(text: str, max_len: int) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    sents: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Sub-split rất dài không có dấu câu (specs key:value nối bằng "; ")
        if len(p) > max_len and "; " in p:
            sents.extend(s.strip() for s in p.split("; ") if s.strip())
        else:
            sents.append(p)
    return sents


def split_long_line(s: str, max_len: int, overlap: int = 80) -> list[str]:
    """Fallback: 1 câu dài không có biên câu -> cắt theo ký tự ở biên câu/"; "/space."""
    pieces: list[str] = []
    start, n = 0, len(s)
    while start < n:
        end = min(start + max_len, n)
        if end < n:
            for sep in (". ", "; ", " "):
                cut = s.rfind(sep, start, end)
                if cut > start + max_len // 2:
                    end = cut + len(sep)
                    break
        piece = s[start:end].strip()
        if piece:
            pieces.append(piece)
        if end < n:
            next_start = end - overlap
            sp = s.find(" ", next_start)
            if 0 <= sp < n:
                next_start = sp + 1
            start = max(next_start, start + 1)
        else:
            start = n
    return pieces


def split_table(text: str, max_len: int) -> list[str]:
    """Bảng markdown: lặp header ở mỗi mảnh, mảnh ≤ max_len."""
    lines = text.split("\n")
    header, body = lines[0:2], lines[2:]
    pieces, cur, cur_len = [], [], 0
    for line in body:
        add = len(line) + 1
        if cur and cur_len + add > max_len:
            pieces.append("\n".join(header + cur).strip())
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += add
    if cur:
        pieces.append("\n".join(header + cur).strip())
    return [p for p in pieces if p.strip()] or [text]


def split_by_sentences(text: str, max_len: int = 800) -> list[str]:
    """Sentence-aware split: gom câu tới max_len, cắt ở biên câu,
    overlap = câu cuối hoàn chỉnh của mảnh trước."""
    sents = split_sentences(text, max_len)
    pieces, buf, last = [], "", ""
    for s in sents:
        if buf and len(buf) + 1 + len(s) > max_len:
            pieces.append(buf.strip())
            if last and len(last) + 1 + len(s) <= max_len:
                buf = last + " " + s
            else:
                buf = s
        else:
            buf = (buf + " " + s) if buf else s
        last = s
    if buf:
        pieces.append(buf.strip())
    # hard fallback: câu đơn vẫn > max_len (không có biên câu/"; ") -> cắt ký tự
    final: list[str] = []
    for p in pieces:
        if len(p) > max_len:
            final.extend(split_long_line(p, max_len))
        else:
            final.append(p)
    return [p for p in final if len(p.strip()) >= 20]


def apply_chunking(chunks: list[dict[str, Any]], max_len: int = 800) -> list[dict[str, Any]]:
    """Chunk > max_len -> cắt theo câu (bảng thì lặp header). Giữ metadata gốc."""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if len(chunk["text"]) <= max_len:
            out.append(chunk)
            continue
        lines = chunk["text"].split("\n")
        if lines and lines[0].lstrip().startswith("|") and len(lines) >= 2 \
                and lines[1].strip().startswith("|") and "---" in lines[1]:
            pieces = split_table(chunk["text"], max_len)
        else:
            pieces = split_by_sentences(chunk["text"], max_len)
        for p in pieces:
            out.append({**chunk, "text": p})
    return out
