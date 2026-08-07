#!/usr/bin/env python3
"""
Crawler generic — nhập link, tự crawl bất kỳ trang web nào, lấy dữ liệu thô.

Cách dùng:
    python scripts/crawl.py <URL>
    python scripts/crawl.py <URL> --out raw.txt          # chỉ định file output
    python scripts/crawl.py <URL> --html                  # lưu thêm HTML gốc
    python scripts/crawl.py <URL> --selector "article"    # chỉ crawl vùng có selector CSS (chỉ HTML)

Hỗ trợ cả PDF: tự nhận diện qua Content-Type / đuôi .pdf, rút text thô bằng pymupdf
(fallback pdfplumber). Khi là PDF, --selector bị bỏ qua.

Output mặc định: data/raw/<slug>_<timestamp>.txt  (text thô)
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

# Header giống trình duyệt thật — nhiều site chặn nếu thiếu / dùng UA mặc định.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en;q=0.9",
}

# Các tag không mang nội dung text có ý nghĩa — bỏ đi cho text thô sạch hơn.
DROP_TAGS = ["script", "style", "noscript", "iframe", "svg", "template",
             "nav", "footer", "header", "form", "button"]

# Tag inline: text của chúng nằm cùng dòng, không tạo block mới.
INLINE_TAGS = {"a", "span", "strong", "b", "em", "i", "u", "s", "small",
               "sub", "sup", "mark", "code", "abbr", "cite", "q", "time",
               "label", "font", "tt", "kbd"}

# Tag block-level sẽ được render riêng; các tag container khác (div, section...)
# được đệ quy vào con.
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = HEADING_TAGS | {"p", "ul", "ol", "li", "table", "tr", "blockquote",
                             "pre", "hr", "dl", "figure", "figcaption", "address"}


def slugify(url: str) -> str:
    """Tạo tên file an toàn từ URL."""
    p = urlparse(url)
    base = (p.path.strip("/").replace("/", "_") or p.netloc.replace(".", "_"))
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)
    return base[:80] or "page"


def fetch(url: str, timeout: int = 30) -> "requests.Response":
    """Tải tài nguyên (HTML hoặc PDF), có retry nhẹ khi bị lỗi mạng. Trả về Response."""
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            # Một số site chặn UA → thử thêm referer rồi retry nếu 403.
            if r.status_code == 403 and attempt == 0:
                HEADERS["Referer"] = urlparse(url).scheme + "://" + urlparse(url).netloc + "/"
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"Không tải được {url}: {last_err}")


def fetch_firecrawl(url: str) -> tuple[str, str]:
    """Crawl bằng Firecrawl API (cloud): scrape + JS render + markdown server-side.

    Dùng cho trang SPA/JS-render (vd shop.vinfastauto.com — bảng thông số kỹ thuật
    tải động sau load mà `requests` không bắt được). Cần FIRECRAWL_API_KEY trong .env.
    Trả (markdown, title).
    """
    import os
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        raise RuntimeError(
            "FIRECRAWL_API_KEY chưa set trong .env (lấy tại https://firecrawl.dev)"
        )
    resp = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown"]},
        timeout=90,
    )
    data = resp.json()
    if resp.status_code != 200 or not data.get("success"):
        raise RuntimeError(f"Firecrawl API lỗi ({resp.status_code}): {data.get('error','')}")
    result = data.get("data", {}) or {}
    md = result.get("markdown", "")
    title = result.get("metadata", {}).get("title", "")
    return md, title


def is_pdf(resp: "requests.Response", url: str) -> bool:
    """Nhận diện PDF qua Content-Type hoặc đuôi URL."""
    ctype = resp.headers.get("Content-Type", "").lower()
    path = urlparse(url).path.lower()
    return "application/pdf" in ctype or path.endswith(".pdf")


def extract_pdf_text(content: bytes) -> str:
    """Rút text thô từ PDF. Dùng pymupdf (nhanh), fallback pdfplumber."""
    try:
        import fitz  # pymupdf
        text_parts = []
        with fitz.open(stream=content, filetype="pdf") as doc:
            for i, page in enumerate(doc, 1):
                text_parts.append(f"--- Trang {i} ---\n{page.get_text()}")
        return "\n\n".join(text_parts)
    except Exception as e_fitz:
        print(f"  (pymupdf lỗi: {e_fitz}; thử pdfplumber)")
        try:
            import pdfplumber
            import io
            text_parts = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    text_parts.append(f"--- Trang {i} ---\n{page.extract_text() or ''}")
            return "\n\n".join(text_parts)
        except Exception as e_plumb:
            raise RuntimeError(f"Không đọc được PDF: {e_plumb}")


def _inline_text(node) -> str:
    """Gom text của một node inline (và các con inline), <br> thành dấu cách."""
    from bs4 import NavigableString
    parts = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif child.name == "br":
            parts.append(" ")
        elif child.name == "img":
            alt = child.get("alt") or ""
            if alt:
                parts.append(alt)
        else:
            parts.append(_inline_text(child))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _render_table(node) -> str:
    rows = node.find_all("tr")
    if not rows:
        return ""
    md, header_done = [], False
    for r in rows:
        cells = r.find_all(["th", "td"])
        if not cells:
            continue
        vals = [_inline_text(c).replace("|", "\\|") or " " for c in cells]
        md.append("| " + " | ".join(vals) + " |")
        if not header_done:
            md.append("| " + " | ".join(["---"] * len(vals)) + " |")
            header_done = True
    return "\n".join(md) + "\n\n"


def _render_list(node, ordered: bool, depth: int = 0) -> str:
    lines, i = [], 1
    for li in node.find_all("li", recursive=False):
        marker = f"{i}." if ordered else "-"
        i += 1
        text_parts, nested = [], []
        for child in li.children:
            if isinstance(child, str):
                if child.strip():
                    text_parts.append(child)
            elif child.name in ("ul", "ol"):
                nested.append(_render_list(child, child.name == "ol", depth + 1))
            elif child.name == "br":
                text_parts.append(" ")
            else:
                txt = _inline_text(child) if child.name in INLINE_TAGS else _inline_text(child)
                if txt:
                    text_parts.append(txt)
        item = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
        indent = "  " * depth
        lines.append(f"{indent}{marker} {item}")
        for n in nested:
            lines.append(n.rstrip())
    return "\n".join(lines) + "\n\n"


def _breadcrumb(stack) -> str:
    return " > ".join(t for _, t in stack)


def _adjust_stack(stack, level: int, text: str) -> None:
    """Giữ stack heading theo cấp: pop các heading cùng cấp / sâu hơn trước khi push."""
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, text))


def _render_block_md(node, stack) -> str:
    """Render 1 block ngữ nghĩa, chèn marker chunk phía trước kèm breadcrumb + type."""
    name = node.name
    if name in HEADING_TAGS:
        level = int(name[1])
        txt = _inline_text(node)
        if not txt:
            return ""
        _adjust_stack(stack, level, txt)
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: section -->\n{'#' * level} {txt}\n"
    if name == "table":
        tbl = _render_table(node)
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: table -->\n{tbl}" if tbl.strip() else ""
    if name in ("ul", "ol"):
        lst = _render_list(node, name == "ol")
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: list -->\n{lst}" if lst.strip() else ""
    if name == "p":
        txt = _inline_text(node)
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: paragraph -->\n{txt}\n" if txt else ""
    if name == "blockquote":
        txt = _inline_text(node)
        if not txt:
            return ""
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: quote -->\n> {txt.replace(chr(10), chr(10) + '> ')}\n"
    if name == "pre":
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: code -->\n```\n{node.get_text()}\n```\n"
    if name == "hr":
        return "---\n"
    if name == "dl":
        out = []
        for dt in node.find_all("dt", recursive=False):
            dd = dt.find_next_sibling("dd")
            out.append(f"- **{_inline_text(dt)}**: {_inline_text(dd) if dd else ''}".strip())
        dl = "\n".join(out) + "\n"
        return f"<!-- chunk | path: {_breadcrumb(stack)} | type: list -->\n{dl}" if out else ""
    # container (div, section, article, figure, ...) -> đệ quy vào con, giữ nguyên stack.
    return _render_md(node, stack)


def _render_md(node, stack) -> str:
    """Duyệt con theo thứ tự document, gom inline text thành paragraph, render block."""
    from bs4 import NavigableString
    out, para = [], []

    def flush():
        if para:
            txt = re.sub(r"\s+", " ", " ".join(para)).strip()
            if txt:
                out.append(f"<!-- chunk | path: {_breadcrumb(stack)} | type: paragraph -->\n{txt}\n")
        para.clear()

    for child in node.children:
        if isinstance(child, NavigableString):
            s = str(child)
            if s.strip():
                para.append(s)
        elif child.name == "br":
            para.append(" ")
        elif child.name == "img":
            alt = child.get("alt") or ""
            if alt:
                para.append(alt)
        elif child.name in INLINE_TAGS:
            t = _inline_text(child)
            if t:
                para.append(t)
        elif child.name in BLOCK_TAGS or child.name in ("div", "section", "article",
                                                        "main", "aside", "figure",
                                                        "figcaption", "span"):
            flush()
            out.append(_render_block_md(child, stack))
        else:
            # tag lạ: đệ quy an toàn
            flush()
            out.append(_render_md(child, stack))
    flush()
    return "".join(out)


CHUNK_MARKER_RE = re.compile(r"<!-- chunk \| path: (.*?) \| type: (\w+) -->")


def parse_chunks(md_text: str) -> list[dict]:
    """Tách Markdown có marker thành list chunk {path, type, text}."""
    chunks = []
    cur_path, cur_type, buf = "", "", []

    def emit():
        body = "\n".join(buf).strip()
        if body:
            chunks.append({"path": cur_path, "type": cur_type, "text": body})

    for line in md_text.splitlines():
        m = CHUNK_MARKER_RE.match(line.strip())
        if m:
            emit()
            cur_path, cur_type = m.group(1), m.group(2)
            buf = []
        else:
            buf.append(line)
    emit()
    return chunks


def _clean_md(marker_md: str) -> str:
    """Bỏ các dòng marker chunk -> Markdown sạch để người đọc/verify."""
    lines = [l for l in marker_md.splitlines() if not CHUNK_MARKER_RE.match(l.strip())]
    md = "\n".join(lines)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def _split_oversized(chunk: dict, hard: int) -> list[dict]:
    """Tách 1 chunk quá lớn theo dòng. Nếu là bảng Markdown, lặp lại hàng header ở mỗi mảnh."""
    text = chunk["text"]
    lines = text.split("\n")
    header, body = [], lines
    if lines and lines[0].lstrip().startswith("|") and len(lines) >= 2:
        header, body = lines[0:2], lines[2:]  # hàng header + hàng phân tách `---`

    pieces, cur, cur_len = [], [], 0
    for line in body:
        add = len(line) + 1
        if cur and cur_len + add > hard:
            piece = (header + cur) if header else cur
            pieces.append({"path": chunk["path"], "type": chunk["type"],
                           "text": "\n".join(piece).strip()})
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += add
    if cur:
        piece = (header + cur) if header else cur
        pieces.append({"path": chunk["path"], "type": chunk["type"],
                       "text": "\n".join(piece).strip()})
    return pieces or [chunk]


def build_chunks(marker_md: str, target: int = 1000, hard: int = 1500) -> list[dict]:
    """
    Từ Markdown có marker -> chunk đã định cỡ:
    - merge: gộp chunk liên tiếp (kế thừa path rỗng từ path gần nhất) tới ~target ký tự.
    - split: chunk lớn quá hard -> tách theo dòng (bảng giữ header).
    """
    raw = parse_chunks(marker_md)

    merged, buf, buf_len, cur_path = [], [], 0, ""

    def flush():
        nonlocal buf, buf_len
        if not buf:
            return
        p = next((c["path"] for c in buf if c["path"]), cur_path)
        types = ",".join(sorted({c["type"] for c in buf}))
        text = "\n\n".join(c["text"] for c in buf).strip()
        if text:
            merged.append({"path": p, "type": types, "text": text})
        buf, buf_len = [], 0

    for c in raw:
        if c["path"]:
            cur_path = c["path"]
        c_eff = {"path": c["path"] or cur_path, "type": c["type"], "text": c["text"]}
        if buf and buf_len + len(c_eff["text"]) + 2 > target:
            flush()
        buf.append(c_eff)
        buf_len += len(c_eff["text"]) + 2
    flush()

    final = []
    for c in merged:
        final.extend(_split_oversized(c, hard) if len(c["text"]) > hard else [c])
    return final


def process_html(html: str, selector: str | None = None, plain: bool = False):
    """
    Rút nội dung HTML. Trả về (text_sạch, title, marker_md).
    - plain=True : text phẳng.
    - plain=False: Markdown sạch (cho .txt) + marker_md nội bộ (để build chunk).
    """
    from bs4 import BeautifulSoup  # lazy: chỉ cần cho crawl HTML thường (không Firecrawl)
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(selector) if selector else soup.body or soup
    if root is None:
        return "(không tìm thấy vùng nội dung với selector đã cho)", "", ""

    for tag in root.find_all(DROP_TAGS):
        tag.decompose()

    title = (soup.title.get_text(strip=True) if soup.title else "")
    title = title.split("|")[0].strip()  # bỏ suffix tên site kiểu "... | VinFast"

    if plain:
        text = root.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text), title, ""

    # Seed context: trang KHÔNG có h1 -> dùng <title> làm gốc breadcrumb.
    seed = [] if root.find("h1") else [(0, title)]
    marker_md = _render_md(root, seed)
    marker_md = re.sub(r"[ \t]+\n", "\n", marker_md)
    marker_md = re.sub(r"\n{3,}", "\n\n", marker_md).strip() + "\n"
    return _clean_md(marker_md), title, marker_md


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl raw text từ bất kỳ trang web nào.")
    ap.add_argument("url", help="URL trang cần crawl")
    ap.add_argument("--out", help="File output (mặc định: data/raw/<slug>_<ts>.txt)")
    ap.add_argument("--selector", help="Selector CSS để chỉ crawl một vùng (vd: 'article', 'div.node-detail')")
    ap.add_argument("--html", action="store_true", help="Lưu thêm file HTML gốc")
    ap.add_argument("--print", action="store_true", help="In text thô ra stdout ngoài việc lưu file")
    ap.add_argument("--plain", action="store_true",
                    help="HTML: xuất text phẳng thay vì Markdown có cấu trúc")
    ap.add_argument("--firecrawl", action="store_true",
                    help="Crawl bằng Firecrawl API (scrape + JS render + markdown cloud). "
                         "Cần FIRECRAWL_API_KEY trong .env")
    ap.add_argument("--split", action="store_true",
                    help="HTML (Markdown mode): tách thêm ra <out>.chunks.json — mỗi chunk "
                         "{path, type, text} đã merge/split, sẵn sàng cho embedding")
    args = ap.parse_args()

    print(f"→ Đang tải: {args.url}")
    if args.firecrawl:
        print("  → Crawl bằng Firecrawl API (scrape + JS render + markdown)...")
        text, fc_title = fetch_firecrawl(args.url)
        raw_bytes = text.encode("utf-8")
        kind = "html"
        title = fc_title
        marker_md = ""
        html = text  # cho nhánh --html (nếu dùng)
        print(f"  Đã tải {len(raw_bytes):,} bytes (markdown sau JS render)")
    else:
        resp = fetch(args.url)
        raw_bytes = resp.content
        print(f"  Đã tải {len(raw_bytes):,} bytes ({resp.headers.get('Content-Type','?')})")

    if not args.firecrawl:
        if is_pdf(resp, args.url):
            print("  → Phát hiện PDF, đang rút text...")
            if args.selector:
                print("  (PDF bỏ qua --selector)")
            text = extract_pdf_text(raw_bytes)
            title, marker_md = "", ""
            kind = "pdf"
        else:
            # HTML: ép encoding cho site VN.
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding
            html = resp.text
            text, title, marker_md = process_html(html, args.selector, plain=args.plain)
            kind = "html"

    print(f"  Đã rút {len(text):,} ký tự text thô")

    # Đặt file output.
    if args.out:
        out_txt = args.out
    else:
        os.makedirs("data/raw", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_txt = os.path.join("data/raw", f"{slugify(args.url)}_{ts}.txt")

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"# Nguồn: {args.url}\n")
        f.write(f"# Crawl lúc: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"# Loại: {kind}\n")
        f.write(f"# Selector: {args.selector or '(toàn trang / N/A với PDF)'}\n")
        f.write("\n" + "=" * 80 + "\n\n")
        f.write(text)
    print(f"  ✓ Đã lưu text: {out_txt}")

    if args.html:
        out_bin = os.path.splitext(out_txt)[0] + ("." + kind if kind == "pdf" else ".html")
        mode = "wb" if kind == "pdf" else "w"
        with open(out_bin, mode) if kind == "pdf" else open(out_bin, mode, encoding="utf-8") as f:
            f.write(raw_bytes if kind == "pdf" else html)
        print(f"  ✓ Đã lưu file gốc: {out_bin}")

    if args.split and kind == "html" and not args.plain:
        chunks = build_chunks(marker_md)
        out_json = os.path.splitext(out_txt)[0] + ".chunks.json"
        import json
        doc = {
            "url": args.url,
            "title": title,
            "crawled_at": datetime.now().isoformat(timespec="seconds"),
            "selector": args.selector or None,
            "n_chunks": len(chunks),
            "chunks": chunks,
        }
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        # Thống kê kích thước chunk.
        sizes = [len(c["text"]) for c in chunks]
        if sizes:
            print(f"  ✓ Đã tách {len(chunks)} chunk → {out_json}  "
                  f"(size: min {min(sizes)}, max {max(sizes)}, trung bình {sum(sizes)//len(sizes)})")

    if args.print:
        print("\n" + "=" * 80 + "\n")
        print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())