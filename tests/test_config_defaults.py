import pytest

from apps.hospital_mcp import server as hospital_server
from apps.hospital_mcp.config import HospitalMCPConfig
from apps.tee_service.config import TeeServiceConfig


def _reset_hospital_server(monkeypatch):
    monkeypatch.setattr(hospital_server, "_config", None)
    monkeypatch.setattr(hospital_server, "_gateway", None)
    monkeypatch.setattr(hospital_server, "_mcp", None)


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


def test_hospital_config_parses_allowed_hosts_and_origins(monkeypatch):
    monkeypatch.setenv("MEDASSIST_MCP_ALLOWED_HOSTS", " 10.17.41.30:*, server:* , ")
    monkeypatch.setenv("MEDASSIST_MCP_ALLOWED_ORIGINS", " https://mcp.example.com , http://localhost:3000 ")

    config = HospitalMCPConfig.from_env()

    assert config.allowed_hosts == ["10.17.41.30:*", "server:*"]
    assert config.allowed_origins == ["https://mcp.example.com", "http://localhost:3000"]


def test_hospital_mcp_requires_allowed_hosts_for_wildcard_bind(monkeypatch):
    _reset_hospital_server(monkeypatch)
    monkeypatch.setenv("MEDASSIST_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("MEDASSIST_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MEDASSIST_MCP_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(ValueError, match="MEDASSIST_MCP_ALLOWED_HOSTS is required"):
        hospital_server.build_app()


def test_tee_config_defaults_to_longer_session_ttl(monkeypatch):
    monkeypatch.delenv("MEDASSIST_SESSION_TTL_SECONDS", raising=False)

    config = TeeServiceConfig.from_env()

    assert config.session_ttl_seconds == 11400
