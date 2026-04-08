from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from starlette.testclient import TestClient

from apps.hospital_mcp import server


def _reset_hospital_server(monkeypatch):
    monkeypatch.setattr(server, "_config", None)
    monkeypatch.setattr(server, "_gateway", None)
    monkeypatch.setattr(server, "_mcp", None)


def _initialize_payload() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "initialize",
        "params": {
            "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[-1],
            "capabilities": {},
            "clientInfo": {
                "name": "pytest",
                "version": "1.0",
            },
        },
    }


def test_build_app_exposes_single_mcp_path(monkeypatch):
    _reset_hospital_server(monkeypatch)
    monkeypatch.setenv("MEDASSIST_MCP_HOST", "127.0.0.1")

    app = server.build_app()

    route_paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/mcp" in route_paths
    assert "/mcp/mcp" not in route_paths


def test_explicit_allowed_hosts_accept_matching_host(monkeypatch):
    _reset_hospital_server(monkeypatch)
    monkeypatch.setenv("MEDASSIST_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MEDASSIST_MCP_ALLOWED_HOSTS", "allowed.example:*")
    monkeypatch.delenv("MEDASSIST_MCP_ALLOWED_ORIGINS", raising=False)

    with TestClient(server.build_app()) as client:
        response = client.post(
            "/mcp",
            headers={
                "accept": "application/json",
                "host": "allowed.example:9123",
            },
            json=_initialize_payload(),
        )

    assert response.status_code == 200


def test_explicit_allowed_hosts_reject_non_matching_host(monkeypatch):
    _reset_hospital_server(monkeypatch)
    monkeypatch.setenv("MEDASSIST_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MEDASSIST_MCP_ALLOWED_HOSTS", "allowed.example:*")
    monkeypatch.delenv("MEDASSIST_MCP_ALLOWED_ORIGINS", raising=False)

    with TestClient(server.build_app()) as client:
        response = client.post(
            "/mcp",
            headers={
                "accept": "application/json",
                "host": "blocked.example:9123",
            },
            json=_initialize_payload(),
        )

    assert response.status_code == 421
    assert response.text == "Invalid Host header"


def test_specific_host_is_allowed_without_explicit_whitelist(monkeypatch):
    _reset_hospital_server(monkeypatch)
    monkeypatch.setenv("MEDASSIST_MCP_HOST", "medassist.internal")
    monkeypatch.delenv("MEDASSIST_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MEDASSIST_MCP_ALLOWED_ORIGINS", raising=False)

    with TestClient(server.build_app()) as client:
        response = client.post(
            "/mcp",
            headers={
                "accept": "application/json",
                "host": "medassist.internal:9123",
            },
            json=_initialize_payload(),
        )

    assert response.status_code == 200


def test_nested_mcp_path_is_not_exposed(monkeypatch):
    _reset_hospital_server(monkeypatch)
    monkeypatch.setenv("MEDASSIST_MCP_HOST", "127.0.0.1")

    with TestClient(server.build_app()) as client:
        response = client.post(
            "/mcp/mcp",
            headers={
                "accept": "application/json",
                "host": "127.0.0.1:9123",
            },
            json=_initialize_payload(),
        )

    assert response.status_code == 404
