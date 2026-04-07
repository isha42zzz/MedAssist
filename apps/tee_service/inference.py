from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict

import onnxruntime as ort

from shared.schemas import encode_model_input

from .models import ModelRecord, ModelRegistry


class InferenceService:
    def __init__(self, registry: ModelRegistry):
        self._registry = registry
        self._sessions: Dict[str, ort.InferenceSession] = {}
        for model in registry.list_models():
            if model.backend != "onnxruntime":
                raise ValueError(f"unsupported backend: {model.backend}")
            self._sessions[model.model_id] = ort.InferenceSession(
                str(model.artifact_uri),
                providers=["CPUExecutionProvider"],
            )

    def run(self, model_id: str, request_input: Mapping[str, Any]) -> tuple[ModelRecord, float]:
        model = self._registry.get(model_id)
        session = self._sessions[model_id]
        input_name = session.get_inputs()[0].name
        feature_vector = encode_model_input(model.input_features, request_input)
        output = session.run(None, {input_name: feature_vector})
        score = float(output[0].reshape(-1)[0])
        return model, score
