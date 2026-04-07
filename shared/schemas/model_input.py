from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import numpy as np


MODEL_FEATURE_TYPES = {"number", "enum", "binary"}


class FeatureSpecLike(Protocol):
    name: str
    type: str
    allowed_values: Sequence[str]


def validate_feature_specs(features: Sequence[FeatureSpecLike]) -> None:
    seen_names: set[str] = set()
    for feature in features:
        if feature.name in seen_names:
            raise ValueError(f"duplicate input feature name: {feature.name}")
        seen_names.add(feature.name)
        if feature.type not in MODEL_FEATURE_TYPES:
            raise ValueError(f"unsupported feature type: {feature.type}")
        if feature.type == "number":
            if feature.allowed_values:
                raise ValueError(f"feature {feature.name} must not define allowed_values")
            continue
        if not feature.allowed_values:
            raise ValueError(f"feature {feature.name} must define allowed_values")
        if len(set(feature.allowed_values)) != len(tuple(feature.allowed_values)):
            raise ValueError(f"feature {feature.name} allowed_values must be unique")


def encode_model_input(features: Sequence[FeatureSpecLike], raw_input: Mapping[str, Any]) -> np.ndarray:
    if not isinstance(raw_input, Mapping):
        raise ValueError("input must be an object")
    unknown_fields = sorted(set(raw_input.keys()) - {feature.name for feature in features})
    if unknown_fields:
        raise ValueError(f"unknown input features: {', '.join(unknown_fields)}")

    values: list[float] = []
    for feature in features:
        if feature.name not in raw_input:
            raise ValueError(f"missing input feature: {feature.name}")
        value = raw_input[feature.name]
        if feature.type == "number":
            values.append(_coerce_number(feature.name, value))
            continue
        values.append(_encode_categorical(feature, value))
    return np.asarray([values], dtype=np.float32)


def _coerce_number(feature_name: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"feature {feature_name} must be a number") from exc


def _encode_categorical(feature: FeatureSpecLike, value: Any) -> float:
    allowed_values = tuple(str(item) for item in feature.allowed_values)
    normalized = _normalize_allowed_value(value, allowed_values)
    try:
        return float(allowed_values.index(normalized))
    except ValueError as exc:
        joined = ", ".join(allowed_values)
        raise ValueError(f"feature {feature.name} must be one of: {joined}") from exc


def _normalize_allowed_value(value: Any, allowed_values: Sequence[str]) -> str:
    candidates: list[str] = []
    if isinstance(value, bool):
        candidates.extend(("1" if value else "0", "true" if value else "false"))
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric.is_integer():
            candidates.append(str(int(numeric)))
        candidates.append(str(numeric))
    else:
        text = str(value).strip()
        candidates.append(text)
    lowered_map = {item.lower(): item for item in allowed_values}
    for candidate in candidates:
        if candidate in allowed_values:
            return candidate
        lowered = candidate.lower()
        if lowered in lowered_map:
            return lowered_map[lowered]
    if candidates:
        return candidates[0]
    return str(value)
