#!/usr/bin/env python3
"""
parse_pdf_specs.py — Trích thông số kỹ thuật từ data/raw_pdf/*.txt (brochure)
→ data/clean/<version>/postgres/specs.csv

Khác với parse_specs.py (chỉ giữ BASIC_SPECS), script này extract TOÀN BỘ row
từ bảng spec trong brochure PDF — gồm cả spec số (công suất, pin…) lẫn spec
tính năng (Có/Không, LED, v.v.).

Nguồn: data/raw_pdf/*.txt (output từ crawl_pdf.py). Chỉ extract pipe-table
3 cột (bảng so sánh edition). Cột 1 = edition đầu, cột 2 = edition cuối
(theo MODEL_EDITIONS).
"""
import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PDF_DIR = REPO_ROOT / "data" / "raw_pdf"
CLEAN_DIR = REPO_ROOT / "data" / "clean"

# ── Mappings ─────────────────────────────────────────────────────────────────
MODEL_LABEL = {
    "VF2": "VF 2", "VF3": "VF 3", "VF5": "VF 5", "VF6": "VF 6",
    "VF7": "VF 7", "VF8": "VF 8", "VF8NEW": "VF 8 All New",
    "VF9": "VF 9", "VFMPV7": "VF MPV 7", "ECVAN": "EC Van",
    "FADIL": "Fadil", "HERIO": "Herio Green", "LIMO": "Limo Green",
    "LUXA": "LUX A", "LUXSA": "LUX SA", "MINIO": "Minio Green",
    "NERIO": "Nerio Green",
}

MODEL_EDITIONS = {
    "VF2": ["TieuChuan"],
    "VF3": ["Eco", "Plus"],
    "VF5": ["Plus"],
    "VF6": ["Eco", "Plus"],
    "VF7": ["Eco", "Plus", "PlusCaptain"],
    "VF8": ["Eco", "Plus"],
    "VF8NEW": ["Eco", "Plus"],
    "VF9": ["Eco", "Plus"],
    "VFMPV7": ["Eco", "Plus"],
}

# Label map từ parse_specs.py (subset cho các spec thường gặp)
LABEL_MAP = {
    "cong suat toi da (kw)": ("power_kw", "kW", "powertrain"),
    "cong suat toi da": ("power_kw", "kW", "powertrain"),
    "cong suat toi da (kw/hp)": ("power_kw", "kW", "powertrain"),
    "cong suat": ("power_kw", "kW", "powertrain"),
    "mo men xoan cuc dai (nm)": ("torque_nm", "Nm", "powertrain"),
    "mo-men xoan cuc dai": ("torque_nm", "Nm", "powertrain"),
    "quang duong chay mot lan sac day (km) (nedc)": ("range_km", "km", "battery"),
    "quang duong chay mot lan sac day (km)": ("range_km", "km", "battery"),
    "quang duong chay mot lan sac day": ("range_km", "km", "battery"),
    "quang duong chay (nedc)": ("range_km", "km", "battery"),
    "quang duong di chuyen": ("range_km", "km", "battery"),
    "quang duong": ("range_km", "km", "battery"),
    "dung luong pin kha dung": ("battery_kwh", "kWh", "battery"),
    "dung luong pin (kwh)": ("battery_kwh", "kWh", "battery"),
    "dung luong pin": ("battery_kwh", "kWh", "battery"),
    "thoi gian nap pin nhanh nhat (phut)": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat (tu 10 den 70%) (phut)": ("fast_charge_min", "phút", "battery"),
    "dai x rong x cao (mm)": ("dimension_triple", "mm", "dimension"),
    "dai x rong x cao": ("dimension_triple", "mm", "dimension"),
    "chieu dai co so": ("wheelbase_mm", "mm", "dimension"),
    "khoang sang gam xe": ("ground_clearance_mm", "mm", "dimension"),
    "khoang sang gam": ("ground_clearance_mm", "mm", "dimension"),
    "dan dong": ("drivetrain", "", "powertrain"),
    "he dan dong": ("drivetrain", "", "powertrain"),
    "so ghe ngoi": ("seats", "", "interior"),
    "so cho ngoi": ("seats", "", "interior"),
    "cho ngoi": ("seats", "", "interior"),
    "tui khi": ("airbags", "", "safety"),
    "so luong tui khi": ("airbags", "", "safety"),
    "tang toc 0-100 km/h": ("acceleration_0_100_s", "s", "powertrain"),
    "tang toc 0-100km/h (s)": ("acceleration_0_100_s", "s", "powertrain"),
    "kha nang tang toc tu 0-100km/h (s)": ("acceleration_0_100_s", "s", "powertrain"),
    "kich thuoc la-zang": ("wheel_size_inch", "inch", "exterior"),
    "loai la-zang": ("wheel_size_inch", "inch", "exterior"),
    "man hinh giai tri cam ung": ("display_inch", "inch", "interior"),
    "he thong loa": ("speakers", "số lượng", "interior"),
    "khoi luong khong tai": ("curb_weight_kg", "kg", "dimension"),
    "dung tich cop sau": ("trunk_capacity", "L", "dimension"),
    "dung tich khoang chua hanh ly": ("trunk_capacity", "L", "dimension"),
}

ALIASES_BY_LEN = sorted(LABEL_MAP.keys(), key=len, reverse=True)

CSV_FIELDS = ["model_code", "version_name", "version_code", "spec_category",
              "spec_key", "spec_value", "spec_unit", "source_url"]

# Section headers trong bảng — rows mà tất cả data cols rỗng
SECTION_HEADERS = {
    "pin", "khung gam", "ngoai that", "ngoai that den pha", "noi that & tien nghi",
    "noi that", "thong so truyen dong khac", "giam xoc", "phanh",
    "vanh va lop banh xe", "ghe toan xe", "ghe lai", "ghe phu", "khung gam khac",
    "phien ban", "thong so", "dau xe", "hong xe", "duoi xe",
    "he thong truyen dong", "dong co", "den ngoai that", "ngoai that khac",
    "dieu hoa khong khi", "tien nghi", "an toan & an ninh", "an toan",
    "he thong tui khi", "he thong ho tro nguoi lai nang cao adas",
    "tro lai tren cao toc", "tro lan", "ho tro hanh trinh",
    "canh bao va cham", "tro lai khi co nguy co va cham",
    "cac tinh nang khac", "tinh nang thong minh",
    "he thong tin giai tri tren xe", "tro ly ao",
    "ung dung dien thoai", "kich thuoc & tai trong",
    "noi that", "den ngoai that khac", "ghe phu",
}
# Cũng check với norm lowercase + no diacritics

# ── FEATURE_NORM_MAP: normalize feature label → (eng_key, category) ─────────
# Dùng cho spec tính năng (Có/Không, LED, v.v.) không có trong LABEL_MAP.
FEATURE_NORM_MAP = {
    # ── Exterior ──
    "guong chieu hau chinh dien tich hop den bao re": ("power_folding_mirrors", "exterior"),
    "kinh cua so chinh dien len xuong mot cham": ("one_touch_windows", "exterior"),
    "den chieu sang phia truoc": ("headlight_type", "exterior"),
    "den chieu sang ban ngay": ("drl_type", "exterior"),
    "den pha": ("headlight_feature", "exterior"),
    "den pha tu dong": ("auto_headlights", "exterior"),
    "den pha tu dong den pha thich ung": ("adaptive_headlights", "exterior"),
    "den hau": ("tail_light_type", "exterior"),
    "den nhan dien thuong hieu phia truoc": ("front_brand_light", "exterior"),
    "den nhan dien thuong hieu phia sau": ("rear_brand_light", "exterior"),
    "tu dong bat tat den": ("auto_headlights", "exterior"),
    "tu dong bat tat che do chieu xa": ("auto_high_beam", "exterior"),
    "gạt mưa truoc tu dong": ("auto_wiper", "exterior"),
    "chia khoa thong minh": ("smart_key", "exterior"),
    # ── Interior ──
    "ghe boc da nhan tao": ("leatherette_seats", "interior"),
    "chat lieu boc ghe": ("seat_material_type", "interior"),
    "ghe lai": ("driver_seat_type", "interior"),
    "ghe phu": ("passenger_seat_type", "interior"),
    "kinh cua so chinh dien len xuong mot cham tat ca cac vi tri": ("one_touch_windows_all", "interior"),
    "phanh do dien tu va che do tu dong giu phanh": ("epb_auto_hold", "convenience"),
    "so cho ngoi": ("seats", "interior"),
    "so ghe ngoi": ("seats", "interior"),
    "cho ngoi": ("seats", "interior"),
    # ── Infotainment ──
    "man hinh giai tri cam ung": ("display_inch", "interior"),
    "he thong loa": ("speakers", "interior"),
    "ket noi voi android auto va apple carplay": ("smartphone_integration", "infotainment"),
    "dieu huong dan duong tren man hinh trung tam": ("navigation", "infotainment"),
    "trinh duyet web": ("web_browser", "infotainment"),
    "tro choi": ("gaming", "infotainment"),
    "tu chan doan loi": ("self_diagnosis", "infotainment"),
    "cap nhat phan mem tu xa": ("ota_update", "infotainment"),
    "tro ly ao": ("virtual_assistant", "infotainment"),
    "giai tri truc tuyen": ("online_entertainment", "infotainment"),
    "khung tien ich co ban lich duong thoi tiet media ban do": ("basic_widgets", "infotainment"),
    "hoi dap va tim kiem thong tin co ban": ("voice_search", "infotainment"),
    "ho tro dieu khien cac chuc nang xe co ban": ("voice_control", "infotainment"),
    "ho tro dieu huong dan duong co ban": ("voice_navigation", "infotainment"),
    "tu van tinh trang xe va ho tro xu ly su co": ("vehicle_status_assist", "infotainment"),
    "chao hoi thuc hien lenh theo kich ban tao san co ban": ("voice_greeting", "infotainment"),
    "ung dung dien thoai": ("phone_app", "infotainment"),
    "ung dung dien thoait": ("phone_app", "infotainment"),
    "dan duong nang cao cho xe dien tim tram sac goi y duong toi uu de sac": ("ev_routing", "infotainment"),
    # ── Safety ──
    "he thong chong bo cung phanh abs": ("abs", "safety"),
    "chuc nang phan phoi luc phanh dien tu ebd": ("ebd", "safety"),
    "ho tro phanh khan cap ba": ("brake_assist", "safety"),
    "he thong can bang dien tu esc": ("esc", "safety"),
    "chuc nang kiem soat luc keo tcs": ("tcs", "safety"),
    "ho tro khoi hanh ngang doc hsa": ("hsa", "safety"),
    "giam sat ap suat lop": ("tpms", "safety"),
    "tinh nang khoa dong co khi co trom": ("immobilizer", "security"),
    "canh bao chong trom": ("anti_theft_alarm", "security"),
    # ── ADAS ──
    "canh bao diem mu": ("blind_spot_warning", "adas"),
    "canh bao chech lan": ("lane_departure_warning", "adas"),
    "ho tro giu lan": ("lane_keep_assist", "adas"),
    "ho tro giu lan khan cap": ("emergency_lane_keep", "adas"),
    "canh bao va cham phia truoc": ("forward_collision_warning", "adas"),
    "phanh tu dong khan cap truoc": ("aeb_front", "adas"),
    "phanh tu dong khan cap truoc sau": ("aeb_front_rear", "adas"),
    "ho tro tu dong chuyen lan": ("auto_lane_change", "adas"),
    "tro lai tren cao toc di chuyen khi tac duong": ("highway_driving_assist", "adas"),
    "ho tro di chuyen khi un tac": ("traffic_jam_assist", "adas"),
    "ho tro lai tren duong cao toc": ("highway_assist", "adas"),
    "canh bao phuong tien cat ngang phia sau": ("rear_cross_traffic_alert", "adas"),
    "canh bao mo cua": ("door_open_warning", "adas"),
    "canh bao tai xe buon ngu va mat tap trung": ("driver_monitoring", "adas"),
    "ho tro do xe phia sau": ("rear_parking_assist", "adas"),
    "camera lui": ("rearview_camera", "adas"),
    "camera 360": ("surround_view_camera", "adas"),
    "kiem soat hanh trinh": ("cruise_control_type", "adas"),
    "dieu chinh toc do thong minh": ("adaptive_cruise_control", "adas"),
    "nhan biet bien bao giao thong": ("traffic_sign_recognition", "adas"),
    "kiem soat di giua lan": ("lane_centering", "adas"),
    "he thong giam sat lai xe": ("driver_monitoring", "adas"),
    "he thong camera 360 do giam sat xung quanh": ("surround_view_camera", "adas"),
    # ── Chassis ──
    "he thong treo truoc": ("front_suspension_type", "chassis"),
    "he thong treo sau": ("rear_suspension_type", "chassis"),
    "he thong phanh truoc sau": ("brake_type", "chassis"),
    "tro luc lai": ("steering_assist_type", "chassis"),
    "loai la-zang": ("wheel_type", "chassis"),
    "loai lop": ("tire_type", "chassis"),
    "lop du phong": ("spare_tire_type", "chassis"),
    # ── Powertrain ──
    "che do lai": ("drive_modes", "powertrain"),
    "chon che do lai": ("drive_modes", "powertrain"),
    "suoi pin cao the": ("battery_heater", "powertrain"),
    "bo sac tai nha": ("home_charger_type", "powertrain"),
    "day sac di dong": ("mobile_charger_type", "powertrain"),
    # ── Connected car ──
    "dong bo tai khoan ung dung phan quyen tai xe": ("account_sync", "connected"),
    "thong bao trang thai co ban tren xe trang thai hieu suat van hanh thong tin pin": ("vehicle_status_notification", "connected"),
    "quan ly sac thanh toan phi sac": ("charge_management", "connected"),
    "ban do tram sac": ("charger_map", "connected"),
    "dich vu hau mai dat lich sua chua lai thu": ("service_booking", "connected"),
    "mua ban phu kien": ("online_accessory_shop", "connected"),
    # ── sion ──
    "trong luong khong tai": ("curb_weight_kg", "dimension"),
    "tai trong hanh ly noc xe": ("roof_load_kg", "dimension"),
    "dung tich khoang chua hanh ly": ("trunk_capacity", "dimension"),
    # ── Catch-all cho các label dài còn lại (prefix match) ──
    "che do xe co ban cam trai nguoi la thu cung rua xe": ("vehicle_modes", "infotainment"),
    "sac vv": ("charging_etc", "general"),
}


def no_diacritics(s: str) -> str:
    """Bỏ dấu, lowercase, đổi đ → d."""
    s = s.lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                 if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def norm(s: str) -> str:
    """Normalize label: bỏ dấu, lowercase, gom space, strip trailing punct."""
    s = no_diacritics(s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(":|-–— \t")


def norm_strict(s: str) -> str:
    """Strict normalize: norm() + loại bỏ internal punctuation (, : ; / () & -)."""
    s = norm(s)
    s = re.sub(r"[,:;()/&\-–—]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── FEATURE_ALIASES (strict-normalized) ──────────────────────────────────────
FEATURE_ALIASES = sorted(FEATURE_NORM_MAP.keys(), key=len, reverse=True)
FEATURE_ALIASES_STRICT = {norm_strict(k): k for k in FEATURE_NORM_MAP}
FEATURE_ALIASES_BY_LEN = sorted(FEATURE_ALIASES_STRICT.keys(), key=len, reverse=True)


def infer_model_from_path(path: Path) -> str | None:
    """Rút model_id từ tên file."""
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    keys = sorted([
        ("mpv7", "VFMPV7"),
        ("vf206", "VF6"), ("vf6", "VF6"),
        ("vf2", "VF2"), ("vf3", "VF3"), ("vf5", "VF5"),
        ("vf7", "VF7"), ("vf8theallnew", "VF8NEW"),
        ("vf8thenew", "VF8NEW"), ("vf8allnew", "VF8NEW"),
        ("vf8", "VF8"), ("vf9", "VF9"),
    ], key=lambda x: -len(x[0]))
    for key, model in keys:
        if key in name:
            return model
    return None


def parse_raw_file(path: Path) -> tuple[dict[str, Any], str]:
    """Parse header metadata + body từ file raw_pdf."""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = {"source_url": "", "fetched_at": "", "source_type": "pdf"}
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# Nguồn:"):
            meta["source_url"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Crawl lúc:"):
            meta["fetched_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Loại:"):
            meta["source_type"] = line.split(":", 1)[1].strip().lower()
        elif re.match(r"^={5,}$", line.strip()):
            body_start = i + 1
            break
    return meta, "\n".join(lines[body_start:])


def is_section_header(norm_label: str) -> bool:
    return norm_label in SECTION_HEADERS


TABLE_ROW_RE = re.compile(r"^\s*\|.*\|")
SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|")


def parse_pdf_specs(path: Path) -> list[dict[str, Any]]:
    """Extract ALL spec rows from PDF brochure tables."""
    meta, body = parse_raw_file(path)
    model_id = infer_model_from_path(path)
    if not model_id:
        print(f"  [skip] can't infer model from {path.name}", file=sys.stderr)
        return []
    model_code = MODEL_LABEL.get(model_id, model_id)
    source_url = meta.get("source_url", "")
    editions = MODEL_EDITIONS.get(model_id, ["Eco", "Plus"])

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (spec_key, edition) — trùng trong file

    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if not (TABLE_ROW_RE.match(lines[i]) and i + 1 < len(lines)
                and SEP_RE.match(lines[i + 1])):
            i += 1
            continue

        # lines[i] = header, lines[i+1] = separator, data từ i+2
        header_line = lines[i].strip()
        header_cells = [c.strip() for c in header_line.strip("|").split("|")]
        data_start = i + 2

        # Phát hiện edition: kiểm tra header, fallback MODEL_EDITIONS
        edition_cols: dict[int, str] = {}
        for ci in range(1, len(header_cells)):
            h_text = header_cells[ci]
            h_norm = norm(h_text)
            for kw in ["PlusCaptain", "Plus", "Eco", "TieuChuan", "NangCao", "CaoCap"]:
                if kw.lower() in h_norm:
                    edition_cols[ci] = kw
                    break

        # Header trống → gán theo vị trí cột
        if not edition_cols and len(header_cells) >= 3:
            for ci in range(1, min(len(header_cells), len(editions) + 1)):
                edition_cols[ci] = editions[ci - 1]

        if not edition_cols:
            # Không phát hiện được edition → skip table này
            i += 1
            continue

        j = data_start
        while j < len(lines) and TABLE_ROW_RE.match(lines[j]) and not SEP_RE.match(lines[j]):
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            if not cells:
                j += 1
                continue

            label = cells[0]
            if not label:
                j += 1
                continue

            label_norm = norm(label)
            if is_section_header(label_norm):
                j += 1
                continue

            # Bỏ price row
            price_labels = ("gia", "lan bangh", "lan bang", "niem yet", "gia ban", "phien ban")
            if any(p in label_norm for p in price_labels):
                j += 1
                continue

            for ci, ed in edition_cols.items():
                if ci >= len(cells) or not cells[ci]:
                    continue
                raw_value = cells[ci]

                # Xác định spec_key, category, unit
                mapped = None
                for alias in ALIASES_BY_LEN:
                    if label_norm.startswith(alias) or label_norm == alias:
                        mapped = LABEL_MAP[alias]
                        break

                if mapped:
                    spec_key, spec_unit, spec_category = mapped
                    # dimension_triple → tách thành length/width/height
                    if spec_key == "dimension_triple":
                        dim_parts = parse_dimension_triple(raw_value)
                        for sub_key, sub_val in dim_parts:
                            if sub_val is None:
                                continue
                            k = (sub_key, ed)
                            if k in seen:
                                continue
                            seen.add(k)
                            rows.append(make_row(model_code, ed, "dimension",
                                                 sub_key, sub_val, "mm", source_url))
                        continue
                else:
                    # Không có trong LABEL_MAP → check FEATURE_NORM_MAP (tính năng)
                    feat_mapped = None
                    label_strict = norm_strict(label)
                    for alias in FEATURE_ALIASES_BY_LEN:
                        if label_strict.startswith(alias) or label_strict == alias:
                            orig_key = FEATURE_ALIASES_STRICT[alias]
                            feat_mapped = FEATURE_NORM_MAP[orig_key]
                            break
                    if feat_mapped:
                        spec_key, spec_category = feat_mapped
                        spec_unit = ""
                    else:
                        # Vẫn unmapped → dùng raw norm label
                        spec_key = label_norm
                        spec_unit = ""
                        spec_category = "general"

                # Dedup trong file
                k = (spec_key, ed)
                if k in seen:
                    continue
                seen.add(k)

                value_clean = raw_value.strip()
                if not value_clean:
                    continue

                rows.append(make_row(model_code, ed, spec_category,
                                     spec_key, value_clean, spec_unit, source_url))
            j += 1
        i = j if j > i + 1 else i + 1

    return rows


def parse_dimension_triple(value: str) -> list[tuple[str, str]]:
    """Tách '4.750 x 1.934 x 1.667' → [(length_mm, val), (width_mm, val), (height_mm, val)]."""
    value = value.replace(",", ".")  # chuẩn hóa decimal
    parts = re.split(r"\s*[xX×]\s*", value)
    keys = ["length_mm", "width_mm", "height_mm"]
    result = []
    for k, p in zip(keys, parts):
        # Bỏ dot hàng nghìn
        p = p.replace(".", "")
        try:
            float(p)  # validate
            result.append((k, p))
        except ValueError:
            result.append((k, None))
    return result


def make_row(model_code: str, edition: str, category: str,
             key: str, value: str, unit: str, url: str) -> dict[str, Any]:
    return {
        "model_code": model_code,
        "version_name": edition,
        "version_code": None,
        "spec_category": category,
        "spec_key": key,
        "spec_value": value,
        "spec_unit": unit,
        "source_url": url,
    }


def run(version: str = "v2") -> int:
    """Main: read raw_pdf, extract all spec tables, write CSV."""
    version_dir = CLEAN_DIR / version
    pg_dir = version_dir / "postgres"
    pg_dir.mkdir(parents=True, exist_ok=True)

    if not RAW_PDF_DIR.exists():
        print(f"[parse_pdf_specs] raw_pdf dir not found: {RAW_PDF_DIR}", file=sys.stderr)
        return 1

    all_rows: list[dict[str, Any]] = []
    by_model: dict[str, int] = {}
    n_files = 0

    for path in sorted(RAW_PDF_DIR.iterdir()):
        if not path.is_file() or path.suffix not in (".txt",):
            continue
        print(f"  📄 {path.name}")
        rows = parse_pdf_specs(path)
        if not rows:
            print(f"    → no spec tables found")
            continue
        n_files += 1
        all_rows.extend(rows)
        for r in rows:
            mc = r["model_code"]
            by_model[mc] = by_model.get(mc, 0) + 1
        print(f"    → {len(rows)} spec rows")

    if not all_rows:
        print("[parse_pdf_specs] no data found")
        return 1

    # Ghi CSV
    out_path = pg_dir / "specs.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter="|")
        w.writeheader()
        for r in all_rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_FIELDS})

    print(f"\n[parse_pdf_specs] version={version}  files={n_files}")
    for mc in sorted(by_model):
        print(f"  {mc}: {by_model[mc]} rows")
    print(f"  → {out_path}: {len(all_rows)} rows")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract all spec rows from PDF brochure tables.")
    ap.add_argument("--version", default="v2", help="Output version folder (default v2)")
    args = ap.parse_args()
    return run(args.version)


if __name__ == "__main__":
    sys.exit(main())
