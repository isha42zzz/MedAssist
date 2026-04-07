import numpy as np
import pytest

from apps.tee_service.models import FeatureSpecRecord
from shared.schemas import encode_model_input, validate_feature_specs


def test_encode_model_input_uses_feature_order_and_allowed_value_order():
    features = (
        FeatureSpecRecord("height", "Height", "number", "cm", "Height in centimeters.", ()),
        FeatureSpecRecord("severity", "Severity", "enum", "category", "Severity level.", ("low", "medium", "high")),
        FeatureSpecRecord("flag", "Flag", "binary", "flag", "Binary flag.", ("0", "1")),
    )

    vector = encode_model_input(
        features,
        {
            "height": 172,
            "severity": "high",
            "flag": 1,
        },
    )

    assert vector.dtype == np.float32
    assert vector.tolist() == [[172.0, 2.0, 1.0]]


def test_encode_model_input_rejects_missing_feature():
    features = (
        FeatureSpecRecord("height", "Height", "number", "cm", "Height in centimeters.", ()),
    )

    with pytest.raises(ValueError, match="missing input feature: height"):
        encode_model_input(features, {})


def test_encode_model_input_rejects_unknown_feature():
    features = (
        FeatureSpecRecord("height", "Height", "number", "cm", "Height in centimeters.", ()),
    )

    with pytest.raises(ValueError, match="unknown input features: extra"):
        encode_model_input(features, {"height": 170, "extra": 1})


def test_encode_model_input_rejects_invalid_number():
    features = (
        FeatureSpecRecord("height", "Height", "number", "cm", "Height in centimeters.", ()),
    )

    with pytest.raises(ValueError, match="feature height must be a number"):
        encode_model_input(features, {"height": "abc"})


def test_encode_model_input_rejects_invalid_enum_value():
    features = (
        FeatureSpecRecord("severity", "Severity", "enum", "category", "Severity level.", ("low", "high")),
    )

    with pytest.raises(ValueError, match="feature severity must be one of: low, high"):
        encode_model_input(features, {"severity": "medium"})


def test_validate_feature_specs_rejects_duplicate_names():
    features = (
        FeatureSpecRecord("height", "Height", "number", "cm", "Height in centimeters.", ()),
        FeatureSpecRecord("height", "Height Again", "number", "cm", "Duplicate feature.", ()),
    )

    with pytest.raises(ValueError, match="duplicate input feature name: height"):
        validate_feature_specs(features)
