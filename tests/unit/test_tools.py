from unittest.mock import AsyncMock

import pytest

from app.agent.tools import (
    TOOL_REGISTRY,
    _model_id,
    ask_clarification,
    get_active_promotions,
    get_booking_link,
    get_colors,
    get_loan_estimate_link,
    get_maintenance_link,
    get_onroad_cost_link,
    get_price,
    get_showroom_charging_link,
    get_specs,
    list_available_models,
    search_knowledge_base,
)


class TestModelIdMapping:
    """Test model code to compact DB model ID mapping."""

    @pytest.mark.parametrize(
        ("model_code", "expected_id"),
        [
            ("VF 8 All New", "VF8NEW"),
            ("vf8 all new", "VF8NEW"),
            ("VF 8 The All New", "VF8NEW"),
            ("vf 8 new", "VF8NEW"),
            ("VF MPV 7", "VFMPV7"),
            ("vf mpv7", "VFMPV7"),
            ("VF 8", "VF8"),
            ("vf 8", "VF8"),
            ("vf3", "VF3"),
            ("VF 9", "VF9"),
            ("VF e34", "VFE34"),
        ],
    )
    def test_model_id_mapping(self, model_code: str, expected_id: str):
        assert _model_id(model_code) == expected_id


class TestGetPrice:
    """Test get_price tool with mock database and cache."""

    @pytest.mark.asyncio
    async def test_get_price_success(self, mock_db_pool, mock_redis):
        res = await get_price("VF 8")
        assert res["model_code"] == "VF 8"
        assert len(res["prices"]) == 2
        assert res["prices"][0]["version_name"] == "Eco"
        assert res["prices"][1]["version_name"] == "Plus"
        assert len(res["related_models"]) > 0

    @pytest.mark.asyncio
    async def test_get_price_with_version(self, mock_db_pool, mock_redis):
        res = await get_price("VF 8", version="Plus")
        assert res["model_code"] == "VF 8"
        assert len(res["prices"]) > 0

    @pytest.mark.asyncio
    async def test_get_price_db_error_graceful(self, mock_redis, monkeypatch):
        monkeypatch.setattr("app.core.storage.db.get_pool", AsyncMock(side_effect=Exception("DB down")))
        res = await get_price("VF 888 DB Error")
        assert res["model_code"] == "VF 888 DB Error"
        assert res["prices"] == []
        assert res["source_url"] == ""


class TestGetColors:
    """Test get_colors tool."""

    @pytest.mark.asyncio
    async def test_get_colors_success(self, mock_db_pool, mock_redis):
        res = await get_colors("VF 8")
        assert res["model_code"] == "VF 8"
        assert "Trắng" in res["colors"]
        assert "Đỏ" in res["colors"]
        assert "Đen" in res["interiors"]
        assert "Nâu" in res["interiors"]
        assert len(res["variants"]) == 2

    @pytest.mark.asyncio
    async def test_get_colors_empty_rows(self, mock_db_conn, mock_db_pool, mock_redis):
        mock_db_conn.fetch = AsyncMock(return_value=[])

        res = await get_colors("VF Unknown")
        assert res["colors"] == []
        assert res["interiors"] == []
        assert res["variants"] == []


class TestGetSpecs:
    """Test get_specs tool."""

    @pytest.mark.asyncio
    async def test_get_specs_success(self, mock_db_pool, mock_redis):
        res = await get_specs("VF 8")
        assert res["model_code"] == "VF 8"
        assert len(res["specs"]) == 3
        keys = [s["key"] for s in res["specs"]]
        assert "battery_kwh" in keys
        assert "power_kw" in keys
        assert "sunroof_type" in keys

    @pytest.mark.asyncio
    async def test_get_specs_filters_khong_sentinel(self, mock_db_conn, mock_db_pool, mock_redis):
        rows = [
            {
                "version_name": None,
                "version_code": None,
                "spec_category": "interior",
                "spec_key": "sunroof_type",
                "spec_value": "Không",
                "spec_unit": "",
                "source_url": "https://vinfastauto.com",
                "page": "",
            },
            {
                "version_name": "Eco",
                "version_code": "VF8_ECO",
                "spec_category": "battery",
                "spec_key": "battery_kwh",
                "spec_value": "87.7",
                "spec_unit": "kWh",
                "source_url": "https://vinfastauto.com",
                "page": "",
            },
        ]
        mock_db_conn.fetch = AsyncMock(side_effect=[rows, [{"model_code": "VF 9"}]])

        res = await get_specs("VF 8 Sentinel Unique")
        assert len(res["specs"]) == 1
        assert res["specs"][0]["key"] == "battery_kwh"


class TestSearchKnowledgeBase:
    """Test search_knowledge_base tool with hybrid_search mock."""

    @pytest.mark.asyncio
    async def test_search_kb_filters_low_scores(self, monkeypatch):
        mock_hybrid = AsyncMock(
            return_value=[
                {
                    "id": "chunk-1",
                    "text": "Thông tin bảo hành 10 năm pin VF 8",
                    "model_id": "VF8",
                    "text_type": "policy",
                    "source_type": "warranty",
                    "source_url": "https://vinfastauto.com/bao-hanh",
                    "page": "1",
                    "section": "Pin",
                    "score": 0.85,
                },
                {
                    "id": "chunk-2",
                    "text": "Nội dung nhiễu score thấp",
                    "model_id": "VF8",
                    "text_type": "other",
                    "source_type": "forum",
                    "source_url": "",
                    "score": 0.15,
                },
            ]
        )
        monkeypatch.setattr("app.core.rag.retrieval.hybrid_search", mock_hybrid)

        res = await search_knowledge_base("chính sách bảo hành pin VF 8", model_id="VF 8")
        assert res["query"] == "chính sách bảo hành pin VF 8"
        assert len(res["results"]) == 1
        assert res["results"][0]["id"] == "chunk-1"


class TestListAvailableModels:
    """Test list_available_models tool."""

    @pytest.mark.asyncio
    async def test_list_available_models(self, mock_db_pool, mock_redis):
        res = await list_available_models()
        assert "models" in res
        assert len(res["models"]) >= 2
        vf8 = next((m for m in res["models"] if m["model_id"] == "VF8"), None)
        assert vf8 is not None
        assert "Eco" in vf8["versions"]
        assert "Plus" in vf8["versions"]


class TestUtilityTools:
    """Test utility links and clarification tools."""

    @pytest.mark.asyncio
    async def test_utility_links(self):
        promos = await get_active_promotions()
        assert "https://shop.vinfastauto.com" in promos["url"]

        onroad = await get_onroad_cost_link()
        assert "chi-phi-lan-banh" in onroad["url"]

        loan = await get_loan_estimate_link()
        assert len(loan["links"]) == 2

        charging = await get_showroom_charging_link()
        assert "tim-kiem-showroom-tram-sac" in charging["url"]

        booking_maint = await get_booking_link("maintenance")
        assert "dat-lich-dich-vu-bao-duong" in booking_maint["url"]

        booking_drive = await get_booking_link("test_drive")
        assert "dang-ky-lai-thu" in booking_drive["url"]

        maint_link = await get_maintenance_link("VF 8", 2024)
        assert len(maint_link["links"]) == 1

    @pytest.mark.asyncio
    async def test_ask_clarification(self):
        res = await ask_clarification(model_id="VF 8")
        assert res["action"] == "clarify"
        assert res["model_id"] == "VF 8"
        assert "VF 8" in res["message"]
        assert "pin_sạc" in res["available_categories"]


class TestToolRegistry:
    """Test TOOL_REGISTRY completeness."""

    def test_registry_contains_all_tools(self):
        expected_tools = {
            "get_price",
            "get_colors",
            "get_specs",
            "search_knowledge_base",
            "list_available_models",
            "get_active_promotions",
            "get_onroad_cost_link",
            "get_loan_estimate_link",
            "get_showroom_charging_link",
            "get_booking_link",
            "get_maintenance_link",
            "ask_clarification",
        }
        assert set(TOOL_REGISTRY.keys()) == expected_tools
