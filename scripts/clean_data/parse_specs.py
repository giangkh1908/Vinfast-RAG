#!/usr/bin/env python3
"""
parse_specs.py — Trích thông số kỹ thuật từ data/model_data/*.csv (spec sheets)
→ data/clean/<version>/postgres/specs.csv

Nguồn: data/model_data/*.csv — file CSV 2 cột (label, value) export từ bảng spec
brochure (1 file = 1 model + 1 edition, edition đọc từ row "PHIÊN BẢN"/"Phiên bản").
Section header = row có label nhưng value rỗng (vd "KÍCH THƯỚC,").

Script extract TOÀN BỘ row: spec số (công suất, pin…) lẫn spec tính năng
(Có/Không, LED, v.v.). Label không khớp mapping → giữ nguyên label (đã normalize)
làm spec_key, category lấy từ section context.
"""
import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

# Windows console cp1252 → UTF-8 (emoji / tiếng Việt trong print)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Chạy trực tiếp (`python scripts/clean_data/parse_specs.py`) → repo root vào sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.config import CLEAN_DIR, MODEL_DATA_DIR  # noqa: E402
from scripts.clean_data.spec_common import (  # noqa: E402
    MODEL_EDITIONS, MODEL_LABEL, infer_model, no_diacritics,
)

# ── Mappings ─────────────────────────────────────────────────────────────────
# Label map (đã normalize) — spec số + spec tính năng có unit
LABEL_MAP = {
    # ── powertrain ──
    "cong suat toi da (kw)": ("power_kw", "kW", "powertrain"),
    "cong suat toi da (kw/hp)": ("power_kw", "kW", "powertrain"),
    "cong suat toi da (hp/kw)": ("power_kw", "kW", "powertrain"),
    "cong suat toi da": ("power_kw", "kW", "powertrain"),
    "mo men xoan cuc dai (nm)": ("torque_nm", "Nm", "powertrain"),
    "mo-men xoan cuc dai": ("torque_nm", "Nm", "powertrain"),
    "toc do toi da (km/h)": ("top_speed_kmh", "km/h", "powertrain"),
    "toc do toi da (km/h) duy tri 1 phut": ("top_speed_kmh", "km/h", "powertrain"),
    "tang toc 0-100 km/h": ("acceleration_0_100_s", "s", "powertrain"),
    "tang toc 0-100km/h (s)": ("acceleration_0_100_s", "s", "powertrain"),
    "tang toc 0 - 100 km/h (s)": ("acceleration_0_100_s", "s", "powertrain"),
    "tang toc 0 - 50 km/h (s)": ("acceleration_0_50_s", "s", "powertrain"),
    "kha nang tang toc tu 0-100km/h (s)": ("acceleration_0_100_s", "s", "powertrain"),
    "muc tieu thu nl (hon hop) (kwh/100 km)": ("energy_consumption_kwh_100km", "kWh/100km", "powertrain"),
    "cau hinh dong co": ("motor_configuration", "", "powertrain"),
    "dong co": ("motor_configuration", "", "powertrain"),
    "cach chuyen so": ("gear_shift_type", "", "powertrain"),
    "can chuyen so sau vo lang": ("gear_shift_type", "", "powertrain"),
    "che do thay doi toc do den dung": ("creep_mode", "", "powertrain"),
    "dan dong": ("drivetrain", "", "powertrain"),
    "he dan dong": ("drivetrain", "", "powertrain"),
    "khoi dong bang ban dap phanh - bev": ("brake_pedal_start", "", "powertrain"),
    # ── battery ──
    "loai pin": ("battery_type", "", "battery"),
    "quang duong chay mot lan sac day (km) (nedc)": ("range_km", "km", "battery"),
    "quang duong chay mot lan sac day (km)": ("range_km", "km", "battery"),
    "quang duong chay mot lan sac day": ("range_km", "km", "battery"),
    "quang duong chay (nedc)": ("range_km", "km", "battery"),
    "quang duong di chuyen": ("range_km", "km", "battery"),
    "quang duong": ("range_km", "km", "battery"),
    "dung luong pin kha dung": ("battery_kwh", "kWh", "battery"),
    "dung luong pin (kwh)": ("battery_kwh", "kWh", "battery"),
    "dung luong pin (kwh) - kha dung": ("battery_kwh", "kWh", "battery"),
    "dung luong pin": ("battery_kwh", "kWh", "battery"),
    "cong suat sac toi da (kw)": ("max_charge_power_kw", "kW", "battery"),
    "cong suat sac ac toi da (kw)": ("ac_charge_power_kw", "kW", "battery"),
    "cong suat sac cham ac toi da (kw)": ("ac_charge_power_kw", "kW", "battery"),
    "cong suat sac nhanh dc toi da (kw)": ("dc_charge_power_kw", "kW", "battery"),
    "tinh nang sac nhanh": ("fast_charge_capable", "", "battery"),
    "thoi gian nap pin nhanh nhat (phut)": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat (tu 10 den 70%) (phut)": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat (tu 10% len 70%) (phut)": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat tu 10% den 70% (phut)": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh nhat (phut) tu 10% den 70%": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin nhanh (phut)": ("fast_charge_min", "phút", "battery"),
    "thoi gian nap pin binh thuong (gio)": ("normal_charge_hours", "giờ", "battery"),
    # ── dimension ──
    "dai x rong x cao (mm)": ("dimension_triple", "mm", "dimension"),
    "dai x rong x cao": ("dimension_triple", "mm", "dimension"),
    "chieu dai co so": ("wheelbase_mm", "mm", "dimension"),
    "khoang sang gam xe": ("ground_clearance_mm", "mm", "dimension"),
    "khoi luong khong tai": ("curb_weight_kg", "kg", "dimension"),
    "trong luong khong tai": ("curb_weight_kg", "kg", "dimension"),
    "tai trong": ("payload_kg", "kg", "dimension"),
    "suc chua (kg)": ("payload_kg", "kg", "dimension"),
    "duong kinh quay dau toi thieu (m)": ("turning_diameter_m", "m", "dimension"),
    "dung tich cop sau": ("trunk_capacity", "L", "dimension"),
    "dung tich khoang chua hanh ly": ("trunk_capacity", "L", "dimension"),
    "dung tich khoang chua hanh ly (l) - phia truoc": ("frunk_capacity_l", "L", "dimension"),
    "tai trong hanh ly noc xe": ("roof_load_kg", "kg", "dimension"),
    # ── interior ──
    "so ghe ngoi": ("seats", "", "interior"),
    "so cho ngoi": ("seats", "", "interior"),
    "cho ngoi": ("seats", "", "interior"),
    "he thong loa": ("speakers", "số lượng", "interior"),
    "he thong am thanh": ("speakers", "số lượng", "interior"),
    "he thong am thanh cao cap": ("speaker_system", "", "interior"),
    "chuc nang giai tri": ("entertainment_function", "", "interior"),
    "cua gio dieu hoa hang ghe thu 2 va thu 3": ("rear_ac_vents", "", "interior"),
    "cua gio dieu hoa hang ghe thu 2: tren hop de do trung tam": ("row2_ac_vents", "", "interior"),
    "cua gio dieu hoa hang ghe thu 2: tren cot b": ("row2_ac_vents", "", "interior"),
    "man hinh giai tri cam ung": ("display_inch", "inch", "interior"),
    "man hinh giai tri trung tam": ("display_inch", "inch", "interior"),
    "man hinh giai tri cam ung hang ghe sau": ("rear_display_inch", "inch", "interior"),
    "man hinh thong tin lai": ("driver_display_inch", "inch", "interior"),
    "bang dong ho thong tin lai": ("driver_display_inch", "inch", "interior"),
    "man hinh thong tin sau vo lang": ("driver_display_inch", "inch", "interior"),
    "cong ket noi usb": ("usb_ports", "", "interior"),
    "cong ket noi usb loai a": ("usb_port_type_a", "", "interior"),
    "cong ket noi usb loai c": ("usb_port_type_c", "", "interior"),
    "cong ket noi usb loai a hang ghe lai": ("usb_a_front", "", "interior"),
    "cong ket noi usb loai a hang ghe thu 2": ("usb_a_row2", "", "interior"),
    "cong ket noi usb loai a hang ghe thu 3": ("usb_a_row3", "", "interior"),
    "cong sac 12v": ("12v_outlet", "", "interior"),
    "cong sac 12v khoang hanh ly": ("12v_trunk_outlet", "", "interior"),
    "o dien xoay chieu": ("ac_power_outlet", "", "interior"),
    "am ly": ("amplifier", "", "interior"),
    "ghe lai": ("driver_seat_type", "", "interior"),
    "ghe phu": ("passenger_seat_type", "", "interior"),
    "hang ghe thu hai": ("second_row_seat_type", "", "interior"),
    "hang ghe thu 2 dieu chinh huong": ("second_row_adjust", "", "interior"),
    "hang ghe thu 2 dieu chinh gap ty le": ("second_row_fold", "", "interior"),
    "hang ghe thu 2 co massage": ("second_row_massage", "", "interior"),
    "hang ghe thu 2 co suoi": ("second_row_heating", "", "interior"),
    "hang ghe thu 2 co thong gio": ("second_row_ventilation", "", "interior"),
    "gap lung ghe hang ghe thu 2": ("second_row_fold", "", "interior"),
    "gap hang ghe thu 3": ("row3_fold", "", "interior"),
    "len xuong de dang (len/xuong tu hang thu 2)": ("easy_access", "", "interior"),
    "tua dau ghe lai": ("driver_headrest", "", "interior"),
    "tua dau ghe phu": ("passenger_headrest", "", "interior"),
    "tua dau ghe hang 2": ("row2_headrest", "", "interior"),
    "tua dau ghe hang 3": ("row3_headrest", "", "interior"),
    "ghe vip": ("vip_seat", "", "interior"),
    "ghe vip chinh dien": ("vip_seat_power", "", "interior"),
    "ghe vip massage": ("vip_seat_massage", "", "interior"),
    "ghe vip co suoi": ("vip_seat_heating", "", "interior"),
    "ghe vip co thong gio": ("vip_seat_ventilation", "", "interior"),
    "hop do hang ghe sau": ("rear_console_box", "", "interior"),
    "dieu chinh vo lang": ("steering_wheel_adjust", "", "interior"),
    "suoi tay lai": ("heated_steering_wheel", "", "interior"),
    "nho vi tri vo lang": ("steering_wheel_memory", "", "interior"),
    "boc vo lang": ("steering_wheel_wrap", "", "interior"),
    "vo lang": ("steering_wheel_type", "", "interior"),
    "cac ngon ngu ho tro": ("supported_languages", "", "interior"),
    "phanh tay": ("parking_brake", "", "interior"),
    "phanh do": ("parking_brake", "", "interior"),
    "phanh do dien tu va che do tu dong giu phanh": ("epb_auto_hold", "", "convenience"),
    "phanh tay dien tu va tu dong giu phanh": ("epb_auto_hold", "", "convenience"),
    "khay dung dung cu sua xe": ("tool_kit", "", "interior"),
    "moc keo toi": ("tow_hook", "", "interior"),
    # ── exterior ──
    "kich thuoc la-zang": ("wheel_size_inch", "inch", "exterior"),
    "kich thuoc la-zang (inch)": ("wheel_size_inch", "inch", "exterior"),
    "kich thuoc mam xe": ("wheel_size_inch", "inch", "exterior"),
    "loai la-zang": ("wheel_type", "", "exterior"),
    "kich thuoc lop & la-zang": ("tire_wheel_size", "", "exterior"),
    "kich thuoc lop": ("tire_size", "", "exterior"),
    "tay nam cua": ("door_handle_type", "", "exterior"),
    "co che lay mo cua": ("door_opening_mechanism", "", "exterior"),
    "cua hit": ("power_suction_doors", "", "exterior"),
    "dieu khien do cao goc chieu den": ("headlight_leveling", "", "exterior"),
    "den dinh vi": ("position_light", "", "exterior"),
    "den chao mung": ("welcome_light", "", "exterior"),
    "den nhan dien thuong hieu phia truoc/sau": ("brand_light", "", "exterior"),
    "den nhan dien thuong hieu truoc va sau": ("brand_light", "", "exterior"),
    "guong chieu hau ngoai": ("exterior_mirror_type", "", "exterior"),
    "guong chieu hau trong xe": ("interior_mirror_type", "", "interior"),
    "kinh cua so dien": ("power_windows", "", "exterior"),
    "den chieu sang khi mo cua": ("puddle_light", "", "exterior"),
    "den chieu logo mat duong (cam bien da cop)": ("logo_light", "", "exterior"),
    "bac len xuong": ("side_step", "", "exterior"),
    "thanh trang tri noc xe": ("roof_rack", "", "exterior"),
    "canh huong gio": ("spoiler", "", "exterior"),
    "co che dong mo cong sac": ("charge_port_door", "", "exterior"),
    "thanh gia cuong cua xe": ("door_impact_beam", "", "exterior"),
    "dong/mo cop sau": ("trunk_lid_type", "", "exterior"),
    "dong/mo cop da chan": ("kick_sensor_trunk", "", "exterior"),
    "phanh truoc": ("front_brake_type", "", "chassis"),
    "phanh sau": ("rear_brake_type", "", "chassis"),
    "bo va lop": ("tire_repair_kit", "", "chassis"),
    "bo dung cu kich xe": ("jack_kit", "", "chassis"),
    # ── airbag sub-types (prefix match truoc "tui khi" generic) ──
    "he thong tui khi": ("airbags", "", "safety"),
    "tui khi truoc lai va hanh khach phia truoc": ("front_airbags", "", "safety"),
    "tui khi phia truoc cho nguoi lai va hanh khach phia truoc": ("front_airbags", "", "safety"),
    "tui khi danh cho nguoi lai": ("driver_airbag", "", "safety"),
    "tui khi ben hong hang ghe truoc": ("side_airbags_front", "", "safety"),
    "tui khi ben hong hang ghe sau": ("side_airbags_rear", "", "safety"),
    "tui khi ben hong": ("side_airbags", "", "safety"),
    "tui khi rem": ("curtain_airbags", "", "safety"),
    "tui khi bao ve chan hang ghe truoc": ("knee_airbags", "", "safety"),
    "tui khi trung tam hang ghe truoc": ("center_airbags", "", "safety"),
    "so luong tui khi": ("airbags", "", "safety"),
    "tui khi": ("airbags", "", "safety"),
}

ALIASES_BY_LEN = sorted(LABEL_MAP.keys(), key=len, reverse=True)

CSV_FIELDS = ["model_code", "version_name", "version_code",
              "spec_category", "spec_category_vn",
              "spec_key", "spec_key_vn",
              "spec_value", "spec_unit", "source_url"]

# ── Vietnamese labels ────────────────────────────────────────────────────────
CATEGORY_VN_MAP = {
    "dimension": "Kích thước & trọng lượng",
    "powertrain": "Hệ thống truyền động",
    "battery": "Pin & sạc",
    "exterior": "Ngoại thất",
    "interior": "Nội thất",
    "infotainment": "Giải trí & kết nối",
    "safety": "An toàn",
    "adas": "Hỗ trợ lái nâng cao (ADAS)",
    "chassis": "Khung gầm & hệ thống treo",
    "convenience": "Tiện nghi",
    "security": "An ninh",
    "connected": "Kết nối thông minh",
    "general": "Thông tin chung",
}

SPEC_KEY_VN_MAP = {
    # ── dimension ──
    "length_mm": "Chiều dài tổng thể",
    "width_mm": "Chiều rộng tổng thể",
    "height_mm": "Chiều cao tổng thể",
    "wheelbase_mm": "Chiều dài cơ sở",
    "ground_clearance_mm": "Khoảng sáng gầm xe",
    "curb_weight_kg": "Trọng lượng không tải",
    "payload_kg": "Tải trọng / Sức chứa",
    "roof_load_kg": "Tải trọng hành lý nóc xe",
    "turning_diameter_m": "Đường kính quay đầu tối thiểu",
    "trunk_capacity": "Dung tích khoang hành lý",
    "frunk_capacity_l": "Dung tích khoang hành lý phía trước",
    # ── powertrain ──
    "power_kw": "Công suất tối đa",
    "torque_nm": "Mô-men xoắn cực đại",
    "top_speed_kmh": "Tốc độ tối đa",
    "acceleration_0_100_s": "Tăng tốc 0-100 km/h",
    "acceleration_0_50_s": "Tăng tốc 0-50 km/h",
    "energy_consumption_kwh_100km": "Mức tiêu thụ năng lượng",
    "motor_configuration": "Cấu hình động cơ",
    "gear_shift_type": "Cách chuyển số",
    "creep_mode": "Chế độ thay đổi tốc độ đến dừng",
    "drivetrain": "Dẫn động",
    "drive_modes": "Chế độ lái",
    "battery_heater": "Sưởi pin cao thế",
    "home_charger_type": "Bộ sạc tại nhà",
    "mobile_charger_type": "Dây sạc di động",
    "regenerative_braking": "Hệ thống phanh tái sinh",
    "brake_pedal_start": "Khởi động bằng bàn đạp phanh",
    # ── battery ──
    "battery_type": "Loại pin",
    "battery_kwh": "Dung lượng pin khả dụng",
    "range_km": "Phạm vi di chuyển",
    "fast_charge_min": "Thời gian nạp pin nhanh nhất",
    "normal_charge_hours": "Thời gian nạp pin bình thường",
    "max_charge_power_kw": "Công suất sạc tối đa",
    "ac_charge_power_kw": "Công suất sạc AC tối đa",
    "dc_charge_power_kw": "Công suất sạc nhanh DC tối đa",
    "fast_charge_capable": "Tính năng sạc nhanh",
    # ── exterior ──
    "headlight_type": "Đèn chiếu sáng phía trước",
    "headlight_feature": "Đèn pha",
    "headlight_leveling": "Điều khiển góc chiếu đèn",
    "auto_headlights": "Đèn pha tự động",
    "adaptive_headlights": "Đèn pha tự động / thích ứng",
    "drl_type": "Đèn chiếu sáng ban ngày",
    "tail_light_type": "Đèn hậu",
    "position_light": "Đèn định vị",
    "welcome_light": "Đèn chào mừng",
    "front_brand_light": "Đèn nhận diện thương hiệu trước",
    "rear_brand_light": "Đèn nhận diện thương hiệu sau",
    "brand_light": "Đèn nhận diện thương hiệu",
    "auto_high_beam": "Tự động bật/tắt chế độ chiếu xa",
    "auto_wiper": "Gạt mưa trước tự động",
    "power_folding_mirrors": "Gương chiếu hậu chỉnh điện / gập điện",
    "one_touch_windows": "Kính cửa sổ chỉnh điện 1 chạm",
    "power_windows": "Kính cửa sổ điện",
    "wheel_size_inch": "Kích thước la-zăng",
    "wheel_type": "Loại la-zăng",
    "tire_wheel_size": "Kích thước lốp & la-zăng",
    "tire_size": "Kích thước lốp",
    "daytime_running_light": "Đèn chờ dẫn đường",
    "fog_light_front": "Đèn sương mù trước",
    "cornering_light": "Đèn chiếu góc",
    "high_mount_brake_light": "Đèn phanh trên cao phía sau",
    "rearview_mirror_type": "Gương chiếu hậu",
    "exterior_mirror_type": "Gương chiếu hậu ngoài",
    "interior_mirror_type": "Gương chiếu hậu trong xe",
    "window_type": "Kiểu cửa sổ",
    "privacy_glass": "Kính cửa sổ màu đen (riêng tư)",
    "trunk_lid_type": "Điều chỉnh cốp sau",
    "kick_sensor_trunk": "Đóng/mở cốp đá chân",
    "windshield_type": "Kính chắn gió",
    "underbody_protection": "Tấm bảo vệ dưới thân xe",
    "smart_key": "Chìa khóa thông minh",
    "door_handle_type": "Tay nắm cửa",
    "door_opening_mechanism": "Cơ chế mở cửa",
    "power_suction_doors": "Cửa hít",
    "puddle_light": "Đèn chiếu sáng khi mở cửa",
    "logo_light": "Đèn chiếu logo mặt đường",
    "side_step": "Bậc lên xuống",
    "roof_rack": "Thanh trang trí nóc xe",
    "spoiler": "Cánh hướng gió",
    "charge_port_door": "Cơ chế đóng mở cổng sạc",
    "door_impact_beam": "Thanh gia cường cửa xe",
    # ── interior ──
    "leatherette_seats": "Ghế bọc da nhân tạo",
    "seat_material_type": "Chất liệu bọc ghế",
    "seats": "Số ghế ngồi",
    "speakers": "Hệ thống loa",
    "speaker_system": "Hệ thống âm thanh",
    "epb_auto_hold": "Phanh đỗ điện tử & giữ phanh tự động",
    "gps_tracking": "Định vị xe từ xa",
    "second_row_seat_type": "Hàng ghế thứ hai",
    "steering_wheel_type": "Loại vô lăng",
    "ac_type": "Hệ thống điều hòa",
    "cabin_air_filter": "Lọc không khí Cabin",
    "rear_ac_vents": "Ống thông gió dưới chân hành khách sau",
    "head_up_display": "Màn hình hiển thị HUD",
    "usb_port_type_a": "Cổng kết nối USB loại A",
    "usb_port_type_c": "Cổng kết nối USB loại C",
    "usb_ports": "Cổng kết nối USB",
    "usb_a_front": "Cổng USB loại A hàng ghế lái",
    "usb_a_row2": "Cổng USB loại A hàng ghế thứ 2",
    "usb_a_row3": "Cổng USB loại A hàng ghế thứ 3",
    "12v_outlet": "Cổng sạc 12V",
    "12v_trunk_outlet": "Cổng sạc 12V khoang hành lý",
    "ac_power_outlet": "Ổ điện xoay chiều",
    "amplifier": "Âm ly",
    "wireless_charging": "Sạc không dây",
    "wifi_connectivity": "Kết nối Wifi",
    "bluetooth_connectivity": "Kết nối Bluetooth",
    "subwoofer": "Loa trầm",
    "ambient_lighting": "Đèn trang trí nội thất",
    "sunroof_type": "Cửa sổ trời",
    "driver_display_inch": "Màn hình thông tin lái",
    "rear_display_inch": "Màn hình giải trí hàng ghế sau",
    "display_inch": "Màn hình giải trí cảm ứng",
    "parking_brake": "Phanh tay",
    "supported_languages": "Các ngôn ngữ hỗ trợ",
    "driver_seat_type": "Ghế lái",
    "passenger_seat_type": "Ghế phụ",
    "second_row_seat_type": "Hàng ghế thứ hai",
    "tool_kit": "Khay đựng dụng cụ sửa xe",
    "tow_hook": "Móc kéo tời",
    "defroster": "Chức năng làm tan sương/tan băng",
    "air_quality_control": "Kiểm soát chất lượng không khí",
    "air_ionizer": "Ion hóa không khí",
    "rear_defroster": "Sưởi kính sau",
    "glovebox_light": "Đèn hộc để đồ trước",
    "trunk_light": "Đèn khoang hành lý",
    "frunk_light": "Đèn khoang hành lý trước",
    "dome_light": "Đèn trần phía trước",
    "cabin_lights": "Đèn trần cabin",
    "sun_visor_mirror": "Tấm che nắng, có gương",
    "cupholders": "Hộc đựng cốc",
    # ── infotainment ──
    "smartphone_integration": "Kết nối Android Auto / Apple CarPlay",
    "navigation": "Điều hướng & dẫn đường",
    "web_browser": "Trình duyệt web",
    "gaming": "Trò chơi",
    "self_diagnosis": "Tự chẩn đoán lỗi",
    "ota_update": "Cập nhật phần mềm từ xa",
    "basic_widgets": "Khung tiện ích cơ bản (lịch, thời tiết, media, bản đồ)",
    "voice_search": "Hỏi đáp & tìm kiếm thông tin cơ bản",
    "voice_control": "Điều khiển chức năng xe bằng giọng nói",
    "voice_navigation": "Dẫn đường bằng giọng nói",
    "voice_greeting": "Chào hỏi / thực hiện lệnh theo kịch bản",
    "vehicle_status_assist": "Tư vấn tình trạng xe & hỗ trợ xử lý sự cố",
    "phone_app": "Ứng dụng điện thoại",
    "ev_routing": "Dẫn đường nâng cao cho xe điện (tìm trạm sạc)",
    "vehicle_modes": "Chế độ xe cơ bản (cắm trại, người lạ, thú cưng, rửa xe)",
    "basic_entertainment": "Giải trí cơ bản (Đài FM, Bluetooth, USB)",
    "basic_map": "Bản đồ cơ bản",
    "basic_map_navigation": "Bản đồ cơ bản (Tìm địa điểm, Dẫn đường, tình trạng giao thông, hình vệ tinh)",
    "charging_etc": "Sạc, v.v.",
    "online_entertainment": "Giải trí trực tuyến",
    "entertainment_function": "Chức năng giải trí",
    "user_manual": "Hướng dẫn sử dụng",
    "free_software": "Phần mềm miễn phí",
    "paid_software": "Phần mềm thu phí",
    "app_store": "Chợ ứng dụng",
    "special_operation_modes": "Chế độ vận hành đặc biệt",
    "activity_limits": "Giới hạn thời gian hoạt động & khu vực hoạt động",
    "camping_mode": "Chế độ cắm trại",
    "maintenance_reminder": "Đề xuất lịch bảo trì/bảo dưỡng tự động",
    "phone_media": "Giải trí thông qua đồng bộ điện thoại",
    "audio_entertainment": "Giải trí âm thanh",
    "internet_access": "Tra cứu & truy cập Internet",
    "calendar_contact_sync": "Đồng bộ lịch và danh bạ điện thoại",
    "contact_sync": "Đồng bộ danh bạ điện thoại",
    "fota_update": "Cập nhật phần mềm miễn phí FOTA",
    "sota_update": "Cập nhật phần mềm thu phí SOTA",
    # ── safety ──
    "abs": "Chống bó cứng phanh (ABS)",
    "ebd": "Phân phối lực phanh điện tử (EBD)",
    "brake_assist": "Hỗ trợ phanh khẩn cấp (BA)",
    "esc": "Cân bằng điện tử (ESC)",
    "tcs": "Kiểm soát lực kéo (TCS)",
    "hsa": "Hỗ trợ khởi hành ngang dốc (HSA)",
    "tpms": "Giám sát áp suất lốp",
    "airbags": "Túi khí",
    "front_airbags": "Túi khí trước",
    "driver_airbag": "Túi khí người lái",
    "side_airbags": "Túi khí bên hông",
    "side_airbags_front": "Túi khí bên hông ghế trước",
    "side_airbags_rear": "Túi khí bên hông ghế sau",
    "curtain_airbags": "Túi khí rèm",
    "knee_airbags": "Túi khí bảo vệ chân",
    "center_airbags": "Túi khí trung tâm",
    "rollover_mitigation": "Chức năng chống lật ROM",
    "emergency_stop_signal": "Đèn báo phanh khẩn cấp ESS",
    "auto_door_lock": "Khóa cửa xe tự động khi xe di chuyển",
    "pretensioner_seatbelt": "Căng đai khẩn cấp",
    "isofix": "Móc cố định ghế trẻ em ISOFIX",
    "seatbelt_warning": "Cảnh báo dây an toàn",
    "child_lock": "Khóa cửa trẻ em",
    "emergency_call": "Gọi cứu hộ tự động & hỗ trợ trên đường",
    "key_type": "Loại chìa khóa",
    "key_system": "Hệ thống chìa khóa",
    # ── adas ──
    "blind_spot_warning": "Cảnh báo điểm mù",
    "lane_departure_warning": "Cảnh báo chệch làn",
    "lane_keep_assist": "Hỗ trợ giữ làn",
    "emergency_lane_keep": "Hỗ trợ giữ làn khẩn cấp",
    "forward_collision_warning": "Cảnh báo va chạm phía trước",
    "aeb_front": "Phanh tự động khẩn cấp trước",
    "aeb_front_rear": "Phanh tự động khẩn cấp trước/sau",
    "auto_lane_change": "Hỗ trợ tự động chuyển làn",
    "highway_driving_assist": "Trợ lái trên cao tốc / di chuyển khi tắc đường",
    "traffic_jam_assist": "Hỗ trợ di chuyển khi ùn tắc",
    "highway_assist": "Hỗ trợ lái trên đường cao tốc",
    "rear_cross_traffic_alert": "Cảnh báo phương tiện cắt ngang phía sau",
    "door_open_warning": "Cảnh báo mở cửa",
    "driver_monitoring": "Cảnh báo tài xế buồn ngủ & mất tập trung",
    "rear_parking_assist": "Hỗ trợ đỗ xe phía sau",
    "front_parking_assist": "Hỗ trợ đỗ xe phía trước",
    "front_parking_sensor": "Cảm biến đỗ xe phía trước",
    "rear_parking_sensor": "Cảm biến đỗ xe phía sau",
    "rearview_camera": "Camera lùi",
    "surround_view_camera": "Camera 360° / giám sát xung quanh",
    "cruise_control_type": "Kiểm soát hành trình",
    "adaptive_cruise_control": "Điều chỉnh tốc độ thông minh",
    "traffic_sign_recognition": "Nhận biết biển báo giao thông",
    "lane_centering": "Kiểm soát đi giữa làn",
    "hill_descent_control": "Hỗ trợ xuống dốc HDC",
    "emergency_stop": "Tự động dừng khẩn cấp",
    # ── chassis ──
    "front_suspension_type": "Hệ thống treo trước",
    "rear_suspension_type": "Hệ thống treo sau",
    "suspension_type": "Hệ thống treo (trước/sau)",
    "front_brake_type": "Phanh trước",
    "rear_brake_type": "Phanh sau",
    "brake_type": "Hệ thống phanh trước/sau",
    "steering_assist_type": "Trợ lực lái",
    "stabilizer_bar": "Thanh cân bằng trước",
    "tire_repair_kit": "Bộ vá lốp",
    "jack_kit": "Bộ dụng cụ kích xe",
    "driver_headrest": "Tựa đầu ghế lái",
    "passenger_headrest": "Tựa đầu ghế phụ",
    "row2_headrest": "Tựa đầu ghế hàng 2",
    "row3_headrest": "Tựa đầu ghế hàng 3",
    "second_row_adjust": "Hàng ghế thứ 2 điều chỉnh hướng",
    "second_row_fold": "Hàng ghế thứ 2 gập tỷ lệ",
    "second_row_ventilation": "Hàng ghế thứ 2 thông gió",
    "second_row_heating": "Hàng ghế thứ 2 sưởi",
    "second_row_massage": "Hàng ghế thứ 2 massage",
    "row3_fold": "Gập hàng ghế thứ 3",
    "easy_access": "Lên xuống dễ dàng",
    "vip_seat": "Ghế VIP",
    "vip_seat_power": "Ghế VIP chỉnh điện",
    "vip_seat_massage": "Ghế VIP massage",
    "vip_seat_ventilation": "Ghế VIP thông gió",
    "vip_seat_heating": "Ghế VIP sưởi",
    "rear_console_box": "Hộp đồ hàng ghế sau",
    "steering_wheel_adjust": "Điều chỉnh vô lăng",
    "steering_wheel_memory": "Nhớ vị trí vô lăng",
    "steering_wheel_wrap": "Bọc vô lăng",
    "heated_steering_wheel": "Sưởi tay lái",
    "row2_ac_vents": "Cửa gió điều hòa hàng ghế thứ 2",
    "virtual_assistant": "Trợ lý ảo",
    "vehicle_control": "Điều khiển chức năng trên xe",
    "quick_control": "Hỗ trợ điều khiển, thiết lập nhanh",
    "media_control": "Hỗ trợ giải trí đa phương tiện",
    "handsfree_call": "Hỗ trợ gọi điện thoại rảnh tay",
    "small_talk": "Chuyện phiếm & tiếu lâm",
    "general_qa": "Hỏi đáp thông tin chung",
    "basic_settings": "Cài đặt cơ bản",
    "advanced_settings": "Cài đặt nâng cao (AI tạo sinh)",
    "assistant_feedback": "Cập nhật / góp ý cho trợ lý ảo",
    "usage_guidance": "Tư vấn cách thức sử dụng và vận hành",
    # ── security ──
    "immobilizer": "Khoá động cơ khi có trộm",
    "anti_theft_alarm": "Cảnh báo chống trộm",
    # ── connected ──
    "account_sync": "Đồng bộ tài khoản / ứng dụng / phân quyền",
    "vehicle_status_notification": "Thông báo trạng thái xe (pin, hiệu suất, bảo dưỡng)",
    "charge_management": "Quản lý sạc & thanh toán phí sạc",
    "charge_payment": "Thanh toán phí sạc",
    "charger_map": "Bản đồ trạm sạc",
    "service_booking": "Dịch vụ hậu mãi: đặt lịch sửa chữa, lái thử",
    "online_accessory_shop": "Mua bán phụ kiện",
    "vehicle_monitoring": "Giám sát xe từ xa",
    "remote_control": "Điều khiển xe từ xa",
    "remote_settings": "Thiết lập cài đặt từ xa",
    "advanced_battery_management": "Quản lý pin nâng cao",
    "battery_lease_management": "Quản lý gói cước thuê pin trực tuyến",
    "promo_info": "Thông tin khuyến mại & phụ kiện",
    "notifications": "Nhận thông báo",
    "wifi_management": "Quản lý WiFi",
    "bluetooth_management": "Quản lý thiết bị Bluetooth",
    "esim_management": "Quản lý eSIM",
    "battery_monitoring": "Giám sát tình trạng pin",
    "driver_profile": "Hồ sơ người lái",
    "advanced_profile": "Hồ sơ nâng cao",
}

# ── SECTION_CATEGORY_MAP: section header → spec_category ──────────────────────
# Dùng để track context: khi section header xuất hiện, các row không mapped
# phía dưới sẽ được gán category tương ứng thay vì "general".
SECTION_CATEGORY_MAP = {
    "kich thuoc": "dimension",
    "kich thuoc & tai trong": "dimension",
    "tai trong": "dimension",
    "he thong truyen dong": "powertrain",
    "he truyen dong": "powertrain",
    "dong co": "powertrain",
    "thong so dong co": "powertrain",
    "thong so truyen dong khac": "powertrain",
    "truyen dong khac": "powertrain",
    "pin": "battery",
    "pin & sac": "battery",
    "thong so pin": "battery",
    "khung gam": "chassis",
    "khung gam khac": "chassis",
    "giam xoc": "chassis",
    "phanh": "chassis",
    "he thong treo": "chassis",
    "vanh va lop xe": "chassis",
    "vanh va lop banh xe": "chassis",
    "ngoai that": "exterior",
    "den ngoai that": "exterior",
    "den ngoai that khac": "exterior",
    "den pha": "exterior",
    "guong": "exterior",
    "guong chieu hau": "exterior",
    "cua": "exterior",
    "cop": "exterior",
    "thiet ke kieu dang ngoai that": "exterior",
    "noi that & tien nghi": "interior",
    "noi that": "interior",
    "noi that & tien nghi khac": "interior",
    "ghe toan xe": "interior",
    "ghe lai": "interior",
    "ghe phu": "interior",
    "ghe hang 2": "interior",
    "ghe vip": "interior",
    "vo lang": "interior",
    "dieu hoa khong khi": "interior",
    "man hinh va ket noi": "interior",
    "man hinh, ket noi, giai tri, tien nghi": "interior",
    "man hinh, ket noi giai tri": "interior",
    "he thong loa": "interior",
    "he thong den noi that": "interior",
    "thiet ke kieu dang noi that": "interior",
    "an toan & an ninh": "safety",
    "an toan": "safety",
    "he thong tui khi": "safety",
    "he thong ho tro nguoi lai nang cao adas": "adas",
    "cac tinh nang adas": "adas",
    "tro lai tren cao toc": "adas",
    "tro lan": "adas",
    "ho tro hanh trinh": "adas",
    "ho tro lai tieu chuan": "adas",
    "ho tro lan duong": "adas",
    "giam sat hanh trinh thich ung": "adas",
    "canh bao va cham": "adas",
    "tro lai khi co nguy co va cham": "adas",
    "ho tro do xe": "adas",
    "ho tro do xe tieu chuan": "adas",
    "ho tro khac": "adas",
    "cac tinh nang khac": "adas",
    "tinh nang thong minh": "infotainment",
    "cac tinh nang thong minh": "infotainment",
    "cac tinh nang dieu khien thong minh": "infotainment",
    "tinh nang dieu khien thong minh": "infotainment",
    "he thong tin giai tri tren xe": "infotainment",
    "he thong tin giai tri": "infotainment",
    "thong tin & giai tri": "infotainment",
    "tro ly ao": "infotainment",
    "tro ly ao vivi": "infotainment",
    "dieu khien xe thong minh (man hinh, giong noi, c-app)": "infotainment",
    "dieu huong - dan duong": "infotainment",
    "dieu huong, dan duong": "infotainment",
    "tien ich gia dinh va van phong": "infotainment",
    "tien ich": "infotainment",
    "giai tri": "infotainment",
    "che do xe dac biet": "infotainment",
    "quan ly": "connected",
    "quan ly ket noi": "connected",
    "chuan doan loi": "infotainment",
    "cap nhat phan mem tu xa": "infotainment",
    "huong dan su dung va xu ly khi co su co": "infotainment",
    "dieu khien chuc nang tren xe": "infotainment",
    "ca nhan hoa tro ly ao": "infotainment",
    "hoi dap va truy van thong tin": "infotainment",
    "ung dung dien thoai": "connected",
    "ung dung tren dien thoai thong minh": "connected",
    "ung dung vinfast (c-app)": "connected",
    "ung dung tren dong ho thong minh": "connected",
    "quan ly tai khoan & xe": "connected",
    "dieu khien & cai dat xe tu xa": "connected",
    "thiet lap, theo doi va ghi nho ho so nguoi lai": "connected",
    "an ninh - an toan": "connected",
    "an ninh an toan": "connected",
    "dich vu ve xe": "connected",
}

# ── FEATURE_NORM_MAP: normalize feature label → (eng_key, category) ─────────
# Dùng cho spec tính năng (Có/Không, LED, v.v.) không có trong LABEL_MAP.
FEATURE_NORM_MAP = {
    # ── Exterior ──
    "guong chieu hau chinh dien tich hop den bao re": ("power_folding_mirrors", "exterior"),
    "kinh cua so chinh dien len xuong mot cham": ("one_touch_windows", "exterior"),
    "den chieu sang phia truoc": ("headlight_type", "exterior"),
    "den chieu sang ban ngay": ("drl_type", "exterior"),
    "den pha": ("headlight_type", "exterior"),
    "den pha tu dong": ("auto_headlights", "exterior"),
    "den pha tu dong bat tat": ("auto_headlights", "exterior"),
    "den tu dong bat tat": ("auto_headlights", "exterior"),
    "tu dong bat tat den": ("auto_headlights", "exterior"),
    "den pha tu dong den pha thich ung": ("adaptive_headlights", "exterior"),
    "den pha tu dong den pha thich ung": ("adaptive_headlights", "exterior"),
    "den pha thich ung": ("adaptive_headlights", "exterior"),
    "den hau": ("tail_light_type", "exterior"),
    "den nhan dien thuong hieu phia truoc": ("front_brand_light", "exterior"),
    "den nhan dien thuong hieu phia sau": ("rear_brand_light", "exterior"),
    "tu dong bat tat che do chieu xa": ("auto_high_beam", "exterior"),
    "den chieu xa tu dong": ("auto_high_beam", "exterior"),
    "gat mua truoc tu dong": ("auto_wiper", "exterior"),
    "gat mua truoc": ("auto_wiper", "exterior"),
    "gat mua": ("auto_wiper", "exterior"),
    "chia khoa thong minh": ("smart_key", "exterior"),
    "he thong chia khoa xe": ("key_system", "exterior"),
    "chia khoa": ("key_type", "exterior"),
    "den cho dan duong": ("daytime_running_light", "exterior"),
    "den suong mu truoc": ("fog_light_front", "exterior"),
    "den chieu goc": ("cornering_light", "exterior"),
    "den phanh tren cao phia sau": ("high_mount_brake_light", "exterior"),
    "guong chieu hau": ("rearview_mirror_type", "exterior"),
    "kieu cua so": ("window_type", "exterior"),
    "kinh cua so mau den rieng tu": ("privacy_glass", "exterior"),
    "dieu chinh cop sau": ("trunk_lid_type", "exterior"),
    "kinh chan gio": ("windshield_type", "exterior"),
    "tam bao ve duoi than xe": ("underbody_protection", "exterior"),
    "kinh cua so len xuong mot cham": ("one_touch_windows", "exterior"),
    # ── Interior ──
    "ghe boc da nhan tao": ("leatherette_seats", "interior"),
    "chat lieu boc ghe": ("seat_material_type", "interior"),
    "boc ghe": ("seat_material_type", "interior"),
    "ghe lai": ("driver_seat_type", "interior"),
    "ghe phu": ("passenger_seat_type", "interior"),
    "hang ghe thu hai": ("second_row_seat_type", "interior"),
    "kinh cua so chinh dien len xuong mot cham tat ca cac vi tri": ("one_touch_windows_all", "interior"),
    "phanh do dien tu va che do tu dong giu phanh": ("epb_auto_hold", "convenience"),
    "phanh tay dien tu va tu dong giu phanh": ("epb_auto_hold", "convenience"),
    "so cho ngoi": ("seats", "interior"),
    "so ghe ngoi": ("seats", "interior"),
    "cho ngoi": ("seats", "interior"),
    "hang ghe thu hai": ("second_row_seat_type", "interior"),
    "loai vo lang": ("steering_wheel_type", "interior"),
    "he thong dieu hoa": ("ac_type", "interior"),
    "loc khong khi cabin": ("cabin_air_filter", "interior"),
    "ong thong gio duoi chan hanh khach sau": ("rear_ac_vents", "interior"),
    "cua gio dieu hoa hang ghe sau": ("rear_ac_vents", "interior"),
    "man hinh hien thi hud": ("head_up_display", "interior"),
    "man hinh hien thi thong tin tren kinh lai hud": ("head_up_display", "interior"),
    "cong ket noi usb loai a": ("usb_port_type_a", "interior"),
    "cong ket noi usb loai c": ("usb_port_type_c", "interior"),
    "sac khong day": ("wireless_charging", "interior"),
    "ket noi wifi": ("wifi_connectivity", "interior"),
    "ket noi wi fi": ("wifi_connectivity", "interior"),
    "ket noi bluetooth": ("bluetooth_connectivity", "interior"),
    "loa tram": ("subwoofer", "interior"),
    "den trang tri noi that": ("ambient_lighting", "interior"),
    "cua so troi": ("sunroof_type", "interior"),
    "chuc nang lam tan suong tan bang": ("defroster", "interior"),
    "chuc nang kiem soat chat luong khong khi": ("air_quality_control", "interior"),
    "chuc nang ion hoa khong khi": ("air_ionizer", "interior"),
    "suoi kinh sau": ("rear_defroster", "interior"),
    "den hoc de do truoc": ("glovebox_light", "interior"),
    "den khoang hanh ly": ("trunk_light", "interior"),
    "den khoang hanh ly truoc": ("frunk_light", "interior"),
    "den tran phia truoc": ("dome_light", "interior"),
    "den tran hang ghe 1 va hang ghe 2": ("cabin_lights", "interior"),
    "tam che nang co guong": ("sun_visor_mirror", "interior"),
    "hoc dung coc giua hang ghe truoc": ("cupholders", "interior"),
    "khay dung dung cu sua xe": ("tool_kit", "interior"),
    "moc keo toi": ("tow_hook", "interior"),
    "khoi dong bang ban dap phanh bev": ("brake_pedal_start", "powertrain"),
    # ── Infotainment ──
    "man hinh giai tri cam ung": ("display_inch", "interior"),
    "he thong loa": ("speakers", "interior"),
    "ket noi voi android auto va apple carplay": ("smartphone_integration", "infotainment"),
    "ket noi android auto va apple carplay khong day": ("smartphone_integration", "infotainment"),
    "ket noi voi android auto va apple carplay khong day": ("smartphone_integration", "infotainment"),
    "dieu huong dan duong tren man hinh trung tam": ("navigation", "infotainment"),
    "dieu huong va dan duong tren man hinh trung tam": ("navigation", "infotainment"),
    "dieu huong va dan duong tren man hinh trung tam": ("navigation", "infotainment"),
    "tim kiem dia diem va dan duong": ("navigation", "infotainment"),
    "trinh duyet web": ("web_browser", "infotainment"),
    "tro choi": ("gaming", "infotainment"),
    "tu chan doan loi": ("self_diagnosis", "infotainment"),
    "chan doan loi tren xe tu dong": ("self_diagnosis", "infotainment"),
    "cap nhat phan mem tu xa": ("ota_update", "infotainment"),
    "tro ly ao": ("virtual_assistant", "infotainment"),
    "giai tri truc tuyen": ("online_entertainment", "infotainment"),
    "khung tien ich co ban lich duong thoi tiet media ban do": ("basic_widgets", "infotainment"),
    "khung tien ich": ("basic_widgets", "infotainment"),
    "hoi dap va tim kiem thong tin co ban": ("voice_search", "infotainment"),
    "ho tro dieu khien cac chuc nang xe co ban": ("voice_control", "infotainment"),
    "ho tro dieu khien thiet lap nhanh": ("quick_control", "infotainment"),
    "ho tro giai tri da phuong tien": ("media_control", "infotainment"),
    "ho tro dieu huong dan duong": ("voice_navigation", "infotainment"),
    "ho tro goi dien thoai ranh tay": ("handsfree_call", "infotainment"),
    "hoi dap thong tin chung": ("general_qa", "infotainment"),
    "chuyen phiem & tieu lam": ("small_talk", "infotainment"),
    "cai dat co ban": ("basic_settings", "infotainment"),
    "cai dat nang cao (ai tao sinh)": ("advanced_settings", "infotainment"),
    "cap nhat / gop y cho tro ly ao": ("assistant_feedback", "infotainment"),
    "tu van cach thuc su dung va van hanh xe hieu qua": ("usage_guidance", "infotainment"),
    "tu chuan doan loi/chuan doan loi tu xa": ("self_diagnosis", "infotainment"),
    "ho tro dieu huong dan duong co ban": ("voice_navigation", "infotainment"),
    "tu van tinh trang xe va ho tro xu ly su co": ("vehicle_status_assist", "infotainment"),
    "chao hoi thuc hien lenh theo kich ban tao san co ban": ("voice_greeting", "infotainment"),
    "chao hoi, thuc hien lenh theo kich ban tao san": ("voice_greeting", "infotainment"),
    "ung dung dien thoai": ("phone_app", "infotainment"),
    "ung dung dien thoait": ("phone_app", "infotainment"),
    "dan duong nang cao cho xe dien tim tram sac goi y duong toi uu de sac": ("ev_routing", "infotainment"),
    "dan duong nang cao cho xe dien": ("ev_routing", "infotainment"),
    "che do xe co ban cam trai nguoi la thu cung rua xe": ("vehicle_modes", "infotainment"),
    "giai tri co ban dai fm bluetooth usb": ("basic_entertainment", "infotainment"),
    "giai tri co ban": ("basic_entertainment", "infotainment"),
    "ban do co ban tim dia diem dan duong tinh trang giao thong hinh ve tinh": ("basic_map_navigation", "infotainment"),
    "ban do co ban": ("basic_map", "infotainment"),
    "sac vv": ("charging_etc", "general"),
    "huong dan su dung": ("user_manual", "infotainment"),
    "phan mem mien phi": ("free_software", "infotainment"),
    "phan mem thu phi": ("paid_software", "infotainment"),
    "cho ung dung": ("app_store", "infotainment"),
    "lua chon che do van hanh dac biet": ("special_operation_modes", "infotainment"),
    "cac che do van hanh dac biet": ("special_operation_modes", "infotainment"),
    "cai dat gioi han thoi gian hoat dong & khu vuc hoat dong cua xe": ("activity_limits", "infotainment"),
    "cai dat gioi han thoi gian hoat dong va khu vuc hoat dong cua xe": ("activity_limits", "infotainment"),
    "che do van hanh dac biet": ("special_operation_modes", "infotainment"),
    "che do cam trai": ("camping_mode", "infotainment"),
    "de xuat lich bao tri bao duong tu dong": ("maintenance_reminder", "infotainment"),
    "giai tri thong qua dong bo voi dien thoai": ("phone_media", "infotainment"),
    "giai tri am thanh": ("audio_entertainment", "infotainment"),
    "tra cuu va truy cap internet": ("internet_access", "infotainment"),
    "dong bo lich va danh ba dien thoai": ("calendar_contact_sync", "infotainment"),
    "dong bo danh ba dien thoai": ("contact_sync", "infotainment"),
    "cap nhat phan mem mien phi fota": ("fota_update", "infotainment"),
    "cap nhat phan mem thu phi sota": ("sota_update", "infotainment"),
    "cap nhat phan mem khong day fota": ("fota_update", "infotainment"),
    "dieu khien xe va cai dat bang giong noi": ("voice_control", "infotainment"),
    "hoi dap tro ly ao": ("voice_search", "infotainment"),
    "dieu khien xe bang giong noi": ("voice_control", "infotainment"),
    "hoi dap thong tin thoi tiet tien ich tinh nang xe": ("voice_search", "infotainment"),
    "dieu khien chuc nang tren xe": ("vehicle_control", "infotainment"),
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
    "chuc nang chong lat rom": ("rollover_mitigation", "safety"),
    "den bao phanh khan cap ess": ("emergency_stop_signal", "safety"),
    "den bao nguy hiem khi phanh khan cap ess": ("emergency_stop_signal", "safety"),
    "khoa cua xe tu dong khi xe di chuyen": ("auto_door_lock", "safety"),
    "cang dai khan cap": ("pretensioner_seatbelt", "safety"),
    "cang dai khan cap ghe truoc": ("pretensioner_seatbelt", "safety"),
    "mac co dinh ghe tre em isofix hang ghe thu 2": ("isofix", "safety"),
    "moc co dinh ghe tre em isofix hang ghe thu 2": ("isofix", "safety"),
    "moc co dinh ghe tre em isofix": ("isofix", "safety"),
    "moc co dinh ghe tre em isofix hang ghe sau": ("isofix", "safety"),
    "canh bao day an toan hang truoc va hang 2": ("seatbelt_warning", "safety"),
    "canh bao that day an toan hang ghe truoc": ("seatbelt_warning", "safety"),
    "xac dinh hanh khach & canh bao day an toan": ("seatbelt_warning", "safety"),
    "xac dinh hanh khach va canh bao day an toan": ("seatbelt_warning", "safety"),
    "khoa cua tre em": ("child_lock", "safety"),
    "goi cuu ho tu dong va dich vu ho tro tren duong": ("emergency_call", "safety"),
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
    "he thong giam sat lai xe": ("driver_monitoring", "adas"),
    "ho tro do xe phia sau": ("rear_parking_assist", "adas"),
    "ho tro do phia sau": ("rear_parking_assist", "adas"),
    "ho tro do phia truoc": ("front_parking_assist", "adas"),
    "cam bien do xe phia sau": ("rear_parking_sensor", "adas"),
    "cam bien do xe phia truoc": ("front_parking_sensor", "adas"),
    "camera lui": ("rearview_camera", "adas"),
    "he thong camera sau": ("rearview_camera", "adas"),
    "camera 360": ("surround_view_camera", "adas"),
    "he thong camera 360 do giam sat xung quanh": ("surround_view_camera", "adas"),
    "giam sat xung quanh": ("surround_view_camera", "adas"),
    "kiem soat hanh trinh": ("cruise_control_type", "adas"),
    "giam sat hanh trinh": ("cruise_control_type", "adas"),
    "giam sat hanh trinh thich ung": ("adaptive_cruise_control", "adas"),
    "ga tu dong": ("cruise_control_type", "adas"),
    "ga tu dong co ban": ("cruise_control_type", "adas"),
    "ga tu dong thich ung": ("adaptive_cruise_control", "adas"),
    "dieu chinh toc do thong minh": ("adaptive_cruise_control", "adas"),
    "nhan biet bien bao giao thong": ("traffic_sign_recognition", "adas"),
    "kiem soat di giua lan": ("lane_centering", "adas"),
    "ho tro xuong doc hdc": ("hill_descent_control", "adas"),
    "tu dong dung trong truong hop khan cap": ("emergency_stop", "adas"),
    # ── Chassis ──
    "he thong treo truoc": ("front_suspension_type", "chassis"),
    "he thong treo sau": ("rear_suspension_type", "chassis"),
    "he thong phanh truoc sau": ("brake_type", "chassis"),
    "tro luc lai": ("steering_assist_type", "chassis"),
    "thanh can bang truoc": ("stabilizer_bar", "chassis"),
    "loai lop": ("tire_type", "chassis"),
    "lop du phong": ("spare_tire_type", "chassis"),
    # ── Powertrain ──
    "che do lai": ("drive_modes", "powertrain"),
    "chon che do lai": ("drive_modes", "powertrain"),
    "suoi pin cao the": ("battery_heater", "powertrain"),
    "bo sac tai nha": ("home_charger_type", "powertrain"),
    "day sac di dong": ("mobile_charger_type", "powertrain"),
    "he thong phanh tai sinh": ("regenerative_braking", "powertrain"),
    # ── Connected car ──
    "dinh vi xe tu xa": ("gps_tracking", "connected"),
    "dinh vi vi tri xe tu xa": ("gps_tracking", "connected"),
    "dong bo tai khoan ung dung phan quyen tai xe": ("account_sync", "connected"),
    "dong bo va quan ly tai khoan": ("account_sync", "connected"),
    "quan ly tai khoan uy quyen cho lai xe thu 2 dong bo lich": ("account_sync", "connected"),
    "thong bao trang thai co ban tren xe trang thai hieu suat van hanh thong tin pin": ("vehicle_status_notification", "connected"),
    "theo doi va hien thi thong tin tinh trang xe": ("vehicle_status_notification", "connected"),
    "quan ly sac thanh toan phi sac": ("charge_management", "connected"),
    "thanh toan phi sac": ("charge_payment", "connected"),
    "ban do tram sac": ("charger_map", "connected"),
    "tim tram sac": ("charger_map", "connected"),
    "tim kiem tram sac": ("charger_map", "connected"),
    "dich vu hau mai dat lich sua chua lai thu": ("service_booking", "connected"),
    "nhan thong bao va dat dich vu hau mai": ("service_booking", "connected"),
    "dat lich sua chua bao duong": ("service_booking", "connected"),
    "ho tro hau mai": ("service_booking", "connected"),
    "mua ban phu kien": ("online_accessory_shop", "connected"),
    "quan ly goi cuoc thue pin truc tuyen": ("battery_lease_management", "connected"),
    "thong tin khuyen mai va phu kien": ("promo_info", "connected"),
    "nhan thong bao": ("notifications", "connected"),
    "giam sat xe tu xa": ("vehicle_monitoring", "connected"),
    "giam sat xe tu xa va nhan thong bao": ("vehicle_monitoring", "connected"),
    "giam sat xe tu xa vi tri thong so": ("vehicle_monitoring", "connected"),
    "dieu khien tu xa": ("remote_control", "connected"),
    "thiet lap cai dat tu xa": ("remote_settings", "connected"),
    "quan ly pin nang cao": ("advanced_battery_management", "connected"),
    "quan ly wifi ket noi phat hotspot": ("wifi_management", "connected"),
    "quan ly wifi": ("wifi_management", "connected"),
    "quan ly thiet bi bluetooth dien thoai va nghe nhac": ("bluetooth_management", "connected"),
    "quan ly thiet bi bluetooth": ("bluetooth_management", "connected"),
    "quan ly esim": ("esim_management", "connected"),
    "giam sat tinh trang pin gioi han dung luong dong sac": ("battery_monitoring", "connected"),
    "ho so nguoi lai": ("driver_profile", "connected"),
    "tao va ghi nho cai dat theo ho so nguoi lai": ("driver_profile", "connected"),
    "ho so nang cao": ("advanced_profile", "connected"),

    # ── Exterior extras (model_data CSVs) ──
    "den pha tu dong bat/tat": ("auto_headlights", "exterior"),
    "dieu khien do cao goc chieu den": ("headlight_leveling", "exterior"),
    "den dinh vi": ("position_light", "exterior"),
    "den chao mung": ("welcome_light", "exterior"),
    "den nhan dien thuong hieu phia truoc/sau": ("brand_light", "exterior"),
    "den nhan dien thuong hieu truoc va sau": ("brand_light", "exterior"),
    "guong chieu hau ngoai": ("exterior_mirror_type", "exterior"),
    "guong chieu hau trong xe": ("interior_mirror_type", "interior"),
    "kinh cua so len/xuong mot cham": ("one_touch_windows", "exterior"),
    "kinh cua so chinh dien": ("power_windows", "exterior"),
    "tay nam cua": ("door_handle_type", "exterior"),
    "co che lay mo cua": ("door_opening_mechanism", "exterior"),
    "cua hit": ("power_suction_doors", "exterior"),
    "den chieu sang khi mo cua": ("puddle_light", "exterior"),
    "den chieu logo mat duong (cam bien da cop)": ("logo_light", "exterior"),
    "bac len xuong": ("side_step", "exterior"),
    "thanh trang tri noc xe": ("roof_rack", "exterior"),
    "canh huong gio": ("spoiler", "exterior"),
    "co che dong mo cong sac": ("charge_port_door", "exterior"),
    "thanh gia cuong cua xe": ("door_impact_beam", "exterior"),
    "dong/mo cop sau": ("trunk_lid_type", "exterior"),
    "dong/mo cop da chan": ("kick_sensor_trunk", "exterior"),
    "cop sau": ("trunk_lid_type", "exterior"),
    # ── Interior extras (model_data CSVs) ──
    "cua gio dieu hoa hang ghe thu 2 va thu 3": ("rear_ac_vents", "interior"),
    "cua gio dieu hoa hang ghe thu 2: tren hop de do trung tam": ("row2_ac_vents", "interior"),
    "cua gio dieu hoa hang ghe thu 2: tren cot b": ("row2_ac_vents", "interior"),
    "he thong loc bui min combi 1.0": ("cabin_air_filter", "interior"),
    "he thong loc bui min combi 1.0 va ion hoa khong khi": ("cabin_air_filter", "interior"),
    "ghe vip": ("vip_seat", "interior"),
    "ghe vip chinh dien": ("vip_seat_power", "interior"),
    "ghe vip massage": ("vip_seat_massage", "interior"),
    "ghe vip co thong gio": ("vip_seat_ventilation", "interior"),
    "ghe vip co suoi": ("vip_seat_heating", "interior"),
    "hang ghe thu 2 dieu chinh huong": ("second_row_adjust", "interior"),
    "hang ghe thu 2 dieu chinh gap ty le": ("second_row_fold", "interior"),
    "hang ghe thu 2 co thong gio": ("second_row_ventilation", "interior"),
    "hang ghe thu 2 co suoi": ("second_row_heating", "interior"),
    "hang ghe thu 2 co massage": ("second_row_massage", "interior"),
    "gap lung ghe hang ghe thu 2": ("second_row_fold", "interior"),
    "gap hang ghe thu 3": ("row3_fold", "interior"),
    "len xuong de dang (len/xuong tu hang thu 2)": ("easy_access", "interior"),
    "tua dau ghe lai": ("driver_headrest", "interior"),
    "tua dau ghe phu": ("passenger_headrest", "interior"),
    "tua dau ghe hang 2": ("row2_headrest", "interior"),
    "tua dau ghe hang 3": ("row3_headrest", "interior"),
    "boc vo lang": ("steering_wheel_wrap", "interior"),
    "dieu chinh vo lang": ("steering_wheel_adjust", "interior"),
    "suoi tay lai": ("heated_steering_wheel", "interior"),
    "nho vi tri vo lang": ("steering_wheel_memory", "interior"),
    "hop do hang ghe sau": ("rear_console_box", "interior"),
    "phanh truoc": ("front_brake_type", "chassis"),
    "phanh sau": ("rear_brake_type", "chassis"),
    "cong usb": ("usb_ports", "interior"),
    # ── Safety extras ──
    "tui khi danh cho nguoi lai": ("driver_airbag", "safety"),
    "tui khi phia truoc cho nguoi lai va hanh khach phia truoc": ("front_airbags", "safety"),
    "tui khi ben hong": ("side_airbags", "safety"),
    "khoa cua tre em": ("child_lock", "safety"),
    "he thong chia khoa xe": ("key_system", "safety"),
    "chia khoa": ("key_type", "safety"),
    "cang dai khan cap ghe truoc": ("pretensioner_seatbelt", "safety"),
    "den bao nguy hiem khi phanh khan cap (ess)": ("emergency_stop_signal", "safety"),
    "den bao nguy hiem khi phanh khan cap ess": ("emergency_stop_signal", "safety"),
    "goi cuu ho tu dong va dich vu ho tro tren duong": ("emergency_call", "safety"),
    "he thong chong bo cung phanh (abs)": ("abs", "safety"),
    "chuc nang phan phoi luc phanh dien tu (ebd)": ("ebd", "safety"),
    "ho tro phanh khan cap (ba)": ("brake_assist", "safety"),
    "ho tro luc phanh khan cap (ba)": ("brake_assist", "safety"),
    "he thong can bang dien tu (esc)": ("esc", "safety"),
    "chuc nang kiem soat luc keo (tcs)": ("tcs", "safety"),
    "kiem soat luc keo (tcs)": ("tcs", "safety"),
    "ho tro khoi hanh ngang doc (hsa)": ("hsa", "safety"),
    "chuc nang chong lat (rom)": ("rollover_mitigation", "safety"),
    # ── ADAS extras ──
    "ho tro xuong doc hdc": ("hill_descent_control", "adas"),
    "tu dong dung trong truong hop khan cap": ("emergency_stop", "adas"),
    "ga tu dong": ("cruise_control_type", "adas"),
    "ga tu dong co ban": ("cruise_control_type", "adas"),
    "ga tu dong thich ung": ("adaptive_cruise_control", "adas"),
    "giam sat hanh trinh": ("cruise_control_type", "adas"),
    "giam sat hanh trinh thich ung": ("adaptive_cruise_control", "adas"),
    "cam bien do xe phia truoc": ("front_parking_sensor", "adas"),
    "cam bien do xe phia sau": ("rear_parking_sensor", "adas"),
    "ho tro do phia truoc": ("front_parking_assist", "adas"),
    "ho tro do phia sau": ("rear_parking_assist", "adas"),
    "he thong camera sau": ("rearview_camera", "adas"),
    "giam sat xung quanh": ("surround_view_camera", "adas"),
    "den chieu xa tu dong": ("auto_high_beam", "exterior"),
    # ── Chassis extras ──
    "he thong treo (truoc/sau)": ("suspension_type", "chassis"),
    "he thong treo truoc/sau": ("suspension_type", "chassis"),
    "he thong phanh (truoc/sau)": ("brake_type", "chassis"),
    "kich thuoc lop & la-zang": ("tire_wheel_size", "chassis"),
    "kich thuoc lop": ("tire_size", "chassis"),
    "thanh can bang truoc": ("stabilizer_bar", "chassis"),
    "bo va lop": ("tire_repair_kit", "chassis"),
    "bo dung cu kich xe": ("jack_kit", "chassis"),
    # ── Battery extras ──
    "loai pin": ("battery_type", "battery"),
    "dung luong pin (kwh) - kha dung": ("battery_kwh", "battery"),
    "tinh nang sac nhanh": ("fast_charge_capable", "battery"),
    "thoi gian nap pin binh thuong (gio)": ("normal_charge_hours", "battery"),
    "thoi gian nap pin nhanh (phut)": ("fast_charge_min", "battery"),
    "thoi gian nap pin nhanh nhat tu 10% den 70% (phut)": ("fast_charge_min", "battery"),
    "thoi gian nap pin nhanh nhat (phut) tu 10% den 70%": ("fast_charge_min", "battery"),
    "cong suat sac toi da (kw)": ("max_charge_power_kw", "battery"),
    "cong suat sac ac toi da (kw)": ("ac_charge_power_kw", "battery"),
    "cong suat sac cham ac toi da (kw)": ("ac_charge_power_kw", "battery"),
    "cong suat sac nhanh dc toi da (kw)": ("dc_charge_power_kw", "battery"),
    # ── Powertrain extras ──
    "cau hinh dong co": ("motor_configuration", "powertrain"),
    "dong co": ("motor_configuration", "powertrain"),
    "cach chuyen so": ("gear_shift_type", "powertrain"),
    "can chuyen so sau vo lang": ("gear_shift_type", "powertrain"),
    "che do thay doi toc do den dung": ("creep_mode", "powertrain"),
    # ── Dimension extras ──
    "duong kinh quay dau toi thieu (m)": ("turning_diameter_m", "dimension"),
    "suc chua (kg)": ("payload_kg", "dimension"),
    "tai trong (kg)": ("payload_kg", "dimension"),
    # ── Infotainment/connected extras ──
    "dieu khien goc chieu pha thong minh": ("adaptive_headlights", "exterior"),
    "tu dong quay goc chieu den (den liec)": ("cornering_light", "exterior"),
    "virtual_assistant": ("virtual_assistant", "infotainment"),
    "vehicle_control": ("vehicle_control", "infotainment"),
    "dieu khien xe tu xa": ("remote_control", "connected"),
    "dong bo tai khoan & quan ly ho so nguoi lai": ("account_sync", "connected"),
    "thong tin khuyen mai & phu kien": ("promo_info", "connected"),

    # ── sion ──
    "trong luong khong tai": ("curb_weight_kg", "dimension"),
    "tai trong hanh ly noc xe": ("roof_load_kg", "dimension"),
    "dung tich khoang chua hanh ly": ("trunk_capacity", "dimension"),
}


def norm(s: str) -> str:
    """Normalize label: bỏ dấu, lowercase, gom space, strip trailing punct."""
    s = no_diacritics(s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(":|-–— \t")


def norm_strict(s: str) -> str:
    """Strict normalize: norm() + loại bỏ internal punctuation (, : ; / () & -)."""
    s = norm(s)
    s = re.sub(r"[,:;()/&\-–—]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── FEATURE_ALIASES (strict-normalized) ──────────────────────────────────────
FEATURE_ALIASES_STRICT = {norm_strict(k): k for k in FEATURE_NORM_MAP}
FEATURE_ALIASES_BY_LEN = sorted(FEATURE_ALIASES_STRICT.keys(), key=len, reverse=True)

# Section header = label không có value. Một số file dùng prefix "A. ", "B. " (vf2)
SECTION_PREFIX_RE = re.compile(r"^[a-c]\.\s*")

VERSION_HEADER_ALIASES = {"phien ban", "phien bản"}


def parse_dimension_triple(value: str) -> list[tuple[str, str]]:
    """Tách '4.750 x 1.934 x 1.667' / '4,545 x 1,890 x 1,635.75' / '4701 x 1872 x 1670 (mm)'
    → [(length_mm, val), (width_mm, val), (height_mm, val)].

    Xử lý hỗn hợp dấu phân cách (dấu chấm phẩy hàng nghìn / dấu phẩy thập phân):
      - '4.241'  → 4241        (dấu chấm = hàng nghìn)
      - '4,545'  → 4545        (dấu phẩy = hàng nghìn)
      - '1,635.75' → 1635.75   (cả 2: dấu chấm sau cùng = thập phân)
      - '1.663,2' → 1663.2     (cả 2: dấu phẩy sau cùng = thập phân)
    """
    value = re.sub(r"\(mm\)|mm", "", value, flags=re.I).strip()
    parts = re.split(r"\s*[xX×]\s*", value)
    keys = ["length_mm", "width_mm", "height_mm"]
    result = []
    for k, p in zip(keys, parts):
        p = p.strip()
        if not p:
            result.append((k, None))
            continue
        # Bỏ dấu phân cách dựa trên vị trí dấu thập phân
        if "," in p and "." in p:
            # dấu sau cùng là thập phân
            if p.rfind(".") > p.rfind(","):
                p = p.replace(",", "")  # bỏ hàng nghìn (dấu phẩy)
            else:
                p = p.replace(".", "").replace(",", ".")
        elif "," in p:
            # chỉ có dấu phẩy: hàng nghìn (giá trị mm luôn ≥ 3 chữ số)
            p = p.replace(",", "")
        elif "." in p:
            # chỉ có dấu chấm: hàng nghìn (giá trị mm luôn ≥ 3 chữ số)
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
        "spec_category_vn": CATEGORY_VN_MAP.get(category, category),
        "spec_key": key,
        "spec_key_vn": SPEC_KEY_VN_MAP.get(key, key),
        "spec_value": value,
        "spec_unit": unit,
        "source_url": url,
    }


def _parse_edition_header(value: str) -> str:
    """Lấy edition từ row 'PHIÊN BẢN': 'VF 6 Eco' → 'Eco'; 'VF8 The All New' → 'The All New';
    'VF 2' → '' (không có edition)."""
    m = re.match(r"^vf\s*\d+[\s\-]*(.*)$", value, re.I)
    if not m:
        return ""
    return m.group(1).strip()


def parse_model_csv(path: Path) -> list[dict[str, Any]]:
    """Extract ALL spec rows từ 1 file CSV 2 cột (label, value)."""
    model_id = infer_model(path)
    if not model_id:
        print(f"  [skip] can't infer model from {path.name}", file=sys.stderr)
        return []
    model_code = MODEL_LABEL.get(model_id, model_id)
    source_url = f"model_data/{path.name}"

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (spec_key, edition) — trùng trong file
    current_section_category: str | None = None
    edition: str | None = None

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for raw in reader:
            if not raw:
                continue
            label = (raw[0] or "").strip()
            if not label:
                continue
            value = (raw[1] or "").strip() if len(raw) > 1 else ""

            label_norm = norm(label)

            # Row header: "PHIÊN BẢN, VF 6 Eco" → model/edition
            if label_norm in VERSION_HEADER_ALIASES:
                ed = _parse_edition_header(value)
                if ed:
                    edition = ed
                else:
                    # Không có edition trong header → fallback MODEL_EDITIONS
                    eds = MODEL_EDITIONS.get(model_id, [])
                    edition = eds[0] if len(eds) == 1 else None
                continue

            # Section header: label có value rỗng → cập nhật category context
            if not value:
                sec_key = SECTION_PREFIX_RE.sub("", label_norm)
                sec_cat = SECTION_CATEGORY_MAP.get(sec_key)
                if sec_cat is not None:
                    current_section_category = sec_cat
                continue

            # Value nhiều dòng (quoted trong CSV) → gom thành 1 dòng
            value = re.sub(r"\s*\n\s*", " ", value)

            # Mapping label → spec_key/category/unit
            mapped = None
            for alias in ALIASES_BY_LEN:
                if label_norm.startswith(alias) or label_norm == alias:
                    mapped = LABEL_MAP[alias]
                    break

            if mapped:
                spec_key, spec_unit, spec_category = mapped
                if spec_key == "dimension_triple":
                    dim_parts = parse_dimension_triple(value)
                    for sub_key, sub_val in dim_parts:
                        if sub_val is None:
                            continue
                        dedup_key = (sub_key, edition)
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        rows.append(make_row(model_code, edition, "dimension",
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
                    spec_category = current_section_category or "general"

            # Dedup trong file
            dedup_key = (spec_key, edition)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            rows.append(make_row(model_code, edition, spec_category,
                                 spec_key, value, spec_unit, source_url))

    return rows


def run(version: str = "v1") -> int:
    """Main: read model_data CSVs, extract all spec tables, write CSV."""
    version_dir = CLEAN_DIR / version
    pg_dir = version_dir / "postgres"
    pg_dir.mkdir(parents=True, exist_ok=True)

    if not MODEL_DATA_DIR.exists():
        print(f"[parse_specs] model_data dir not found: {MODEL_DATA_DIR}", file=sys.stderr)
        return 1

    all_rows: list[dict[str, Any]] = []
    by_model: dict[str, int] = {}
    n_files = 0

    for path in sorted(MODEL_DATA_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        print(f"  📄 {path.name}")
        rows = parse_model_csv(path)
        if not rows:
            print(f"    → no spec rows found")
            continue
        n_files += 1
        all_rows.extend(rows)
        for r in rows:
            mc = r["model_code"]
            by_model[mc] = by_model.get(mc, 0) + 1
        editions = sorted({r["version_name"] or "" for r in rows})
        print(f"    → {len(rows)} spec rows  (editions: {', '.join(editions)})")

    if not all_rows:
        print("[parse_specs] no data found")
        return 1

    # Ghi CSV
    out_path = pg_dir / "specs.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter="|")
        w.writeheader()
        for r in all_rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_FIELDS})

    print(f"\n[parse_specs] version={version}  files={n_files}")
    for mc in sorted(by_model):
        print(f"  {mc}: {by_model[mc]} rows")
    print(f"  → {out_path}: {len(all_rows)} rows")

    # Cập nhật manifest với car_specs info
    manifest_path = version_dir / "_manifest.json"
    if manifest_path.exists():
        try:
            import json
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["postgres"]["tables"]["car_specs"] = {
                "file": "postgres/specs.csv",
                "rows": len(all_rows),
                "upserted": len(all_rows),
            }
            # Tính lại total_rows_upserted
            total = sum(
                t.get("upserted", 0)
                for t in manifest["postgres"]["tables"].values()
            )
            manifest["postgres"]["total_rows_upserted"] = total
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"  ✓ manifest updated with car_specs")
        except Exception as e:
            print(f"  ⚠ failed to update manifest: {e}", file=sys.stderr)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract all spec rows from model_data CSVs.")
    ap.add_argument("--version", default="v1", help="Output version folder (default v1)")
    args = ap.parse_args()
    return run(args.version)


if __name__ == "__main__":
    sys.exit(main())
