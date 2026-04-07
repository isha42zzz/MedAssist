import json

import pytest
from google.protobuf.struct_pb2 import Struct

from apps.tee_service.inference import InferenceService
from apps.tee_service.models import ModelRegistry
from apps.tee_service.sessions import SessionStore
from apps.tee_service.tee_session_server import DiagnosisService
from scripts.build_demo_onnx import build_demo_model
from shared.proto import diagnosis_pb2
from tests.model_fixtures import demo_registry_payload


def test_model_registry_loads_metadata_and_output_semantics(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(demo_registry_payload(model_path)))

    registry = ModelRegistry(registry_path)
    model = registry.get("cardio-risk-v1")

    assert model.display_name == "Cardio Risk v1"
    assert model.summary.startswith("Structured heart disease risk model")
    assert tuple(feature.name for feature in model.input_features) == (
        "age",
        "sex",
        "chest_pain_type",
        "resting_bp",
        "cholesterol",
        "fasting_blood_sugar",
        "max_heart_rate",
        "exercise_angina",
        "oldpeak",
    )
    assert model.output_spec.name == "risk_score"
    assert model.output_spec.range_min == 0.0
    assert model.output_spec.range_max == 1.0
    assert "lower values indicate lower risk" in model.output_spec.description


def test_model_registry_accepts_non_cardio_feature_names(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    payload["models"][0]["input_features"] = [
        {
            "name": "feature_a",
            "label": "Feature A",
            "type": "number",
            "unit": "unitless",
            "description": "Generic numeric feature.",
            "allowed_values": [],
        },
        {
            "name": "feature_b",
            "label": "Feature B",
            "type": "enum",
            "unit": "category",
            "description": "Generic categorical feature.",
            "allowed_values": ["alpha", "beta"],
        },
        {
            "name": "feature_c",
            "label": "Feature C",
            "type": "binary",
            "unit": "flag",
            "description": "Generic binary feature.",
            "allowed_values": ["0", "1"],
        },
    ]
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload))

    registry = ModelRegistry(registry_path)

    assert [feature.name for feature in registry.get("cardio-risk-v1").input_features] == [
        "feature_a",
        "feature_b",
        "feature_c",
    ]


def test_model_registry_accepts_non_risk_score_output_name(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    payload["models"][0]["output_spec"]["name"] = "probability"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload))

    registry = ModelRegistry(registry_path)

    assert registry.get("cardio-risk-v1").output_spec.name == "probability"


def test_model_registry_rejects_duplicate_model_ids(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    duplicate = json.loads(json.dumps(payload["models"][0]))
    duplicate["summary"] = "duplicate entry"
    payload["models"].append(duplicate)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="duplicate model_id: cardio-risk-v1"):
        ModelRegistry(registry_path)


def test_model_registry_rejects_duplicate_feature_names(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    payload["models"][0]["input_features"][1]["name"] = "age"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="duplicate input feature name: age"):
        ModelRegistry(registry_path)


def test_model_registry_rejects_number_feature_with_allowed_values(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    payload["models"][0]["input_features"][0]["allowed_values"] = ["1", "2"]
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="feature age must not define allowed_values"):
        ModelRegistry(registry_path)


def test_model_registry_rejects_enum_without_allowed_values(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    payload["models"][0]["input_features"][1]["allowed_values"] = []
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="feature sex must define allowed_values"):
        ModelRegistry(registry_path)


def test_model_registry_resolves_relative_artifact_uri_from_registry_directory(tmp_path):
    registry_dir = tmp_path / "deployment"
    registry_dir.mkdir()
    model_path = registry_dir / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    payload = demo_registry_payload(model_path)
    payload["models"][0]["artifact_uri"] = "cardio-risk-v1.onnx"
    registry_path = registry_dir / "registry.json"
    registry_path.write_text(json.dumps(payload))

    registry = ModelRegistry(registry_path)

    assert registry.get("cardio-risk-v1").artifact_uri == model_path


def test_diagnosis_service_returns_model_catalog_and_describe_model_metadata(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(demo_registry_payload(model_path)))

    registry = ModelRegistry(registry_path)
    inference = InferenceService(registry)
    sessions = SessionStore(ttl_seconds=300)
    service = DiagnosisService(sessions=sessions, registry=registry, inference=inference)

    record = sessions.create(
        hospital_org_id="hospital-a",
        nonce=b"nonce",
        hospital_ephemeral_pubkey=b"hospital-pubkey",
        tee_ephemeral_pubkey=b"tee-pubkey",
        expected_user_data_hex="abcd",
        attestation_report=b"report",
    )
    sessions.mark_open(record.session_id)

    catalog_response, should_close = service.dispatch(
        record.session_id,
        diagnosis_pb2.SecureRequest(
            get_model_catalog=diagnosis_pb2.GetModelCatalogRequest(session_id=record.session_id)
        ),
    )
    assert should_close is False
    assert catalog_response.get_model_catalog.models[0].display_name == "Cardio Risk v1"
    assert "Structured heart disease risk model" in catalog_response.get_model_catalog.models[0].summary

    describe_response, should_close = service.dispatch(
        record.session_id,
        diagnosis_pb2.SecureRequest(
            describe_model=diagnosis_pb2.DescribeModelRequest(
                session_id=record.session_id,
                model_id="cardio-risk-v1",
            )
        ),
    )
    assert should_close is False
    assert describe_response.describe_model.output_spec.name == "risk_score"
    assert describe_response.describe_model.output_spec.range_min == 0.0
    assert describe_response.describe_model.output_spec.range_max == 1.0
    assert "lower values indicate lower risk" in describe_response.describe_model.output_spec.description
    assert describe_response.describe_model.input_features[0].name == "age"
    assert describe_response.describe_model.input_features[1].allowed_values == ["female", "male"]

    request_input = Struct()
    request_input.update(
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
        }
    )
    run_response, should_close = service.dispatch(
        record.session_id,
        diagnosis_pb2.SecureRequest(
            run_inference=diagnosis_pb2.RunInferenceRequest(
                session_id=record.session_id,
                request_id="req-1",
                model_id="cardio-risk-v1",
                input=request_input,
            )
        ),
    )
    assert should_close is False
    assert run_response.run_inference.output_name == "risk_score"
    assert 0.0 <= run_response.run_inference.output_value <= 1.0


def test_describe_model_requires_attested_session(tmp_path):
    model_path = tmp_path / "cardio-risk-v1.onnx"
    build_demo_model(model_path)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(demo_registry_payload(model_path)))

    registry = ModelRegistry(registry_path)
    inference = InferenceService(registry)
    sessions = SessionStore(ttl_seconds=300)
    service = DiagnosisService(sessions=sessions, registry=registry, inference=inference)

    record = sessions.create(
        hospital_org_id="hospital-a",
        nonce=b"nonce",
        hospital_ephemeral_pubkey=b"hospital-pubkey",
        tee_ephemeral_pubkey=b"tee-pubkey",
        expected_user_data_hex="abcd",
        attestation_report=b"report",
    )

    with pytest.raises(PermissionError, match="session has not completed attested handshake"):
        service.dispatch(
            record.session_id,
            diagnosis_pb2.SecureRequest(
                describe_model=diagnosis_pb2.DescribeModelRequest(
                    session_id=record.session_id,
                    model_id="cardio-risk-v1",
                )
            ),
        )
