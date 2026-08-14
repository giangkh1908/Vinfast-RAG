#!/usr/bin/env python3
"""
parse_car_deposit.py — Tích hợp dữ liệu scrape trang configurator VinFast
(data/raw/car_deposit_extracted/*.csv) vào clean layer:

  colors.csv      → postgres/colors.csv     (car_colors: màu + phí màu nâng cao)
  options.csv     → postgres/options.csv    (car_options: HUD/AWD/trần kính/lazang...)
  edition.csv     → sync postgres/edition.csv
  price_list.csv  → sync postgres/price_list.csv (giá chuẩn, thay model_data điền tay)

Bước này chạy SAU parse_specs.py trong pipeline (parse_specs sinh specs.csv từ
model_data, rồi bước này override màu/giá/edition + bổ sung option từ nguồn
configurator tự động). Nếu data/raw/car_deposit_extracted chưa có → skip (giữ
nguồn model_data thủ công làm fallback).

Quy ước:
  - delimiter "|" giống các postgres CSV khác.
  - price_extra_vnd trong raw options.csv tính theo NGHÌN đồng → nhân 1000.
  - Edition chuẩn hoá qua alias (_edition_from của parse_specs): option-variant
    (GC12V_T023 → Plus_AWD, GC12V_CR151_T023 → Plus_AWD_PanoramicRoof) thành
    edition riêng có giá riêng, KHÔNG gộp về PlusCaptain như trước.
  - options.csv: option_group = option_id (wheel/hud/driveTypes/options); scope
    theo edition_code = base variant code của edition sở hữu option (VD VF7 HUD
    chỉ ở Eco/GC15V, AWD + trần kính chỉ ở Plus/GC12V). version_code/name rỗng
    = áp dụng mọi bản của model.
  - source_url = trang configurator kèm ?modelId=Products-Car-{MODEL_ID} per xe.

Usage:
    python scripts/clean_data/parse_car_deposit.py --version v2
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.config import CLEAN_DIR, MODEL_DATA_DIR, RAW_DIR  # noqa: E402
from scripts.clean_data.spec_common import MODEL_LABEL  # noqa: E402
from scripts.clean_data.parse_specs import (  # noqa: E402
    COLOR_FIELDS, EDITION_CSV_FIELDS, PRICE_CSV_FIELDS, _edition_from,
    count_csv_rows, parse_colors_csv,
)

CAR_DEPOSIT_DIR = RAW_DIR / "car_deposit_extracted"
CONFIGURATOR_BASE = "https://shop.vinfastauto.com/vn_vi/dat-coc-o-to-dien-vinfast.html"


def configurator_url(model_id: str) -> str:
    """URL trang configurator kèm modelId per xe (đuôi để trace nguồn chính xác)."""
    return f"{CONFIGURATOR_BASE}?modelId=Products-Car-{model_id}"

OPTION_FIELDS = ["model_id", "version_code", "version_name", "option_group",
                 "option_name", "value_id", "value_name", "price_extra_vnd",
                 "source_url", "updated_at"]


def _load_csv(path: Path, delimiter: str = "|") -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(r) for r in csv.DictReader(f, delimiter=delimiter)]


def _write_csv(path: Path, fields: list[str], rows: list[dict], delimiter: str = "|"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=delimiter)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_true(v) -> bool:
    return str(v).lower() in {"true", "t", "1", "yes"}


def _manual_interior_lookup() -> dict[tuple[str, str, str], tuple[str, str]]:
    """Fallback nội thất từ vinfast_color.csv (điền tay) khi scrape chưa có."""
    p = MODEL_DATA_DIR / "variants" / "vinfast_color.csv"
    if not p.exists():
        return {}
    out = {}
    for r in parse_colors_csv(p):
        out[(r["model_id"], r["version_code"], r["color_code"])] = (
            r["interior_code"], r["interior_name"],
        )
    return out


def build_color_rows(raw_colors, raw_editions, manual_int) -> list[dict]:
    code_lookup = {(r["model_id"], r["edition_id"]): r["variant_code"]
                   for r in raw_editions}
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict] = []
    for r in raw_colors:
        mid = r.get("model_id", "").strip()
        ed_name = r.get("edition_id", "").strip()
        if not mid or not ed_name:
            continue
        vc = r.get("variant_code") or code_lookup.get((mid, ed_name), "")
        edition = _edition_from(mid, vc, ed_name)
        cc = r.get("color_code", "").strip()
        fee = int(r.get("price_extra_vnd") or 0)

        # Nội thất: ưu tiên nguồn thủ công per-color (chính xác hơn), fallback scrape
        int_code = r.get("interior_code", "").strip()
        int_name = r.get("interior_name", "").strip()
        if not int_code:
            int_code, int_name = manual_int.get((mid, vc, cc), ("", ""))

        key = (vc, cc, int_code)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "model_id": mid,
            "version_code": vc,
            "version_name": edition,
            "color_code": cc,
            "color_name": r.get("color_name", "").strip(),
            "color_type": "Nâng cao" if fee > 0 else "Cơ bản",
            "color_fee_vnd": fee,
            "interior_code": int_code,
            "interior_name": int_name,
            "source_url": configurator_url(mid),
        })
    return rows


def build_option_rows(raw_options, raw_editions) -> list[dict]:
    """options raw → clean: nhân 1000 giá + scope edition từ edition_code.

    edition_code = base variant code của edition sở hữu option (VD GC15V = Eco,
    GC12V = Plus) — giữ nguyên nguồn truth từ configurator thay vì đoán qua
    value_id. Fallback: value_id nằm trong mã option-variant (GC12V_T023 → T023).
    """
    edition_label = {(r["model_id"], r["variant_code"]): r["edition_id"]
                     for r in raw_editions}
    scopes: dict[tuple[str, str], tuple[str, str]] = {}
    for ed in raw_editions:
        if not _is_true(ed.get("is_option_variant")):
            continue
        base = ed.get("base_edition_code", "").strip()
        if not base:
            continue
        base_name = edition_label.get((ed["model_id"], base), "")
        base_edition = _edition_from(ed["model_id"], base, base_name)
        for part in ed["variant_code"].split("_")[1:]:
            scopes[(ed["model_id"], part)] = (base, base_edition)

    rows = []
    now = _now()
    for r in raw_options:
        mid = r.get("model_id", "").strip()
        vid = r.get("value_id", "").strip()
        raw_price = int(r.get("price_extra_vnd") or 0)
        vc, vname = scopes.get((mid, vid), ("", ""))
        ec = r.get("edition_code", "").strip()
        if ec:
            vc = ec
            vname = _edition_from(mid, ec, edition_label.get((mid, ec), ""))
        rows.append({
            "model_id": mid,
            "version_code": vc,
            "version_name": vname,
            "option_group": r.get("option_id", "").strip(),
            "option_name": r.get("option_name", "").strip(),
            "value_id": vid,
            "value_name": r.get("value_name", "").strip(),
            "price_extra_vnd": raw_price * 1000,  # nghìn đồng → VND
            "source_url": configurator_url(mid),
            "updated_at": r.get("updated_at") or now,
        })
    return rows


def sync_editions(pg_dir: Path, raw_editions) -> int:
    """Bổ sung edition thiếu (chuẩn hoá alias), giữ nguyên row hiện có."""
    ed_path = pg_dir / "edition.csv"
    rows = _load_csv(ed_path)
    keys = {(r["model_id"], r["edition_id"]) for r in rows}
    now = _now()
    added = 0
    for ed in raw_editions:
        mid = ed.get("model_id", "").strip()
        name = ed.get("edition_id", "").strip()
        if not mid or not name:
            continue
        mapped = _edition_from(mid, ed.get("variant_code", ""), name)
        if (mid, mapped) in keys:
            continue
        keys.add((mid, mapped))
        rows.append({
            "model_id": mid, "edition_id": mapped,
            "model_label": MODEL_LABEL.get(mid, mid),
            "edition_label": mapped,
            "year_range": "2026", "is_active": "t",
            "created_at": now, "updated_at": now,
        })
        added += 1
    _write_csv(ed_path, EDITION_CSV_FIELDS, rows)
    return added


def sync_prices(pg_dir: Path, raw_prices, raw_editions) -> tuple[int, int]:
    """Giá chuẩn từ carDeposit → price_list (min theo edition sau alias)."""
    code_lookup = {(r["model_id"], r["edition_id"]): r["variant_code"]
                   for r in raw_editions}
    cd_prices: dict[tuple[str, str], int] = {}
    for r in raw_prices:
        mid = r.get("model_id", "").strip()
        name = r.get("edition_id", "").strip()
        if not mid or not name:
            continue
        price = int(r.get("price_list_vnd") or 0)
        if not price:
            continue
        vc = code_lookup.get((mid, name), "")
        key = (mid, _edition_from(mid, vc, name))
        if key not in cd_prices or price < cd_prices[key]:
            cd_prices[key] = price

    price_path = pg_dir / "price_list.csv"
    rows = _load_csv(price_path)
    index = {(r["model_id"], r["edition_id"]): r for r in rows}
    now = _now()
    updated = added = 0
    for (mid, edition), price in cd_prices.items():
        if (mid, edition) in index:
            pr = index[(mid, edition)]
            if int(pr.get("price_list_vnd") or 0) != price:
                updated += 1
            pr["price_list_vnd"] = price
            pr["price_promo_vnd"] = ""
            pr["promo_label"] = ""
            pr["updated_at"] = now
            pr["source_url"] = configurator_url(mid)
        else:
            rows.append({
                "model_id": mid, "edition_id": edition,
                "price_list_vnd": price, "price_promo_vnd": "",
                "promo_label": "", "vat_included": "t", "battery_included": "t",
                "valid_from": "2026-07-01", "valid_to": "",
                "updated_at": now, "source_url": configurator_url(mid),
            })
            added += 1
    _write_csv(price_path, PRICE_CSV_FIELDS, rows)
    return updated, added


def update_manifest(version: str, n_colors: int, n_options: int) -> None:
    manifest_path = CLEAN_DIR / version / "_manifest.json"
    if not manifest_path.exists():
        return
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        tables = m.setdefault("postgres", {}).setdefault("tables", {})
        tables["car_colors"] = {
            "file": "postgres/colors.csv",
            "rows": n_colors,
            "upserted": n_colors,
        }
        if n_options:
            tables["car_options"] = {
                "file": "postgres/options.csv",
                "rows": n_options,
                "upserted": n_options,
            }
        # edition/price_list được sync lại ở bước này → đếm row thật từ CSV
        pg_dir = CLEAN_DIR / version / "postgres"
        for tbl, fname in (("edition", "edition.csv"), ("price_list", "price_list.csv")):
            n = count_csv_rows(pg_dir / fname)
            tables[tbl] = {
                "file": f"postgres/{fname}",
                "rows": n,
                "upserted": n,
            }
        m["postgres"]["total_rows_upserted"] = sum(
            t.get("upserted", 0) for t in tables.values()
        )
        manifest_path.write_text(
            json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  ✓ manifest updated (car_colors={n_colors}, car_options={n_options})")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ failed to update manifest: {e}", file=sys.stderr)


def run(version: str = "v1") -> int:
    pg_dir = CLEAN_DIR / version / "postgres"
    pg_dir.mkdir(parents=True, exist_ok=True)

    if not CAR_DEPOSIT_DIR.exists():
        print(f"[parse_car_deposit] {CAR_DEPOSIT_DIR} not found — skip "
              f"(giữ nguồn model_data thủ công)")
        return 0

    raw_colors = _load_csv(CAR_DEPOSIT_DIR / "colors.csv")
    raw_editions = _load_csv(CAR_DEPOSIT_DIR / "edition.csv")
    raw_options = _load_csv(CAR_DEPOSIT_DIR / "options.csv")
    raw_prices = _load_csv(CAR_DEPOSIT_DIR / "price_list.csv")
    print(f"[parse_car_deposit] raw: colors={len(raw_colors)} edition={len(raw_editions)} "
          f"options={len(raw_options)} price={len(raw_prices)}")

    # 1. colors (override vinfast_color.csv — scrape là nguồn tự động)
    manual_int = _manual_interior_lookup()
    color_rows = build_color_rows(raw_colors, raw_editions, manual_int)
    if color_rows:
        _write_csv(pg_dir / "colors.csv", COLOR_FIELDS, color_rows)
        print(f"  ✓ postgres/colors.csv: {len(color_rows)} rows")

    # 2. options (bảng mới)
    option_rows = build_option_rows(raw_options, raw_editions)
    if option_rows:
        _write_csv(pg_dir / "options.csv", OPTION_FIELDS, option_rows)
        print(f"  ✓ postgres/options.csv: {len(option_rows)} rows")
        for r in option_rows:
            scope = f"  (scope {r['version_name']})" if r["version_name"] else ""
            print(f"    {r['model_id']} | {r['option_group']} | {r['value_name']} "
                  f"| +{int(r['price_extra_vnd']):,}{scope}")

    # 3. sync edition + price_list
    if raw_editions:
        added = sync_editions(pg_dir, raw_editions)
        print(f"  ✓ edition sync: +{added} edition")
    if raw_prices:
        updated, added = sync_prices(pg_dir, raw_prices, raw_editions)
        print(f"  ✓ price_list sync: {updated} giá cập nhật, +{added} mới")

    update_manifest(version, len(color_rows), len(option_rows))
    print(f"[parse_car_deposit] version={version}  car_colors={len(color_rows)} "
          f"car_options={len(option_rows)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Tích hợp carDeposit scrape vào clean postgres CSVs.")
    ap.add_argument("--version", default="v1", help="Version folder (mặc định v1)")
    return run(ap.parse_args().version)


if __name__ == "__main__":
    sys.exit(main())
