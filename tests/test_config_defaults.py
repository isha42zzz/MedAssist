from apps.hospital_mcp.config import HospitalMCPConfig
from apps.tee_service.config import TeeServiceConfig


def test_hospital_config_defaults_to_three_hour_context_ttl(monkeypatch):
    monkeypatch.delenv("MEDASSIST_CONTEXT_TTL_SECONDS", raising=False)
    monkeypatch.delenv("MEDASSIST_SESSION_TTL_SECONDS", raising=False)

    config = HospitalMCPConfig.from_env()

    assert config.session_ttl_seconds == 10800


def test_hospital_config_prefers_context_ttl_over_legacy_session_ttl(monkeypatch):
    monkeypatch.setenv("MEDASSIST_CONTEXT_TTL_SECONDS", "10800")
    monkeypatch.setenv("MEDASSIST_SESSION_TTL_SECONDS", "999")

    config = HospitalMCPConfig.from_env()

    assert config.session_ttl_seconds == 10800


def test_tee_config_defaults_to_longer_session_ttl(monkeypatch):
    monkeypatch.delenv("MEDASSIST_SESSION_TTL_SECONDS", raising=False)

    config = TeeServiceConfig.from_env()

    assert config.session_ttl_seconds == 11400
