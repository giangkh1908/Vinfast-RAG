#!/usr/bin/env python3
"""
Extract dữ liệu cấu hình xe từ window.carDeposit (trang dat-coc VinFast)
→ data/raw/car_deposit_extracted/{colors,edition,options,price_list}.csv

Pipeline: bước này crawl trang configurator 1 lần, dump TOÀN BỘ dữ liệu
(variant, giá, màu, nội thất, option) ra 4 CSV tên file ổn định để bước clean
(parse_car_deposit.py) đọc — thay cho việc điền tay data/model_data/variants/*.csv.

4 CSV (delimiter |) đúng schema parse_car_deposit.py đọc:
  - edition.csv:    model_id | edition_id | variant_code | is_option_variant |
                    base_edition_code | updated_at
  - price_list.csv: model_id | edition_id | price_list_vnd | price_promo_vnd |
                    promo_label | vat_included | battery_included | valid_from |
                    valid_to | updated_at | source_url
  - colors.csv:     model_id | edition_id | variant_code | color_code |
                    color_name | color_hex | price_extra_vnd | interior_code |
                    interior_name | updated_at
  - options.csv:    model_id | edition_code | option_id | option_name | value_id |
                    value_name | price_extra_vnd | updated_at

Quy ước:
  - edition_id = NHÃN GỐC từ site (VD "Tiêu chuẩn", "Comfort", "Plus 2 động cơ",
    "Plus tùy chọn ghế cơ trưởng") — KHÔNG chuẩn hóa ở raw. Cả colors/edition/
    price dùng chung nhãn này để code_lookup của parse_car_deposit khớp chắc chắn;
    chuẩn hóa (TieuChuan, The All New, Plus_AWD, PlusCaptain…) chỉ xảy ra ở clean
    qua _edition_from().
  - Chỉ xuất 9 xe consumer (CONSUMER_MODELS); 4 xe taxi/van xanh (ECVAN,
    HerioGreen, LimoGreen, MinioGreen) bị LỌC có chủ đích.
  - colors.csv chỉ có base variant (option variant không có listColor).
  - colors.price_extra_vnd: VND thật (8.000.000 → 8000000)
  - options.price_extra_vnd: NGHÌN đồng (site trả 10000 = 10.000.000đ;
    bước clean nhân 1000). Kiểm chứng: VF7 Plus 830tr → PlusCaptain (trần
    kính) 850tr = +20tr = CR151 20000; AWD +49tr = T023 49000.
  - interior_code/name từ listInterior của site (join ", ") — nguồn tự động,
    thay fallback tay vinfast_color.csv.

Cách dùng:
    python scripts/extract_car_deposit.py                          # crawl + extract
    python scripts/extract_car_deposit.py --html <file.html>       # extract từ HTML có sẵn
    python scripts/extract_car_deposit.py --out <dir>              # thư mục output khác
"""

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Fix Unicode trên Windows
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://shop.vinfastauto.com/vn_vi/dat-coc-o-to-dien-vinfast.html"
DEFAULT_OUT = "data/raw/car_deposit_extracted"

# ── Lọc model ──────────────────────────────────────────────────────────────────
# Chỉ 9 xe consumer. 4 xe taxi/van xanh (ECVAN, HerioGreen, LimoGreen, MinioGreen)
# tồn tại trong carDeposit nhưng bị loại có chủ đích (dòng kinh doanh; MinioGreen
# trùng giá VF2 188tr).
CONSUMER_MODELS = {"VF2", "VF3", "VF5", "VF6", "VF7", "VF8", "VF8NEW", "VF9", "VFMPV7"}
# Chuẩn hóa model_id từ site → mã chuẩn (đồng bộ với MODEL_LABEL/price_list)
MODEL_ID_ALIAS = {"VF8-THE-ALL-NEW": "VF8NEW", "VF8-THE-NEW": "VF8NEW"}


def _norm_model_id(raw: str) -> str:
    """'VF8-THE-ALL-NEW' → 'VF8NEW'; giữ nguyên model khác."""
    return MODEL_ID_ALIAS.get((raw or "").strip().upper(), (raw or "").strip().upper())


def configurator_url(model_id: str) -> str:
    """URL trang configurator kèm modelId per xe (đuôi để trace nguồn chính xác)."""
    return f"{BASE_URL}?modelId=Products-Car-{model_id}"


# Schema raw (đầu vào cho scripts/clean_data/parse_car_deposit.py) — 4 bảng
EDITION_FIELDS = ["model_id", "edition_id", "variant_code", "is_option_variant",
                  "base_edition_code", "updated_at"]
PRICE_FIELDS = ["model_id", "edition_id", "price_list_vnd", "price_promo_vnd",
                "promo_label", "vat_included", "battery_included",
                "valid_from", "valid_to", "updated_at", "source_url"]
COLOR_FIELDS = ["model_id", "edition_id", "variant_code", "color_code",
                "color_name", "color_hex", "price_extra_vnd",
                "interior_code", "interior_name", "updated_at"]
OPTION_FIELDS = ["model_id", "edition_code", "option_id", "option_name", "value_id",
                 "value_name", "price_extra_vnd", "updated_at"]


def crawl_html(headless: bool = True) -> str:
    """Dùng Playwright để lấy HTML đầy đủ từ trang configurator."""
    from playwright.async_api import async_playwright

    async def _crawl():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="vi-VN",
            )
            page = await context.new_page()
            print(f"→ Đang tải: {BASE_URL}")
            await page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)  # đợi JS render
            html = await page.content()
            await browser.close()
            return html

    return asyncio.run(_crawl())


def extract_car_deposit(html: str) -> dict:
    """Trích xuất window.carDeposit bằng Node.js → {variants, options}."""
    # Lưu HTML tạm
    tmp_html = Path("data/raw/_tmp_configurator.html")
    tmp_html.parent.mkdir(parents=True, exist_ok=True)
    tmp_html.write_text(html, encoding="utf-8")

    node_script = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');

const match = html.match(/window\.carDeposit\s*=\s*(\{[\s\S]*?\});\s*(?:window\.carDeposit\.|function|\n\s*<\/script>)/);
if (!match) { console.log('NOT FOUND'); process.exit(1); }

eval('var obj = ' + match[1]);
const products = obj.products;
const models = products.models;

function parsePrice(vnd) {
  if (typeof vnd === 'number') return vnd;
  if (typeof vnd === 'string') return parseInt(vnd.replace(/[^0-9]/g, '')) || 0;
  return 0;
}
function priceObj(p) {
  if (!p) return { value: 0, formatted: '' };
  if (typeof p === 'object') return { value: p.value || 0, formatted: p.formatted || '' };
  return { value: parsePrice(p), formatted: String(p) };
}

const variants = [];
const options = [];

models.forEach(m => {
  const modelData = products[m.id];
  if (!modelData || !modelData.model) return;
  const modelId = m.id.replace('Products-Car-', '');

  // Variant: có price (bản chuẩn) HOẶC chỉ có priceWithBattery (tổ hợp option)
  const keys = Object.keys(modelData).filter(k =>
    k !== 'model' && k !== 'label' &&
    typeof modelData[k] === 'object' &&
    (modelData[k].price || modelData[k].priceWithBattery)
  );

  keys.forEach(vk => {
    const v = modelData[vk];
    const isOption = !v.price && !!v.priceWithBattery;

    // Base price = giá màu rẻ nhất (màu cơ bản); option variant = priceWithBattery
    let basePrice = isOption ? (v.priceWithBattery || 0) : (v.priceValue || 0);
    let baseDisplay = isOption
      ? String(v.priceWithBattery || '')
      : (v.price || '');
    const colors = [];

    if (v.listColor) {
      const priced = [];
      v.listColor.forEach(c => {
        const cd = v[c];
        if (!cd || typeof cd !== 'object') return;
        const cp = priceObj(cd.price);
        if (cd.price) priced.push({ code: c, value: cp.value, formatted: cp.formatted });
        colors.push({
          code: c, label: cd.label || '', hex: cd.code || '',
          total_price_vnd: cp.value, formatted: cp.formatted,
        });
      });
      if (!isOption && priced.length > 0) {
        const minC = priced.reduce((a, b) => (a.value < b.value ? a : b));
        basePrice = minC.value;
        baseDisplay = minC.formatted;
      }
    }

    const interiors = [];
    if (v.listInterior) {
      v.listInterior.forEach(ci => {
        const idata = v[ci];
        if (idata && typeof idata === 'object') {
          interiors.push({ code: ci, label: idata.label || '' });
        }
      });
    }

    variants.push({
      model_id: modelId,
      model_name: m.name,
      variant_code: vk,
      edition_name: v.label || '',
      is_option_variant: isOption,
      base_edition_code: isOption ? (v.imageEdition || vk.split('_')[0]) : '',
      price_vnd: basePrice,
      price_display: baseDisplay,
      price_with_battery_vnd: v.priceWithBattery || 0,
      options_name: v.optionsName || '',
      colors: colors.map(c => ({
        code: c.code,
        label: c.label,
        hex: c.hex,
        total_price_vnd: c.total_price_vnd,
        price_extra_vnd: Math.max(0, c.total_price_vnd - basePrice),
      })),
      interiors,
    });
  });

  // productOptions: HUD, AWD, trần kính, lazang... (giá trả theo nghìn đồng)
  // Mỗi option gắn với 1 base edition (po.edition = variant code: GC15V=Eco,
  // GC12V=Plus) → dedup theo (edition, option_id), giữ edition_code để bước clean
  // scope đúng edition (VD VF7 HUD chỉ có ở Eco, không phải toàn model).
  if (modelData.productOptions && Array.isArray(modelData.productOptions)) {
    const seen = new Set();
    modelData.productOptions.forEach(po => {
      if (!po.options) return;
      const edition = po.edition || '';
      po.options.forEach(opt => {
        const key = edition + '|' + opt.id;
        if (seen.has(key)) return;
        seen.add(key);
        (opt.values || []).forEach(val => {
          options.push({
            model_id: modelId,
            edition_code: edition,
            option_id: opt.id,
            option_name: opt.name || opt.label || '',
            value_id: val.id,
            value_name: val.displayValue || '',
            price_extra: parsePrice(val.price),
          });
        });
      });
    });
  }
});

console.log(JSON.stringify({ variants, options }));
"""
    try:
        output = subprocess.check_output(
            ["node", "-e", node_script, str(tmp_html.resolve())],
            timeout=30,
            encoding="utf-8",
        )
        return json.loads(output)
    except subprocess.CalledProcessError as e:
        print(f"Node.js error: {e.stderr}")
        raise
    finally:
        tmp_html.unlink(missing_ok=True)


def _clean(v) -> str:
    return str(v if v is not None else "").replace("\n", " ").replace("\r", " ").strip()


def _now() -> str:
    return datetime.now().isoformat() + "Z"


def build_rows(data: dict) -> dict[str, list[dict]]:
    """Từ {variants, options} → 4 bộ rows cho CSV raw.

    edition.csv + price_list.csv + colors.csv chỉ lấy 9 xe consumer
    (CONSUMER_MODELS); 4 xe taxi/van xanh bị lọc. edition_id = nhãn gốc site
    (chưa chuẩn hóa) — parse_car_deposit sẽ chuẩn hóa qua _edition_from().
    """
    now = _now()
    variants = data["variants"]
    options = data.get("options", [])

    edition_rows: list[dict] = []
    price_rows: list[dict] = []
    color_rows: list[dict] = []
    seen_edition: set[tuple[str, str]] = set()
    seen_color: set[tuple[str, str, str]] = set()

    for v in variants:
        mid = _norm_model_id(v["model_id"])
        if mid not in CONSUMER_MODELS:
            continue
        ed = (v.get("edition_name") or "").strip()
        if not ed:
            continue
        vc = v.get("variant_code") or ""
        is_opt = str(v.get("is_option_variant")).lower()
        base_code = v.get("base_edition_code") or ""

        # edition + price: 1 row per (model, edition) — base variant đứng trước
        ekey = (mid, ed)
        if ekey not in seen_edition:
            seen_edition.add(ekey)
            edition_rows.append({
                "model_id": mid,
                "edition_id": ed,
                "variant_code": vc,
                "is_option_variant": is_opt,
                "base_edition_code": base_code,
                "updated_at": now,
            })
            price_rows.append({
                "model_id": mid,
                "edition_id": ed,
                "price_list_vnd": v.get("price_vnd") or 0,
                "price_promo_vnd": "",
                "promo_label": "",
                "vat_included": "t",
                "battery_included": "t",
                "valid_from": "2026-07-01",
                "valid_to": "",
                "updated_at": now,
                "source_url": configurator_url(mid),
            })

        # colors: chỉ base variant (option variant không có listColor)
        int_codes = ", ".join(i["code"] for i in v.get("interiors", []))
        int_names = ", ".join(i["label"] for i in v.get("interiors", []))
        for c in v.get("colors", []):
            ckey = (mid, ed, c["code"])
            if ckey in seen_color:
                continue
            seen_color.add(ckey)
            color_rows.append({
                "model_id": mid,
                "edition_id": ed,
                "variant_code": vc,
                "color_code": c["code"],
                "color_name": c["label"],
                "color_hex": c["hex"],
                "price_extra_vnd": c["price_extra_vnd"],
                "interior_code": int_codes,
                "interior_name": int_names,
                "updated_at": now,
            })

    option_rows = [{
        "model_id": _norm_model_id(o["model_id"]),
        "edition_code": o.get("edition_code", ""),
        "option_id": o["option_id"],
        "option_name": o["option_name"],
        "value_id": o["value_id"],
        "value_name": o["value_name"],
        "price_extra_vnd": o["price_extra"],
        "updated_at": now,
    } for o in options if _norm_model_id(o["model_id"]) in CONSUMER_MODELS]

    return {
        "edition": edition_rows,
        "price": price_rows,
        "colors": color_rows,
        "options": option_rows,
    }


def write_csv(path: Path, fields: list[str], rows: list[dict], delimiter: str = "|"):
    """Ghi CSV delimiter | (giống các postgres CSV trong clean layer)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(delimiter.join(fields) + "\n")
        for row in rows:
            f.write(delimiter.join(_clean(row.get(h, "")) for h in fields) + "\n")
    print(f"  ✓ {path} ({len(rows)} dòng)")


def main():
    ap = argparse.ArgumentParser(
        description="Extract dữ liệu cấu hình xe từ carDeposit JS (VinFast configurator)"
    )
    ap.add_argument("--html", help="File HTML có sẵn (không có thì crawl tự động)")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"Thư mục output (mặc định: {DEFAULT_OUT})")
    ap.add_argument("--no-crawl", action="store_true", help="Không crawl, chỉ extract từ --html")
    args = ap.parse_args()

    out_dir = Path(args.out)

    # Lấy HTML
    if args.html:
        print(f"→ Đọc HTML từ: {args.html}")
        html = Path(args.html).read_text(encoding="utf-8")
    elif not args.no_crawl:
        html = crawl_html(headless=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = Path("data/raw") / f"configurator_full_{ts}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        print(f"  ✓ Đã lưu HTML: {html_path} ({len(html):,} bytes)")
    else:
        print("Cần --html hoặc không dùng --no-crawl")
        return 1

    # Extract carDeposit
    print("→ Đang extract window.carDeposit...")
    data = extract_car_deposit(html)
    all_mids = {_norm_model_id(v["model_id"]) for v in data["variants"]}
    n_models = len(all_mids & CONSUMER_MODELS)
    skipped = sorted(all_mids - CONSUMER_MODELS)
    print(f"  ✓ {len(data['variants'])} variants, {n_models} xe consumer, "
          f"{len(data.get('options', []))} option values")
    if skipped:
        print(f"  [skip commercial] {', '.join(skipped)} (loại chủ đích)")

    # Tổng quan (chỉ xe consumer)
    print("\n=== TỔNG QUAN ===")
    for v in data["variants"]:
        mid = _norm_model_id(v["model_id"])
        if mid not in CONSUMER_MODELS:
            continue
        tag = " [OPTION]" if v["is_option_variant"] else ""
        print(f"  {mid} | {v['edition_name']} | {v['variant_code']} | "
              f"{v['price_display']}{tag}")
    if data.get("options"):
        print("\n  Options:")
        for o in data["options"]:
            print(f"    {_norm_model_id(o['model_id'])} | {o['option_id']} | "
                  f"{o['value_name']} | +{o['price_extra']}")

    # Lưu JSON đầy đủ (có timestamp để trace lịch sử)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"car_deposit_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✓ JSON đầy đủ: {json_path}")

    # Ghi 4 CSV
    rows = build_rows(data)
    write_csv(out_dir / "edition.csv", EDITION_FIELDS, rows["edition"])
    write_csv(out_dir / "price_list.csv", PRICE_FIELDS, rows["price"])
    write_csv(out_dir / "colors.csv", COLOR_FIELDS, rows["colors"])
    write_csv(out_dir / "options.csv", OPTION_FIELDS, rows["options"])

    print("\nHoàn tất! Bước clean: python scripts/clean_data/parse_car_deposit.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
