# SPEC_SCHEMA — Thông số kỹ thuật cơ bản (car_specs)

> Contract cho bảng `car_specs` (Postgres) / `data/clean/<ver>/postgres/specs.csv`.
> Parser `scripts/clean_data/parse_specs.py` **chỉ** nhận các `spec_key` trong
> `BASIC_SPECS` (whitelist) dưới đây. Key ngoài whitelist → drop (không tạo row).
>
> Phạm vi: **spec cơ bản phục vụ tư vấn mua xe cá nhân** — power/torque/range/pin/
> kích thước/chỗ ngồi. Không lấy spec chi tiết (nội thất, ngoại thất, an toàn,
> màn hình, loa, tiêu thụ...) — không phải yếu tố quyết định việc mua xe.

## Whitelist (12 key, 4 category)

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

## Chuẩn hóa value

- `spec_value` chỉ chứa số / thuần text; đơn vị tách riêng `spec_unit` (riêng
  `drivetrain`, `seats` để unit rỗng).
- Số phải qua sanity range (`SANITY_RANGES`) — value ngoài khoảng = junk → drop.
- `drivetrain` chuẩn hóa về `FWD` / `RWD` / `AWD` (bỏ "Cầu trước"/"Cầu sau").
- `range_km` / `battery_kwh`: nếu nguồn ghi đồng thời NEDC + WLTP → ưu tiên NEDC
  (VinFast marketing dùng NEDC).
- `dimension` label dạng "Dài x Rộng x Cao" → tách 3 row `length_mm`/`width_mm`/`height_mm`.

## Nguồn & caveat đơn vị `power_kw`

- Nguồn mặc định: dat-coc pages (`data/raw/*.txt`) + brochure PDF đã crawl/extract.
  Có thể chạy `parse_specs.py --crawl-brochures` để Crawl4AI tải PDF từ
  `data/raw/link_brochure.md` và LLM map về whitelist này. Conflict → ưu tiên
  `shop.vinfastauto.com`.
- Một số brochure là image-only PDF (ví dụ VF3), không có text layer để Crawl4AI
  đọc. Pipeline fallback sang render ảnh + vision LLM OCR; nếu vision thất bại
  thì giữ fallback từ dat-coc/raw và không tự bịa edition từ ảnh.
- ⚠️ **`power_kw` lấy token số đầu tiên của label `Công suất tối đa`**. Nếu label có
  dạng `(kW/Hp)` / `(hp/kW)` (VD VF 8: `150/201`, VF 9: `402/300`), parser lấy **hp**
  thay vì kW → cảnh báo dữ liệu nhưng hiện chưa tự đổi. Khi cần chính xác phải xử lý
  riêng unit-order (chưa làm).
- ⚠️ **VF 8 All New** (brochure layout "labels-then-values") chưa get được range/DC/FWD.

## Metadata / version

- `model_code`, `version_name`, `version_code` chuẩn hóa từ `car_catalog` (API
  `omapi.vinfastauto.com/fe/v1/carModel`), không tự bịa.
- `source_url` = link nguồn crawl (để trích dẫn + audit).
- Conflict giá trị giữa nhiều nguồn → ưu tiên `shop.vinfastauto.com` >
  `vinfastauto.com` (`SOURCE_PRIORITY`).

## Liên quan

- Bảng: `docs/DATA_SCHEMA_SPEC.md` §5.x `car_specs`.
- Pipeline: `docs/DATA_PIPELINE.md` bước 3/6 `parse_specs.py`.
- Tool đọc: `get_specs(model_code, version)` — trả `[{spec_key, spec_value, spec_unit}]`.
