from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict


@dataclass
class ManagedContextRecord:
    workflow_context_id: str
    tee_session_id: str
    session_handle: Any
    attestation_summary: Dict[str, Any]
    created_at: datetime
    last_accessed_at: datetime
    expires_at: datetime
    lock: Any = field(default_factory=Lock, repr=False)


class WorkflowContextStore:
    def __init__(self, ttl_seconds: int):
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._contexts: Dict[str, ManagedContextRecord] = {}

    def put(
        self,
        workflow_context_id: str,
        tee_session_id: str,
        session_handle: Any,
        attestation_summary: Dict[str, Any],
    ) -> ManagedContextRecord:
        with self._lock:
            now = datetime.now(timezone.utc)
            record = ManagedContextRecord(
                workflow_context_id=workflow_context_id,
                tee_session_id=tee_session_id,
                session_handle=session_handle,
                attestation_summary=dict(attestation_summary),
                created_at=now,
                last_accessed_at=now,
                expires_at=now + timedelta(seconds=self._ttl_seconds),
            )
            self._contexts[workflow_context_id] = record
            return record

    def get(self, workflow_context_id: str) -> ManagedContextRecord:
        with self._lock:
            self._purge_expired_locked()
            record = self._contexts.get(workflow_context_id)
            if record is None:
                raise KeyError(f"unknown workflow_context_id: {workflow_context_id}")
            return record

    def touch(self, workflow_context_id: str) -> ManagedContextRecord:
        with self._lock:
            self._purge_expired_locked()
            record = self._contexts.get(workflow_context_id)
            if record is None:
                raise KeyError(f"unknown workflow_context_id: {workflow_context_id}")
            now = datetime.now(timezone.utc)
            record.last_accessed_at = now
            record.expires_at = now + timedelta(seconds=self._ttl_seconds)
            return record

    def delete(self, workflow_context_id: str) -> bool:
        with self._lock:
            return self._contexts.pop(workflow_context_id, None) is not None

    def _purge_expired_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            workflow_context_id
            for workflow_context_id, record in self._contexts.items()
            if record.expires_at <= now
        ]
        for workflow_context_id in expired:
            record = self._contexts.pop(workflow_context_id, None)
            if record is None:
                continue
            try:
                record.session_handle.close()
            except Exception:
                pass
