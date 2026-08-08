#!/usr/bin/env python3
"""fix_ocr_vf3.py — Sửa lỗi font/OCR cho data/raw/vf3.md (brochure VF3 scan).

3 tầng:
  1. Cyrillic homoglyph → Latin (MОI→MOI, THỊNG СÓ→THỊNG SÓ...). Tổng quát, an toàn.
  2. U+FFFD (mất ký tự) → khôi phục theo ngữ cảnh (2 chỗ).
  3. Từ điển OCR → tiếng Việt chuẩn (toàn văn bản, ưu tiên spec table).

Usage:
    PYTHONUTF8=1 python scripts/clean_data/fix_ocr_vf3.py [--in data/raw/vf3.md] [--out CÙNG]
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Tầng 1: Cyrillic homoglyph → Latin ──────────────────────────────────────
_CYR = {
    "О": "O", "о": "o", "А": "A", "а": "a", "Н": "H", "С": "C", "с": "c",
    "Е": "E", "е": "e", "Р": "P", "р": "p", "Т": "T", "Х": "X", "х": "x",
    "М": "M", "м": "m", "В": "B", "в": "b", "К": "K", "к": "k", "І": "I",
    "і": "i", "Ѕ": "S", "ѕ": "s", "У": "Y", "у": "y", "Н": "H", "н": "h",
    "Д": "D", "д": "d", "И": "N", "и": "n", "П": "P", "п": "n", "Г": "r",
    "г": "r", "Л": "J", "л": "j",
}


def fix_cyrillic(s: str) -> str:
    return "".join(_CYR.get(ch, ch) for ch in s)


# ── Tầng 2: U+FFFD theo ngữ cảnh ────────────────────────────────────────────
_FFFD = {
    "xo�n Panhard": "xoắn Panhard",          # 'thành xoắn Panhard'
    "KH�UNG DÉN": "KHUNG ĐỀN",               # phần nóc xe
}


def fix_fffd(s: str) -> str:
    for bad, good in _FFFD.items():
        s = s.replace(bad, good)
    return s


# ── Tầng 3: từ điển OCR → tiếng Việt chuẩn (sắp theo độ dài giảm dần) ──────
_OCR = {
    # ── marketing (đầu file) ──
    "XE CỔA NHỮNG NGUỂI\nSÀNH ĐIẾU VÀ SÁNG TẢO": "XE CỦA NHỮNG NGƯỜI SÀNH ĐIỆU VÀ SÁNG TẠO",
    "XE CỔA NHỂNG NGUỄi": "XE CỦA NHỮNG NGƯỜI",
    "XE CỬA NHỂNG NGUỄi": "XE CỦA NHỮNG NGƯỜI",
    "*Hinh anh chi mang tính chát minh hqa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tính chát minh hòa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tinh chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tinh chát minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tinh chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tính chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mong tinh chát minh hqa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tinth chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tính chat minh họa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tính chát minh họa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "DẶT CỘC NGAY": "ĐẶT CỌC NGAY",
    "GIÁ BÁN CHÍNH THỜC": "GIÁ BÁN CHÍNH THỨC",
    "GIÁ BÂN CHÍNH THỜC": "GIÁ BÁN CHÍNH THỨC",
    "TRIẾU (XE KÊM PIN)*": "TRIỆU (XE KÈM PIN)*",
    "PHIên BÂN CÓ TÍCH Hợp": "PHIÊN BẢN CÓ TÍCH HỢP",
    "THêm ÓP LA – ZÄNG;": "THÊM ỐP LA-ZĂNG;",
    "THêm ÓP": "THÊM ỐP",
    "GU'ONG CHIÉU HÀU CHÍNH ĐIẾN & GÂP ĐIẾN;": "GƯƠNG CHIẾU HẬU CHỈNH ĐIỆN & GẬP ĐIỆN;",
    "GUỐNG CHIÉU HÂU": "GƯƠNG CHIẾU HẬU",
    "CHÍNH ĐIẾN": "CHỈNH ĐIỆN",
    "& GÂP ĐIỆN*": "& GẬP ĐIỆN*",
    "CAMERA LùI": "CAMERA LÙI",
    "CAMERA LùI*": "CAMERA LÙI*",
    "hoạc showroom/nhà phân phối để biét thêm chi tiết": "hoặc showroom/nhà phân phối để biết thêm chi tiết",
    "**Giá đã bao góm thuế VAT": "**Giá đã bao gồm thuế VAT",
    "THIỆT KÊ": "THIẾT KẾ",
    "TỂNG QUAN": "TỔNG QUAN",
    "THU HÚT NGAY Tù'": "THU HÚT NGAY TỪ",
    "ÁNH NHìN ĐÂU TIẾN": "ÁNH NHÌN ĐẦU TIÊN",
    "NHỒ GỘN": "NHỎ GỌN",
    "NÃNG ĐỔNG": "NĂNG ĐỘNG",
    "SÀNH ĐIẾU": "SÀNH ĐIỆU",
    "KÍCH THUỐC\nTÔNG THẾ": "KÍCH THƯỚC TỔNG THỂ",
    "Chiêu cao\n*tóng thẻ": "Chiều cao tổng thể",
    "chiều cao\n*tóng thẻ": "chiều cao tổng thể",
    "tóng thẻ": "tổng thể",
    "Chiêu cao": "Chiều cao",
    "Chiêu dài tóng thẻ": "Chiều dài tổng thể",
    "Chiêu rồng tóng thẻ": "Chiều rộng tổng thể",
    "Chiêu dài cơ sổ": "Chiều dài cơ sở",
    "PHù Hợp": "PHÙ HỢP",
    "MOI NGUỘI,\nMOI NHÀ": "MỌI NGƯỜI,\nMỌI NHÀ",
    "MOI NGUỘI, MOI NHÀ": "MỌI NGƯỜI, MỌI NHÀ",
    "MOI LÚC\nMOI NOI": "MỌI LÚC\nMỌI NƠI",
    "MOI LÚC MOI NOI": "MỌI LÚC MỌI NƠI",
    "***Hình anh chì mang tính chát minh hòa.": "***Hình ảnh chỉ mang tính chất minh họa.",
    "**Hình anh chi mong tinh chát minh hqa.": "**Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chỉ mang tính chát minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "TÍNH NÃNG": "TÍNH NĂNG",
    "NÂNG CÂP MÓ'I TRêN": "NÂNG CẤP MỚI TRÊN",
    "ĐAI LY PHÂN PHÖI": "ĐẠI LÝ PHÂN PHỐI",
    "THỊNG SÓ\nVÂN HÀNH": "THÔNG SỐ VẬN HÀNH",
    "THỊNG SÓ": "THÔNG SỐ",
    "VÂN HÀNH": "VẬN HÀNH",
    "ĐỔNG CÓ 01 Motor": "ĐỘNG CƠ 01 Motor",
    "CỂNG SUÁT TÓI ĐA (KW) 30": "CÔNG SUẤT TỐI ĐA (kW) 30",
    "MỔ MEN XOÃN CộC ĐAI (NM) 110": "MÔ MEN XOẮN CỰC ĐẠI (Nm) 110",
    "THỊI GIAN NẾP PIN": "THỜI GIAN NẠP PIN",
    "NHANH NHẼT 36 phút": "NHANH NHẤT 36 phút",
    "DÂN ĐỔNG RWD/Câu sau": "DẪN ĐỘNG RWD/Cầu sau",
    "TIỆN LỌI": "TIỆN LỢI",
    "VIF3": "VF3",
    "KHOANG NÓ THÁT KHÔNG PHÂ: DANG VÚA": "KHOANG NỘI THẤT KHÔNG PHÂN DẠNG VỪA",
    "TÀI TRONG 300 KG": "TẢI TRỌNG 300 KG",
    "NÓC XE\nTÀI HÃNH LY\nKHUNG ĐỀN\n50 KG": "NÓC XE TẢI HÀNH LÝ\nKHUNG ĐỀN\n50 KG",
    "TÀI HÃNH LY": "TẢI HÀNH LÝ",
    "MẪN HÍNH\n10 INCH KHÔNG LỘ": "MÀN HÌNH\n10 INCH KHÔNG LỒI",
    "BÁN KÍNH QUAY DÂU": "BÁN KÍNH QUAY ĐẦU",
    "LNH HOAT CHÍ": "LINH HOẠT CHỈ",
    "QUậNG DUỐNG": "QUÃNG ĐƯỜNG",
    "VI VU TÓI DA": "VI VU TỐI ĐA",
    "215 KM (NEDG)": "215 KM (NEDC)",
    "SAC NHANH": "SẠC NHANH",
    "## 36 PHÚT (10% - 70% PIN)": "36 PHÚT (10% - 70% PIN)",
    "KHOÀNG SÁNG GAM XE": "KHOẢNG SÁNG GẦM XE",
    "CAO(175MM)**": "CAO (175MM)**",
    "*Quảng duông di chuyén duoc tinh toan duda trên két qua kiém dinh theo quy chuán toàn cấu (NEDC)":
        "*Quãng đường di chuyển được tính toán dựa trên kết quả kiểm định theo quy chuẩn toàn cầu (NEDC)",
    "Quảng duông di chuyén thuc tê có thể giám so với két qua kiém dinh, phu thuốc vao toc do lái xe, nhiệt dô, dia hình, thủ quen":
        "Quãng đường di chuyển thực tế có thể giảm so với kết quả kiểm định, phụ thuộc vào tốc độ lái xe, nhiệt độ, địa hình, thói quen",
    "sù dung của nguoi lái, ché dô lái duoc cai dôi, sà luong hạnh khách, vá các dieuKIEN giao thông khúc":
        "sử dụng của người lái, chế độ lái được cài đổi, số lượng hành khách, và các điều kiện giao thông khác",
    "**Khoang sang gâm xe không tài.": "**Khoảng sáng gầm xe không tải.",
    "TRÀI NGHIỆM": "TRẢI NGHIỆM",
    "KHÔNG GIÁN ĐOẌN": "KHÔNG GIÁN ĐOẠN",
    "GỘN GÂNG KHI\nVÀO NGỂ, TIỆN LỚI\nHỐN MỄI NGÀY": "GỌN GÀNG KHI VÀO NGÕ, TIỆN LỢI HẰNG NGÀY",
    "TÍNH NÃNG NÂNG CÂP MÓ'I TRêN": "TÍNH NĂNG NÂNG CẤP MỚI TRÊN",
    "SÁNG TẢO": "SÁNG TẠO",
    "ĐÂM CHÂT RIỆNG": "ĐẬM CHẤT RIÊNG",
    "LA - ZĂNG MÓI*": "LA-ZĂNG MỚI*",
    "ĐIỆM NHÁN SÀNH ĐIỆU": "ĐIỂM NHẤN SÀNH ĐIỆU",
    "CHO CHỮ NHÂN": "CHO CHỦ NHÂN",
    "TÚ TIN ĐÖỂ CHUÂN, LÂM CHỮ MÓI GÓC NHìN": "TỰ TIN ĐỂ CHUẨN, LÀM CHỦ MỌI GÓC NHÌN",
    "TÚ TIN ĐÖỂ CHUÂN,": "TỰ TIN ĐỂ CHUẨN,",
    "LÂM CHỮ MÓI GÓC NHìN": "LÀM CHỦ MỌI GÓC NHÌN",
    "*Những tinh nâng, trang bi thuoc phiên bản VF 3 Plus.": "*Những tính năng, trang bị thuộc phiên bản VF 3 Plus.",
    "BỆNG MÀU NÂNG CAO": "BẢNG MÀU NÂNG CAO",
    "ĐỔ - SOLAR RUBY**": "ĐỎ - SOLAR RUBY**",
    "HÔNG (ROSE PINK)": "HỒNG (ROSE PINK)",
    "+ NÓC TRẢNG": "+ NÓC TRẮNG",
    "TRÁNG - INFINITY BLANC": "TRẮNG - INFINITY BLANC",
    "XANH DUỐNG (SKY BLUE)": "XANH DƯƠNG (SKY BLUE)",
    "XANH LÁ NHAT": "XANH LÁ NHẠT",
    "BỆNG MÀU CO' BÀN": "BẢNG MÀU CƠ BẢN",
    "**Luu ý: Màu Đô (Solar Ruby) sẽ thay thể mài Đô (Crimson Red) khi hét hang dê dâm bào tiên độ":
        "**Lưu ý: Màu Đỏ (Solar Ruby) sẽ thay thế màu Đỏ (Crimson Red) khi hết hàng để đảm bảo tiến độ",
    "bàn giao xe. Xín vui lòng liên hệ với dài lý phản phối gân nhật dê duỘc hố trợ.":
        "bàn giao xe. Xin vui lòng liên hệ với đại lý phân phối gần nhất để được hỗ trợ.",
    "HÂU MÃI VỤ ĐOÔI": "HẬU MÃI VÀ ĐỔI",
    "BÃO HÀNH XE MÓI*": "BẢO HÀNH XE MỚI*",
    "BÃO HÀNH PIN CAO ÁP*": "BẢO HÀNH PIN CAO ÁP*",
    "(DiêuKIên sù dung tiêu chuán)": "(Điều kiện sử dụng tiêu chuẩn)",
    "(Sù dung muc dích Dich vu thuáng mai)": "(Sử dụng mục đích Dịch vụ thương mại)",
    "## LU'U Y": "## LƯU Ý",
    "LIÊN HĨ HOTLINE HOẚC ĐAI LY PHÂN PHÖI GÂN NHÁT": "LIÊN HỆ HOTLINE HOẶC ĐẠI LÝ PHÂN PHỐI GẦN NHẤT",
    "ĐÉ TİM HIÉU THỎNG TIN CHI TIÉT.": "ĐỂ TÌM HIỂU THÔNG TIN CHI TIẾT.",
    "ĐАI LY PHÂN PHÖI": "ĐẠI LÝ PHÂN PHỐI",
    "*Tüy diếu kiên nào đến truóc.": "*Tùy điều kiện nào đến trước.",
    # ── spec table ──
    "KICH THUỐC & TAI TRONG": "KÍCH THƯỚC & TẢI TRỌNG",
    "KICH THUỐC": "KÍCH THƯỚC",
    "Chiêu dài cố sá (mm)": "Chiều dài cơ sở (mm)",
    "Dai x Rông x Cao (mm)": "Dài x Rộng x Cao (mm)",
    "Khoáng sảng gám xe không tái (mm)": "Khoảng sáng gầm xe không tải (mm)",
    "MOI NGUỘI,": "MỌI NGƯỜI,",
    "MOI LÚC": "MỌI LÚC",
    "MOI NOI": "MỌI NƠI",
    "Dung tích khoáng chúa hánh lý (L) - Dung hàng ghé cuối": "Dung tích khoang chứa hành lý (L) - Dựng hàng ghế cuối",
    "Dung tích khoáng chlua hánh lý (L) - Gáp hàng ghé cuối": "Dung tích khoang chứa hành lý (L) - Gập hàng ghế cuối",
    "Bán khính quay dấu tôi thiêu (m)": "Bán kính quay đầu tối thiểu (m)",
    "TAI TRONG": "TẢI TRỌNG",
    "Trong luồng không tái (kg)": "Trọng lượng không tải (kg)",
    "Tài trong (kg)": "Tải trọng (kg)",
    "Tài trong hành lý nóc xe (kg)": "Tải trọng hành lý nóc xe (kg)",
    "KHUNG GÁM": "KHUNG GẦM",
    "GIAM XÓC": "GIẢM XÓC",
    "Đọc lp, MacPherson": "Độc lập, MacPherson",
    "Phu thuốc, truc cùng với": "Phụ thuộc, trục cứng cùng với",
    "PHANH": "PHANH",
    "Phanth trúc": "Phanh trước",
    "Phanh dlà, calip nĩi": "Phanh đĩa, calip nổi",
    "Phanh tang tróng": "Phanh tang trống",
    "VÂNH VÀ LÖP BAHN XE": "VÀNH VÀ LỐP BÁNH XE",
    "Kích thước láp": "Kích thước lốp",
    "Bộ vά lóp": "Bộ vành lốp",
    "KHAC": "KHÁC",
    "Tr/q luc lái": "Trợ lực lái",
    "NGOAI THẾ": "NGOẠI THẤT",
    "Dèn pha": "Đèn pha",
    "Dèn hduce": "Đèn hậu",
    "Dèn dinh vi": "Đèn định vị",
    "Dieu chính cóp sau": "Điều chỉnh cốp sau",
    "Cánh huống gió": "Cánh hướng gió",
    "Chịnh cã": "Chỉnh cơ",
    "HÉ THONG TRUYÊN ĐỘNG": "HỆ THỐNG TRUYỀN ĐỘNG",
    "Dòng CÓ": "Động cơ",
    "Cộng suất tải do (kW)": "Công suất tối đa (kW)",
    "Mô men xoàn cuc đài (Nm)": "Mô men xoắn cực đại (Nm)",
    "Tác dở tải da (km/h)": "Tốc độ tối đa (km/h)",
    "100km/h khi dung luận pin >50%": "100 km/h khi dung lượng pin >50%",
    "PIN": "PIN",
    "Dung luận pin (kWh)": "Dung lượng pin (kWh)",
    "Quảng dụng chạy mật lân sac dây (km)": "Quãng đường chạy một lần sạc đầy (km)",
    "Tình nạng sac nhanh": "Tính năng sạc nhanh",
    "Hê thông.phanh.tai sinh": "Hệ thống phanh tái sinh",
    "Thời gian nap pin nhanh (phút)": "Thời gian nạp pin nhanh (phút)",
    "THONG SÓ TRUYÊN ĐỘNG KHAC": "THÔNG SỐ TRUYỀN ĐỘNG KHÁC",
    "Dăn dông": "Dẫn động",
    "Chơn chéo dô lái": "Chế độ lái",
    "Nời THÂT VÀ TIEN NGHI": "NỘI THẤT VÀ TIỆN NGHI",
    "GHÉ TOÁN XE": "GHẾ TOÀN XE",
    "Số chỗ ngại": "Số chỗ ngồi",
    "Chát liêu boc ghé": "Chất liệu bọc ghế",
    "Ní": "Nỉ",
    "GHÉ LАI": "GHẾ LÁI",
    "Từ dâu ghé lái": "Tựa đầu ghế lái",
    "Chinh cã 4 huàng": "Chỉnh cơ 4 hướng",
    "Có - tich hạp": "Có - tích hợp",
    "GHÉ PHU": "GHẾ PHỤ",
    "Ghế phuo": "Ghế phụ",
    "Từ dâu ghé phuo": "Tựa đầu ghế phụ",
    "GHÉ HANG 2": "GHẾ HÀNG 2",
    "Gập lung hàng ghé 2": "Gập lưng hàng ghế 2",
    "Từ dâu ghé hàng 2": "Tựa đầu ghế hàng 2",
    "Có - có định": "Có - cố định",
    "DIEU HOÁ KHONG KHÍ": "ĐIỀU HÒA KHÔNG KHÍ",
    "Hệ thống diếu hoà": "Hệ thống điều hòa",
    "Loc không khi cabin": "Lọc không khí cabin",
    "Chúc nâng lâm tan suàng/tan băng": "Chức năng làm tan sương/tan băng",
    "Chinh cã, 1 vùng": "Chỉnh cơ, 1 vùng",
    "Loc bui": "Lọc bụi",
    "MÂN HİNH, KET NÓI GIAI TRÍ": "MÀN HÌNH, KẾT NỐI GIẢI TRÍ",
    "Män hình giài trì càm ứng": "Màn hình giải trí cảm ứng",
    "Công kết noi USB - C cho hàng ghé trúc": "Cổng kết nối USB-C cho hàng ghế trước",
    "Kết nơi Wi-Fi": "Kết nối Wi-Fi",
    "Kết nơi Bluetooth": "Kết nối Bluetooth",
    "HÉ THONG LOA": "HỆ THỐNG LOA",
    "Hề_thông_loa": "Hệ thống loa",
    "Nời THÂT & TIEN NGHI KHAC": "NỘI THẤT & TIỆN NGHI KHÁC",
    "Phanth tay": "Phanh tay",
    "Guang chiêu hậu trong xe": "Gương chiếu hậu trong xe",
    "Dên trần phía trùc": "Đèn trần phía trước",
    "Tấm che nâng": "Tấm che nắng",
    "Hódung các trùdc/sau": "Hộc đựng các trước/sau",
    "AN TOÂN & AN NINH": "AN TOÀN & AN NINH",
    "Hề_thông_chóng_bó_cüng_phanh_ABS": "Hệ thống chống bó cứng phanh ABS",
    "Chúc nâng kiêm soátLuc kéo TCS": "Chức năng kiểm soát lực kéo TCS",
    "Hồ trák khái nhánh ngàng dốc HSA": "Hỗ trợ khởi hành ngang dốc HSA",
    "Khoa cura xe tx động khi xe di chuyen": "Khóa cửa xe tự động khi xe di chuyển",
    "Công_dai_khan_caq ghé_truć": "Công đai khẩn cấp ghế trước",
    "Chúc nâng phấn phiên_luc phanh_DIEN_tU EBD": "Chức năng phân phối lực phanh điện tử EBD",
    "Tình négnh Khóa dòng cã khi có trôm": "Tính năng khóa động cơ khi có trộm",
    "C Anh báo chóng tröm": "Cảnh báo chống trộm",
    "C anh báo dây an toàn hàng ghé truć": "Cảnh báo dây an toàn hàng ghế trước",
    "HÉ THONG TUI KHÍ": "HỆ THỐNG TÚI KHÍ",
    "TUi khi trước dành cho nguội lái": "Túi khí trước dành cho người lái",
    "HỎ TRỌ DỔ XE": "HỖ TRỢ ĐỖ XE",
    "Hồ trå dổ phia sau": "Hỗ trợ đỗ phía sau",
    "Camera lui": "Camera lùi",
    # ── cuối file ──
    "CÂM O'N BẰN Vì ĐÃ CHỐN": "CẢM ƠN BẠN VÌ ĐÃ CHỌN",
    "## VINFAST NGÀY HÔM NAY": "## VINFAST NGÀY HÔM NAY",
    "THỊNG TIN LIên Hê": "THÔNG TIN LIÊN HỆ",
    "1. Liên hệ ĐQUI lý phân phối chính hạng của": "1. Liên hệ ĐẠI LÝ phân phối chính hãng của",
    "VinFast tại Viêt Nam.": "VinFast tại Việt Nam.",
    "Tìm hiêu thông tin sàn phạm tại dây:": "Tìm hiểu thông tin sản phẩm tại đây:",
    "Hê thông Showroom VinFast:": "Hệ thống Showroom VinFast:",
    "2. Liên hệ VinFast Viêt Nam.": "2. Liên hệ VinFast Việt Nam.",
    "Facebookhttp://fb.com/VinFastAuto.Official": "Facebook: http://fb.com/VinFastAuto.Official",
}

_OCR_ITEMS = sorted(_OCR.items(), key=lambda kv: len(kv[0]), reverse=True)


def fix_ocr(s: str) -> str:
    for bad, good in _OCR_ITEMS:
        s = s.replace(bad, good)
    return s


def clean_vf3(text: str) -> str:
    text = fix_cyrillic(text)
    text = fix_fffd(text)
    text = fix_ocr(text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix font/OCR data/raw/vf3.md")
    ap.add_argument("--in", dest="inp", default="data/raw/vf3.md")
    ap.add_argument("--out", default=None, help="File output (mặc định: ghi đè file --in)")
    args = ap.parse_args()

    src = REPO_ROOT / args.inp
    text = src.read_text(encoding="utf-8")
    cleaned = clean_vf3(text)
    out = REPO_ROOT / (args.out or args.inp)
    out.write_text(cleaned, encoding="utf-8")
    print(f"[fix_ocr_vf3] {src} → {out}")
    print(f"  chars: {len(text)} → {len(cleaned)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())