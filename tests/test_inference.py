import json

from apps.tee_service.inference import InferenceService
from apps.tee_service.models import ModelRegistry
from scripts.build_demo_onnx import build_demo_model
from tests.model_fixtures import demo_registry_payload


def test_inference_service_runs_demo_onnx(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(demo_registry_payload(model_path)))
    registry = ModelRegistry(registry_path)
    inference = InferenceService(registry)
    model, score = inference.run(
        "cardio-risk-v1",
        {
            "age": 63,
            "sex": "male",
            "chest_pain_type": "asymptomatic",
            "resting_bp": 145,
            "cholesterol": 233,
            "fasting_blood_sugar": 1,
            "max_heart_rate": 150,
            "exercise_angina": 0,
            "oldpeak": 2.3,
        },
    )
    assert model.model_id == "cardio-risk-v1"
    assert 0.0 <= score <= 1.0
