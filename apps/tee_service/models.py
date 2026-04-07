from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Tuple

from shared.schemas import validate_feature_specs


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    display_name: str
    model_version: str
    backend: str
    summary: str
    description: str
    input_features: Tuple["FeatureSpecRecord", ...]
    output_spec: "OutputSpecRecord"
    artifact_uri: Path
    artifact_sha256: str


@dataclass(frozen=True)
class FeatureSpecRecord:
    name: str
    label: str
    type: str
    unit: str
    description: str
    allowed_values: Tuple[str, ...]


@dataclass(frozen=True)
class OutputSpecRecord:
    name: str
    label: str
    type: str
    description: str
    range_min: float
    range_max: float


class ModelRegistry:
    def __init__(self, registry_path: Path):
        self._registry_path = registry_path
        self._models = self._load_registry(registry_path)

    def list_models(self) -> List[ModelRecord]:
        return list(self._models.values())

    def get(self, model_id: str) -> ModelRecord:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise KeyError(f"unknown model_id: {model_id}") from exc

    def _load_registry(self, registry_path: Path) -> Dict[str, ModelRecord]:
        data = json.loads(registry_path.read_text())
        models: Dict[str, ModelRecord] = {}
        for item in data["models"]:
            artifact_path = Path(item["artifact_uri"])
            if not artifact_path.is_absolute():
                artifact_path = registry_path.parent / artifact_path
            digest = sha256(artifact_path.read_bytes()).hexdigest()
            if digest != item["artifact_sha256"]:
                raise ValueError(f"artifact digest mismatch for {item['model_id']}")
            input_features = self._parse_input_features(item["input_features"])
            output_spec = self._parse_output_spec(item["output_spec"])
            record = ModelRecord(
                model_id=item["model_id"],
                display_name=item["display_name"],
                model_version=item["model_version"],
                backend=item["backend"],
                summary=item["summary"],
                description=item["description"],
                input_features=input_features,
                output_spec=output_spec,
                artifact_uri=artifact_path,
                artifact_sha256=item["artifact_sha256"],
            )
            models[record.model_id] = record
        return models

    @staticmethod
    def _parse_input_features(items: list[dict]) -> Tuple[FeatureSpecRecord, ...]:
        features = tuple(
            FeatureSpecRecord(
                name=item["name"],
                label=item["label"],
                type=item["type"],
                unit=item["unit"],
                description=item["description"],
                allowed_values=tuple(str(value) for value in item.get("allowed_values", [])),
            )
            for item in items
        )
        validate_feature_specs(features)
        return features

    @staticmethod
    def _parse_output_spec(item: dict) -> OutputSpecRecord:
        output = OutputSpecRecord(
            name=item["name"],
            label=item["label"],
            type=item["type"],
            description=item["description"],
            range_min=float(item["range_min"]),
            range_max=float(item["range_max"]),
        )
        if output.range_min > output.range_max:
            raise ValueError("output_spec range_min must be less than or equal to range_max")
        if output.type != "number":
            raise ValueError("output_spec.type must be number")
        return output
