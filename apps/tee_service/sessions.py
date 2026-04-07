from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Dict
from uuid import uuid4


@dataclass
class SessionRecord:
    session_id: str
    hospital_org_id: str
    nonce: bytes
    hospital_ephemeral_pubkey: bytes
    tee_ephemeral_pubkey: bytes
    expected_user_data_hex: str
    attestation_report: bytes
    open: bool
    created_at: datetime
    expires_at: datetime


class SessionStore:
    def __init__(self, ttl_seconds: int):
        self._ttl_seconds = ttl_seconds
        self._sessions: Dict[str, SessionRecord] = {}
        self._lock = Lock()

    def create(
        self,
        hospital_org_id: str,
        nonce: bytes,
        hospital_ephemeral_pubkey: bytes,
        tee_ephemeral_pubkey: bytes,
        expected_user_data_hex: str,
        attestation_report: bytes,
    ) -> SessionRecord:
        with self._lock:
            now = datetime.now(timezone.utc)
            record = SessionRecord(
                session_id=uuid4().hex,
                hospital_org_id=hospital_org_id,
                nonce=nonce,
                hospital_ephemeral_pubkey=hospital_ephemeral_pubkey,
                tee_ephemeral_pubkey=tee_ephemeral_pubkey,
                expected_user_data_hex=expected_user_data_hex,
                attestation_report=attestation_report,
                open=False,
                created_at=now,
                expires_at=now + timedelta(seconds=self._ttl_seconds),
            )
            self._sessions[record.session_id] = record
            return record

    def mark_open(self, session_id: str) -> SessionRecord:
        with self._lock:
            record = self._require(session_id)
            record.open = True
            return record

    def get(self, session_id: str) -> SessionRecord:
        with self._lock:
            return self._require(session_id)

    def get_open(self, session_id: str) -> SessionRecord:
        with self._lock:
            record = self._require(session_id)
            if not record.open:
                raise PermissionError("session has not completed attested handshake")
            return record

    def end(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def _require(self, session_id: str) -> SessionRecord:
        self._purge_expired_locked()
        record = self._sessions.get(session_id)
        if record is None:
            raise KeyError(f"unknown session_id: {session_id}")
        record.expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        return record

    def _purge_expired_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [session_id for session_id, record in self._sessions.items() if record.expires_at <= now]
        for session_id in expired:
            self._sessions.pop(session_id, None)
