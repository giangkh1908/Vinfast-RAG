# SPEC_SCHEMA — Thông số kỹ thuật (car_specs)

> Contract cho bảng `car_specs` (Postgres) / `data/clean/<ver>/postgres/specs.csv`.
>
> **Nguồn duy nhất: `data/raw_pdf/*.txt`** (brochure PDF pipe-tables) — extract
> **toàn bộ** spec (BASIC_SPECS lẫn feature specs: nội thất, ngoại thất, an toàn,
> ADAS, túi khí, giải trí...). Không dùng `data/raw/*.txt` dat-coc pages.
>
> Script: `parse_pdf_specs.py` lookup LABEL_MAP trước, fallback FEATURE_NORM_MAP
> (150+ feature aliases) nếu label không phải spec cơ bản.

## BASIC_SPECS Whitelist (12 key, 4 category)

| Category | Key | Nhãn VN | unit | Ghi chú |
|---|---|---|---|---|
| `dimension` | length_mm | Dài | mm | |
| `dimension` | width_mm | Rộng | mm | |
| `dimension` | height_mm | Cao | mm | |
| `dimension` | wheelbase_mm | Chiều dài cơ sở | mm | |
| `dimension` | ground_clearance_mm | Khoảng sáng gầm | mm | |
| `powertrain` | power_kw | Công suất | kW | |
| `powertrain` | torque_nm | Mô-men xoắn | Nm | |
| `powertrain` | drivetrain | Dẫn động | — | value chuẩn: `FWD` / `RWD` / `AWD` |
| `battery` | battery_kwh | Dung lượng pin | kWh | |
| `battery` | range_km | Quãng đường | km | |
| `battery` | dc_charge_kw | Sạc nhanh DC | kW | |
| `interior` | seats | Số chỗ ngồi | — | |

Ngoài BASIC_SPECS, `parse_pdf_specs.py` còn extract **feature specs** (mở rộng):
nội thất, ngoại thất, ADAS, an toàn, túi khí, giải trí, kết nối, tiện nghi —
từ bảng so sánh edition trong brochure PDF.

## Chuẩn hóa value

- `spec_value` chỉ chứa số / thuần text; đơn vị tách riêng `spec_unit` (riêng
  `drivetrain`, `seats` để unit rỗng).
- Số phải qua sanity range (`SANITY_RANGES`) — value ngoài khoảng = junk → drop.
- `drivetrain` chuẩn hóa về `FWD` / `RWD` / `AWD` (bỏ "Cầu trước"/"Cầu sau").
- `range_km` / `battery_kwh`: nếu nguồn ghi đồng thời NEDC + WLTP → ưu tiên NEDC
  (VinFast marketing dùng NEDC).
- `dimension` label dạng "Dài x Rộng x Cao" → tách 3 row `length_mm`/`width_mm`/`height_mm`.

## Nguồn

- Chỉ từ `data/raw_pdf/*.txt` (brochure PDF VF6, VF8 — chạy `parse_pdf_specs.py`).
- Không dùng `data/raw/*.txt` dat-coc pages (tránh spec lẫn giữa model không chính xác).
- ⚠️ **`power_kw` lấy token số đầu tiên của label `Công suất tối đa`**. Nếu label có
  dạng `(kW/Hp)` / `(hp/kW)` (VD VF 8: `150/201`), parser lấy **hp** thay vì kW →
  cảnh báo dữ liệu nhưng hiện chưa tự đổi.
- ⚠️ **VF 8 All New** (brochure layout "labels-then-values") chưa get được range/DC/FWD.

## Metadata / version

- `model_code`, `version_name`, `version_code` chuẩn hóa từ `car_catalog` (API
  `omapi.vinfastauto.com/fe/v1/carModel`), không tự bịa.
- `source_url` = link nguồn crawl (để trích dẫn + audit).

## Liên quan

- Bảng: `docs/DATA_SCHEMA_SPEC.md` §5.x `car_specs`.
- Pipeline: `docs/DATA_PIPELINE.md` bước 3/6 `parse_pdf_specs.py`.
- Tool đọc: `get_specs(model_code, version)` — nên dùng VIEW `car_specs_active` thay vì query trực tiếp base table (hỗ trợ rollback version).
- Versioning: `car_specs` có `ingest_version` column — rollback specs được support (cùng với edition/price_list).
