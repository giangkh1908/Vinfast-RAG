"""Unit tests for app.agent.intent module."""

from unittest.mock import MagicMock

import pytest

from app.agent.intent import (
    _validate_llm_result,
    classify_intent,
    extract_spec_category,
    extract_spec_key,
    llm_classify_fallback,
)


class TestExtractSpecCategory:
    """Test deterministic mapping from query keywords to spec categories."""

    @pytest.mark.parametrize(
        ("query", "expected_cat"),
        [
            # Battery
            ("Thời gian sạc đầy pin là bao lâu?", "battery"),
            ("VF 8 sạc nhanh từ 10-70 mất bao nhiêu phút?", "battery"),
            ("Dung lượng pin của VF 3 là bao nhiêu kWh?", "battery"),
            ("Quãng đường đi được của xe là bao xa?", "battery"),
            ("Tầm di chuyển một lần nạp pin", "battery"),
            ("Phạm vi hoạt động của VF 7", "battery"),
            # Powertrain
            ("Công suất động cơ VF 8 là bao nhiêu mã lực?", "powertrain"),
            ("Mô men xoắn cực đại của xe?", "powertrain"),
            ("Thời gian tăng tốc 0-100 km/h mất mấy giây?", "powertrain"),
            ("Tốc độ tối đa của VF 9", "powertrain"),
            ("Xe này dẫn động cầu trước hay AWD?", "powertrain"),
            # Dimension
            ("Kích thước dài rộng cao của VF 6?", "dimension"),
            ("Khoảng sáng gầm xe là bao nhiêu mm?", "dimension"),
            ("Chiều dài cơ sở của VF 8", "dimension"),
            ("Dung tích cốp xe bao nhiêu lít?", "dimension"),
            ("Trọng lượng xe VF 3", "dimension"),
            # Safety
            ("Xe có mấy túi khí an toàn?", "safety"),
            ("Hệ thống phanh ABS và cân bằng điện tử ESC", "safety"),
            ("Xe có camera 360 độ không?", "safety"),
            ("Hệ thống phanh khẩn cấp tự động", "safety"),
            # Interior
            ("VF 8 có cửa sổ trời toàn cảnh không?", "interior"),
            ("Xe có mấy chỗ ngồi?", "interior"),
            ("Màn hình giải trí bao nhiêu inch?", "interior"),
            ("Hệ thống điều hòa và số lượng loa", "interior"),
            ("Xe có hiển thị HUD trên kính lái không?", "interior"),
            ("Ghế có tính năng sưởi và massage không?", "interior"),
            # Exterior
            ("Hệ thống đèn LED phía trước", "exterior"),
            ("Mâm xe la-zăng bao nhiêu inch?", "exterior"),
            ("Màu sơn ngoại thất xe", "exterior"),
            ("Gương chiếu hậu chỉnh điện", "exterior"),
            # ADAS
            ("Hệ thống hỗ trợ lái ADAS cấp độ mấy?", "adas"),
            ("Tính năng ga tự động thích ứng cruise control", "adas"),
            ("Tính năng hỗ trợ giữ làn và điểm mù", "adas"),
            # Security
            ("Hệ thống chống trộm và định vị xe", "security"),
            ("Khóa điện tử thông minh", "security"),
            # Chassis
            ("Hệ thống treo trước và khung gầm", "chassis"),
            ("Hệ thống trợ lực lái", "chassis"),
            # Multi-category (None)
            ("Các tính năng tiện nghi nổi bật", None),
            ("Trang bị giải trí và kết nối thông minh", None),
            ("Ứng dụng điều khiển từ xa qua app", None),
        ],
    )
    def test_extract_spec_category(self, query: str, expected_cat: str | None):
        assert extract_spec_category(query) == expected_cat


class TestExtractSpecKey:
    """Test deterministic mapping to specific spec keys for feature presence."""

    @pytest.mark.parametrize(
        ("query", "expected_key"),
        [
            ("VF 8 có cửa sổ trời không?", "sunroof_type"),
            ("Xe có bao nhiêu túi khí?", "airbags"),
            ("Công suất động cơ bao nhiêu mã lực?", "power_kw"),
            ("Mô men xoắn của xe là bao nhiêu?", "torque_nm"),
            ("Tầm di chuyển được bao nhiêu km?", "range_km"),
            ("Dung lượng pin là bao nhiêu?", "battery_kwh"),
            ("Thời gian sạc nhanh bao lâu?", "fast_charge_min"),
            ("Khả năng tăng tốc 0-100 giây?", "acceleration_0_100_s"),
            ("Vận tốc tối đa của xe?", "top_speed_kmh"),
            ("Xe dẫn động 2 cầu AWD hay FWD?", "drivetrain"),
            ("Chiều dài xe bao nhiêu mm?", "length_mm"),
            ("Chiều rộng xe?", "width_mm"),
            ("Chiều cao của VF 6?", "height_mm"),
            ("Trục cơ sở xe?", "wheelbase_mm"),
            ("Khoảng sáng gầm xe?", "ground_clearance_mm"),
            ("Cân nặng trọng lượng xe?", "curb_weight_kg"),
            ("Xe có mấy chỗ ngồi?", "seats"),
            ("Xe có HUD hiển thị kính lái không?", "head_up_display"),
            ("Có camera 360 toàn cảnh không?", "surround_view_camera"),
            ("Xe có ghế da không?", "leatherette_seats"),
            ("Hệ thống có mấy loa?", "speakers"),
            ("Màn hình trung tâm bao nhiêu inch?", "display_inch"),
            ("Hệ thống điều hòa mấy vùng?", "ac_type"),
            ("Dung tích cốp xe?", "trunk_capacity"),
            ("Kích thước mâm xe la-zăng?", "wheel_size_inch"),
            ("Câu hỏi chung chung không có spec key", None),
        ],
    )
    def test_extract_spec_key(self, query: str, expected_key: str | None):
        assert extract_spec_key(query) == expected_key


class TestClassifyIntent:
    """Test rule-based intent classification for all 14 intents."""

    def test_greeting(self):
        assert classify_intent("Xin chào") == "greeting"
        assert classify_intent("chào bạn") == "greeting"
        assert classify_intent("Hello Vivu!") == "greeting"
        assert classify_intent("Hi") == "greeting"

    def test_thanks(self):
        assert classify_intent("Cảm ơn bạn nhé") == "thanks"
        assert classify_intent("Thank you") == "thanks"
        assert classify_intent("Tạm biệt") == "thanks"
        assert classify_intent("bye") == "thanks"

    def test_identity(self):
        assert classify_intent("Bạn là ai?") == "identity"
        assert classify_intent("Vivu là ai?") == "identity"
        assert classify_intent("Giới thiệu bản thân") == "identity"
        assert classify_intent("Bạn có chức năng gì?") == "identity"

    def test_price(self):
        assert classify_intent("VF 8 giá bao nhiêu?") == "price"
        assert classify_intent("Giá niêm yết của xe VF 3") == "price"
        assert classify_intent("Mua xe hết bao nhiêu tiền?") == "price"

    def test_compare(self):
        assert classify_intent("So sánh VF 6 và VF 7") == "compare"
        assert classify_intent("VF 8 vs VF 9 khác gì nhau?") == "compare"
        assert classify_intent("Nên mua VF 3 hay VF 5?") == "compare"

    def test_cross_model_feature(self):
        assert classify_intent("Xe nào có camera 360?") == "cross_model_feature"
        assert classify_intent("Những xe nào có cửa sổ trời?") == "cross_model_feature"

    def test_feature_presence(self):
        assert classify_intent("VF 8 có túi khí không?") == "feature_presence"
        assert classify_intent("VF 6 có sạc không dây ko?") == "feature_presence"

    def test_models_list(self):
        assert classify_intent("Danh sách các mẫu xe VinFast") == "models_list"
        assert classify_intent("VinFast đang bán những xe nào?") == "models_list"

    def test_versions_list(self):
        assert classify_intent("VF 8 có mấy phiên bản?") == "versions_list"
        assert classify_intent("VF 7 có những bản nào?") == "versions_list"

    def test_colors(self):
        assert classify_intent("VF 3 có những màu sơn nào?") == "colors"
        assert classify_intent("Màu sắc ngoại thất VF 8") == "colors"

    def test_utility(self):
        assert classify_intent("Tìm showroom gần nhất") == "utility"
        assert classify_intent("Đặt lịch bảo dưỡng xe") == "utility"
        assert classify_intent("Đăng ký lái thử VF 8") == "utility"
        assert classify_intent("Dự toán trả góp xe") == "utility"
        assert classify_intent("Hotline VinFast là gì?") == "utility"

    def test_policy(self):
        assert classify_intent("Chính sách bảo hành pin xe điện") == "policy"
        assert classify_intent("Quy định dịch vụ cứu hộ") == "policy"
        assert classify_intent("Điều khoản đặt cọc xe") == "policy"

    def test_out_of_scope(self):
        assert classify_intent("Thời tiết hôm nay thế nào?") == "out_of_scope"
        assert classify_intent("Viết code Python quicksort") == "out_of_scope"
        assert classify_intent("Cách nấu phở bò ngon") == "out_of_scope"
        assert classify_intent("Tin tức chứng khoán") == "out_of_scope"

    def test_spec_query_from_topic(self):
        assert classify_intent("kích thước thế nào", topic="kích_thước") == "spec_query"

    def test_general_fallback(self):
        assert classify_intent("tôi muốn tìm hiểu một vài điều") == "general"


class TestValidateLLMResult:
    """Test LLM classification output validation."""

    def test_valid_result(self):
        data = {
            "intent": "price",
            "model_code": "VF 8",
            "version": "Plus",
            "spec_category": "powertrain",
        }
        res = _validate_llm_result(data)
        assert res is not None
        assert res["intent"] == "price"
        assert res["model_code"] == "VF 8"
        assert res["version"] == "Plus"
        assert res["spec_category"] == "powertrain"

    def test_invalid_intent_rejected(self):
        data = {"intent": "invalid_intent_name", "model_code": "VF 8"}
        assert _validate_llm_result(data) is None

    def test_invalid_spec_category_filtered(self):
        data = {"intent": "spec_query", "model_code": "VF 8", "spec_category": "non_existent_category"}
        res = _validate_llm_result(data)
        assert res is not None
        assert res["spec_category"] is None


class TestLLMClassifyFallback:
    """Test LLM classification fallback with mock."""

    @pytest.mark.asyncio
    async def test_fallback_success(self, mock_llm_client):
        res = await llm_classify_fallback("Hỏi giá xe", [])
        assert res is not None
        assert res["intent"] == "price"
        assert res["model_code"] == "VF 8"

    @pytest.mark.asyncio
    async def test_fallback_exception_handling(self, monkeypatch):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("LLM connection error")
        monkeypatch.setattr("app.agent.llm.get_llm", lambda: client)

        res = await llm_classify_fallback("query", [])
        assert res is None
