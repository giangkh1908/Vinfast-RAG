#!/usr/bin/env python3
"""fix_ocr.py — Sửa lỗi font/OCR cho brochure PDF (scan) trong data/raw/*.md.

3 tầng:
  1. Cyrillic homoglyph → Latin (MОI→MOI, THỊNG СÓ→THỊNG SÓ, VОI→VOI...). Tổng quát.
  2. U+FFFD (mất ký tự) → khôi phục theo ngữ cảnh.
  3. Từ điển OCR → tiếng Việt chuẩn. Có: SHARED (dùng chung mọi file) + FILE_DICTS
     (riêng vf3/vf5/vf6...). Sắp theo độ dài giảm dần.

Usage:
    PYTHONUTF8=1 python scripts/clean_data/fix_ocr.py data/raw/vf3.md data/raw/vf5.md data/raw/vf6.md
    PYTHONUTF8=1 python scripts/clean_data/fix_ocr.py --all          # toàn bộ *.md trong data/raw
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Tầng 1: Cyrillic homoglyph → Latin ──────────────────────────────────────
_CYR = {
    "О": "O", "о": "o", "А": "A", "а": "a", "Н": "H", "н": "h", "С": "C", "с": "c",
    "Е": "E", "е": "e", "Р": "P", "р": "p", "Т": "T", "т": "t", "Х": "X", "х": "x",
    "М": "M", "м": "m", "В": "B", "в": "b", "К": "K", "к": "k", "І": "I", "і": "i",
    "Ѕ": "S", "ѕ": "s", "У": "Y", "у": "y", "Д": "D", "д": "d", "И": "N", "и": "n",
    "П": "P", "п": "n", "Г": "r", "г": "r", "Л": "J", "л": "j", "Ё": "E", "ё": "e",
    "Æ": "AE", "æ": "ae",
}


def fix_cyrillic(s: str) -> str:
    return "".join(_CYR.get(ch, ch) for ch in s)


# ── Tầng 2: U+FFFD theo ngữ cảnh ────────────────────────────────────────────
_FFFD = {  # sentinel "@@" = ký tự U+FFFD (replace trước khi áp dict)
    "xon Panhard": "xoắn Panhard",
    "KH@@UNG DÉN": "KHUNG ĐỀN",
    "Dèn nh@@n điện thuong hiêu phla trước": "Đèn nhận diện thương hiệu phía trước",
    "Cánh báo chech l@@n": "Cảnh báo chệch làn",
    "Phanh tú dạng kh@@n cáp trừc/sau": "Phanh tự động khẩn cấp trước/sau",
    "đ@@n duàng trên màn hình trung tâm": "dẫn đường trên màn hình trung tâm",
    "đến tr@@uć": "đến trước",
    "DIỀU KHIÉN THONG MINH": "ĐIỀU KHIỂN THÔNG MINH",
}


def fix_fffd(s: str) -> str:
    s = s.replace("�", "@@")  # U+FFFD → sentinel
    for bad, good in _FFFD.items():
        s = s.replace(bad, good)
    s = s.replace("@@" * 1, "")  # sentinel dư (nếu còn) → bỏ
    s = s.replace("&amp;", "&")  # HTML entity (Firecrawl) → &
    return s


# ── Tầng 3a: từ điển dùng chung (boilerplate + thuật ngữ lặp lại) ───────────
_SHARED = {
    "*Hình anh chi mang tính chát minh hqa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tính chát minh hòa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tinh chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tinh chát minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tinh chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tính chat minh hoa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mong tinh chát minh hqa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chì mang tinh chát minh hòa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "*Hinh anh chi mang tinh chát minh họa.": "*Hình ảnh chỉ mang tính chất minh họa.",
    "Hình ảnh mang tính chất minh họa và có thể khác so với thực tế": "Hình ảnh mang tính chất minh họa và có thể khác so với thực tế",
    "Hinh anh mang tinh chát minh hoa": "Hình ảnh mang tính chất minh họa",
    "Hình ảnh mang tính chất minh hoạ": "Hình ảnh mang tính chất minh họa",
    "Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước.":
        "Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước.",
    "Các tinh nâng, dãc diêm, thông số ký thuật của xe có thể dûç_DIEU chính bội Nhà Sân Xuát mà khổ thông báo trúc.":
        "Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước.",
    "Các tinh nâng, dãc diêm, thông số ký thuật của xe có thể dãuc díeu chinh bôi Nhà Sân Xuất mà không thông báo trúac.":
        "Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước.",
    "Hình ánh mang tính chât minh hoa và có thekhác so với tc té":
        "Hình ảnh mang tính chất minh họa và có thể khác so với thực tế",
    "Hinh anh mang tính chât minh hoa và có thekhóc so voi tc té":
        "Hình ảnh mang tính chất minh họa và có thể khác so với thực tế",
    "Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước":
        "Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước",
    "Hình ảnh mang tính chất minh họa và có thể khác so với thực tế Các tính năng, đặc điểm, thông số kỹ thuật của xe có thể được điều chỉnh bởi Nhà Sản Xuất mà không thông báo trước.":
        "Hình ảnh mang tính chất minh họa và có thể khác so với thực tế.",
    # thuật ngữ lặp lại dùng chung (spec)
    "Công suất tối đa (kW)": "Công suất tối đa (kW)",
    "Mô men xoắn cực đại (Nm)": "Mô men xoắn cực đại (Nm)",
    "Quãng đường chạy một lần sạc đầy (km)": "Quãng đường chạy một lần sạc đầy (km)",
    "Số chỗ ngồi": "Số chỗ ngồi",
}


# ── Tầng 3b: từ điển riêng từng file ────────────────────────────────────────
_VF3 = {
    "XE CỔA NHỮNG NGUỂI\nSÀNH ĐIẾU VÀ SÁNG TẢO": "XE CỦA NHỮNG NGƯỜI SÀNH ĐIỆU VÀ SÁNG TẠO",
    "XE CỔA NHỂNG NGUỄi": "XE CỦA NHỮNG NGƯỜI",
    "XE CỬA NHỂNG NGUỄi": "XE CỦA NHỮNG NGƯỜI",
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
    "tóng thẻ": "tổng thể",
    "Chiêu cao": "Chiều cao",
    "Chiêu dài tóng thẻ": "Chiều dài tổng thể",
    "Chiêu rồng tóng thẻ": "Chiều rộng tổng thể",
    "Chiêu dài cơ sổ": "Chiều dài cơ sở",
    "PHù Hợp": "PHÙ HỢP",
    "MOI NGUỘI, MOI NHÀ": "MỌI NGƯỜI, MỌI NHÀ",
    "MOI NGUỘI,": "MỌI NGƯỜI,",
    "MOI LÚC": "MỌI LÚC",
    "MOI NOI": "MỌI NƠI",
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
    "TÍNH NÃNG\nNÂNG CÂP MÓ'I TRêN": "TÍNH NĂNG\nNÂNG CẤP MỚI TRÊN",
    "TÍNH NÃNG": "TÍNH NĂNG",
    "NÂNG CÂP MÓ'I TRêN": "NÂNG CẤP MỚI TRÊN",
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
    "ĐAI LY PHÂN PHÖI": "ĐẠI LÝ PHÂN PHỐI",
    "*Tüy diếu kiên nào đến truóc.": "*Tùy điều kiện nào đến trước.",
    "KICH THUỐC & TAI TRONG": "KÍCH THƯỚC & TẢI TRỌNG",
    "KICH THUỐC": "KÍCH THƯỚC",
    "Chiêu dài cố sá (mm)": "Chiều dài cơ sở (mm)",
    "Dai x Rông x Cao (mm)": "Dài x Rộng x Cao (mm)",
    "Khoáng sảng gám xe không tái (mm)": "Khoảng sáng gầm xe không tải (mm)",
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
    "CÂM O'N BẰN Vì ĐÃ CHỐN": "CẢM ƠN BẠN VÌ ĐÃ CHỌN",
    "THỊNG TIN LIên Hê": "THÔNG TIN LIÊN HỆ",
    "1. Liên hệ ĐQUI lý phân phối chính hạng của": "1. Liên hệ ĐẠI LÝ phân phối chính hãng của",
    "VinFast tại Viêt Nam.": "VinFast tại Việt Nam.",
    "Tìm hiêu thông tin sàn phạm tại dây:": "Tìm hiểu thông tin sản phẩm tại đây:",
    "Hê thông Showroom VinFast:": "Hệ thống Showroom VinFast:",
    "2. Liên hệ VinFast Viêt Nam.": "2. Liên hệ VinFast Việt Nam.",
    "Facebookhttp://fb.com/VinFastAuto.Official": "Facebook: http://fb.com/VinFastAuto.Official",
    "VIF3": "VF3",
}

_VF5 = {
    # spec table KÍCH THƯỚC & TẢI TRỌNG
    "| Chiéu dài cô sò (mm) |": "| Chiều dài cơ sở (mm) |",
    "| Dài x rông x cao (mm) |": "| Dài x Rộng x Cao (mm) |",
    "| Khoảng sáng gám xe không tái (mm) |": "| Khoảng sáng gầm xe không tải (mm) |",
    "| Dung tích khoang chúa hành lý (lit) |": "| Dung tích khoang chứa hành lý (lit) |",
    "Có/gêp hàng ghé cuoi (ISO 3832)": "Có/gập hàng ghế cuối (ISO 3832)",
    "| Tròng luóng không tái (kg) |": "| Trọng lượng không tải (kg) |",
    "| Tái trông (kg) |": "| Tải trọng (kg) |",
    "KHUNG GẦ M": "KHUNG GẦM",
    "| Hê thông treo - truóc | Đốc láp, MacPherson |": "| Hệ thống treo - trước | Độc lập, MacPherson |",
    "| Hê thông treo - sau | Dám xoán |": "| Hệ thống treo - sau | Dầm xoắn |",
    "| Hê thông phanh truóc/sau | Đição thông gió/địa |": "| Hệ thống phanh trước/sau | Đĩa thông gió/đĩa |",
    "| Loai la-zāng | Hạp kim 17 inch |": "| Loại la-zăng | Hợp kim 17 inch |",
    "| Trợ luc lái | EPS/Trợ luc diên |": "| Trợ lực lái | EPS/Trợ lực điện |",
    # NGOẠI THẤT
    "| Đèn pha | Halogen Tư dông bét/tát |": "| Đèn pha | Halogen Tự động bật/tắt |",
    "| Đèn hạu | Halogen |": "| Đèn hậu | Halogen |",
    "| Guảng chiêu hạu | Chính diên tích hợp báo rẽ |": "| Gương chiếu hậu | Chỉnh điện tích hợp báo rẽ |",
    "| Kính của sơ chinh diên |": "| Kính cửa sổ chỉnh điện |",
    "Lên/xuóng một chạm của tài xẽ": "Lên/xuống một chạm của tài xế",
    "| Kính chăn gió | Chóng tia UV |": "| Kính chắn gió | Chống tia UV |",
    "| Tám bào vê duoi thần xe | Có |": "| Tấm bảo vệ dưới thân xe | Có |",
    # HỆ TRUYỀN ĐỘNG
    "# THÔNG SỐ ĐỘ NG CƠ": "# THÔNG SỐ ĐỘNG CƠ",
    "Cấu hì nh độ ng cơ": "Cấu hình động cơ",
    "Công suất tố i đa (kW/hp)": "Công suất tối đa (kW/hp)",
    "Mô men xoắn cực đạ i (Nm)": "Mô men xoắn cực đại (Nm)",
    "Tăng tố c 0 - 100 km/h (s)": "Tăng tốc 0 - 100 km/h (s)",
    "1 Motor điệ n": "1 Motor điện",
    "THÔNG SỐ TRUYỀ N ĐỘ NG KHÁ C": "THÔNG SỐ TRUYỀN ĐỘNG KHÁC",
    "Hệ dẫn độ ng FWD/Cầ u trước": "Hệ dẫn động FWD/Cầu trước",
    "Chọ n chế độ lái Eco/Sport": "Chọn chế độ lái Eco/Sport",
    # PIN
    "## THÔNG SỐ PIN": "## THÔNG SỐ PIN",
    "## NỘ I THẤ T & TIỆ N NGHI": "## NỘI THẤT & TIỆN NGHI",
    "Số chỗ ngồi": "Số chỗ ngồi",
    "Chất liệ u bọc ghế": "Chất liệu bọc ghế",
    "Ghế lá i": "Ghế lái",
    "Hà ng ghế thứ hai": "Hàng ghế thứ hai",
    "Chỉnh cơ 6 hướng": "Chỉnh cơ 6 hướng",
    "Có thể gậ p theo tỷ lệ 60:40": "Có thể gập theo tỷ lệ 60:40",
    "Vô lăng Chỉnh cơ 2 hướng, tí ch hợ p nút bấm điều khiển\n": "Vô lăng Chỉnh cơ 2 hướng, tích hợp nút bấm điều khiển\n",
    "tí nh năng giả i trí và ga tự độ ng": "tính năng giải trí và ga tự động",
    "Hệ thố ng điều hòa": "Hệ thống điều hòa",
    "Chức năng là m tan sương/tan băng Có": "Chức năng làm tan sương/tan băng Có",
    "Mà n hì nh giả i trí cả m ứng": "Màn hình giải trí cảm ứng",
    "Bả ng đồng hồ thông tin lá i": "Bảng đồng hồ thông tin lái",
    "Cổng kế t nố i USB Hà ng ghế trước: 1 (cổng dữ liệ u và sạ c 7,5 W)": "Cổng kết nối USB Hàng ghế trước: 1 (cổng dữ liệu và sạc 7,5 W)",
    "Hà ng ghế thứ hai: 1 (cổng sạ c 18 W)": "Hàng ghế thứ hai: 1 (cổng sạc 18 W)",
    "Quả n lý WiFi (kế t nố i / phá t hotspot) Có": "Quản lý WiFi (kết nối / phát hotspot) Có",
    "Quả n lý thiế t bị Bluetooth (Điệ n thoạ i và nghe nhạ c) Có": "Quản lý thiết bị Bluetooth (Điện thoại và nghe nhạc) Có",
    "Chì a khóa": "Chìa khóa",
    "Hệ thố ng loa": "Hệ thống loa",
    "Chì a khóa từ xa": "Chìa khóa từ xa",
    # AN TOÀN
    "## AN TOÀ N & AN NINH": "## AN TOÀN & AN NINH",
    "Hệ thố ng chố ng bó cứng phanh ABS": "Hệ thống chống bó cứng phanh ABS",
    "Chức năng phân phố i lực phanh điệ n tử EBD": "Chức năng phân phối lực phanh điện tử EBD",
    "Hệ thố ng cân bằng điệ n tử ESC": "Hệ thống cân bằng điện tử ESC",
    "Chức năng kiểm soá t lực kéo TCS": "Chức năng kiểm soát lực kéo TCS",
    "Hỗ trợ khở i hà nh ngang dố c HSA": "Hỗ trợ khởi hành ngang dốc HSA",
    "Đèn bá o nguy hiểm khi phanh khẩn cấp ESS": "Đèn báo nguy hiểm khi phanh khẩn cấp ESS",
    "Giá m sá t á p suất lố p": "Giám sát áp suất lốp",
    "Khóa cửa xe tự độ ng khi xe di chuyển": "Khóa cửa xe tự động khi xe di chuyển",
    "Móc cố đị nh ghế trẻ em ISOFIX, hà ng ghế thứ 2": "Móc cố định ghế trẻ em ISOFIX, hàng ghế thứ 2",
    "Cả nh bá o thắt dây an toà n hà ng ghế trước": "Cảnh báo thắt dây an toàn hàng ghế trước",
    "Cả nh bá o chố ng trộ m": "Cảnh báo chống trộm",
    "Tí nh năng khóa độ ng cơ khi có trộ m": "Tính năng khóa động cơ khi có trộm",
    "HỆ THỐ NG TÚ I KHÍ": "HỆ THỐNG TÚI KHÍ",
    "Túi khí trước lá i và hà nh khá ch phí a trước": "Túi khí trước lái và hành khách phía trước",
    "Túi khí bên hông hà ng ghế trước": "Túi khí bên hông hàng ghế trước",
    # ADAS
    "## TÍNH NĂNG ADAS": "## TÍNH NĂNG ADAS",
    "Cả nh bá o phương tiệ n cắt ngang phí a sau": "Cảnh báo phương tiện cắt ngang phía sau",
    "Cả nh bá o điểm mù": "Cảnh báo điểm mù",
    "Cả nh bá o mở cửa": "Cảnh báo mở cửa",
    "Hệ thố ng camera sau": "Hệ thống camera sau",
    "Hỗ trợ đỗ phí a sau": "Hỗ trợ đỗ phía sau",
    # THÔNG MINH
    "Chẩn đoá n lỗi trên xe tự độ ng": "Chẩn đoán lỗi trên xe tự động",
    "Đồng bộ tà i khoả n & Quả n lý hồ sơ ngườ i lá i Có": "Đồng bộ tài khoản & Quản lý hồ sơ người lái Có",
    "Giả i trí âm thanh: FM Radio, USB, Bluetooth": "Giải trí âm thanh: FM Radio, USB, Bluetooth",
    "Kế t nố i Android Auto và Apple Carplay không dây Có": "Kết nối Android Auto và Apple Carplay không dây Có",
    "Quãng đườ ng chạ y mộ t lầ n sạ c đầ y (km) -\nĐiều kiệ n tiêu chuẩn NEDC": "Quãng đường chạy một lần sạc đầy (km) -\nĐiều kiện tiêu chuẩn NEDC",
    "Thờ i gian nạ p pin nhanh nhất": "Thời gian nạp pin nhanh nhất",
    "Điều khiển xe bằng giọng nói": "Điều khiển xe bằng giọng nói",
    "Hỏi đá p thông tin thờ i tiế t, tiệ n í ch, tí nh năng xe Có": "Hỏi đáp thông tin thời tiết, tiện ích, tính năng xe Có",
    "Giá m sá t xe từ xa (vị trí, thông số, cả nh bá o) Có": "Giám sát xe từ xa (vị trí, thông số, cảnh báo) Có",
    "Tì m kiế m trạ m sạ c": "Tìm kiếm trạm sạc",
    "Thanh toá n phí sạ c": "Thanh toán phí sạc",
    "Đặt lị ch sửa chữa, bả o dưỡng": "Đặt lịch sửa chữa, bảo dưỡng",
    "Thông tin khuyế n mạ i & phụ kiệ n": "Thông tin khuyến mại & phụ kiện",
    # prose (trang chủ)
    "Kí ch thước xe 3.967 x 1.723 x 1.579 mm": "Kích thước xe 3.967 x 1.723 x 1.579 mm",
    "giúp bạ n di chuyển thuậ n lợ i trong thà nh phố.": "giúp bạn di chuyển thuận lợi trong thành phố.",
    "Không gian rộ ng rãi với chiều dà i cơ sở 2.514 mm,": "Không gian rộng rãi với chiều dài cơ sở 2.514 mm,",
    "thoả i má i cho 5 chỗ ngồi.": "thoải mái cho 5 chỗ ngồi.",
    "6 tí nh năng hỗ trợ lá i và 19 tí nh năng": "6 tính năng hỗ trợ lái và 19 tính năng",
    "thông minh": "thông minh",
    "Cảnh báo phương tiện cắt ngang phía sau: Hỗ trợ phá t hiệ n vậ t cả n hay": "Cảnh báo phương tiện cắt ngang phía sau: Hỗ trợ phát hiện vật cản hay",
    "phương tiệ n di chuyển từ phí a sau hoặc hai bên, đặc biệ t là cá c điểm mù.":
        "phương tiện di chuyển từ phía sau hoặc hai bên, đặc biệt là các điểm mù.",
    "Cảnh báo mở cửa: Hỗ trợ và cả nh bá o khi có chướng ngạ i vậ t, xe hoặc ngườ i từ":
        "Cảnh báo mở cửa: Hỗ trợ và cảnh báo khi có chướng ngại vật, xe hoặc người từ",
    "hai bên hoặc phí a sau, giúp trá nh va chạ m khi mở cửa xe.": "hai bên hoặc phía sau, giúp tránh va chạm khi mở cửa xe.",
    "Cảnh báo điểm mù: Cả m biế n giúp phá t hiệ n ngườ i hoặc xe từ phí a sau, đưa ra":
        "Cảnh báo điểm mù: Cảm biến giúp phát hiện người hoặc xe từ phía sau, đưa ra",
    "cả nh bá o để ngườ i lá i chú ý quan sá t và xử lý tì nh huố ng.":
        "cảnh báo để người lái chú ý quan sát và xử lý tình huống.",
    "Hỗ trợ đỗ phía sau: Cụ m cả m biế n phí a sau phá t hiệ n chướng ngạ i vậ t và gửi":
        "Hỗ trợ đỗ phía sau: Cụm cảm biến phía sau phát hiện chướng ngại vật và gửi",
    "cả nh bá o, hỗ trợ bạ n đỗ xe an toà n.": "cảnh báo, hỗ trợ bạn đỗ xe an toàn.",
    "Trợ lý ảo ViVi  đượ c tí ch hợ p AI": "Trợ lý ảo ViVi được tích hợp AI",
    "tạ o sinh, nhằm giúp xử lý nhiều": "tạo sinh, nhằm giúp xử lý nhiều",
    "tá c vụ và cá c câu hỏi phức tạ p": "tác vụ và các câu hỏi phức tạp",
    "với tương tá c tự nhiên để tạ o ra": "với tương tác tự nhiên để tạo ra",
    "những trả i nghiệ m đượ c cá nhân": "những trải nghiệm được cá nhân",
    "hóa thông qua giọng nói.": "hóa thông qua giọng nói.",
    "Độ chí nh xá c khi nhậ n": "Độ chính xác khi nhận",
    "ngôn ngữ Tiế ng Việ t": "ngôn ngữ Tiếng Việt",
    "n diệ Nghe hiểu đượ c ngôn ngữ": "n dịệ Nghe hiểu được ngôn ngữ",
    "tiế ng Việ t đa vùng miền": "tiếng Việt đa vùng miền",
    "ở nhiều tỉnh thà nh khá c nhau.": "ở nhiều tỉnh thành khác nhau.",
    "Trợ lý ả o ViVi giúp điều khiển dễ dà ng cá c tí nh năng trên xe như":
        "Trợ lý ảo ViVi giúp điều khiển dễ dàng các tính năng trên xe như",
    "điều hòa, giả i trí, bả n đồ và nhiều hơn thế, chỉ bằng giọng nói.":
        "điều hòa, giải trí, bản đồ và nhiều hơn thế, chỉ bằng giọng nói.",
    "Trợ lý ả o ViVi có khả năng hỏi đá p những câu hỏi cơ bả n như":
        "Trợ lý ảo ViVi có khả năng hỏi đáp những câu hỏi cơ bản như",
    "tin tức, thờ i tiế t, truyệ n cườ i – mang đế n trả i nghiệ m lá i xe":
        "tin tức, thời tiết, truyện cười – mang đến trải nghiệm lái xe",
    "sinh độ ng và trọn vẹn hơn.": "sinh động và trọn vẹn hơn.",
    "Đuôi xe *VF 5* có thiết kế vuông vứ c,": "Đuôi xe *VF 5* có thiết kế vuông vức,",
    "tối giản điểm nhấn là dả i chữ V đượ c là m từ": "tối giản điểm nhấn là dải chữ V được làm từ",
    "chất liệ u phả n quang. Đuôi xe cũng đượ c": "chất liệu phản quang. Đuôi xe cũng được",
    "trang bị đầ y đủ hệ thố ng cả m biế n đỗ xe": "trang bị đầy đủ hệ thống cảm biến đỗ xe",
    "và camera lùi.": "và camera lùi.",
    "Đầ u xe *VF 5* với thiế t kế chữ V": "Đầu xe *VF 5* với thiết kế chữ V",
    "đặc trưng đượ c mạ crom tinh": "đặc trưng được mạ crom tinh",
    "tế, không có lưới tả n nhiệ t": "tế, không có lưới tản nhiệt",
    "nhờ công nghệ điệ n hóa": "nhờ công nghệ điện hóa",
    "Phố i mà u sắc độ c đá o hai mà u củ a thân và": "Phối màu sắc độc đáo hai màu của thân và",
    "nóc xe, cá c chi tiế t ngoạ i thất đồng mà u củ a ố p": "nóc xe, các chi tiết ngoại thất đồng màu của ốp",
    "ngoà i gương chiế u hậ u với nóc xe, tay nắm cửa với": "ngoài gương chiếu hậu với nóc xe, tay nắm cửa với",
    "thân xe tạ o nên phong cá ch riêng củ a *VF 5*": "thân xe tạo nên phong cách riêng của *VF 5*",
    "La zăng mạ nh mẽ với phiên bả n *VF 5:*": "La zăng mạnh mẽ với phiên bản *VF 5:*",
    "La-zăng hợ p kim 17 inch": "La-zăng hợp kim 17 inch",
    "Gương chiếu hậu": "Gương chiếu hậu",
    "chỉnh điện": "chỉnh điện",
    "Thiế t kế nộ i thất ô tô điệ n VinFast *VF 5* hướng tới sự": "Thiết kế nội thất ô tô điện VinFast *VF 5* hướng tới sự",
    "tố i giả n với cá ch phố i mà u nộ i thất đồng điệ u với ngoạ i thất":
        "tối giản với cách phối màu nội thất đồng điệu với ngoại thất",
    "là m nổi bậ t lên vẻ cuố n hút nhờ cá c đườ ng viền bắt mắt.":
        "làm nổi bật lên vẻ cuốn hút nhờ các đường viền bắt mắt.",
    "Bả ng đồng hồ kỹ thuậ t số": "Bảng đồng hồ kỹ thuật số",
    "sau vô lăng 7 inch và mà n hì nh": "sau vô lăng 7 inch và màn hình",
    "trung tâm cả m ứng 8 inch": "trung tâm cảm ứng 8 inch",
    "Hệ thống 4 loa,": "Hệ thống 4 loa,",
    "Âm thanh sắc nét": "Âm thanh sắc nét",
    "## Cổng USB ở 2 hà ng ghế": "## Cổng USB ở 2 hàng ghế",
    "Điều hoà chỉnh cơ 1 vùng, mà ng lọc bụ i PM2.5": "Điều hoà chỉnh cơ 1 vùng, màng lọc bụi PM2.5",
    "VF 5 với nền tả ng khung gầ m toà n cầ u củ a": "VF 5 với nền tảng khung gầm toàn cầu của",
    "VinFast đã đượ c kiểm chứng qua hà ng": "VinFast đã được kiểm chứng qua hàng",
    "trăm ngà n xe bá n ra tạ i Việ t Nam.": "trăm ngàn xe bán ra tại Việt Nam.",
    "VF 5 đượ c trang bị hệ thố ng an toà n hiệ n": "VF 5 được trang bị hệ thống an toàn hiện",
    "đạ i vớ i *hơn 11 chức năng* an toàn": "đại với *hơn 11 chức năng* an toàn",
    "nổ i trội, nhằm đả m bả o an toà n khi tham gia": "nổi trội, nhằm đảm bảo an toàn khi tham gia",
    "giao thông cho ngườ i dùng, cụ thể:": "giao thông cho người dùng, cụ thể:",
    "Sạ c mọi lúc tạ i nhà và trên mọi hà nh trì nh với bộ sạ c di độ ng tiệ n lợ i.":
        "Sạc mọi lúc tại nhà và trên mọi hành trình với bộ sạc di động tiện lợi.",
    "Hệ thố ng tram sạ c nhanh phủ khắp toà n quố c, với khoả ng cá ch trung bì nh":
        "Hệ thống trạm sạc nhanh phủ khắp toàn quốc, với khoảng cách trung bình",
    "là 3.5 km giữa cá c trạ m. (cậ p nhậ t đế n thá ng 09/2023)":
        "là 3.5 km giữa các trạm. (cập nhật đến tháng 09/2023)",
    "Tạ i mà n hì nh trang chủ Ứng dụ ng VinFast,": "Tại màn hình trang chủ Ứng dụng VinFast,",
    "chọn mụ c “Pin và sạ c” để tì m kiế m danh sá ch": "chọn mục “Pin và sạc” để tìm kiếm danh sách",
    "cá c trạ m sạ c gầ n đó.": "các trạm sạc gần đó.",
    "Bấm chọn trạ m sạ c trong danh sá ch": "Bấm chọn trạm sạc trong danh sách",
    "có sẵn tạ i mụ c “Pin và Sạ c”": "có sẵn tại mục “Pin và Sạc”",
    "Trạ m sạ c đã chọn sẽ hiển thị bả n đồ di chuyển trên":
        "Trạm sạc đã chọn sẽ hiển thị bản đồ di chuyển trên",
    "mà n hì nh ứng dụ ng.": "màn hình ứng dụng.",
    "Bấm “Chỉ đườ ng” và điều khiển xe theo hướng dẫn củ a":
        "Bấm “Chỉ đường” và điều khiển xe theo hướng dẫn của",
    "ứng dụ ng để tì m đế n trạ m sạ c nà y.": "ứng dụng để tìm đến trạm sạc này.",
    "Chính sách bảo hành": "Chính sách bảo hành",
    "Dịch vụ hậu mãi xuất sắc": "Dịch vụ hậu mãi xuất sắc",
    "*· Cứu hộ bằng xe kéo (RSA)*": "*· Cứu hộ bằng xe kéo (RSA)*",
    "*· Cứu hộ 24/7 trong suốt thời gian bảo hành*": "*· Cứu hộ 24/7 trong suốt thời gian bảo hành*",
    "*· Mạng lưới 150.000 cổng sạc phủ rộng toàn quốc.*": "*· Mạng lưới 150.000 cổng sạc phủ rộng toàn quốc.*",
    "## 100 kW (134 HP)": "100 kW (134 HP)",
    "# ÊM ÁI": "# ÊM ÁI",
    "## 135 Nm": "135 Nm",
    "## 326 Km": "326 Km",
    "## BẢNG THÔNG SỐ KỸ THUẬT\n\n## KÍCH THƯỚC & TẢI TRỌNG": "## BẢNG THÔNG SỐ KỸ THUẬT\n\n## KÍCH THƯỚC & TẢI TRỌNG",
}

_VF6 = {
    # prose đầu
    "MANH MÊ, NĂNG ĐỔNG,\nSUỐ LÚA CHỎN LY TUỂNG CỬA GIA ĐìNH TRÉ!":
        "MẠNH MẼ, NĂNG ĐỘNG,\nSỨ LỬA CHỌN LÝ TƯỞNG CỦA GIA ĐÌNH TRẺ!",
    "MANH MÉ, NĂNG ĐỔNG,\nSỨ LỬA CHỐN LY TUỂNG CÙA GIA ĐìNH TRÊ!":
        "MẠNH MẼ, NĂNG ĐỘNG,\nSỨ LỬA CHỌN LÝ TƯỞNG CỦA GIA ĐÌNH TRẺ!",
    "VОI KIЁU DÁNG ĐÚỔNG ĐАI YỆ": "VỚI KIỂU DÁNG ĐƯỜNG ĐAI VỆ",
    "VF 6 mang đâm dâu ăn hiên dài và thanh lich, được sáng táo bôi":
        "VF 6 mang đậm dấu ấn hiện đại và thanh lịch, được sáng tạo bởi",
    "Studio Torino Design – nhưng chuyèn gia hàng đAu thê giói.":
        "Studio Torino Design – những chuyên gia hàng đầu thế giới.",
    "Tùng đuǒng nét đeu toát lên suú dõt phá, phù hợp với phong cách của":
        "Từng đường nét đều toát lên sự đột phá, phù hợp với phong cách của",
    "gia đính trè.": "gia đình trẻ.",
    "Không gian nội thất rông rải, tinh tế cua VF 6 mang đён càm giác":
        "Không gian nội thất rộng rãi, tinh tế của VF 6 mang đến cảm giác",
    "thoaMi mái và sang trong, huý một ngôinhà thu hai lý tuǒng cho":
        "thoải mái và sang trọng, như một ngôi nhà thứ hai lý tưởng cho",
    "những chuyến dişi dây y nghïa.": "những chuyến đi đầy ý nghĩa.",
    "Giài thuảng do Người tiêu dung va Hội đồng thăm định binh chon":
        "Giải thưởng do Người tiêu dùng và Hội đồng thẩm định bình chọn",
    "BETTER CHOICE AWARDS 2024": "BETTER CHOICE AWARDS 2024",
    "3 Chế Độ Lái": "3 Chế Độ Lái",
    "ECO / NORMAL / SPORT": "ECO / NORMAL / SPORT",
    "Phạm vi di chuyển": "Phạm vi di chuyển",
    "lên tới 485 KM**": "lên tới 485 KM**",
    "Công Suất Tối Đa": "Công Suất Tối Đa",
    "150 kW/201 hp*": "150 kW/201 hp*",
    "Mô Men Xoắn Cực Đại": "Mô Men Xoắn Cực Đại",
    "310Nm*": "310Nm*",
    "*Phiên bản VF 6 Plus **Phiên bản VF 6 Eco": "*Phiên bản VF 6 Plus **Phiên bản VF 6 Eco",
    "*GiÆm sát hành trình thích ứng**": "*Giám sát hành trình thích ứng**",
    "*Phanh tự động khẩn cấp trước**": "*Phanh tự động khẩn cấp trước**",
    "*Cảnh báo điểm mù*": "*Cảnh báo điểm mù*",
    "*Nhận biết biển báo giao thông**": "*Nhận biết biển báo giao thông**",
    "*Để biết chi tiết hơn về hệ thống ADAS trŒn VF 6, khÆch hng vui lòng liên hệ*":
        "*Để biết chi tiết hơn về hệ thống ADAS trên VF 6, khách hàng vui lòng liên hệ*",
    "*tư vấn bán hàng tại Showroom gần nhất hoặc Hotline 1900 23 23 89*":
        "*tư vấn bán hàng tại Showroom gần nhất hoặc Hotline 1900 23 23 89*",
    "*MN HNH HUD**": "*MÀN HÌNH HUD**",
    "*HỆ THỐNG*": "*HỆ THỐNG*",
    "*CHỐNG LẬT ROM*": "*CHỐNG LẬT ROM*",
    "**Ghế lái chỉnh điện 8 hướng***": "**Ghế lái chỉnh điện 8 hướng***",
    "**Phiên bản VF 6 Plus*": "**Phiên bản VF 6 Plus*",
    "## KHNG GIAN THOẢI M`I": "## KHÔNG GIAN THOẢI MÁI",
    "*Dung tích cốp 1.576L*": "*Dung tích cốp 1.576L*",
    "khi gập hàng ghế cuối": "khi gập hàng ghế cuối",
    "**Màn hình giải trí 12.9 inch**": "**Màn hình giải trí 12.9 inch**",
    "**Hệ thống lọc Combi 1.0***": "**Hệ thống lọc Combi 1.0***",
    "điều hoà không khí v lọc bụi mịn": "điều hoà không khí và lọc bụi mịn",
    "**Ghế ngồi với chất liệu da nhân tạo**": "**Ghế ngồi với chất liệu da nhân tạo**",
    "mềm mại, thân thiện môi trường": "mềm mại, thân thiện môi trường",
    "## KẾT NỐI THÔNG MINH": "## KẾT NỐI THÔNG MINH",
    "## CHO TRẢI NGHIỆM THÊM LIỀN MẠCH": "## CHO TRẢI NGHIỆM THÊM LIỀN MẠCH",
    "MU CƠ BẢN": "MÀU CƠ BẢN",
    "MU N´NG CAO": "MÀU NÂNG CAO",
    "Nu Mocha - Mocha Brown": "Nâu Mocha - Mocha Brown",
    "PLUS Be - Beige": "PLUS Be - Beige",
    "## DẢI MÀU ĐA DẠNG 3 màu nội thất": "## DẢI MÀU ĐA DẠNG 3 màu nội thất",
    # spec table
    "| KÍCH THUỆC | VF 6 ECO | VF 6 PLUS |": "| KÍCH THƯỚC | VF 6 ECO | VF 6 PLUS |",
    "| Dai x Rồng x Cao (mm) |": "| Dài x Rộng x Cao (mm) |",
    "| Chiêu dài cd sò (mm) |": "| Chiều dài cơ sở (mm) |",
    "| Khoảng sàng gâm xe không tái (mm) |": "| Khoảng sáng gầm xe không tải (mm) |",
    "| HÉ THONG TRUYÊN DÔNG |": "| HỆ THỐNG TRUYỀN ĐỘNG |",
    "| DÔNG CÓ |": "| ĐỘNG CƠ |",
    "| Cóng suát tái da (kW) |": "| Công suất tối đa (kW) |",
    "| Mó men xoăn cuc dai (Nm) |": "| Mô men xoắn cực đại (Nm) |",
    "| Quảng duống chay môt lân sac dây (km) (NEDC) |": "| Quãng đường chạy một lần sạc đầy (km) (NEDC) |",
    "| Dung luáng pin khá dung (kWh) |": "| Dung lượng pin khả dụng (kWh) |",
    "| Dày sac di dòng (kW) |": "| Dây sạc di động (kW) |",
    "| Bố sac tai nhác (kW) |": "| Bộ sạc tại nhà (kW) |",
    "| Thhör gian ngap pin nhanh nhật (phút) |": "| Thời gian nạp pin nhanh nhất (phút) |",
    "| THONG SÓ TRUYÊN DÔNG KHÁC |": "| THÔNG SỐ TRUYỀN ĐỘNG KHÁC |",
    "| Dán dòng |": "| Dẫn động |",
    "Câu trúc (FWD)": "Cầu trước (FWD)",
    "| Ché dô lái |": "| Chế độ lái |",
    "| KHUNG GAM |": "| KHUNG GẦM |",
    "| Kích thước la-zäng |": "| Kích thước la-zăng |",
    "| Hệ thống treo – trùc |": "| Hệ thống treo – trước |",
    "Đốc lp, MacPherson": "Độc lập, MacPherson",
    "| Hệ thống trea – sau |": "| Hệ thống treo – sau |",
    "| NGOAI THẾT |": "| NGOẠI THẤT |",
    "| DÉN NGOAI THẾT |": "| ĐÈN NGOẠI THẤT |",
    "| Dèn chiêu sang phla trước |": "| Đèn chiếu sáng phía trước |",
    "| Tư động bât/tát đến |": "| Tự động bật/tắt đèn |",
    "| Dèn chiêu sang ban ngày |": "| Đèn chiếu sáng ban ngày |",
    "| Tư động bât/tát ché dô chiêu xa |": "| Tự động bật/tắt chế độ chiếu xa |",
    "| Dèn hàu |": "| Đèn hậu |",
    "| Dèn nhnan điện thuong hiêu phla sau |": "| Đèn nhận diện thương hiệu phía sau |",
    "| NGOAI THẾT KHÁC |": "| NGOẠI THẤT KHÁC |",
    "| Guang chiêu hậu chinh diên, tích hgp den bao rê |": "| Gương chiếu hậu chỉnh điện, tích hợp đèn báo rẽ |",
    "| Guang chiêu hậu gập diên, sóy mát guǒng, tư động chính phla hànkhách khi lui |":
        "| Gương chiếu hậu gập điện, sấy mát gương, tự động chính phía hành khách khi lui |",
    "| Gat müa trước tư dòng |": "| Gạt mưa trước tự động |",
    "| Chia khoa thông minh |": "| Chìa khóa thông minh |",
    "| NОI THẾT & TIEN NGHI |": "| NỘI THẤT & TIỆN NGHI |",
    "| DIEU HOA KHÒNG KHÍ |": "| ĐIỀU HÒA KHÔNG KHÍ |",
    "| Hệ thông dieu hòa |": "| Hệ thống điều hòa |",
    "| Hệ thông loc bui min Combi 1.0 |": "| Hệ thống lọc bụi mịn Combi 1.0 |",
    "| Chúc nâng kiem soát chat luông không khi |": "| Chức năng kiểm soát chất lượng không khí |",
    "| Chúc nâng ion hòa không khi |": "| Chức năng ion hóa không khí |",
    "| MAN HINH VA KET NOI | VF 6 ECO | VF 6 PLUS |": "| MÀN HÌNH VÀ KẾT NỐI | VF 6 ECO | VF 6 PLUS |",
    "| Mán hinh hiên thi thẳng tín trén kinh lái (HUD) |": "| Màn hình hiển thị thông tin trên kính lái (HUD) |",
    "| Mán hinh giài tri cóm ung |": "| Màn hình giải trí cảm ứng |",
    "| Kết nối vại Android Auto và Apple CarPlay |": "| Kết nối với Android Auto và Apple CarPlay |",
    "| Hé thông liao |": "| Hệ thống loa |",
    "| TIEN NGHI |": "| TIỆN NGHI |",
    "| Glvé fái |": "| Ghế lái |",
    "Chính co 6 huáng": "Chỉnh cơ 6 hướng",
    "Chính diên 8 huáng": "Chỉnh điện 8 hướng",
    "| Ghế bọc da nhăn tao |": "| Ghế bọc da nhân tạo |",
    "| Kính của số chinh diên, lên/xuàng một cham |": "| Kính cửa sổ chỉnh điện, lên/xuống một chạm |",
    "| Phanth độ diên tù và ché dô tu dòng giú phanth |": "| Phanh đỗ điện tử và chế độ tự động giữ phanh |",
    "| AN TOA N & AN NINH |": "| AN TOÀN & AN NINH |",
    "| Sõ luông tui khi |": "| Số lượng túi khí |",
    "| Hê thông chóng bó công phanth ABS |": "| Hệ thống chống bó cứng phanh ABS |",
    "| Chúc nóng phần phối luc phanth diên tù EBD |": "| Chức năng phân phối lực phanh điện tử EBD |",
    "| Họ tra phanth khần cáp BA |": "| Hỗ trợ phanh khẩn cấp BA |",
    "| Hê thông cân bảng diên tù ESC |": "| Hệ thống cân bằng điện tử ESC |",
    "| Chúc nóng kiêm soát luc kéo TCS |": "| Chức năng kiểm soát lực kéo TCS |",
    "| Họ tra khôi hánh ngang dóc HSA |": "| Hỗ trợ khởi hành ngang dốc HSA |",
    "| Giám sát ap suát lap |": "| Giám sát áp suất lốp |",
    "| Họ tra tÚ dòng chuyen lán |": "| Hỗ trợ tự động chuyển làn |",
    "| Giâm sát hạnh trình |": "| Giám sát hành trình |",
    "| Nhân biét biên báo giao thông |": "| Nhận biết biển báo giao thông |",
    "| Dléu chinh tộc dô thông minh |": "| Điều chỉnh tốc độ thông minh |",
    "| Họ tra giú lán |": "| Hỗ trợ giữ làn |",
    "| Họ tra giú lán khrán cáp |": "| Hỗ trợ giữ làn khẩn cấp |",
    "| Cánh báo va char phia trước |": "| Cảnh báo va chạm phía trước |",
    "| Cánh báo diém mù |": "| Cảnh báo điểm mù |",
    "| Cánh báo phuáng tiên cát ngang phia sau |": "| Cảnh báo phương tiện cắt ngang phía sau |",
    "| Cánh báo mô cúa |": "| Cảnh báo mở cửa |",
    "| Họ tra dô xe phia sau |": "| Hỗ trợ đỗ xe phía sau |",
    "| Camera lüi |": "| Camera lùi |",
    "| Děn pha tù dòng |": "| Đèn pha tự động |",
    "| Cánh báo tái xẻ buôn ngú và mát táp trung |": "| Cảnh báo tài xế buồn ngủ và mất tập trung |",
    "| Cánh báo chồng trôm |": "| Cảnh báo chống trộm |",
    "| Tinh nâng khóa dông ca khi có trôm |": "| Tính năng khóa động cơ khi có trộm |",
    "| TÍNH NÂNG DIÉU KHIẾN THÔNG MINH | VF 6 ECO | VF 6 PLUS |": "| TÍNH NĂNG ĐIỀU KHIỂN THÔNG MINH | VF 6 ECO | VF 6 PLUS |",
    "| Lua chon ché dô vân hành dắc biên |": "| Lựa chọn chế độ vận hành đặc biệt |",
    "| Giái trí trúc tuyến |": "| Giải trí trực tuyến |",
    "| Trò chái |": "| Trò chơi |",
    "| Trịnh duyêt web |": "| Trình duyệt web |",
    "| Tu chán doán lối |": "| Tự chẩn đoán lỗi |",
    "| Cáp nhật ph án mêm tù xa |": "| Cập nhật phần mềm từ xa |",
    "| Trơ lý año |": "| Trợ lý ảo |",
    "| Úng dung dièn thoaqit |": "| Ứng dụng điện thoại |",
    # cuối
    "\\ TRAM SAC & NHÀ PHÂN PHÓI": "\\ TRẠM SẠC & NHÀ PHÂN PHỐI",
    "không ngày nghi": "không ngày nghỉ",
    "Hệ thống Showroom/Nhà phân phối/Xuồng": "Hệ thống Showroom/Nhà phân phối/Xưởng",
    "Dịch vú và trạm sác VinFast liên túc mổ ròng": "Dịch vụ và trạm sạc VinFast liên tục mở rộng",
    "và không ngùng phát trién trên kháp cả": "và không ngừng phát triển trên khắp cả",
    "nuóc, nhàm tội uu hòa trài nghiêm của khách": "nước, nhằm tối ưu hóa trải nghiệm của khách",
    "hàng, tùng buộc kiên tạo nèn tuóng lai": "hàng, từng bước kiến tạo nên tương lai",
    '"xanh" tải Viêt Nam.': '"xanh" tại Việt Nam.',
    "Báo hành xe mói 7 năm": "Bảo hành xe mới 7 năm",
    "hoặc 160.000km": "hoặc 160.000km",
    "Báo hành pin 8 năm": "Bảo hành pin 8 năm",
    "Dịch vú hậu mãi xuất sác": "Dịch vụ hậu mãi xuất sắc",
    "Sứa chữ lưu đông": "Sửa chữa lưu động",
    "Cúu hộ 24/7 trong suất": "Cứu hộ 24/7 trong suốt",
    "thời gian bào hành": "thời gian bảo hành",
    "Cam kết cung cấp": "Cam kết cung cấp",
    "phủ tùng trong 24 gið": "phụ tùng trong 24 giờ",
    "## VỚI GIẢI PHÁP SẠC DI ĐỘNG VINFAST": "## VỚI GIẢI PHÁP SẠC DI ĐỘNG VINFAST",
    "*Nhằm giúp người dùng chủ động kế hoạch di chuyển, tiết kiệm thời gian v chi*":
        "*Nhằm giúp người dùng chủ động kế hoạch di chuyển, tiết kiệm thời gian và chi phí*",
    "*ph, VinFast cung cấp giải phÆp sạc di động theo xe đáp ứng những tiêu chuẩn*":
        "*phí, VinFast cung cấp giải pháp sạc di động theo xe đáp ứng những tiêu chuẩn*",
    "## 01": "## 01",
    "Cắm trực tiếp phch chắm của bộ sạc vo ổ": "Cắm trực tiếp phích cắm của bộ sạc vào ổ",
    "điện loại E/F v chờ đến khi đèn LED mu xanh": "điện loại E/F và chờ đến khi đèn LED màu xanh",
    "dương v xanh lÆ cy sÆng.": "dương và xanh lá cây sáng.",
    ## 02
    "Trong quÆ trnh sạc, nếu cần tạm dừng chu trnh": "Trong quá trình sạc, nếu cần tạm dừng chu trình",
    "sạc, có 3 cÆch như sau: nhấn nút dừng sạc trŒn": "sạc, có 3 cách như sau: nhấn nút dừng sạc trên",
    "màn hình sạc của xe, rœt phch cắm điện hoặc": "màn hình sạc của xe, rút phích cắm điện hoặc",
    "## Cắm súng sạc vào vị trí sạc trên xe.": "## Cắm súng sạc vào vị trí sạc trên xe.",
    "Bộ sạc tự động sạc cho xe khi đèn LED đỏ": "Bộ sạc tự động sạc cho xe khi đèn LED đỏ",
    "sáng, đèn LED xanh và đèn LED vng": "sáng, đèn LED xanh và đèn LED vàng",
    "nhÆy 1 lần.": "nháy 1 lần.",
    "## Muôn yếu tố ĐỒNG ĐIỆU": "## Muôn yếu tố ĐỒNG ĐIỆU",
}

_VF7 = {
    # boilerplate / footer
    "Hinh anh mang tinh minh hoa, su dung hinh anh của sán phạm trong giài doan tiên thưởng mai. Các thavg tin sân phạm có thể thay đổi mô khương cán bdo truoc":
        "Hình ảnh mang tính minh họa, sử dụng hình ảnh của sản phẩm trong giai đoạn tiền thương mại. Các thông tin sản phẩm có thể thay đổi mà không cần báo trước",
    # summary table (giá/spec trước)
    "| Công suất cước đài | 130 kW/174 m² lúc |  | 260 kW/349 m² lúc |":
        "| Công suất tối đa | 130 kW/174 mã lực |  | 260 kW/349 mã lực |",
    "| Mô men xoán tôi da | 250 Nm |  | 500 Nm |": "| Mô men xoắn tối đa | 250 Nm |  | 500 Nm |",
    "Hệ{dân}{dòng}": "Hệ dẫn động",
    "| Quảng{dυong}{di}{chuyén}/1{lần}{sqc}{đáy} | 430 km |  | 496 km |":
        "| Quãng đường di chuyển/1 lần sạc đầy | 430 km |  | 496 km |",
    "| Dung luçng pin khà{dung} | 59,6 kWh |  | 75,3 kWh |": "| Dung lượng pin khả dụng | 59,6 kWh |  | 75,3 kWh |",
    "| Tăng{Tóc}{0}-100km/h} | 10 s |  | 5,8 s |": "| Tăng tốc 0-100 km/h | 10 s |  | 5,8 s |",
    "| Giá{niêm}{yét}{không}{góm}{pin} | 850 triều{dòng} |  | 999 triều{dòng} |":
        "| Giá niêm yết không gồm pin | 850 triệu đồng |  | 999 triệu đồng |",
    "| Giá{niêm}{yет}{bao}{góm}{pin} | 999 triều{dòng} |  | 1,199 triều{dòng} |":
        "| Giá niêm yết bao gồm pin | 999 triệu đồng |  | 1,199 triệu đồng |",
    "| Tüy{chợ}{trần}{kính} |  |  | 25 triều{dòng} |": "| Tùy chọn trần kính |  |  | 25 triệu đồng |",
    "| Chi phí sqc pin |": "| Chi phí sạc pin |",
    "| NÓ THAT & TEN NGHI |": "| NỘI THẤT & TIỆN NGHI |",
    "Bảng thông số (KÍCH THƯỚC & TẢI TRỌNG)":
        "Bảng thông số (KÍCH THƯỚC & TẢI TRỌNG)",
    # spec table — KÍCH THƯỚC
    "| Công khoản cach mm | 2,840 | 2,840 |": "| Chiều dài cơ sở (mm) | 2,840 | 2,840 |",
    "| Dai rẻng cao (mm) |": "| Dài x Rộng x Cao (mm) |",
    "| Khód sàng gам xe không tái (mm) | 190 | 190 |": "| Khoảng sáng gầm xe không tải (mm) | 190 | 190 |",
    "| Dung tích khoaeng chula hanh y (L)- Cô ghế cuudi | 403 | 403 |":
        "| Dung tích khoang chứa hành lý (L) - Có ghế cuối | 403 | 403 |",
    "| Dung tích khoaeng chula hanh y (L)- Gáp ghế cuudi | 1,275 | 1,275 |":
        "| Dung tích khoang chứa hành lý (L) - Gập ghế cuối | 1,275 | 1,275 |",
    "| Dung kinh quay dù tâ thêu m) | 11.3 | 11.3 |": "| Bán kính quay đầu tối thiểu (m) | 11.3 | 11.3 |",
    "| Trung kương khiong tái (kg) | 2.085 (muc tuku) | 2.205 (muc tuku) |":
        "| Trọng lượng không tải (kg) | 2.085 (mục tiêu) | 2.205 (mục tiêu) |",
    "| Tạ tróng (kg) | 375 | 375 |": "| Tải trọng (kg) | 375 | 375 |",
    "| Tạ tróng hạnh lv nxc xe (kg) | 75 | 75 |": "| Tải trọng hành lý nóc xe (kg) | 75 | 75 |",
    # HỆ THỐNG TRUYỀN ĐỘNG
    "| HÉ THANG TRUVEN DONG |": "| HỆ THỐNG TRUYỀN ĐỘNG |",
    "| BẰNG GIỘ |": "| ĐỘNG CƠ |",
    "| Đăng cd | 1 Đăng cd | 2 Đăng cd |": "| Động cơ | 1 Động cơ | 2 Động cơ |",
    "| Cộng suài tái da (kW) | 130 | 150 (OTP 260) |": "| Công suất tối đa (kW) | 130 | 150 (OTP 260) |",
    "| Mổ men xđàn cuc tái (km) | 250 | 310 (OTP 500) |": "| Mô men xoắn cực đại (Nm) | 250 | 310 (OTP 500) |",
    "| Tác dị tái km/h | 150 | 175 |": "| Tốc độ tối đa (km/h) | 150 | 175 |",
    "| Trang tác dị 100 km/h (s) | 10-115 | 9.55 (OTP 5.8) |": "| Tăng tốc 0-100 km/h (s) | 10-11.5 | 9.55 (OTP 5.8) |",
    "| Múc đèn ndingtuição thu (Whkm) | 118.2 | 211 |": "| Mức tiêu thụ năng lượng (Wh/km) | 118.2 | 211 |",
    # PIN
    "| Loại pin | Gолium LFP (PB pin 2) | CATL (PB pin 1)/ New Golium (PB pin 3) tháng 9/2025 |":
        "| Loại pin | Golium LFP (PB pin 2) | CATL (PB pin 1)/ New Golium (PB pin 3) tháng 9/2025 |",
    "| Dung luận pin (kWh) – thái dung | 59.6 | 75.3 (ODO 94%) |":
        "| Dung lượng pin (kWh) – khả dụng | 59.6 | 75.3 (ODC 94%) |",
    "| Chủ động chạy chayı mtj tái sap dý (km) – tiêu chuán NEDCC\\*\\*\\* | 430 | 430 |":
        "| Quãng đường chạy một lần sạc đầy (km) – tiêu chuẩn NEDC*** | 430 | 430 |",
    "| Chủ động trans sac cóng công |": "| Chủ động trạm sạc công cộng |",
    "| Dày sac di đàng |": "| Dây sạc di động |",
    "| Bố sac tịnh nhã |": "| Bộ sạc tại nhà |",
    "| Công sau sac cát da (kW) |": "| Công suất sạc cắt da (kW) |",
    "| Thính năng sac chanthào sieu rhanh |": "| Tính năng sạc chậm siêu nhanh |",
    "| Hệ thống phanth tải sinh |": "| Hệ thống phanh tái sinh |",
    "| Thị gia napan pin binh thưởng (gá) |": "| Thời gian nạp pin bình thường (giờ) |",
    "| Thị gia napan pin binh th修士 (ph汁) |": "| Thời gian nạp pin nhanh (phút) |",
    # THÔNG SỐ TRUYỀN ĐỘNG KHÁC
    "| THÍCH TRUVEN DONG KHAC |": "| THÔNG SỐ TRUYỀN ĐỘNG KHÁC |",
    "| Dân dòng | FW/D/Cu được | FW/D/Cu được - OTP - AWD/2 c舟 toàn thi |":
        "| Dẫn động | FWD/Cầu trước | FWD/Cầu trước - OTP - AWD/2 cầu toàn thời gian |",
    "| Chơn che dĩ bã | EcoNormal/Sport | GIan |": "| Chọn chế độ lái | Eco/Normal/Sport | - |",
    "| Kiêm sót hánh tình co bã | Có | EcoNormal/Sport |": "| Kiểm soát hành trình cơ bản | Có | Eco/Normal/Sport |",
    "| Giao tốc dĩ\\* | Có | - |": "| Giới hạn tốc độ* | Có | - |",
    # KHUNG GẦM
    "| GAM XGC |": "| GIẢM XÓC |",
    "| Hệ thống tre - trudc | Dóc láp, MacPherson |": "| Hệ thống treo - trước | Độc lập, MacPherson |",
    "| Hệ thống tre - sou | Thành düy hưng dã dém |": "| Hệ thống treo - sau | Thanh xoắn hướng đa điểm |",
    "| Phân trúc | Día | Día |": "| Phanh trước | Đĩa | Đĩa |",
    "| Phân sau | Día | Día |": "| Phanh sau | Đĩa | Đĩa |",
    "| VANH VÀ LÖP BАН XE |": "| VÀNH VÀ LỐP BÁNH XE |",
    "| Kích thước la-zéd\\* | 19 inch | 20 inch (OPT 21 inch tháng 1/2025) |":
        "| Kích thước la-zăng* | 19 inch | 20 inch (OPT 21 inch tháng 1/2025) |",
    "| Loai la-zéd | Háp kim | Háp kim |": "| Loại la-zăng | Hợp kim | Hợp kim |",
    "| Láp du phong | Athersales | Athersales |": "| Lốp dự phòng | Aftersales | Aftersales |",
    "| Bố va lóp | Athersales | Athersales |": "| Bộ vành lốp | Aftersales | Aftersales |",
    "| NHƠNG GAM KHAC |": "| KHUNG GẦM KHÁC |",
    "| Từ bù dữ | Trq luc dữ | Trq luc dữ |": "| Trợ lực lái | Trợ lực điện | Trợ lực điện |",
    # NGOẠI THẤT (đèn pha)
    "| NGOAI THAT |": "| NGOẠI THẤT |",
    "| BēN PHIA |": "| ĐÈN PHA |",
    "| Dên phia | LED | LED |": "| Đèn pha | LED | LED |",
    "| Dên phua tu dĩ bã/bã | Có | Có |": "| Đèn pha tự động bật/tắt | Có | Có |",
    "| Dên khún gác chú phụ thông minh | - | Có (tu dêng) |": "| Đèn khúc gác chiếu phụ thông minh | - | Có (tự động) |",
    "| NGOAI THAT KHAC |": "| NGOẠI THẤT KHÁC |",
    "| Dên chiều sảng ban ngüy | LED | LED |": "| Đèn chiếu sáng ban ngày | LED | LED |",
    "| Dên huu | LED | LED |": "| Đèn hậu | LED | LED |",
    "| Dên indian thuurng hieu phlu trdc | Có | Có |": "| Đèn nhận diện thương hiệu phía trước | Có | Có |",
    "| Dên nhín dieur thuurng hieu phlu sau | Có | Có |": "| Đèn nhận diện thương hiệu phía sau | Có | Có |",
    "| BỊ CHI |": "| GƯƠNG CHIẾU |",
    "| Guing chieu huar chinh diên | Có | Có |": "| Gương chiếu hậu chỉnh điện | Có | Có |",
    "| Guing chieu huar gập diên | Có | Có |": "| Gương chiếu hậu gập điện | Có | Có |",
    "| Guing chieu huar bào rê | Có | Có |": "| Gương chiếu hậu báo rẽ | Có | Có |",
    "| Guing chieu huar sòy má quang | Có | Có |": "| Gương chiếu hậu sấy mát gương | Có | Có |",
    "| Guing chieu huar tù dейств hiếu khi lái | OFT | OFT |": "| Gương chiếu hậu tự động hiệu chỉnh khi lái | OPT | OPT |",
    "| Guing chieu huar chhing chhai tu dạng | - | Có |": "| Gương chiếu hậu chống chói tự động | - | Có |",
    "| Guing chieu huar nhíd vì trì | Có | Có |": "| Gương chiếu hậu nhớ vị trí | Có | Có |",
    "| CUA |": "| CỬA |",
    "| Dife chinh cp sau | Chinh cd | Chinh dien |": "| Điều chỉnh cốp sau | Chỉnh cơ | Chỉnh điện |",
    "| Khinh chá gí, cháng tia UV | CÓ (Cach dm nhieu ldp) |": "| Kính chắn gió, chống tia UV | CÓ (Cách âm nhiều lớp) |",
    "| Gat mu truc đuc tù dòng | CÓ | CÓ |": "| Gạt mưa trước tự động | CÓ | CÓ |",
    "| Gat mua sau | CÓ | CÓ |": "| Gạt mưa sau | CÓ | CÓ |",
    "| Thanh trung trì toc xe | Afterales | Afterales |": "| Thanh trung chống lật xe | Aftersales | Aftersales |",
    "| Tân bái wú dhu thán xe | OTP | CÓ |": "| Tấm bảo vệ dưới thân xe | OTP | CÓ |",
    # NỘI THẤT
    "| GHE TOAN XE |": "| GHẾ TOÀN XE |",
    "| Số chỗ ngôn | 5 | 5 |": "| Số chỗ ngồi | 5 | 5 |",
    "| Chhai bóc ghé | Da nhàn tao | Da nhàn tao |": "| Chất liệu bọc ghế | Da nhân tạo | Da nhân tạo |",
    "| GHE KI |": "| GHẾ LÁI |",
    "| Ghe lai - dile chinh huding | Chinh dèn 8 hudung | Chinh dèn 8 hudung |":
        "| Ghế lái - điều chỉnh hướng | Chỉnh điện 8 hướng | Chỉnh điện 8 hướng |",
    "| Tua dûh ghe lai | Chinh cα cao tháp | Chinh cα cao tháp |": "| Tựa đầu ghế lái | Chỉnh cơ cao thấp | Chỉnh cơ cao thấp |",
    "| BIE PHU |": "| GHẾ PHỤ |",
    "| Ghe phu - dile chinh huding | Chinh cα 4 hudung | Chinh dèn 6 hudung |":
        "| Ghế phụ - điều chỉnh hướng | Chỉnh cơ 4 hướng | Chỉnh điện 6 hướng |",
    "| Tua dûh ghe phu | Chinh cα cao tháp | Chinh cα cao tháp |": "| Tựa đầu ghế phụ | Chỉnh cơ cao thấp | Chỉnh cơ cao thấp |",
    "| GHE HANG 2 |": "| GHẾ HÀNG 2 |",
    "| Hang ghe thu 2 dile chinh gap tù lê | 60:40 | 60:40 |": "| Hàng ghế thứ 2 điều chỉnh gập tỷ lệ | 60:40 | 60:40 |",
    "| Bē gac tay hong ghe 2 | CÓ, tích hop hoc để các |": "| Bệ gác tay hàng ghế 2 | CÓ, tích hợp hộc để các |",
    "| VO LANG |": "| VÔ LĂNG |",
    "| Diffe chinh võ lâng | Chinh cα 4 hudung | Chinh cα 4 hudung |": "| Điều chỉnh vô lăng | Chỉnh cơ 4 hướng | Chỉnh cơ 4 hướng |",
    "| Bac võ lâng | Boc da | Boc da |": "| Bọc vô lăng | Bọc da | Bọc da |",
    "| BIE HOA KHONG KHI |": "| ĐIỀU HÒA KHÔNG KHÍ |",
    "| He hndg dèu hoa | Tu dòng, 2 vàng |": "| Hệ thống điều hòa | Tự động, 2 vùng |",
    "| Chịng kîng bém soát chải kuring khòng khi |": "| Chức năng kiểm soát chất lượng không khí |",
    "| Lac khring kah仁 | BuìPhin hao | Combi PM 1.0 |": "| Lọc không khí Cabin | Bụi, phấn hoa | Combi PM 1.0 |",
    "| Chịng nóng lam tan suiting tian bäng | CÓ | CÓ |": "| Chức năng làm tan sương/tan băng | CÓ | CÓ |",
    "| MANYTHING BEGE FUTURE TEN NGHI |": "| MÀN HÌNH, KẾT NỐI, GIẢI TRÍ, TIỆN NGHI |",
    "| Män hinh g髵 trì cam dng | 12.9 inch |": "| Màn hình giải trí cảm ứng | 12.9 inch |",
    "| Män hinh hiên thi HUD | OPT | CÓ |": "| Màn hình hiển thị HUD | OPT | CÓ |",
    "| Công kînt USB loai A hinge ghe lái | 2 | 2 |": "| Cổng kết nối USB loại A hàng ghế lái | 2 | 2 |",
    "| Công kînt USB loai A hinge ghe thui 2 | - | 2 |": "| Cổng kết nối USB loại A hàng ghế thứ 2 | - | 2 |",
    "| Công kînt USB loai C | - | 1 |": "| Cổng kết nối USB loại C | - | 1 |",
    "| Công séc 12V hung trúc | CÓ | CÓ |": "| Cổng sạc 12V hàng trước | CÓ | CÓ |",
    "| Sac khring day | - | CÓ |": "| Sạc không dây | - | CÓ |",
    "| Kết nôi Wi-Fi | CÓ | CÓ |": "| Kết nối Wi-Fi | CÓ | CÓ |",
    "| Kết nối Bluetooth | CÓ | CÓ |": "| Kết nối Bluetooth | CÓ | CÓ |",
    "| BIE DURS COW |": "| HỆ THỐNG LOA |",
    "| He thng loa | 6 | 8 |": "| Hệ thống loa | 6 | 8 |",
    "| HE THONG ĐEN NỘ THAT |": "| HỆ THỐNG ĐÈN NỘI THẤT |",
    "| NÓ THAT & TEN NGHI KHÁC |": "| NỘI THẤT & TIỆN NGHI KHÁC |",
    "| Phanth tay | Điện tuž | Điện tuž |": "| Phanh tay | Điện tử | Điện tử |",
    # AN TOÀN
    "| NÎT VOAN & NINHA |": "| AN TOÀN & AN NINH |",
    "| Lake dòng gi an toon™ | - | ASEAN NCAP 5\\* |": "| Đánh giá an toàn™ | - | ASEAN NCAP 5* |",
    "| He thng ch髻 bo cáng phanth ABS | CÓ | CÓ |": "| Hệ thống chống bó cứng phanh ABS | CÓ | CÓ |",
    "| Chịng nóng phanth luoc phanth tù EBD | CÓ | CÓ |": "| Chức năng phân phối lực phanh điện tử EBD | CÓ | CÓ |",
    "| Hồ trph phanth khản cáp BA | CÓ | CÓ |": "| Hỗ trợ phanh khẩn cấp BA | CÓ | CÓ |",
    "| He thng ch髻 bố bàng tù ESC | CÓ | CÓ |": "| Hệ thống cân bằng điện tử ESC | CÓ | CÓ |",
    "| Chịng nóng侮寿 lut kex TCS | CÓ | CÓ |": "| Chức năng kiểm soát lực kéo TCS | CÓ | CÓ |",
    "| Hồ kínhnh ngang dς HSA | CÓ | CÓ |": "| Hỗ trợ khởi hành ngang dốc HSA | CÓ | CÓ |",
    "| Chịng nông chồng lột ROM | CÓ | CÓ |": "| Chức năng chống lật ROM | CÓ | CÓ |",
    "| Dên bà phanth khин cáp ESS | CÓ | CÓ |": "| Đèn báo phanh khẩn cấp ESS | CÓ | CÓ |",
    "| Gden sơ自助 loa | dTPMS | dTPMS |": "| Giám sát áp suất lốp | dTPMS | dTPMS |",
    "| Khao caa xe tu dòng khi xe di chuyen | C6 | C6 |": "| Khóa cửa xe tự động khi xe di chuyển | Có | Có |",
    "| Công dai khdn cdp ghé trúc | C6 | C6 |": "| Căng đai khẩn cấp ghế trước | Có | Có |",
    "| Công dai khdn cdp ghé hang 2 | C6 | C6 |": "| Căng đai khẩn cấp ghế hàng 2 | Có | Có |",
    "| Xác định trình trang hanhkhách - ghé trúc | C6 | C6 |": "| Xác định tình trạng hành khách - ghế trước | Có | Có |",
    "| Móc cích nghe trém em ISOFIX, hang ghé thù 2 | C6 | C6 |": "| Móc cố định ghế trẻ em ISOFIX, hàng ghế thứ 2 | Có | Có |",
    "| THE NONG BUI TRÍ | 4 | 7 |": "| HỆ THỐNG TÚI KHÍ | 4 | 7 |",
    "| Tui khi trUDE tã va hanh khach phla trúc | 2 | 2 |": "| Túi khí trước lái và hành khách phía trước | 2 | 2 |",
    "| Tui khi rêm | - | 2 |": "| Túi khí rèm | - | 2 |",
    "| Tui khi bèn häng hung ghé trúc | 2 | 2 |": "| Túi khí bên hông hàng ghế trước | 2 | 2 |",
    "| Tui khi bào vê chán hung ghé trúc | - | 1 (philo nguôi lái) |": "| Túi khí bảo vệ chân hàng ghế trước | - | 1 (phía người lái) |",
    "| CÁC TINH NANG ADAS | 4 | 2.2 |": "| CÁC TÍNH NĂNG ADAS | 4 | 2.2 |",
    "| TRỌ LAI TRÉN CAO TOC |": "| TRỢ LÁI TRÊN CAO TỐC |",
    "| Guing chieu huar tù deйctb hiếu khi lái | OFT | OFT |":
        "| Gương chiếu hậu tự động hiệu chỉnh khi lái | OPT | OPT |",
}

_VF8 = {
    # boilerplate
    "Hình anh mang tinh chat minh hoa và có thể khác so võt xe thuc tê. Tính păng, dắc diêm, thông số ký thuát có the thay doi mà không thông báo truác":
        "Hình ảnh mang tính chất minh họa và có thể khác so với xe thực tế. Tính năng, đặc điểm, thông số kỹ thuật có thể thay đổi mà không thông báo trước",
    "Hình anh mang tính chât minh hòa và có thể khác so với xe thực tế. Tính nâng, dắc diêm, thông số ký thuột có thể thay đổi mà không thông báo trước.":
        "Hình ảnh mang tính chất minh họa và có thể khác so với xe thực tế. Tính năng, đặc điểm, thông số kỹ thuật có thể thay đổi mà không thông báo trước.",
    "Hinh anh mang tinh chat minh hoa và có thể khác so với xe thực tế. Tính nâng, dắc diêm, thông số ký thuật có thể thay đổi mà không thông báo trước.":
        "Hình ảnh mang tính chất minh họa và có thể khác so với xe thực tế. Tính năng, đặc điểm, thông số kỹ thuật có thể thay đổi mà không thông báo trước.",
    "ĐẶT CÓC NGAY": "ĐẶT CỌC NGAY",
    "SỨ LỬA CHỐN XÚNG TÂM\nTRONG PHÂN KHÚC\nSUV 5 CHÔ": "SỨ LỬA CHỌN XỨNG TẦM\nTRONG PHÂN KHÚC\nSUV 5 CHỖ",
    # exterior/prose
    "GUỐNG CHIÉU HÀU": "GƯƠNG CHIẾU HẬU",
    "ĐÈN HÂU": "ĐÈN HẬU",
    "Chiêu dài ca sá (mm)": "Chiều dài cơ sở (mm)",
    "Dai x Róng x Cao (mm)": "Dài x Rộng x Cao (mm)",
    "Khód sông gám xe không tái (mm)": "Khoảng sáng gầm xe không tải (mm)",
    # spec table — ngoại thất
    "| Dèn phoa | LED, Tu dừng bột/dát, dieu chinh gốc chu島 thông minh |":
        "| Đèn pha | LED, Tự động bật/tắt, điều chỉnh góc chiếu thông minh |",
    "| Dèn chiều sông banNgby | LED | LED |": "| Đèn chiếu sáng ban ngày | LED | LED |",
    "| Dèn hulu | LED | LED |": "| Đèn hậu | LED | LED |",
    "| Guang chihu hulu | Chinh dien, góp diên |": "| Gương chiếu hậu | Chỉnh điện, gập điện |",
    "| Kiêu ciao số | Chinh dien, lín/uudng |": "| Kính cửa sổ | Chỉnh điện, lên/xuống |",
    "| Kinh chén góc | Chhing ta LV |": "| Kính chắn gió | Chống tia UV |",
    "| Gat muu trusc | Tu dòng | Tu dòng |": "| Gạt mưa trước | Tự động | Tự động |",
    "| Tâm bão vẽ dudi thần xe | Có | Có |": "| Tấm bảo vệ dưới thân xe | Có | Có |",
    # spec table — HỆ TRUYỀN ĐỘNG
    "| HÉ THONG TRUVÉN DONG |": "| HỆ THỐNG TRUYỀN ĐỘNG |",
    "| DŒNG CO |": "| ĐỘNG CƠ |",
    "| Hê đàm dòng | FWD/Cdu trước | AWD/2 cùu toán thải gian |":
        "| Hệ dẫn động | FWD/Cầu trước | AWD/2 cầu toàn thời gian |",
    "| Cộng sudtú dôi (kW/Hp) | 150/201 | 300/402 |": "| Công suất tối đa (kW/Hp) | 150/201 | 300/402 |",
    "| Mó men xoen cúc dû (Nm) | 310 | 620 |": "| Mô men xoắn cực đại (Nm) | 310 | 620 |",
    "| Tảng toc 0-100Km/h (s) | 11.8 | 5.58 |": "| Tăng tốc 0-100 km/h (s) | 11.8 | 5.58 |",
    # PIN
    "| Dung liong pin kinh dung (kWh) | 87.7 | 87.7 |": "| Dung lượng pin khả dụng (kWh) | 87.7 | 87.7 |",
    "| Quảng dương chay mát lân sac (dkm) | 562 (NEDC) | 457 (WLTP) |":
        "| Quãng đường chạy một lần sạc đầy (km) | 562 (NEDC) | 457 (WLTP) |",
    "| Thủ gian nop pin rhnhh nhật (tú 10 đến 70%) (phút) | 31 | 31 |":
        "| Thời gian nạp pin nhanh nhất (từ 10 đến 70%) (phút) | 31 | 31 |",
    # THÔNG SỐ TRUYỀN ĐỘNG KHÁC
    "| THÔNG SÓ TRUVÉN DONG KHAC |": "| THÔNG SỐ TRUYỀN ĐỘNG KHÁC |",
    "| Chon chữ dà lái | EcoNormal/Sport | EcoNormal/Sport |": "| Chọn chế độ lái | Eco/Normal/Sport | Eco/Normal/Sport |",
    "| Suid pin cao thế | Có | Có |": "| Sưởi pin cao thế | Có | Có |",
    # KHUNG GẦM
    "| Hê thông treo – trữdc |": "| Hệ thống treo - trước |",
    "| Hê thông treo – sou |": "| Hệ thống treo - sau |",
    "| Hê thông phanth trudio/sau | Dia thông guí/Dia thông gío |":
        "| Hệ thống phanh trước/sau | Đĩa thông gió/Đĩa thông gió |",
    "| Loral lu chng | Háp km 120ch | Háp km 20ch |": "| Loại la-zăng | Hợp kim 19/20 inch | Hợp kim 20 inch |",
    "| Trsat luc lái | Trsat luc dên | Trsat luc dên |": "| Trợ lực lái | Trợ lực điện | Trợ lực điện |",
    # NỘI THẤT
    "| NÓI THÁT &amp; TÉN NGHI |": "| NỘI THẤT & TIỆN NGHI |",
    "| Só chỗ ngôi | 5 | 5 |": "| Số chỗ ngồi | 5 | 5 |",
    "| Chát lẻ buoc ghé | Gia da | Danh nhân tao |": "| Chất liệu bọc ghế | Giả da | Da nhân tạo |",
    "| GHé lái | Chinh diện 6 hútng |": "| Ghế lái | Chỉnh điện 6 hướng |",
    "| GHé phu | Chinh diện 6 hútng |": "| Ghế phụ | Chỉnh điện 6 hướng |",
    "| Hàng ghé thu hai | Chinh diện 2 hútng, ty lê gap 60:40 |": "| Hàng ghế thứ hai | Chỉnh điện 2 hướng, tỷ lệ gập 60:40 |",
    "| Loai vó láng | Boc da, dạng D-cut |": "| Loại vô lăng | Bọc da, dạng D-cut |",
    "| Hè không dieu hoa | Tu dòng, 2 vung |": "| Hệ thống điều hòa | Tự động, 2 vùng |",
    "| Loc không khi Cabin | Combi 1.0 | Combi 1.0 |": "| Lọc không khí Cabin | Combi 1.0 | Combi 1.0 |",
    "| Man hinh gải tri Cam ung | 15.6 inch | 15.6 inch |": "| Màn hình giải trí cảm ứng | 15.6 inch | 15.6 inch |",
    "| Man hinh hien thi HUD | Có | Có |": "| Màn hình hiển thị HUD | Có | Có |",
    "| Cóng kết nú USR loai A | Hàng ghé trUTC 2 |": "| Cổng kết nối USB loại A | Hàng ghế trước 2 |",
    "| Cóng kết nú USR loai C | Hàng ghé trUTC 2 |": "| Cổng kết nối USB loại C | Hàng ghế trước 2 |",
    "| Kết nú WiFi | Có | Có |": "| Kết nối WiFi | Có | Có |",
    "| Kết nú Bluetooth | Có | Có |": "| Kết nối Bluetooth | Có | Có |",
    "| Hè thông loa | 8 | 10 |": "| Hệ thống loa | 8 | 10 |",
    "| Loa tram | Không | 1 |": "| Loa trầm | Không | 1 |",
    "| Guong chữ hua trong xe | Chống choi tu dòng |": "| Gương chiếu hậu trong xe | Chống chói tự động |",
    # AN TOÀN
    "| AN TOA NAM AN WIN |": "| AN TOÀN & AN NINH |",
    "| Mě không chhing bổ sung phanth ABS | Có | Có |": "| Hệ thống chống bó cứng phanh ABS | Có | Có |",
    "| Chuar nông phanth phoj luc phanth diên to EBD | Có | Có |": "| Chức năng phân phối lực phanh điện tử EBD | Có | Có |",
    "| Hồ trop phanth khép BA | Có | Có |": "| Hỗ trợ phanh khẩn cấp BA | Có | Có |",
    "| Hồ thông can bảng dên tu ESC | Có | Có |": "| Hệ thống cân bằng điện tử ESC | Có | Có |",
    "| Chuc nông khép soi luc keo TCS | Có | Có |": "| Chức năng kiểm soát lực kéo TCS | Có | Có |",
    "| Hồ tro khép hánh ngāng dác HSA | Có | Có |": "| Hỗ trợ khởi hành ngang dốc HSA | Có | Có |",
    "| Chuc nông chồng lát ROM | Có | Có |": "| Chức năng chống lật ROM | Có | Có |",
    "| Đến báo phanth khép cáp ESS | Có | Có |": "| Đèn báo phanh khẩn cấp ESS | Có | Có |",
    "| Güm sál ap suít fő | dTPMS | dTPMS |": "| Giám sát áp suất lốp | dTPMS | dTPMS |",
    "| Phàn cáo an dòng khi xe di chuyén | Có | Có |": "| Khóa cửa tự động khi xe di chuyển | Có | Có |",
    "| Clang dài khadelph | Có | Có |": "| Căng đai khẩn cấp | Có | Có |",
    "| Móc có định ghé trUTC em ISOFX, hang ghé thư 2 | Có | Có |": "| Móc cố định ghế trẻ em ISOFIX, hàng ghế thứ 2 | Có | Có |",
    "| Canh biao day an toan hangu trước và häng 2 | Có | Có |": "| Cảnh báo dây an toàn hàng trước và hàng 2 | Có | Có |",
    "| HE THONG TU KHI | 10 | 11 |": "| HỆ THỐNG TÚI KHÍ | 10 | 11 |",
    "| Tui khi truc tâ la vanh khách phia truoc | 2 | 2 |": "| Túi khí trước lái và hành khách phía trước | 2 | 2 |",
    "| Tui khi rem | 2 | 2 |": "| Túi khí rèm | 2 | 2 |",
    "| Tui khi ben hong hang ghé truoc | 2 | 2 |": "| Túi khí bên hông hàng ghế trước | 2 | 2 |",
    "| Tui khi ben hong hang ghé sau | 2 | 2 |": "| Túi khí bên hông hàng ghế sau | 2 | 2 |",
    "| Tui khi biao ve chín hang ghé truoc | 2 | 2 |": "| Túi khí bảo vệ chân hàng ghế trước | 2 | 2 |",
    "| Tui khi trung kim hang ghé truoc | 0 | 1 |": "| Túi khí trung tâm hàng ghế trước | 0 | 1 |",
    # ADAS
    "| HE THONG TAO TRONG DI LAI HANG CAO ADAS |": "| HỆ THỐNG HỖ TRỢ LÁI NÂNG CAO ADAS |",
    "| TRỌ kai thẻ cao dốc |": "| TRỢ LÁI TRÊN CAO TỐC |",
    "| Hồ đài chuyến khi un tắc | Không | Có |": "| Hỗ trợ di chuyển khi ùn tắc | Không | Có |",
    "| Hồ lài trên duồng cao tác | Không | Có |": "| Hỗ trợ lái trên đường cao tốc | Không | Có |",
    "| TRO LAN |": "| TRỢ LÀN |",
    "| Căn biao chích lân | Không | Có |": "| Cảnh báo chệch làn | Không | Có |",
    "| Hồ tro gũ lân | Không | Có |": "| Hỗ trợ giữ làn | Không | Có |",
    "| Kiem soát di giza lân | Không | Có |": "| Kiểm soát di giữa làn | Không | Có |",
    "| HÓ TRỌ HANN TRINH |": "| HỖ TRỢ HÀNH TRÌNH |",
    "| Kiem soaat hinh trinh | Ga tu dòng co bàn | Ga tu dòng thick ung |":
        "| Kiểm soát hành trình | Ga tự động cơ bản | Ga tự động thích ứng |",
    "| Điều chính toc, độ thông minh | Không | Có |": "| Điều chỉnh tốc độ thông minh | Không | Có |",
    "| Nhận biết biên biao giao thông | Không | Có |": "| Nhận biết biển báo giao thông | Không | Có |",
    "| CAMH KIO VE CHAM |": "| CẢNH BÁO VA CHẠM |",
    "| Câm biao va chény phía truoc | Không | Có |": "| Cảnh báo va chạm phía trước | Không | Có |",
    "| Câm biao phụng tiện célé ngàng phía sau | Không | Có |": "| Cảnh báo phương tiện cắt ngang phía sau | Không | Có |",
    "| Câm biao diêm mu | Có | Có |": "| Cảnh báo điểm mù | Có | Có |",
    "| Câm biao mô ciao | Không | Có |": "| Cảnh báo mở cửa | Không | Có |",
    "| TRO LAI KHI CO NGUY CO VA CHAM |": "| TRỢ LÁI KHI CÓ NGUY CƠ VA CHẠM |",
    "| Phanth tu dòng khn klän cáp truoc | Không | Có |": "| Phanh tự động khẩn cấp trước | Không | Có |",
    "| Hồ tro gũ lân klän cáp | Không | Có |": "| Hỗ trợ giữ làn khẩn cấp | Không | Có |",
    "| CACTINH NANG KHAC |": "| CÁC TÍNH NĂNG KHÁC |",
    "| Bạnpha tu dòng/Benpha phiaisung | Không | Có |": "| Đèn pha tự động/Đèn pha thích ứng | Không | Có |",
    "| Hồ trong glam sat la xe | Không | Có |": "| Hệ thống giám sát lái xe | Không | Có |",
    "| Hồ trong camera 360 dû glam sat xung quanh | Có | Có |": "| Hệ thống camera 360 độ giám sát xung quanh | Có | Có |",
    "| THUNG NOI MOGNUN VIEN |": "| THÔNG TIN NỘI DUNG |",
    "| HE THONG TU GIA TI TRN XE |": "| HỆ THỐNG GIẢI TRÍ TRÊN XE |",
    "| Che do xe co bàn. Càm trai, Ngũi la, Thuo Cung, Rua Xe | Có | Có |":
        "| Chế độ xe cơ bản. Cắm trại, Ngủ lái, Thú cưng, Rửa xe | Có | Có |",
    "| Gái tin co bàn (Bai FM, Bluetooth, USB) | Có | Có |": "| Giải trí cơ bản (Đài FM, Bluetooth, USB) | Có | Có |",
    "| Kết niú Android Auto via Apple Carplay | Có | Có |": "| Kết nối Android Auto và Apple Carplay | Có | Có |",
    "| Trinh duyet web | Có | Có |": "| Trình duyệt web | Có | Có |",
    "| TRO LIV AO |": "| TRỢ LÝ ẢO |",
    "| Hồ druđu bén識 các chúc ngxe co bàn | Có | Có |": "| Hỗ trợ điều khiển các chức năng xe cơ bản | Có | Có |",
    "| Cáp nhật phán mém tù xa | Có | Có |": "| Cập nhật phần mềm từ xa | Có | Có |",
    "| UNG DUNG DIEN THOAI |": "| ỨNG DỤNG ĐIỆN THOẠI |",
    "| Dông bổ tài khoản, ứng dụng, phàn quyên tài xế | Có | Có |":
        "| Đồng bộ tài khoản, ứng dụng, phân quyền tài xế | Có | Có |",
    "| Quán lý sqc &amp; thanh toán phí sqc | Có | Có |": "| Quản lý sạc & thanh toán phí sạc | Có | Có |",
    "| Bn độ trạm sqc | Có | Có |": "| Bản đồ trạm sạc | Có | Có |",
    "| Dịch vụ hậu mài: dặt lich sùa chừa, lái thủ | Có | Có |":
        "| Dịch vụ hậu mãi: đặt lịch sửa chữa, lái thử | Có | Có |",
    "| Mua bán phy kiên | Có | Có |": "| Mua bán phụ kiện | Có | Có |",
    "| Dinh vj xe tù xa |  |  |": "| Định vị xe từ xa |  |  |",
    "Hình anh mang tính chât minh hоя và có thể khác so với xe thực tế. Tính năng, đ薬 diêm, thông só ký thuật có thể thay dối mà không thông báo truóc.":
        "Hình ảnh mang tính chất minh họa và có thể khác so với xe thực tế. Tính năng, đặc điểm, thông số kỹ thuật có thể thay đổi mà không thông báo trước.",
}

_VF9 = {
    # boilerplate
    "SỨ LUỆA CHỐN\nCÙA NGUỒI THÀNH ĐАT, TIẾN PHONG": "SỨ LỬA CHỌN\nCỦA NGƯỜI THÀNH ĐẠT, TIẾN PHONG",
    "* Hình anh xe VF 9 phiên bản PLUS tqai thị trưởng khác. Phiên bản cho thị trương Viêt Nam có thể có những khác biét nhật dїnh":
        "* Hình ảnh xe VF 9 phiên bản PLUS tại thị trường khác. Phiên bản cho thị trường Việt Nam có thể có những khác biệt nhất định",
    "* Hình anh xe VF 9 phiên bản PLUS tai thi trưởng khác. Phiên bàn cho thi trương Viêt Nam có thể có những khác biên nhát định":
        "* Hình ảnh xe VF 9 phiên bản PLUS tại thị trường khác. Phiên bản cho thị trường Việt Nam có thể có những khác biệt nhất định",
    "(*) Hình anh hiên thị chí mang tính chat minh hòa, sán phạm thực tế có thể khác.":
        "(*) Hình ảnh hiển thị chỉ mang tính chất minh họa, sản phẩm thực tế có thể khác.",
    "Thông minh vước trội": "Thông minh vượt trội",
    "Câm hưng thiêt kê\nCân băng dòng": "Cảm hứng thiết kế\nCân bằng động",
    "Công suất tội da\n402 hp": "Công suất tối đa\n402 hp",
    "Mô men xoăn các dài\n620 Nm": "Mô men xoắn cực đại\n620 Nm",
    "Hệ{dän}{đòng}\nHAI CÃU\ntoàn thời gian (AWD)": "Hệ dẫn động\nHAI CẦU\ntoàn thời gian (AWD)",
    "QUÂNG ĐUỒNG\ndi chuyến tối da\nsau một lân sác dây\n626 km*": "QUÃNG ĐƯỜNG\ndi chuyển tối đa\nsau một lần sạc đầy\n626 km*",
    # spec table — KÍCH THƯỚC
    "| KICH THUOC &amp; TAI TRONG |": "| KÍCH THƯỚC & TẢI TRỌNG |",
    "| KICH THUOC |": "| KÍCH THƯỚC |",
    "| Chiêu dài cα só (mm) | 3.149 |  | 3.149 |": "| Chiều dài cơ sở (mm) | 3.149 |  | 3.149 |",
    "| Dai x Rong x Cao (mm) | 5.119 x 2.254 x 1.697 |  | 5.119 x 2.254 x 1.697 |":
        "| Dài x Rộng x Cao (mm) | 5.119 x 2.254 x 1.697 |  | 5.119 x 2.254 x 1.697 |",
    "| Khoàng sáng gám xe khòng tái (mm) | 174 |  | 184 |": "| Khoảng sáng gầm xe không tải (mm) | 174 |  | 184 |",
    "| Dung tich khoang chua hanh lý (L)-Có hang ghé cuoí | 212 |  | 212 |":
        "| Dung tích khoang chứa hành lý (L)-Có hàng ghế cuối | 212 |  | 212 |",
    "| Dung tich khoang chua hanh lý (L)-Gáp hang ghé cuoí | 926 |  | 926 |":
        "| Dung tích khoang chứa hành lý (L)-Gập hàng ghế cuối | 926 |  | 926 |",
    "| Dung tich khoang chua hanh lý (L)-Phia truoc | 100 |  | 100 |":
        "| Dung tích khoang chứa hành lý (L)-Phía trước | 100 |  | 100 |",
    "| TAI TRONG |": "| TẢI TRỌNG |",
    "| Trong luong khong tái (kg) | 2.911 |  | 7 chô:2.968|6 chô:2.932 |":
        "| Trọng lượng không tải (kg) | 2.911 |  | 7 chỗ:2.968|6 chỗ:2.932 |",
    "| Tai trong (kg) | 550 |  | 7 chô:550|6 chô:475 |": "| Tải trọng (kg) | 550 |  | 7 chỗ:550|6 chỗ:475 |",
    "| Tai trong hánh lý nóc xe (kg) | 75 |  | 75 |": "| Tải trọng hành lý nóc xe (kg) | 75 |  | 75 |",
    # HỆ THỐNG TRUYỀN ĐỘNG
    "| HÉ THONG TRUYEN DONG |": "| HỆ THỐNG TRUYỀN ĐỘNG |",
    "| Dòng ca |  |  |": "| Động cơ |  |  |",
    "| Dòng ca | 2 motor 150 kW |  | 2 motor 150 kW |": "| Động cơ | 2 motor 150 kW |  | 2 motor 150 kW |",
    "| Cóng suát tôi da (hp/kW) | 402/300 |  | 402/300 |": "| Công suất tối đa (hp/kW) | 402/300 |  | 402/300 |",
    "| Mò men xoán cuc dài (Nm) | 620 |  | 620 |": "| Mô men xoắn cực đại (Nm) | 620 |  | 620 |",
    "| Tốc dό tôi da (km/h) | 200 |  | 200 |": "| Tốc độ tối đa (km/h) | 200 |  | 200 |",
    # PIN
    "| Loai pin | CATL |  | CATL |": "| Loại pin | CATL |  | CATL |",
    "| Dung luong pin (kWh)-khà dung | 123 |  | 123 |": "| Dung lượng pin (kWh)-khả dụng | 123 |  | 123 |",
    "| Quảng duông chay một lân sac dây (km)-Điều kiên tiêu chuán châu Âu (WLTP) | 626 |  | 602 |":
        "| Quãng đường chạy một lần sạc đầy (km)-Điều kiện tiêu chuẩn châu Âu (WLTP) | 626 |  | 602 |",
    "| Cóng suát sac AC toi da (kW) | 6.6 kW 1 pha,11 kW 3 pha |  | 6.6 kW 1 pha,11 kW 3 pha |":
        "| Công suất sạc AC tối đa (kW) | 6.6 kW 1 pha,11 kW 3 pha |  | 6.6 kW 1 pha,11 kW 3 pha |",
    "| Hê thông phanth tái sinh | Có (Tât, Tháp, Trung binh, Cao) |  | Có (Tât, Tháp, Trung binh, Cao) |":
        "| Hệ thống phanh tái sinh | Có (Tắt, Thấp, Trung bình, Cao) |  | Có (Tắt, Thấp, Trung bình, Cao) |",
    "| Thoi gian nap pin nhanh nhật (phút) | 35 phút(10-70%) |  | 35 phút(10-70%) |":
        "| Thời gian nạp pin nhanh nhất (phút) | 35 phút (10-70%) |  | 35 phút (10-70%) |",
    # THÔNG SỐ TRUYỀN ĐỘNG KHÁC
    "| THONG SÓ TRUYEN DONG KHAC |": "| THÔNG SỐ TRUYỀN ĐỘNG KHÁC |",
    "| Cách chuyén só | Nut bãm |  | Nut bãm |": "| Cách chuyển số | Nút bấm |  | Nút bấm |",
    "| Dăn dòng | AWD/2 cái toàn thời gian |  | AWD/2 cái toàn thhljsian |":
        "| Dẫn động | AWD/2 cầu toàn thời gian |  | AWD/2 cầu toàn thời gian |",
    "| Chon ché dô lái | Eco/Normal/Sport |  | Eco/Normal/Sport |": "| Chọn chế độ lái | Eco/Normal/Sport |  | Eco/Normal/Sport |",
    "| Ché dô thay dối tóc dô dé düng | Có |  | Có |": "| Chế độ thay đổi tốc độ dễ dàng | Có |  | Có |",
    # KHUNG GẦM
    "| KHUNG GAM |": "| KHUNG GẦM |",
    "| GIAM XOC |": "| GIẢM XÓC |",
    "| Hê thông treo - truoc | Dọc lap, tay dôn kép |  | D-doc lap, tay dôn kEP |":
        "| Hệ thống treo - trước | Độc lập, tay đòn kép |  | Độc lập, tay đòn kép |",
    "| Hê thông treo - sau | Lièn két da diém, giam chän khi nén |  | Lièn két da diém, giam chän khi nén |":
        "| Hệ thống treo - sau | Liên kết đa điểm, giảm chấn khí nén |  | Liên kết đa điểm, giảm chấn khí nén |",
    "| PHANH |": "| PHANH |",
    "| Phanh truoc | Día thông gió |  | Día thông gió |": "| Phanh trước | Đĩa thông gió |  | Đĩa thông gió |",
    "| Phanh sau | Día thông gió |  | Día thông gió |": "| Phanh sau | Đĩa thông gió |  | Đĩa thông gió |",
    "| VANH VA LOP BАНH XE |": "| VÀNH VÀ LỐP BÁNH XE |",
    "| Kich thuoc La-zäng | 20 Inch |  | 21 Inch |": "| Kích thước la-zăng | 20 Inch |  | 21 Inch |",
    "| Loai la-zäng | Hop kim |  | Hop kim |": "| Loại la-zăng | Hợp kim |  | Hợp kim |",
    # NỘI THẤT
    "| NOI THAT &amp; TIEN NGHI |": "| NỘI THẤT & TIỆN NGHI |",
    "| GHE TOAN XE |": "| GHẾ TOÀN XE |",
    "| Số chô ngói | 7 | 7 hoãc 6 |": "| Số chỗ ngồi | 7 | 7 hoặc 6 |",
    "| Chât liEU boc ghé | Da nhàn tao | Da nhàn tao cao cáp |": "| Chất liệu bọc ghế | Da nhân tạo | Da nhân tạo cao cấp |",
    "| GHE LAI |": "| GHẾ LÁI |",
    "| Ghe lai - diEU chinh huông | Chinh diên 8 huông | Chinh diên 12 huông |":
        "| Ghế lái - điều chỉnh hướng | Chỉnh điện 8 hướng | Chỉnh điện 12 hướng |",
    "| Ghe lai nho vi tri | Không | Có |": "| Ghế lái nhớ vị trí | Không | Có |",
    "| Ghe lai co massage | Không | Có |": "| Ghế lái có massage | Không | Có |",
    "| Ghe lai co thông gió | Không | Có |": "| Ghế lái có thông gió | Không | Có |",
    "| Ghe lai co suài | Có | Có |": "| Ghế lái có sưởi | Có | Có |",
    "| GHE PHU |": "| GHẾ PHỤ |",
    "| Ghe phu - diEU chinh huông | Chinh diên 6 huông | Chinh diên 10 huông |":
        "| Ghế phụ - điều chỉnh hướng | Chỉnh điện 6 hướng | Chỉnh điện 10 hướng |",
    "| GHÉ HANG 2 |": "| GHẾ HÀNG 2 |",
    "| Hang ghé thu 2 diếu chinh huóng | Chinh diên 4 huóng | Chinh diên 8 huóng |":
        "| Hàng ghế thứ 2 điều chỉnh hướng | Chỉnh điện 4 hướng | Chỉnh điện 8 hướng |",
    "| Hang ghé thu 2 diếu chinh gap ty lè | 40:20:40, hô trág dé vao hang 3 |":
        "| Hàng ghế thứ 2 điều chỉnh gập tỷ lệ | 40:20:40, hỗ trợ để vào hàng 3 |",
    "| Hang ghé thu 2 cò thông gió | Không | Có |": "| Hàng ghế thứ 2 có thông gió | Không | Có |",
    "| Hang ghé thu 2 cò suoi | Không | Có |": "| Hàng ghế thứ 2 có sưởi | Không | Có |",
    "| Hang ghé thu 2 cò massage | Không | Có |": "| Hàng ghế thứ 2 có massage | Không | Có |",
    "| GHÉ VIP |": "| GHẾ VIP |",
    "| Ghe VIP chinh dièn | Không | 6 chóc. Chinh dièn 8 huóng7 chóc. Không |":
        "| Ghế VIP chỉnh điện | Không | 6 chỗ. Chỉnh điện 8 hướng/7 chỗ. Không |",
    "| Hóp dό hàng ghé sau | Không | 6 chóc. Có, tich hop sac khòng day7 chóc. Không |":
        "| Hộp đồ hàng ghế sau | Không | 6 chỗ. Có, tích hợp sạc không dây/7 chỗ. Không |",
    "| Ghé VIP massage | Không | Có |": "| Ghế VIP massage | Không | Có |",
    "| Ghé VIP cò thông gió | Không | Có |": "| Ghế VIP có thông gió | Không | Có |",
    "| Ghé VIP cò suoi | Không | Có |": "| Ghế VIP có sưởi | Không | Có |",
    "| VO LANG |": "| VÔ LĂNG |",
    "| Dieu chinh vó lâng | Chinh co 4 huóng | Chinh diên 4 huóng |": "| Điều chỉnh vô lăng | Chỉnh cơ 4 hướng | Chỉnh điện 4 hướng |",
    "| Suôi tay lái | Có | Có |": "| Sưởi tay lái | Có | Có |",
    "| Nhó ví tri vó lâng | Không | Có |": "| Nhớ vị trí vô lăng | Không | Có |",
    "| DIEU HOA KHONG KHI |": "| ĐIỀU HÒA KHÔNG KHÍ |",
    "| Hê thông dieu hoa | Tú dong, 3 vùng | Tú dong, 3 vùng |": "| Hệ thống điều hòa | Tự động, 3 vùng | Tự động, 3 vùng |",
    "| Chúc nảng kiém soát chât lung không khi | Có | Có |": "| Chức năng kiểm soát chất lượng không khí | Có | Có |",
    "| Chúc nảng ion hoa không khi | Có | Có |": "| Chức năng ion hóa không khí | Có | Có |",
    "| Loc không khi Cabin | Combi 1.0 | Combi 1.0 |": "| Lọc không khí Cabin | Combi 1.0 | Combi 1.0 |",
    "| MÁN HINH, KET NÓI, GIAI TRI, TIEN NGHI |": "| MÀN HÌNH, KẾT NỐI, GIẢI TRÍ, TIỆN NGHI |",
    "| Man hinh giài tri câm ung | 15,6 Inch | 15,6 Inch |": "| Màn hình giải trí cảm ứng | 15,6 Inch | 15,6 Inch |",
    "| Man hinh giài tri câm ung hang ghé sau | Không | 8 Inch |": "| Màn hình giải trí cảm ứng hàng ghế sau | Không | 8 Inch |",
    "| Man hinh hiên thi HUD | Có | Có |": "| Màn hình hiển thị HUD | Có | Có |",
    "| Cóng két noi USB loai A hang ghé lái | 2 | 2 |": "| Cổng kết nối USB loại A hàng ghế lái | 2 | 2 |",
    "| Cóng két noi USB loai A hang ghé thu 2 | 2 | 7 chóc: 2 | 6 chóc: 4 |":
        "| Cổng kết nối USB loại A hàng ghế thứ 2 | 2 | 7 chỗ: 2 | 6 chỗ: 4 |",
    "| Cóng két noi USB loai A hang ghé thu 3 | 2 | 2 |": "| Cổng kết nối USB loại A hàng ghế thứ 3 | 2 | 2 |",
    "| Cóng két noi USB loai C | Có | Có |": "| Cổng kết nối USB loại C | Có | Có |",
    "| Cóng sac 12V khoang hanh lý | Có | Có |": "| Cổng sạc 12V khoang hành lý | Có | Có |",
    "| Ò dien xoay chiêu | Không | 230 V/150 W |": "| Ổ điện xoay chiều | Không | 230 V/150 W |",
    "| Sac không day | Có | Có |": "| Sạc không dây | Có | Có |",
    "| HЕ THONG LOA | 11 | 13 |": "| HỆ THỐNG LOA | 11 | 13 |",
    "| Loa trám | 0 | 1 |": "| Loa trầm | 0 | 1 |",
    "| HЕ THONG DEN NOI THẌT |": "| HỆ THỐNG ĐÈN NỘI THẤT |",
    "| Dèn trang tri noi thất | Có(Da mùu) | Có(Da mùu) |": "| Đèn trang trí nội thất | Có (Đa màu) | Có (Đa màu) |",
    "| Dèn học để độ trước | Có | Có |": "| Đèn hộc để đồ trước | Có | Có |",
    "| Dèn khoang hanh lý | Có | Có |": "| Đèn khoang hành lý | Có | Có |",
    "| Dèn khoang hanh lý trước | Có | Có |": "| Đèn khoang hành lý trước | Có | Có |",
    "| Tãm che nâng, có guong | Ghé lái và ghé phuo, thêm dèn |": "| Tấm che nắng, có gương | Ghế lái và ghế phụ, thêm đèn |",
    "| NOI THÂT &amp; TIēN NGHI KHAC |": "| NỘI THẤT & TIỆN NGHI KHÁC |",
    "| Phanh tay | Diên tũ | Diên tũ |": "| Phanh tay | Điện tử | Điện tử |",
    "| Guong chiêu hâu trong xe | Chóng choi tu dòng | Chng choi tu dòng |":
        "| Gương chiếu hậu trong xe | Chống chói tự động | Chống chói tự động |",
    # AN TOÀN
    "| AN TOAN &amp; AN NINH |": "| AN TOÀN & AN NINH |",
    "| Hê thông chồng bo cùng phanth ABS | Có | Có |": "| Hệ thống chống bó cứng phanh ABS | Có | Có |",
    "| Chúc nảng phanth phôi luc phanth diên tù EBD | Có | Có |": "| Chức năng phân phối lực phanh điện tử EBD | Có | Có |",
    "| Hô trơ phanth khán cấp BA | Có | Có |": "| Hỗ trợ phanh khẩn cấp BA | Có | Có |",
    "| Hê thông cân bàng diên tù ESC | Có | Có |": "| Hệ thống cân bằng điện tử ESC | Có | Có |",
    "| Chúc nảng kiêm soát luc keo TCS | Có | Có |": "| Chức năng kiểm soát lực kéo TCS | Có | Có |",
    "| Hô trơ khi髙 hngang dóc HSA | Có | Có |": "| Hỗ trợ khởi hành ngang dốc HSA | Có | Có |",
    "| Chúc nảng chiong lát ROM | Có | Có |": "| Chức năng chống lật ROM | Có | Có |",
    "| Dèn bao phanth khán cấp ESS | Có | Có |": "| Đèn báo phanh khẩn cấp ESS | Có | Có |",
    "| Giâm sât áp suát lóp | dTPMS | dTPMS |": "| Giám sát áp suất lốp | dTPMS | dTPMS |",
    "| HЕ THONG TUI KHI | 11 | 11 |": "| HỆ THỐNG TÚI KHÍ | 11 | 11 |",
    "| Túi khi trước lái và hanh khach phía trước | 2 | 2 |": "| Túi khí trước lái và hành khách phía trước | 2 | 2 |",
    "| Túi khi rêm | 2 | 2 |": "| Túi khí rèm | 2 | 2 |",
    "| Túi khi bén hóng hàng ghé trước | 2 | 2 |": "| Túi khí bên hông hàng ghế trước | 2 | 2 |",
    "| Túi khi bén hóng hàng ghé sau | 2 | 2 |": "| Túi khí bên hông hàng ghế sau | 2 | 2 |",
    "| Túi khi bão vẻ chần hạng ghé tr祖先 | 2 | 2 |": "| Túi khí bảo vệ chân hàng ghế trước | 2 | 2 |",
    "| Túi khi trung tấm hàng ghé tr祖先 | 1 | 1 |": "| Túi khí trung tâm hàng ghế trước | 1 | 1 |",
    # ADAS
    "| CAC TINH NANG ADAS |": "| CÁC TÍNH NĂNG ADAS |",
    "| TRO LAI TRЕН CAO TOC |": "| TRỢ LÁI TRÊN CAO TỐC |",
    "| Hô trơ di chuynên khi un tác | Có | Có |": "| Hỗ trợ di chuyển khi ùn tắc | Có | Có |",
    "| Hô trơ lái trên duông cao tác | Có | Có |": "| Hỗ trợ lái trên đường cao tốc | Có | Có |",
    "| TRO LAN |": "| TRỢ LÀN |",
    "| Cánh báo chích lân | Có | Có |": "| Cảnh báo chệch làn | Có | Có |",
    "| Hô trơ giűn lân | Có | Có |": "| Hỗ trợ giữ làn | Có | Có |",
    "| Kiém soát di giùa lân | Có | Có |": "| Kiểm soát di giữa làn | Có | Có |",
    "| GIAM SAT HÂNH TRINH THÍCH ÜNG |": "| GIÁM SÁT HÀNH TRÌNH THÍCH ỨNG |",
    "| Giám sát hanh trinh thich üng | Có | Có |": "| Giám sát hành trình thích ứng | Có | Có |",
    "| Diên chinh toc dô thông minh | Có | Có |": "| Điều chỉnh tốc độ thông minh | Có | Có |",
    "| Nhân biét biên bao giao thông | Có | Có |": "| Nhận biết biển báo giao thông | Có | Có |",
    "| CÂNH BÃO VA CHAM |": "| CẢNH BÁO VA CHẠM |",
    "| Cânh bao va cham phia truóc | Có | Có |": "| Cảnh báo va chạm phía trước | Có | Có |",
    "| Cânh bao phuong tiên cát ngang phia sau | Có | Có |": "| Cảnh báo phương tiện cắt ngang phía sau | Có | Có |",
    "| Cânh bao diêm mù | Có | Có |": "| Cảnh báo điểm mù | Có | Có |",
    "| Cânh bao mơ của | Có | Có |": "| Cảnh báo mở cửa | Có | Có |",
    "| TRỘ LAI KHI CÓ NGUY CO VA CHAM |": "| TRỢ LÁI KHI CÓ NGUY CƠ VA CHẠM |",
    "| Phanth tu đòng khán cáp truóc | Có | Có |": "| Phanh tự động khẩn cấp trước | Có | Có |",
    "| Hồ trợ giú lán khăn cáp | Có | Có |": "| Hỗ trợ giữ làn khẩn cấp | Có | Có |",
    "| HỎ TRO DÒ XE |": "| HỖ TRỢ ĐỖ XE |",
    "| Hồ tr讶 phia truóc | Có | Có |": "| Hỗ trợ đỗ phía trước | Có | Có |",
    "| Hồ tr讶 phia sau | Có | Có |": "| Hỗ trợ đỗ phía sau | Có | Có |",
    "| Hề thông camera sau | Có | Có |": "| Hệ thống camera sau | Có | Có |",
    "| Gíamos sat xung quanh | Có | Có |": "| Giám sát xung quanh | Có | Có |",
    "| CÁC TINH NÂNG KHAC |": "| CÁC TÍNH NĂNG KHÁC |",
    "| Dènpha thich üng | Có | Có |": "| Đèn pha thích ứng | Có | Có |",
    "| Hề thông giám sat lái xe | Có | Có |": "| Hệ thống giám sát lái xe | Có | Có |",
    "| THIET KE KIEU DÂNG NGOAI THẾT |": "| THIẾT KẾ KIỂU DÁNG NGOẠI THẤT |",
    "| Tây nâm cua | Loài án | Loài án |": "| Tay nắm cửa | Loại ẩn | Loại ẩn |",
    "| Bác l’en xuóng | AFS | Có |": "| Bặc lên xuống | AFS | Có |",
    "| THIET KE KIEU DÂNG NOI THẾT |": "| THIẾT KẾ KIỂU DÁNG NỘI THẤT |",
    "| VỂ LANG |": "| VÔ LĂNG |",
    "| Loai vò lâng | Dàng D-cut | Dàng D-cut |": "| Loại vô lăng | Dạng D-cut | Dạng D-cut |",
    "| Boc vò lâng | Da thành thiên môi truONG |": "| Bọc vô lăng | Da thân thiện môi trường |",
    "| CÁC TINH NÂNG DIEU KHIEN THONG MINH (*) |": "| CÁC TÍNH NĂNG ĐIỀU KHIỂN THÔNG MINH (*) |",
    "| Lua chon ché dô vàn hánh dác biêt | Có | Có |": "| Lựa chọn chế độ vận hành đặc biệt | Có | Có |",
    "| Cà dát Gioi han thơi gian hoat dòng &amp; khu vúc hoat dòng cua xe | Có | Có |":
        "| Cài đặt Giới hạn thời gian hoạt động & khu vực hoạt động của xe | Có | Có |",
    "| Giãt trí truc tuyến | Có | Có |": "| Giải trí trực tuyến | Có | Có |",
    "| Trô choi | Có | Có |": "| Trò chơi | Có | Có |",
    "| Diêu huong và dân duong trn màn hình trung tâm | Có | Có |":
        "| Điều hướng và dẫn đường trên màn hình trung tâm | Có | Có |",
    "| Trinh duyёт web | Có | Có |": "| Trình duyệt web | Có | Có |",
    "| Tu chán doan lòi | Có | Có |": "| Tự chẩn đoán lỗi | Có | Có |",
    "| Hói dアップ lý áo | Có | Có |": "| Hỏi đáp trợ lý ảo | Có | Có |",
    "| Diêu khiênxe và cái dât bảng giong noi | Có | Có |": "| Điều khiển xe và cài đặt bằng giọng nói | Có | Có |",
    "| Úng dung diên thoai | Có | Có |": "| Ứng dụng điện thoại | Có | Có |",
    "| Cáp nhật phán mём tù xa | Có | Có |": "| Cập nhật phần mềm từ xa | Có | Có |",
    # footer
    "Đ饯 khách hàng Làm trông tâm": "Đặt khách hàng Làm trọng tâm",
    "Chính sác Báo hành\ntôt nhật thi trưởng": "Chính sách Bảo hành\ntốt nhất thị trường",
    "Báo hành xe mói 10 năm": "Bảo hành xe mới 10 năm",
    "Báo hành pin 10 năm\nhoặc 200.000 km": "Bảo hành pin 10 năm\nhoặc 200.000 km",
    "Dịch vụ Hậu mãi\nxuất sắc": "Dịch vụ Hậu mãi\nxuất sắc",
    "Sừa chủa luuu đông (Mobile\nService) & Cúu hô 24/7 trong\nsuột thời gian bảo hành":
        "Sửa chữa lưu động (Mobile\nService) & Cứu hộ 24/7 trong\nsuốt thời gian bảo hành",
    "Mảng luối 150.000 công sạc\nphù rộng 34/34 tính, thành phố":
        "Mạng lưới 150.000 cổng sạc\nphủ rộng 34/34 tỉnh, thành phố",
    "Hệ thống showroom,\nxuống dích vụ không\nngùng được mở rộng.":
        "Hệ thống showroom,\nxưởng dịch vụ không\nngừng được mở rộng.",
    "Hệ thống Showroom/Nha phàn phối/\nXuống Dịch vụ và trạm sác VinFast liên\ntúc mô rông và không ngùng\nphát triên trên kháp cà nuóc, nhàm\ntói uu hóa trai nghiem của khách\nhàng, tùng buócKIEN táo nèn\ntuồng lai xanh tái Việt Nam.":
        "Hệ thống Showroom/Nhà phân phối/\nXưởng Dịch vụ và trạm sạc VinFast liên\ntục mở rộng và không ngừng\nphát triển trên khắp cả nước, nhằm\ntối ưu hóa trải nghiệm của khách\nhàng, từng bước kiến tạo nên\ntương lai xanh tại Việt Nam.",
    "QUÂN ĐАО\nHOÀNG SA": "QUÂN ĐẢO\nHOÀNG SA",
    "QUÂN ĐАО\nTRUỂNG SA": "QUÂN ĐẢO\nTRƯỜNG SA",
    # màu
    "# Nng cao": "# Nâng cao",
    "# Tiêu chuẩn": "# Tiêu chuẩn",
    "Miễn ph giao nhận xe tại địa điểm theo yŒu cầu của qu khÆch \n(trong giờ hnh chnh, phạm vi 30 km từ xưởng dịch vụ\nVinFast gần nhất).":
        "Miễn phí giao nhận xe tại địa điểm theo yêu cầu của quý khách \n(trong giờ hành chính, phạm vi 30 km từ xưởng dịch vụ\nVinFast gần nhất).",
    "Hỗ trợ chi ph sửa chữa cho đại l, đảm bảo qu khÆch được phục \nvụ nhanh chng v hiệu quả nhất.":
        "Hỗ trợ chi phí sửa chữa cho đại lý, đảm bảo quý khách được phục \nvụ nhanh chóng và hiệu quả nhất.",
    "Được tiếp đn v tư vấn bởi đội ngũ cố vấn dịch vụ, kỹ thuật viŒn giu \nkinh nghiệm v c tay nghề cao nhất.":
        "Được tiếp đón và tư vấn bởi đội ngũ cố vấn dịch vụ, kỹ thuật viên giàu \nkinh nghiệm và có tay nghề cao nhất.",
    "Qu khÆch sẽ được ưu tiŒn sắp xếp lịch bảo dưỡng, sửa chữa theo thời \ngian v nhu cầu của bản thn.":
        "Quý khách sẽ được ưu tiên sắp xếp lịch bảo dưỡng, sửa chữa theo thời \ngian và nhu cầu của bản thân.",
    "CHẤT LƯỢNG ĐẲNG CẤP": "CHẤT LƯỢNG ĐẲNG CẤP",
    "CAM KẾT ĐỒNG HÀNH TRỌN VẸN": "CAM KẾT ĐỒNG HÀNH TRỌN VẸN",
    "TRẢI NGHIỆM XỨNG TẦM TINH HOA": "TRẢI NGHIỆM XỨNG TẦM TINH HOA",
    "01. TIẾP CẬN DỊCH VỤ SỬA CHỮA\n      NHANH CHNG V THUẬN TIỆN":
        "01. TIẾP CẬN DỊCH VỤ SỬA CHỮA\n      NHANH CHÓNG VÀ THUẬN TIỆN",
    "02. TRẢI NGHIỆM VIP TẠI\n\n## XƯỞNG DỊCH VỤ VINFAST":
        "02. TRẢI NGHIỆM VIP TẠI\n\n## XƯỞNG DỊCH VỤ VINFAST",
    "03. DỊCH VỤ CHĂM SC KH`CH HNG TẬN T´M, CHU Đ`O":
        "03. DỊCH VỤ CHĂM SÓC KHÁCH HÀNG TẬN TÂM, CHU ĐÁO",
    "04. SẠC ĐIỆN MIỄN PHÍ 2 NĂM": "04. SẠC ĐIỆN MIỄN PHÍ 2 NĂM",
    "Miễn ph 2 năm sạc điện tại hệ thống trạm sạc cng cộng VinFast trŒn \nton quốc tới 30/06/2027.":
        "Miễn phí 2 năm sạc điện tại hệ thống trạm sạc công cộng VinFast trên \ntoàn quốc tới 30/06/2027.",
    "Cùng bạn\nbút phá mội giói h quan": "Cùng bạn\nbút phá mọi giới hạn",
}

_VF2 = {
    "Hình anh chi mang tính chát minh hoq.": "Hình ảnh chỉ mang tính chất minh họa.",
    "Ồ Tô ĐÂU ĐỒI\nUỐC MÓ'\nTRONG TÀM VỔI\nDÉ DÙNG\nDÉ MUA\nDÉ NUỔI\nDÉ THÍCH":
        "Ô TÔ ĐẦU ĐỜI\nƯỚC MƠ\nTRONG TẦM VỚI\nDỄ DÙNG\nDỄ MUA\nDỄ NUÔI\nDỄ THÍCH",
    "(phœt)": "(phút)",
    "| DÂN DÔNG | RWD/CÂU SAU |": "| DẪN ĐỘNG | RWD/CẦU SAU |",
    "| HÉ THONG PHANH TÁI SINH | CÓ |": "| HỆ THỐNG PHANH TÁI SINH | CÓ |",
    "| CHÉ DỘ LÀI | ECO/NORMAL |": "| CHẾ ĐỘ LÁI | ECO/NORMAL |",
    "MÂN HÍNH THÔNG TIN LÁI": "MÀN HÌNH THÔNG TIN LÁI",
    "| HÈ THONG ÅM THANH | 2 LOA |": "| HỆ THỐNG ÂM THANH | 2 LOA |",
    "| GHÉ LÁI | CHÎNH CÔ 4 HUỘNG |": "| GHẾ LÁI | CHỈNH CƠ 4 HƯỚNG |",
    "| BQC CHÉ | N1 |": "| BỌC GHẾ | NỈ |",
}

_VF8NEW = {
    "Kích thước mâm xe19 Inch": "Kích thước mâm xe 19 Inch",
    "Đèn chiếu xa tự độngCó": "Đèn chiếu xa tự động Có",
    "170 (kW)": "170 (kW)",
    "60,13": "60,13",
}

FILE_DICTS = {
    "vf2.md": _VF2,
    "vf3.md": _VF3,
    "vf5.md": _VF5,
    "vf6.md": _VF6,
    "vf7.md": _VF7,
    "vf8.md": _VF8,
    "vf8-the-new.md": _VF8NEW,
    "vf9.md": _VF9,
}


def _build_apply(files: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Ghép shared + file dict thành list (bad, good) theo độ dài giảm dần."""
    shared = list(_SHARED.items())
    file_entries = []
    for f in files:
        file_entries.extend(FILE_DICTS.get(f, {}).items())
    all_items = shared + file_entries
    # bỏ trùng bad
    seen, uniq = set(), []
    for bad, good in all_items:
        if bad in seen:
            continue
        seen.add(bad)
        uniq.append((bad, good))
    # sort theo độ dài giảm dần (ưu tiên chuỗi dài), cùng độ dài giữ thứ tự
    uniq.sort(key=lambda kv: len(kv[0]), reverse=True)
    return uniq, []


def clean_text(text: str, fname: str | None = None) -> str:
    text = fix_cyrillic(text)
    text = fix_fffd(text)
    if fname:
        items = _build_apply([fname])[0]
    else:
        items = _build_apply(list(FILE_DICTS))[0]
    for bad, good in items:
        text = text.replace(bad, good)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix OCR/font cho brochure PDF trong data/raw")
    ap.add_argument("files", nargs="*", help="Các file .md cần sửa (mặc định nếu --all)")
    ap.add_argument("--all", action="store_true", help="Sửa toàn bộ *.md trong data/raw")
    args = ap.parse_args()

    if args.all:
        targets = sorted(p for p in (REPO_ROOT / "data" / "raw").glob("*.md"))
    else:
        targets = [REPO_ROOT / f for f in args.files]
    if not targets:
        print("Chưa chỉ định file. Dùng: fix_ocr.py data/raw/vf3.md ... hoặc --all")
        return 1

    for t in targets:
        if not t.exists():
            print(f"  (bỏ qua, không tồn tại): {t}")
            continue
        txt = t.read_text(encoding="utf-8")
        cleaned = clean_text(txt, t.name)
        t.write_text(cleaned, encoding="utf-8")
        print(f"[fix_ocr] {t.name}: {len(txt)} → {len(cleaned)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
