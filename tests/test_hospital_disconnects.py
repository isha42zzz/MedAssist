from types import SimpleNamespace

import pytest

from apps.hospital_mcp.server import HospitalGateway
from apps.hospital_mcp.tee_session_client import AttestedSession, SessionDisconnectedError
from apps.hospital_mcp.config import HospitalMCPConfig
from shared.secure_channel import SecureSessionCodec


class _BrokenSocket:
    def __init__(self):
        self.closed = False

    def sendall(self, _data):
        raise BrokenPipeError("broken pipe")

    def close(self):
        self.closed = True


class _DisconnectingHandle:
    def __init__(self):
        self.closed = False

    def get_model_catalog(self, session_id: str):
        raise SessionDisconnectedError("TEE session disconnected")

    def describe_model(self, session_id: str, model_id: str):
        raise SessionDisconnectedError("TEE session disconnected")

    def run_inference(self, **_kwargs):
        raise SessionDisconnectedError("TEE session disconnected")

    def get_session_evidence(self, session_id: str):
        raise SessionDisconnectedError("TEE session disconnected")

    def end_session(self, session_id: str):
        raise SessionDisconnectedError("TEE session disconnected")

    def close(self):
        self.closed = True


class _CatalogHandle:
    def __init__(self):
        self.closed = False
        self.calls = 0

    def get_model_catalog(self, session_id: str):
        self.calls += 1
        return SimpleNamespace(
            models=[
                SimpleNamespace(
                    model_id="cardio-risk-v1",
                    display_name="Cardio Risk",
                    version="1.0.0",
                    engine="onnxruntime",
                    summary="test model",
                )
            ]
        )

    def close(self):
        self.closed = True


def _build_gateway() -> HospitalGateway:
    return HospitalGateway(
        HospitalMCPConfig(
            host="127.0.0.1",
            port=9123,
            path="/mcp",
            tee_target="127.0.0.1:50051",
            hospital_org_id="hospital-a",
            session_ttl_seconds=300,
            tee_timeout_seconds=10.0,
        )
    )


def test_attested_session_request_maps_broken_socket_to_session_disconnected():
    sock = _BrokenSocket()
    session = AttestedSession(
        sock=sock,
        codec=SecureSessionCodec(
            session_id="session-1",
            send_key=b"\x01" * 32,
            receive_key=b"\x02" * 32,
        ),
    )

    with pytest.raises(SessionDisconnectedError, match="TEE session disconnected"):
        session.request(SimpleNamespace(SerializeToString=lambda: b"payload"))

    assert session.closed is True
    assert sock.closed is True


def test_list_models_disconnect_deletes_local_context_and_raises_key_error():
    gateway = _build_gateway()
    handle = _DisconnectingHandle()
    gateway._contexts.put(
        workflow_context_id="ctx-1",
        tee_session_id="session-1",
        session_handle=handle,
        attestation_summary={"verified": True, "tee_type": "csv"},
    )

    with pytest.raises(
        KeyError,
        match="workflow_context_id ctx-1 is no longer active; restart the workflow context",
    ):
        gateway.list_models("ctx-1")

    assert handle.closed is True
    with pytest.raises(KeyError, match="unknown workflow_context_id: ctx-1"):
        gateway._contexts.get("ctx-1")


def test_release_context_disconnect_is_best_effort():
    gateway = _build_gateway()
    handle = _DisconnectingHandle()
    gateway._contexts.put(
        workflow_context_id="ctx-1",
        tee_session_id="session-1",
        session_handle=handle,
        attestation_summary={"verified": True, "tee_type": "csv"},
    )

    response = gateway.release_context("ctx-1")

    assert response == {"released": True}
    assert handle.closed is True
    with pytest.raises(KeyError, match="unknown workflow_context_id: ctx-1"):
        gateway._contexts.get("ctx-1")


def test_release_context_missing_is_idempotent():
    gateway = _build_gateway()

    response = gateway.release_context("missing")

    assert response == {"released": True}


def test_list_models_auto_opens_context_and_reuses_it(monkeypatch):
    gateway = _build_gateway()
    handle = _CatalogHandle()
    open_calls = 0

    def _open(workflow_context_id: str):
        nonlocal open_calls
        open_calls += 1
        return gateway._contexts.put(
            workflow_context_id=workflow_context_id,
            tee_session_id="session-1",
            session_handle=handle,
            attestation_summary={"verified": True, "tee_type": "csv"},
        )

    monkeypatch.setattr(gateway, "_open_tee_session", _open)

    first = gateway.list_models("ctx-1")
    second = gateway.list_models("ctx-1")

    assert first["models"][0]["model_id"] == "cardio-risk-v1"
    assert second["models"][0]["model_id"] == "cardio-risk-v1"
    assert open_calls == 1
    assert handle.calls == 2
