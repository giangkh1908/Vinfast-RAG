#!/usr/bin/env python3
"""
parse_pdf_specs.py — Trích thông số kỹ thuật từ data/raw_pdf/*.txt (brochure)
→ data/clean/<version>/postgres/specs.csv

Script này extract TOÀN BỘ row từ bảng spec trong brochure PDF — gồm cả spec số
(công suất, pin…) lẫn spec tính năng (Có/Không, LED, v.v.).

Nguồn: data/raw_pdf/*.txt (output từ crawl_pdf.py). Chỉ extract pipe-table
3 cột (bảng so sánh edition). Cột 1 = edition đầu, cột 2 = edition cuối
(theo MODEL_EDITIONS).
"""
import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

# Chạy trực tiếp (`python scripts/clean_data/parse_pdf_specs.py`) → repo root vào sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.config import CLEAN_DIR, RAW_PDF_DIR  # noqa: E402
from scripts.clean_data.spec_common import (  # noqa: E402
    MODEL_EDITIONS, MODEL_LABEL, infer_model, no_diacritics, parse_raw_file,
)

# ── Mappings ─────────────────────────────────────────────────────────────────
# Label map (đã normalize) — subset các spec thường gặp trong brochure
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
    "ghe lai": ("driver_seat_type", "", "interior"),
    "ghe phu": ("passenger_seat_type", "", "interior"),
    "khoi luong khong tai": ("curb_weight_kg", "kg", "dimension"),
    "dung tich cop sau": ("trunk_capacity", "L", "dimension"),
    "dung tich khoang chua hanh ly": ("trunk_capacity", "L", "dimension"),
    "dung tich khoang chua hanh ly (l) - phia truoc": ("frunk_capacity_l", "L", "dimension"),
    # -- Airbag sub-types (prefix match truoc "tui khi" generic) --
    "he thong tui khi": ("airbags", "", "safety"),
    "tui khi truoc lai va hanh khach phia truoc": ("front_airbags", "", "safety"),
    "tui khi ben hong hang ghe truoc": ("side_airbags_front", "", "safety"),
    "tui khi ben hong hang ghe sau": ("side_airbags_rear", "", "safety"),
    "tui khi rem": ("curtain_airbags", "", "safety"),
    "tui khi bao ve chan hang ghe truoc": ("knee_airbags", "", "safety"),
    "tui khi trung tam hang ghe truoc": ("center_airbags", "", "safety"),
}

ALIASES_BY_LEN = sorted(LABEL_MAP.keys(), key=len, reverse=True)

CSV_FIELDS = ["model_code", "version_name", "version_code",
              "spec_category", "spec_category_vn",
              "spec_key", "spec_key_vn",
              "spec_value", "spec_unit", "source_url",
              "page"]

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
    "roof_load_kg": "Tải trọng hành lý nóc xe",
    "trunk_capacity": "Dung tích khoang hành lý",
    "frunk_capacity_l": "Dung tích khoang hành lý phía trước",
    # ── powertrain ──
    "power_kw": "Công suất tối đa",
    "torque_nm": "Mô-men xoắn cực đại",
    "acceleration_0_100_s": "Tăng tốc 0-100 km/h",
    "drivetrain": "Dẫn động",
    "drive_modes": "Chế độ lái",
    "battery_heater": "Sưởi pin cao thế",
    "home_charger_type": "Bộ sạc tại nhà",
    "mobile_charger_type": "Dây sạc di động",
    # ── battery ──
    "battery_kwh": "Dung lượng pin khả dụng",
    "range_km": "Phạm vi di chuyển",
    "fast_charge_min": "Thời gian nạp pin nhanh nhất",
    # ── exterior ──
    "headlight_type": "Đèn chiếu sáng phía trước",
    "headlight_feature": "Đèn pha",
    "auto_headlights": "Đèn pha tự động",
    "adaptive_headlights": "Đèn pha tự động / thích ứng",
    "drl_type": "Đèn chiếu sáng ban ngày",
    "tail_light_type": "Đèn hậu",
    "front_brand_light": "Đèn nhận diện thương hiệu trước",
    "rear_brand_light": "Đèn nhận diện thương hiệu sau",
    "auto_high_beam": "Tự động bật/tắt chế độ chiếu xa",
    "auto_wiper": "Gạt mưa trước tự động",
    "power_folding_mirrors": "Gương chiếu hậu chỉnh điện / gập điện",
    "one_touch_windows": "Kính cửa sổ chỉnh điện 1 chạm",
    "wheel_size_inch": "Kích thước la-zăng",
    "daytime_running_light": "Đèn chờ dẫn đường",
    "fog_light_front": "Đèn sương mù trước",
    "cornering_light": "Đèn chiếu góc",
    "high_mount_brake_light": "Đèn phanh trên cao phía sau",
    "rearview_mirror_type": "Gương chiếu hậu",
    "window_type": "Kiểu cửa sổ",
    "privacy_glass": "Kính cửa sổ màu đen (riêng tư)",
    "trunk_lid_type": "Điều chỉnh cốp sau",
    "windshield_type": "Kính chắn gió",
    "underbody_protection": "Tấm bảo vệ dưới thân xe",
    "smart_key": "Chìa khóa thông minh",
    # ── interior ──
    "leatherette_seats": "Ghế bọc da nhân tạo",
    "seat_material_type": "Chất liệu bọc ghế",
    "seats": "Số ghế ngồi",
    "speakers": "Hệ thống loa",
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
    "wireless_charging": "Sạc không dây",
    "wifi_connectivity": "Kết nối Wifi",
    "bluetooth_connectivity": "Kết nối Bluetooth",
    "subwoofer": "Loa trầm",
    "ambient_lighting": "Đèn trang trí nội thất",
    "sunroof_type": "Cửa sổ trời",
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
    "basic_map_navigation": "Bản đồ cơ bản (Tìm địa điểm, Dẫn đường, tình trạng giao thông, hình vệ tinh)",
    "charging_etc": "Sạc, v.v.",
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
    "side_airbags_front": "Túi khí bên hông ghế trước",
    "side_airbags_rear": "Túi khí bên hông ghế sau",
    "curtain_airbags": "Túi khí rèm",
    "knee_airbags": "Túi khí bảo vệ chân",
    "center_airbags": "Túi khí trung tâm",
    "rollover_mitigation": "Chức năng chống lật ROM",
    "emergency_stop_signal": "Đèn báo phanh khẩn cấp ESS",
    "auto_door_lock": "Khóa cửa xe tự động khi xe di chuyển",
    "pretensioner_seatbelt": "Căng đai khẩn cấp",
    "isofix": "Móc cố định ghế trẻ em ISOFIX, hàng ghế thứ 2",
    "seatbelt_warning": "Cảnh báo dây an toàn hàng trước và hàng 2",
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
    "rearview_camera": "Camera lùi",
    "surround_view_camera": "Camera 360° / giám sát xung quanh",
    "cruise_control_type": "Kiểm soát hành trình",
    "adaptive_cruise_control": "Điều chỉnh tốc độ thông minh",
    "traffic_sign_recognition": "Nhận biết biển báo giao thông",
    "lane_centering": "Kiểm soát đi giữa làn",
    # ── chassis ──
    "front_suspension_type": "Hệ thống treo trước",
    "rear_suspension_type": "Hệ thống treo sau",
    "brake_type": "Hệ thống phanh trước/sau",
    "steering_assist_type": "Trợ lực lái",
    # ── security ──
    "immobilizer": "Khoá động cơ khi có trộm",
    "anti_theft_alarm": "Cảnh báo chống trộm",
    "epb_auto_hold": "Phanh đỗ điện tử & giữ phanh tự động",
    "gps_tracking": "Định vị xe từ xa",
    # ── connected ──
    "account_sync": "Đồng bộ tài khoản / ứng dụng / phân quyền",
    "vehicle_status_notification": "Thông báo trạng thái xe (pin, hiệu suất, bảo dưỡng)",
    "charge_management": "Quản lý sạc & thanh toán phí sạc",
    "charger_map": "Bản đồ trạm sạc",
    "service_booking": "Dịch vụ hậu mãi: đặt lịch sửa chữa, lái thử",
    "online_accessory_shop": "Mua bán phụ kiện",
}

# Section headers trong bảng — rows mà tất cả data cols rỗng
SECTION_HEADERS = {
    "pin", "khung gam", "ngoai that", "ngoai that den pha", "noi that & tien nghi",
    "noi that", "thong so truyen dong khac", "giam xoc", "phanh",
    "vanh va lop banh xe", "ghe toan xe", "ghe lai", "ghe phu", "khung gam khac",
    "phien ban", "thong so", "dau xe", "hong xe", "duoi xe",
    "he thong truyen dong", "dong co", "den ngoai that", "ngoai that khac",
    "dieu hoa khong khi", "tien nghi", "an toan & an ninh", "an toan",
    "he thong ho tro nguoi lai nang cao adas",
    "tro lai tren cao toc", "tro lan", "ho tro hanh trinh",
    "canh bao va cham", "tro lai khi co nguy co va cham",
    "cac tinh nang khac", "tinh nang thong minh",
    "he thong tin giai tri tren xe", "tro ly ao",
    "ung dung dien thoai", "kich thuoc & tai trong",
    "den ngoai that khac",
}
# Cũng check với norm lowercase + no diacritics

# ── SECTION_CATEGORY_MAP: section header → spec_category ──────────────────────
# Dùng để track context: khi section header xuất hiện, các row không mapped
# phía dưới sẽ được gán category tương ứng thay vì "general".
SECTION_CATEGORY_MAP = {
    "kich thuoc & tai trong": "dimension",
    "he thong truyen dong": "powertrain",
    "dong co": "powertrain",
    "pin": "battery",
    "thong so truyen dong khac": "powertrain",
    "khung gam": "chassis",
    "khung gam khac": "chassis",
    "ngoai that": "exterior",
    "noi that & tien nghi": "interior",
    "noi that": "interior",
    "an toan & an ninh": "safety",
    "an toan": "safety",
    "he thong tui khi": "safety",
    "he thong ho tro nguoi lai nang cao adas": "adas",
    "tro lai tren cao toc": "adas",
    "tro lan": "adas",
    "ho tro hanh trinh": "adas",
    "canh bao va cham": "adas",
    "tro lai khi co nguy co va cham": "adas",
    "cac tinh nang khac": "general",
    "tinh nang thong minh": "infotainment",
    "he thong tin giai tri tren xe": "infotainment",
    "tro ly ao": "infotainment",
    "ung dung dien thoai": "connected",
}

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
    "gat mua truoc": ("auto_wiper", "exterior"),
    "chia khoa thong minh": ("smart_key", "exterior"),
    # Trang 18 — đèn & ngoại thất khác
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
    # Trang 19 — nội thất khác
    "hang ghe thu hai": ("second_row_seat_type", "interior"),
    "loai vo lang": ("steering_wheel_type", "interior"),
    "he thong dieu hoa": ("ac_type", "interior"),
    "loc khong khi cabin": ("cabin_air_filter", "interior"),
    "ong thong gio duoi chan hanh khach sau": ("rear_ac_vents", "interior"),
    "man hinh hien thi hud": ("head_up_display", "interior"),
    "cong ket noi usb loai a": ("usb_port_type_a", "interior"),
    "cong ket noi usb loai c": ("usb_port_type_c", "interior"),
    "sac khong day": ("wireless_charging", "interior"),
    "ket noi wifi": ("wifi_connectivity", "interior"),
    "ket noi bluetooth": ("bluetooth_connectivity", "interior"),
    "loa tram": ("subwoofer", "interior"),
    "den trang tri noi that": ("ambient_lighting", "interior"),
    "cua so troi": ("sunroof_type", "interior"),
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
    # Trang 19 — an toàn khác
    "chuc nang chong lat rom": ("rollover_mitigation", "safety"),
    "den bao phanh khan cap ess": ("emergency_stop_signal", "safety"),
    "khoa cua xe tu dong khi xe di chuyen": ("auto_door_lock", "safety"),
    "cang dai khan cap": ("pretensioner_seatbelt", "safety"),
    "mac co dinh ghe tre em isofix hang ghe thu 2": ("isofix", "safety"),
    "moc co dinh ghe tre em isofix hang ghe thu 2": ("isofix", "safety"),
    "moc co dinh ghe tre em isofix": ("isofix", "safety"),
    "canh bao day an toan hang truoc va hang 2": ("seatbelt_warning", "safety"),
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
    "dinh vi xe tu xa": ("gps_tracking", "connected"),
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
    "giai tri co ban dai fm bluetooth usb": ("basic_entertainment", "infotainment"),
    "ban do co ban tim dia diem dan duong tinh trang giao thong hinh ve tinh": ("basic_map_navigation", "infotainment"),
    "sac vv": ("charging_etc", "general"),
}


def norm(s: str) -> str:
    """Normalize label: bỏ dấu, lowercase, gom space, strip trailing punct."""
    # no_diacritics (common) KHÔNG lowercase — lower() trước để 'Đ' hoa cũng
    # thành 'd' (giữ nguyên hành vi cũ của no_diacritics trong file này).
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
FEATURE_ALIASES = sorted(FEATURE_NORM_MAP.keys(), key=len, reverse=True)
FEATURE_ALIASES_STRICT = {norm_strict(k): k for k in FEATURE_NORM_MAP}
FEATURE_ALIASES_BY_LEN = sorted(FEATURE_ALIASES_STRICT.keys(), key=len, reverse=True)


def is_section_header(norm_label: str) -> bool:
    return norm_label in SECTION_HEADERS


TABLE_ROW_RE = re.compile(r"^\s*\|.*\|")
SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|")
PAGE_MARKER_RE = re.compile(r"---\s*Trang\s+(\d+)\s*---")


def parse_pdf_specs(path: Path) -> list[dict[str, Any]]:
    """Extract ALL spec rows from PDF brochure tables."""
    meta, body = parse_raw_file(path)
    model_id = infer_model(path)
    if not model_id:
        print(f"  [skip] can't infer model from {path.name}", file=sys.stderr)
        return []
    model_code = MODEL_LABEL.get(model_id, model_id)
    source_url = meta.get("source_url", "")
    editions = MODEL_EDITIONS.get(model_id, ["Eco", "Plus"])

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (spec_key, edition) — trùng trong file

    current_page: int | None = None

    lines = body.splitlines()
    i = 0
    while i < len(lines):
        # Track page markers
        page_m = PAGE_MARKER_RE.match(lines[i].strip())
        if page_m:
            current_page = int(page_m.group(1))
            i += 1
            continue

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

        current_section_category: str | None = None
        j = data_start
        while j < len(lines) and TABLE_ROW_RE.match(lines[j]) and not SEP_RE.match(lines[j]):
            # ── Merge continuation lines (multi-line cell values) ─────────────
            # Một số spec có giá trị xuống dòng trong PDF, làm text bị split
            # thành nhiều dòng. Tất cả dòng giữa 2 pipe-table rows là continuation.
            row_text = lines[j]
            k = j + 1
            while k < len(lines):
                next_line = lines[k].strip()
                if not next_line or PAGE_MARKER_RE.match(next_line) or SEP_RE.match(lines[k]):
                    break
                if TABLE_ROW_RE.match(lines[k]):
                    break
                # Continuation line — ghép vào row_text
                row_text += " " + next_line
                k += 1

            cells = [c.strip() for c in row_text.strip().strip("|").split("|")]
            if not cells:
                j = k
                continue

            label = cells[0]
            if not label:
                j = k
                continue

            label_norm = norm(label)
            # Chỉ skip section header nếu tất cả cột dữ liệu đều trống.
            # Nếu section header có dữ liệu (vd "Ghế lái | Chỉnh điện 6 hướng | ..."),
            # để nó đi qua mapping bình thường.
            if is_section_header(label_norm):
                has_data = any(cells[ci] for ci in edition_cols if ci < len(cells))
                if not has_data:
                    # Cập nhật section context cho các row phía dưới
                    sec_cat = SECTION_CATEGORY_MAP.get(label_norm)
                    if sec_cat is not None:
                        current_section_category = sec_cat
                    j = k
                    continue

            # Bỏ price row (dùng \b word boundary để tránh false positive:
            # "gia" (không word-boundary) match substring "thời gian", "giải trí", "giao thông",...)
            price_labels = ("lan bangh", "lan bang", "niem yet", "gia ban", "phien ban")
            if any(p in label_norm for p in price_labels) or re.search(r'\bg(iá|a)\b', label_norm):
                j = k
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
                            dedup_key = (sub_key, ed)
                            if dedup_key in seen:
                                continue
                            seen.add(dedup_key)
                            rows.append(make_row(model_code, ed, "dimension",
                                                 sub_key, sub_val, "mm", source_url,
                                                 page=current_page))
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
                        # Dùng section context nếu có
                        spec_category = current_section_category or "general"

                # Dedup trong file
                dedup_key = (spec_key, ed)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                value_clean = raw_value.strip()
                if not value_clean:
                    continue

                rows.append(make_row(model_code, ed, spec_category,
                                     spec_key, value_clean, spec_unit, source_url,
                                     page=current_page))
            j = k
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
             key: str, value: str, unit: str, url: str,
             page: int | None = None) -> dict[str, Any]:
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
        "page": page,
    }


def run(version: str = "v1") -> int:
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
    ap = argparse.ArgumentParser(description="Extract all spec rows from PDF brochure tables.")
    ap.add_argument("--version", default="v1", help="Output version folder (default v1)")
    args = ap.parse_args()
    return run(args.version)


if __name__ == "__main__":
    sys.exit(main())
