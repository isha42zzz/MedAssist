from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


@dataclass(frozen=True)
class TeeServiceConfig:
    host: str
    port: int
    model_registry_path: Path
    session_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "TeeServiceConfig":
        return cls(
            host=os.getenv("MEDASSIST_TEE_HOST", "127.0.0.1"),
            port=int(os.getenv("MEDASSIST_TEE_PORT", "50051")),
            model_registry_path=_resolve_path(os.getenv("MEDASSIST_MODEL_REGISTRY", "models/registry.json")),
            session_ttl_seconds=int(os.getenv("MEDASSIST_SESSION_TTL_SECONDS", "11400")),
        )
