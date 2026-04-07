from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, Callable, Dict, Optional

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount
import uvicorn

from shared.attestation import build_user_data, verify_report

from .tee_session_client import SessionDisconnectedError, TeeServiceClient
from .config import HospitalMCPConfig
from .sessions import ManagedContextRecord, WorkflowContextStore


class HospitalGateway:
    def __init__(self, config: HospitalMCPConfig):
        self._config = config
        self._client = TeeServiceClient(config)
        self._contexts = WorkflowContextStore(ttl_seconds=config.session_ttl_seconds)
        self._creation_lock = Lock()

    def _open_tee_session(self, workflow_context_id: str) -> ManagedContextRecord:
        nonce = secrets.token_bytes(16)
        pending = self._client.start_session(
            nonce=nonce,
            hospital_org_id=self._config.hospital_org_id,
        )
        try:
            parsed = verify_report(pending.attestation_report)
            expected_user_data = build_user_data(
                pending.tee_ephemeral_pubkey,
                pending.hospital_ephemeral_pubkey,
                nonce,
            )
            actual_user_data = parsed.user_data
            if actual_user_data != expected_user_data:
                raise ValueError("attestation UserData does not match tee_pubkey + hospital_pubkey + nonce")
            session_handle = self._client.finish_session(pending)
        except Exception:
            pending.close()
            raise
        return self._contexts.put(
            workflow_context_id=workflow_context_id,
            tee_session_id=pending.session_id,
            session_handle=session_handle,
            attestation_summary={
                "verified": True,
                "tee_type": parsed.tee_type,
            },
        )

    def list_models(self, workflow_context_id: str) -> Dict[str, Any]:
        response = self._with_workflow_context(
            workflow_context_id,
            lambda record: record.session_handle.get_model_catalog(session_id=record.tee_session_id),
        )
        return {
            "models": [
                {
                    "model_id": item.model_id,
                    "display_name": item.display_name,
                    "version": item.version,
                    "engine": item.engine,
                    "summary": item.summary,
                }
                for item in response.models
            ]
        }

    def describe_model(self, workflow_context_id: str, model_id: str) -> Dict[str, Any]:
        response = self._with_workflow_context(
            workflow_context_id,
            lambda record: record.session_handle.describe_model(
                session_id=record.tee_session_id,
                model_id=model_id,
            ),
        )
        return {
            "model_id": response.model_id,
            "display_name": response.display_name,
            "version": response.version,
            "engine": response.engine,
            "summary": response.summary,
            "description": response.description,
            "input_features": [
                {
                    "name": feature.name,
                    "label": feature.label,
                    "type": feature.type,
                    "unit": feature.unit,
                    "description": feature.description,
                    "allowed_values": list(feature.allowed_values),
                }
                for feature in response.input_features
            ],
            "output_spec": {
                "name": response.output_spec.name,
                "label": response.output_spec.label,
                "type": response.output_spec.type,
                "description": response.output_spec.description,
                "range_min": response.output_spec.range_min,
                "range_max": response.output_spec.range_max,
            },
        }

    def invoke_diagnosis(
        self,
        workflow_context_id: str,
        request_id: str,
        model_id: str,
        input: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = self._with_workflow_context(
            workflow_context_id,
            lambda record: record.session_handle.run_inference(
                session_id=record.tee_session_id,
                request_id=request_id,
                model_id=model_id,
                input_data=input,
            ),
        )
        return {
            "request_id": response.request_id,
            "model_id": response.model_id,
            "model_version": response.model_version,
            "result": {
                "output_name": response.output_name,
                "output_value": response.output_value,
            },
        }

    def get_attestation_info(self, workflow_context_id: str) -> Dict[str, Any]:
        response = self._with_workflow_context(
            workflow_context_id,
            lambda record: record.session_handle.get_session_evidence(record.tee_session_id),
        )
        return {
            "workflow_context_id": workflow_context_id,
            "tee_type": response.evidence.tee_type,
            "report_digest": response.evidence.report_digest,
            "verified_user_data": response.evidence.verified_user_data,
            "created_at": response.evidence.created_at,
        }

    def release_context(self, workflow_context_id: str) -> Dict[str, Any]:
        try:
            record = self._contexts.get(workflow_context_id)
        except KeyError:
            return {"released": True}
        with record.lock:
            try:
                record.session_handle.end_session(record.tee_session_id)
            except SessionDisconnectedError:
                pass
            finally:
                record.session_handle.close()
                self._contexts.delete(workflow_context_id)
        return {"released": True}

    def _with_workflow_context(
        self,
        workflow_context_id: str,
        action: Callable[[ManagedContextRecord], Any],
    ) -> Any:
        record = self._get_or_open_context(workflow_context_id)
        with record.lock:
            self._contexts.touch(workflow_context_id)
            try:
                result = action(record)
            except SessionDisconnectedError as exc:
                record.session_handle.close()
                self._contexts.delete(workflow_context_id)
                raise KeyError(
                    "workflow_context_id "
                    f"{workflow_context_id} is no longer active; restart the workflow context"
                ) from exc
            self._contexts.touch(workflow_context_id)
            return result

    def _get_or_open_context(self, workflow_context_id: str) -> ManagedContextRecord:
        try:
            return self._contexts.get(workflow_context_id)
        except KeyError:
            pass
        with self._creation_lock:
            try:
                return self._contexts.get(workflow_context_id)
            except KeyError:
                return self._open_tee_session(workflow_context_id)


_config: Optional[HospitalMCPConfig] = None
_gateway: Optional[HospitalGateway] = None
_mcp = FastMCP("MedAssist Hospital MCP", stateless_http=True, json_response=True)


def get_config() -> HospitalMCPConfig:
    global _config
    if _config is None:
        _config = HospitalMCPConfig.from_env()
    return _config


def get_gateway() -> HospitalGateway:
    global _gateway
    if _gateway is None:
        _gateway = HospitalGateway(get_config())
    return _gateway


@_mcp.tool()
def list_models(workflow_context_id: str) -> Dict[str, Any]:
    """List diagnosis models using a workflow-scoped internally managed TEE session."""
    return get_gateway().list_models(workflow_context_id)


@_mcp.tool()
def describe_model(workflow_context_id: str, model_id: str) -> Dict[str, Any]:
    """Return model input/output metadata for a workflow-scoped context."""
    return get_gateway().describe_model(workflow_context_id, model_id)


@_mcp.tool()
def invoke_diagnosis(
    workflow_context_id: str,
    request_id: str,
    model_id: str,
    input: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the selected diagnosis model using a workflow-scoped internally managed TEE session."""
    return get_gateway().invoke_diagnosis(
        workflow_context_id=workflow_context_id,
        request_id=request_id,
        model_id=model_id,
        input=input,
    )


@_mcp.tool()
def get_attestation_info(workflow_context_id: str) -> Dict[str, Any]:
    """Return attestation evidence for the internally managed TEE session of a workflow context."""
    return get_gateway().get_attestation_info(workflow_context_id)


@_mcp.tool()
def release_context(workflow_context_id: str) -> Dict[str, Any]:
    """Release a workflow-scoped context and best-effort close its internal TEE session."""
    return get_gateway().release_context(workflow_context_id)


def build_app() -> Starlette:
    config = get_config()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with _mcp.session_manager.run():
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Mount(config.path, app=_mcp.streamable_http_app()),
        ]
    )


def main() -> None:
    config = get_config()
    uvicorn.run(build_app(), host=config.host, port=config.port)
