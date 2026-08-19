"""Unit tests for app.agent.classifier module."""

import pytest

from app.agent.classifier import (
    ClassifyResult,
    QueryClassifier,
    _normalize_version,
    get_classifier,
    normalize_model,
)


class TestNormalizeModel:
    """Test model name normalization rules."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("vf3", "VF 3"),
            ("VF3", "VF 3"),
            ("vf 3", "VF 3"),
            ("vf5", "VF 5"),
            ("vf6", "VF 6"),
            ("vf7", "VF 7"),
            ("vf8", "VF 8"),
            ("VF8", "VF 8"),
            ("vf 8", "VF 8"),
            ("vf9", "VF 9"),
            ("vf e34", "VF E34"),
            ("vfe34", "VF E34"),
            # All New / New / The New / Thế hệ mới variants -> "VF 8 All New"
            ("vf8 all new", "VF 8 All New"),
            ("VF 8 All New", "VF 8 All New"),
            ("vf 8 all new", "VF 8 All New"),
            ("vf 8 new", "VF 8 All New"),
            ("VF 8 New", "VF 8 All New"),
            ("VF 8 The New", "VF 8 All New"),
            ("vf 8 the all new", "VF 8 All New"),
            ("vf 8 thế hệ mới", "VF 8 All New"),
            ("vf 8 the he moi", "VF 8 All New"),
            ("vf8 thế hệ mới", "VF 8 All New"),
            # MPV
            ("vf mpv 7", "VF MPV 7"),
            ("vf mpv7", "VF MPV 7"),
            ("VF MPV 7", "VF MPV 7"),
            ("vfmpv7", "VF MPV 7"),
            # Green series
            ("herio green", "Herio Green"),
            ("minio green", "Minio Green"),
            ("limo green", "Limo Green"),
            ("ec van", "Ec Van"),
            ("nerio green", "Nerio Green"),
        ],
    )
    def test_normalize_model_variations(self, raw: str, expected: str):
        assert normalize_model(raw) == expected


class TestNormalizeVersion:
    """Test version alias normalization."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("eco", "Eco"),
            ("ECO", "Eco"),
            ("bản eco", "Eco"),
            ("ban eco", "Eco"),
            ("plus", "Plus"),
            ("PLUS", "Plus"),
            ("bản plus", "Plus"),
            ("tiêu chuẩn", "TieuChuan"),
            ("tieuchuan", "TieuChuan"),
            ("tiêu_chuẩn", "TieuChuan"),
            ("nâng cao", "NangCao"),
            ("nangcao", "NangCao"),
            ("cao cấp", "CaoCap"),
            ("caocap", "CaoCap"),
            ("pluscaptain", "PlusCaptain"),
            ("plus captain", "PlusCaptain"),
            ("the all new", "The All New"),
            ("all new", "The All New"),
            ("thenew", "The All New"),
            ("the new", "The All New"),
            ("new", "The All New"),
            ("thế hệ mới", "The All New"),
            ("the he moi", "The All New"),
            ("plus awd", "Plus AWD"),
            ("plusawd", "Plus AWD"),
        ],
    )
    def test_version_aliases(self, raw: str, expected: str):
        assert _normalize_version(raw) == expected

    def test_unknown_version_returns_none(self):
        assert _normalize_version("unknown_ver") is None
        assert _normalize_version("") is None


class TestQueryClassifier:
    """Test QueryClassifier detection and classify methods."""

    def test_detect_model_found(self):
        classifier = QueryClassifier()
        clean, raw = classifier._detect_model("VF 8 Plus giá bao nhiêu?")
        assert clean == "VF 8"
        assert raw == "VF 8"

    def test_detect_model_all_new(self):
        classifier = QueryClassifier()
        clean, raw = classifier._detect_model("Thông số xe vf 8 all new")
        assert clean == "VF 8 All New"

    def test_detect_model_not_found(self):
        classifier = QueryClassifier()
        clean, raw = classifier._detect_model("Xe nào có camera 360?")
        assert clean is None
        assert raw is None

    def test_classify_with_model_and_version(self):
        classifier = QueryClassifier()
        res = classifier.classify("VF 8 Plus pin bao nhiêu kWh?")
        assert isinstance(res, ClassifyResult)
        assert res.decision == "answer"
        assert res.reason == "proceed to retrieval"
        assert res.specificity == "clear"
        assert res.entities.get("model_code") == "VF 8"
        assert res.entities.get("version") == "Plus"

    def test_classify_with_model_only(self):
        classifier = QueryClassifier()
        res = classifier.classify("Giá xe VF 3?")
        assert res.specificity == "clear"
        assert res.entities.get("model_code") == "VF 3"
        assert "version" not in res.entities

    def test_classify_without_model(self):
        classifier = QueryClassifier()
        res = classifier.classify("Xe nào có 7 chỗ?")
        assert res.specificity == "unclear"
        assert "model_code" not in res.entities

    def test_get_classifier_singleton(self):
        c1 = get_classifier()
        c2 = get_classifier()
        assert c1 is c2
        assert isinstance(c1, QueryClassifier)
