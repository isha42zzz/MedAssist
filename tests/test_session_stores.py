from datetime import datetime, timedelta, timezone

import pytest

from apps.hospital_mcp.sessions import WorkflowContextStore
from apps.tee_service.sessions import SessionStore


class _ClosableHandle:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_tee_session_requires_attestation_before_access():
    store = SessionStore(ttl_seconds=300)
    record = store.create(
        hospital_org_id="hospital-a",
        nonce=b"nonce",
        hospital_ephemeral_pubkey=b"hospital-pubkey",
        tee_ephemeral_pubkey=b"pubkey",
        expected_user_data_hex="abcd",
        attestation_report=b"report",
    )
    try:
        store.get_open(record.session_id)
    except PermissionError:
        pass
    else:
        raise AssertionError("expected PermissionError for unattested session")


def test_tee_session_access_refreshes_expiry():
    store = SessionStore(ttl_seconds=300)
    record = store.create(
        hospital_org_id="hospital-a",
        nonce=b"nonce",
        hospital_ephemeral_pubkey=b"hospital-pubkey",
        tee_ephemeral_pubkey=b"pubkey",
        expected_user_data_hex="abcd",
        attestation_report=b"report",
    )
    old_expires_at = record.expires_at

    touched = store.get(record.session_id)

    assert touched.expires_at >= old_expires_at


def test_local_session_store_delete():
    store = WorkflowContextStore(ttl_seconds=300)
    record = store.put(
        workflow_context_id="ctx-1",
        tee_session_id="session-1",
        session_handle=object(),
        attestation_summary={"verified": True, "tee_type": "csv"},
    )
    assert store.get(record.workflow_context_id).tee_session_id == "session-1"
    assert store.delete(record.workflow_context_id) is True


def test_local_session_store_delete_unknown_returns_false():
    store = WorkflowContextStore(ttl_seconds=300)
    assert store.delete("missing") is False


def test_local_session_store_purges_expired_records_and_closes_handle():
    store = WorkflowContextStore(ttl_seconds=300)
    handle = _ClosableHandle()
    record = store.put(
        workflow_context_id="ctx-1",
        tee_session_id="session-1",
        session_handle=handle,
        attestation_summary={"verified": True, "tee_type": "csv"},
    )
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    with pytest.raises(KeyError, match="unknown workflow_context_id: ctx-1"):
        store.get("ctx-1")

    assert handle.closed is True


def test_local_session_store_touch_refreshes_expiry():
    store = WorkflowContextStore(ttl_seconds=300)
    record = store.put(
        workflow_context_id="ctx-1",
        tee_session_id="session-1",
        session_handle=object(),
        attestation_summary={"verified": True, "tee_type": "csv"},
    )
    old_expires_at = record.expires_at

    touched = store.touch("ctx-1")

    assert touched.last_accessed_at >= touched.created_at
    assert touched.expires_at >= old_expires_at
