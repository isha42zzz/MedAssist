from __future__ import annotations

import socket
import socketserver
from datetime import timezone

from google.protobuf.json_format import MessageToDict

from shared.attestation import build_user_data, generate_report, report_digest
from shared.proto import diagnosis_pb2
from shared.secure_channel import build_server_codec, derive_session_keys, generate_ephemeral_keypair
from shared.transport import recv_frame, send_frame

from .config import TeeServiceConfig
from .inference import InferenceService
from .models import ModelRegistry
from .sessions import SessionRecord, SessionStore


class DiagnosisService:
    def __init__(self, sessions: SessionStore, registry: ModelRegistry, inference: InferenceService):
        self._sessions = sessions
        self._registry = registry
        self._inference = inference

    def start_session(self, request: diagnosis_pb2.StartSessionRequest) -> tuple[SessionRecord, object]:
        tee_private_key, tee_ephemeral_pubkey = generate_ephemeral_keypair()
        expected_user_data = build_user_data(
            tee_ephemeral_pubkey,
            bytes(request.hospital_ephemeral_pubkey),
            bytes(request.nonce),
        )
        record = self._sessions.create(
            hospital_org_id=request.hospital_org_id,
            nonce=bytes(request.nonce),
            hospital_ephemeral_pubkey=bytes(request.hospital_ephemeral_pubkey),
            tee_ephemeral_pubkey=tee_ephemeral_pubkey,
            expected_user_data_hex=expected_user_data.hex(),
            attestation_report=generate_report(expected_user_data),
        )
        return record, tee_private_key

    def build_start_session_response(self, record: SessionRecord) -> diagnosis_pb2.StartSessionResponse:
        return diagnosis_pb2.StartSessionResponse(
            session_id=record.session_id,
            tee_ephemeral_pubkey=record.tee_ephemeral_pubkey,
            attestation_report=record.attestation_report,
            tee_type="csv",
        )

    def open_codec(self, record: SessionRecord, tee_private_key: object):
        keys = derive_session_keys(
            private_key=tee_private_key,
            peer_public_key=record.hospital_ephemeral_pubkey,
            session_id=record.session_id,
            nonce=record.nonce,
        )
        return build_server_codec(keys, record.session_id)

    def mark_open(self, session_id: str) -> None:
        self._sessions.mark_open(session_id)

    def dispatch(self, session_id: str, request: diagnosis_pb2.SecureRequest) -> tuple[diagnosis_pb2.SecureResponse, bool]:
        if request.HasField("get_model_catalog"):
            payload = request.get_model_catalog
            self._require_session_match(session_id, payload.session_id)
            self._sessions.get_open(session_id)
            return _secure_response(
                get_model_catalog=diagnosis_pb2.GetModelCatalogResponse(
                    models=[
                        diagnosis_pb2.ModelInfo(
                            model_id=model.model_id,
                            display_name=model.display_name,
                            version=model.model_version,
                            engine=model.backend,
                            summary=model.summary,
                        )
                        for model in self._registry.list_models()
                    ]
                )
            ), False

        if request.HasField("describe_model"):
            payload = request.describe_model
            self._require_session_match(session_id, payload.session_id)
            self._sessions.get_open(session_id)
            model = self._registry.get(payload.model_id)
            return _secure_response(
                describe_model=diagnosis_pb2.DescribeModelResponse(
                    model_id=model.model_id,
                    display_name=model.display_name,
                    version=model.model_version,
                    engine=model.backend,
                    summary=model.summary,
                    description=model.description,
                    input_features=[
                        diagnosis_pb2.FeatureSpec(
                            name=feature.name,
                            label=feature.label,
                            type=feature.type,
                            unit=feature.unit,
                            description=feature.description,
                            allowed_values=list(feature.allowed_values),
                        )
                        for feature in model.input_features
                    ],
                    output_spec=diagnosis_pb2.OutputSpec(
                        name=model.output_spec.name,
                        label=model.output_spec.label,
                        type=model.output_spec.type,
                        description=model.output_spec.description,
                        range_min=model.output_spec.range_min,
                        range_max=model.output_spec.range_max,
                    ),
                )
            ), False

        if request.HasField("run_inference"):
            payload = request.run_inference
            self._require_session_match(session_id, payload.session_id)
            self._sessions.get_open(session_id)
            model_input = MessageToDict(payload.input, preserving_proto_field_name=True)
            model, output_value = self._inference.run(payload.model_id, model_input)
            return _secure_response(
                run_inference=diagnosis_pb2.RunInferenceResponse(
                    request_id=payload.request_id,
                    model_id=model.model_id,
                    model_version=model.model_version,
                    output_name=model.output_spec.name,
                    output_value=output_value,
                )
            ), False

        if request.HasField("get_session_evidence"):
            payload = request.get_session_evidence
            self._require_session_match(session_id, payload.session_id)
            record = self._sessions.get_open(session_id)
            return _secure_response(
                get_session_evidence=diagnosis_pb2.GetSessionEvidenceResponse(
                    evidence=diagnosis_pb2.SessionEvidence(
                        session_id=record.session_id,
                        tee_type="csv",
                        report_digest=report_digest(record.attestation_report),
                        verified_user_data=record.expected_user_data_hex,
                        created_at=record.created_at.astimezone(timezone.utc).isoformat(),
                    )
                )
            ), False

        if request.HasField("end_session"):
            payload = request.end_session
            self._require_session_match(session_id, payload.session_id)
            closed = self._sessions.end(session_id)
            return _secure_response(
                end_session=diagnosis_pb2.EndSessionResponse(closed=closed)
            ), True

        raise ValueError("unsupported secure request")

    def end(self, session_id: str) -> None:
        self._sessions.end(session_id)

    @staticmethod
    def _require_session_match(expected: str, actual: str) -> None:
        if expected != actual:
            raise PermissionError("session_id does not match the secure channel")


class DiagnosisTCPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        service = self.server.service
        session_id: str | None = None
        try:
            frame = recv_frame(self.request)
            if not frame.HasField("start_session_request"):
                send_frame(
                    self.request,
                    diagnosis_pb2.Frame(
                        error=diagnosis_pb2.ErrorResponse(
                            code="INVALID_BOOTSTRAP",
                            message="expected StartSessionRequest",
                        )
                    ),
                )
                return

            record, tee_private_key = service.start_session(frame.start_session_request)
            session_id = record.session_id
            send_frame(
                self.request,
                diagnosis_pb2.Frame(
                    start_session_response=service.build_start_session_response(record)
                ),
            )

            codec = service.open_codec(record, tee_private_key)
            secure_request = _recv_secure_request(self.request, codec)
            if not secure_request.HasField("handshake_open"):
                return
            if secure_request.handshake_open.session_id != session_id:
                return

            service.mark_open(session_id)
            send_frame(
                self.request,
                diagnosis_pb2.Frame(
                    secure_envelope=codec.encrypt_message(
                        _secure_response(
                            handshake_open=diagnosis_pb2.HandshakeOpenResponse(attested=True)
                        )
                    )
                ),
            )

            while True:
                try:
                    secure_request = _recv_secure_request(self.request, codec)
                    secure_response, should_close = service.dispatch(session_id, secure_request)
                except EOFError:
                    break
                except (KeyError, PermissionError, ValueError) as exc:
                    secure_response = _secure_response(
                        error=diagnosis_pb2.ErrorResponse(
                            code=_error_code(exc),
                            message=str(exc),
                        )
                    )
                    should_close = isinstance(exc, PermissionError)
                except Exception as exc:
                    secure_response = _secure_response(
                        error=diagnosis_pb2.ErrorResponse(
                            code="INTERNAL",
                            message=str(exc),
                        )
                    )
                    should_close = True

                send_frame(
                    self.request,
                    diagnosis_pb2.Frame(
                        secure_envelope=codec.encrypt_message(secure_response)
                    ),
                )
                if should_close:
                    break
        finally:
            if session_id is not None:
                service.end(session_id)
            self.request.close()


class ThreadedDiagnosisServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], service: DiagnosisService):
        self.service = service
        super().__init__(server_address, DiagnosisTCPHandler)


def build_server(config: TeeServiceConfig) -> ThreadedDiagnosisServer:
    registry = ModelRegistry(config.model_registry_path)
    inference = InferenceService(registry)
    sessions = SessionStore(ttl_seconds=config.session_ttl_seconds)
    service = DiagnosisService(sessions=sessions, registry=registry, inference=inference)
    return ThreadedDiagnosisServer((config.host, config.port), service)


def main() -> None:
    config = TeeServiceConfig.from_env()
    server = build_server(config)
    with server:
        print(f"TEE diagnosis service listening on {config.host}:{config.port}")
        server.serve_forever()


def _recv_secure_request(sock: socket.socket, codec) -> diagnosis_pb2.SecureRequest:
    frame = recv_frame(sock)
    if not frame.HasField("secure_envelope"):
        raise ValueError("expected secure_envelope")
    return codec.decrypt_message(frame.secure_envelope, diagnosis_pb2.SecureRequest)


def _secure_response(**kwargs) -> diagnosis_pb2.SecureResponse:
    return diagnosis_pb2.SecureResponse(**kwargs)


def _error_code(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return "NOT_FOUND"
    if isinstance(exc, PermissionError):
        return "PERMISSION_DENIED"
    if isinstance(exc, ValueError):
        return "INVALID_ARGUMENT"
    return "INTERNAL"
