from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from haptic_bridge.events import EventKind, Pattern, Pulse

CONFIG_ENV = "HAPTIC_BRIDGE_CONFIG"
TOKEN_ENV = "HAPTIC_BRIDGE_TOKEN"  # noqa: S105 - variable name, not a secret
CONFIG_FILENAME = "haptic-bridge.toml"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    auth_token: str | None = Field(default=None, min_length=8)


class EngineConfig(BaseModel):
    max_intensity: float = Field(default=0.8, ge=0.0, le=1.0)
    cooldown_ms: int = Field(default=1500, ge=0, le=60_000)


DEFAULT_PATTERNS: dict[str, Pattern] = {
    "permission": Pattern(
        pulses=[
            Pulse(intensity=0.6, duration_ms=180, pause_ms=120),
            Pulse(intensity=0.6, duration_ms=180),
        ],
        color=(255, 160, 0),
    ),
    "input": Pattern(pulses=[Pulse(intensity=0.4, duration_ms=400)], color=(0, 120, 255)),
    "done": Pattern(pulses=[Pulse(intensity=0.8, duration_ms=500)], color=(0, 200, 90)),
}

DEFAULT_EVENTS: dict[EventKind, str] = {
    EventKind.PERMISSION: "permission",
    EventKind.INPUT: "input",
    EventKind.DONE: "done",
}


def _default_backends() -> dict[str, dict[str, Any]]:
    return {"mock": {}}


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    patterns: dict[str, Pattern] = Field(default_factory=lambda: dict(DEFAULT_PATTERNS))
    events: dict[EventKind, str] = Field(default_factory=lambda: dict(DEFAULT_EVENTS))
    backends: dict[str, dict[str, Any]] = Field(default_factory=_default_backends)

    @model_validator(mode="after")
    def _events_must_reference_known_patterns(self) -> AppConfig:
        missing = sorted(name for name in self.events.values() if name not in self.patterns)
        if missing:
            raise ValueError(f"events reference unknown patterns: {missing}")
        return self

    def resolved_token(self) -> str | None:
        return os.environ.get(TOKEN_ENV) or self.server.auth_token


def find_config_path() -> Path | None:
    candidates: list[Path] = []
    if env_path := os.environ.get(CONFIG_ENV):
        candidates.append(Path(env_path))
    candidates.append(Path.cwd() / CONFIG_FILENAME)
    candidates.append(Path.home() / f".{CONFIG_FILENAME}")
    return next((path for path in candidates if path.is_file()), None)


def load_config(path: Path | None = None) -> AppConfig:
    resolved = path if path is not None else find_config_path()
    if resolved is None:
        return AppConfig()
    if not resolved.is_file():
        raise FileNotFoundError(f"config file not found: {resolved}")
    with resolved.open("rb") as fh:
        raw: dict[str, Any] = tomllib.load(fh)
    return AppConfig.model_validate(raw)
