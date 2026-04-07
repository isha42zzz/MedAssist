from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HospitalMCPConfig:
    host: str
    port: int
    path: str
    tee_target: str
    hospital_org_id: str
    session_ttl_seconds: int
    tee_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "HospitalMCPConfig":
        context_ttl = os.getenv("MEDASSIST_CONTEXT_TTL_SECONDS")
        if context_ttl is None:
            context_ttl = os.getenv("MEDASSIST_SESSION_TTL_SECONDS", "10800")
        return cls(
            host=os.getenv("MEDASSIST_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("MEDASSIST_MCP_PORT", "9123")),
            path=os.getenv("MEDASSIST_MCP_PATH", "/mcp"),
            tee_target=os.getenv("MEDASSIST_TEE_TARGET", "127.0.0.1:50051"),
            hospital_org_id=os.getenv("MEDASSIST_HOSPITAL_ORG_ID", "hospital-a"),
            session_ttl_seconds=int(context_ttl),
            tee_timeout_seconds=float(os.getenv("MEDASSIST_TEE_TIMEOUT_SECONDS", "10.0")),
        )
