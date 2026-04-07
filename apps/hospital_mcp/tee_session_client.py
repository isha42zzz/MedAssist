from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any, Callable

from google.protobuf.struct_pb2 import Struct

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from shared.proto import diagnosis_pb2
from shared.secure_channel import (
    SecureSessionCodec,
    build_client_codec,
    derive_session_keys,
    generate_ephemeral_keypair,
)
from shared.transport import recv_frame, send_frame

from .config import HospitalMCPConfig


ErrorFactory = Callable[[str], Exception]
ERROR_MAP: dict[str, ErrorFactory] = {
    "NOT_FOUND": KeyError,
    "PERMISSION_DENIED": PermissionError,
    "INVALID_ARGUMENT": ValueError,
}


class SessionDisconnectedError(ConnectionError):
    pass


@dataclass
class PendingSession:
    sock: socket.socket
    nonce: bytes
    hospital_org_id: str
    hospital_private_key: X25519PrivateKey
    hospital_ephemeral_pubkey: bytes
    start_response: diagnosis_pb2.StartSessionResponse

    @property
    def session_id(self) -> str:
        return self.start_response.session_id

    @property
    def tee_ephemeral_pubkey(self) -> bytes:
        return bytes(self.start_response.tee_ephemeral_pubkey)

    @property
    def attestation_report(self) -> bytes:
        return bytes(self.start_response.attestation_report)

    def close(self) -> None:
        self.sock.close()


@dataclass
class AttestedSession:
    sock: socket.socket
    codec: SecureSessionCodec
    closed: bool = False

    @property
    def session_id(self) -> str:
        return self.codec.session_id

    def handshake_open(self) -> None:
        request = diagnosis_pb2.SecureRequest(
            handshake_open=diagnosis_pb2.HandshakeOpenRequest(session_id=self.session_id)
        )
        response = self.request(request)
        if not response.HasField("handshake_open") or not response.handshake_open.attested:
            raise PermissionError("TEE session was not opened")

    def get_model_catalog(self, session_id: str):
        request = diagnosis_pb2.SecureRequest(
            get_model_catalog=diagnosis_pb2.GetModelCatalogRequest(
                session_id=session_id,
            )
        )
        response = self.request(request)
        return response.get_model_catalog

    def describe_model(self, session_id: str, model_id: str):
        request = diagnosis_pb2.SecureRequest(
            describe_model=diagnosis_pb2.DescribeModelRequest(
                session_id=session_id,
                model_id=model_id,
            )
        )
        response = self.request(request)
        return response.describe_model

    def run_inference(self, session_id: str, request_id: str, model_id: str, input_data: dict[str, Any]):
        request_input = Struct()
        request_input.update(input_data)
        request = diagnosis_pb2.SecureRequest(
            run_inference=diagnosis_pb2.RunInferenceRequest(
                session_id=session_id,
                request_id=request_id,
                model_id=model_id,
                input=request_input,
            )
        )
        response = self.request(request)
        return response.run_inference

    def get_session_evidence(self, session_id: str):
        request = diagnosis_pb2.SecureRequest(
            get_session_evidence=diagnosis_pb2.GetSessionEvidenceRequest(session_id=session_id)
        )
        response = self.request(request)
        return response.get_session_evidence

    def end_session(self, session_id: str):
        request = diagnosis_pb2.SecureRequest(
            end_session=diagnosis_pb2.EndSessionRequest(session_id=session_id)
        )
        response = self.request(request)
        self.close()
        return response.end_session

    def close(self) -> None:
        if not self.closed:
            self.sock.close()
            self.closed = True

    def request(self, request: diagnosis_pb2.SecureRequest) -> diagnosis_pb2.SecureResponse:
        if self.closed:
            raise SessionDisconnectedError("TEE session disconnected")
        try:
            envelope = self.codec.encrypt_message(request)
            send_frame(self.sock, diagnosis_pb2.Frame(secure_envelope=envelope))
            frame = recv_frame(self.sock)
        except (EOFError, OSError) as exc:
            self.close()
            raise SessionDisconnectedError("TEE session disconnected") from exc
        if frame.HasField("error"):
            raise _build_error(frame.error.code, frame.error.message)
        if not frame.HasField("secure_envelope"):
            raise ValueError("expected secure_envelope response")
        response = self.codec.decrypt_message(frame.secure_envelope, diagnosis_pb2.SecureResponse)
        if response.HasField("error"):
            raise _build_error(response.error.code, response.error.message)
        return response


class TeeServiceClient:
    def __init__(self, config: HospitalMCPConfig):
        self._config = config

    def start_session(self, nonce: bytes, hospital_org_id: str) -> PendingSession:
        private_key, public_key = generate_ephemeral_keypair()
        sock = socket.create_connection(
            _split_host_port(self._config.tee_target),
            timeout=self._config.tee_timeout_seconds,
        )
        sock.settimeout(self._config.tee_timeout_seconds)
        request = diagnosis_pb2.StartSessionRequest(
            nonce=nonce,
            hospital_org_id=hospital_org_id,
            hospital_ephemeral_pubkey=public_key,
        )
        send_frame(sock, diagnosis_pb2.Frame(start_session_request=request))
        frame = recv_frame(sock)
        if frame.HasField("error"):
            sock.close()
            raise _build_error(frame.error.code, frame.error.message)
        if not frame.HasField("start_session_response"):
            sock.close()
            raise ValueError("expected StartSessionResponse")
        return PendingSession(
            sock=sock,
            nonce=nonce,
            hospital_org_id=hospital_org_id,
            hospital_private_key=private_key,
            hospital_ephemeral_pubkey=public_key,
            start_response=frame.start_session_response,
        )

    def finish_session(self, pending: PendingSession) -> AttestedSession:
        keys = derive_session_keys(
            private_key=pending.hospital_private_key,
            peer_public_key=pending.tee_ephemeral_pubkey,
            session_id=pending.session_id,
            nonce=pending.nonce,
        )
        session = AttestedSession(
            sock=pending.sock,
            codec=build_client_codec(keys, pending.session_id),
        )
        session.handshake_open()
        return session


def _build_error(code: str, message: str) -> Exception:
    factory = ERROR_MAP.get(code, RuntimeError)
    if factory is RuntimeError:
        return RuntimeError(f"{code}: {message}")
    return factory(message)


def _split_host_port(value: str) -> tuple[str, int]:
    host, port = value.rsplit(":", 1)
    return host, int(port)
