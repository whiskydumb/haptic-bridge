from __future__ import annotations

import asyncio
import os
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator
from structlog.typing import FilteringBoundLogger

from haptic_bridge.backends.base import BackendError
from haptic_bridge.backends.httpclient import JsonHttp
from haptic_bridge.events import DeviceInfo, Pattern

log: FilteringBoundLogger = structlog.get_logger(__name__)

TOKEN_ENV = "OPENSHOCK_TOKEN"  # noqa: S105 - variable name, not a secret
MIN_DURATION_MS = 300
MAX_DURATION_MS = 65_535
CONTROL_PATH = "/2/shockers/control"
OWN_SHOCKERS_PATH = "/1/shockers/own"
SELF_INFO_PATH = "/2/tokens/self"
REQUIRED_PERMISSION = "shockers.use"

ControlType = Literal["Vibrate", "Sound", "Shock"]


class OpenShockConfig(BaseModel):
    enabled: bool = True
    api_url: str = "https://api.openshock.app"
    token: str | None = None
    shockers: list[UUID] = Field(default_factory=list)
    control_type: ControlType = "Vibrate"
    allow_shock: bool = False
    max_intensity: int = Field(default=50, ge=0, le=100)
    exclusive: bool = True
    timeout_s: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def _shock_requires_opt_in(self) -> OpenShockConfig:
        if self.control_type == "Shock" and not self.allow_shock:
            raise ValueError('control_type = "Shock" requires allow_shock = true')
        return self


class _Shocker(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    name: str
    isPaused: bool = False  # noqa: N815 - field name is dictated by the api


class _Hub(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    name: str
    shockers: list[_Shocker] = Field(default_factory=list)


class _OwnShockersResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: list[_Hub] | None = None


class _Range(BaseModel):
    model_config = ConfigDict(extra="ignore")
    min: int
    max: int


class _ShockerControl(BaseModel):
    model_config = ConfigDict(extra="ignore")
    paused: bool = False
    intensity: _Range | None = None
    duration: _Range | None = None


class _TokenSelf(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    permissions: list[str] = Field(default_factory=list)
    shockerControl: _ShockerControl | None = None  # noqa: N815 - field name is dictated by the api


class OpenShockBackend:
    name = "openshock"

    def __init__(self, config: OpenShockConfig, token: str | None) -> None:
        self._cfg = config
        self._token = token
        self._http = JsonHttp(
            self.name,
            config.api_url,
            headers={"OpenShockToken": token or ""},
            timeout_s=config.timeout_s,
        )
        self._ids: list[UUID] = list(config.shockers)
        self._max_intensity = config.max_intensity
        self._max_duration = MAX_DURATION_MS

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> OpenShockBackend:
        cfg = OpenShockConfig.model_validate(raw)
        return cls(cfg, os.environ.get(TOKEN_ENV) or cfg.token)

    async def start(self) -> None:
        if not self._token:
            raise BackendError(
                self.name, f"no api token: set {TOKEN_ENV} or backends.openshock.token"
            )
        await self._http.open()
        info = await self._fetch_token_info()
        if REQUIRED_PERMISSION not in info.permissions:
            raise BackendError(self.name, f"token {info.name!r} lacks {REQUIRED_PERMISSION}")
        control = info.shockerControl
        if control is not None:
            if control.paused:
                raise BackendError(self.name, f"token {info.name!r} is paused")
            if control.intensity is not None:
                self._max_intensity = min(self._max_intensity, control.intensity.max)
            if control.duration is not None:
                self._max_duration = min(self._max_duration, control.duration.max)
        await self._load_targets()
        log.info(
            "backend.connected",
            backend=self.name,
            token=info.name,
            shockers=[str(i) for i in self._ids],
            control_type=self._cfg.control_type,
            max_intensity=self._max_intensity,
            max_duration_ms=self._max_duration,
        )

    async def close(self) -> None:
        await self.halt()
        await self._http.close()

    async def play(self, pattern: Pattern) -> None:
        ids = await self._targets()
        try:
            for pulse in pattern.pulses:
                await self._control(
                    ids,
                    self._cfg.control_type,
                    intensity=self._scale(pulse.intensity),
                    duration=self._clamp(pulse.duration_ms),
                )
                await asyncio.sleep((pulse.duration_ms + pulse.pause_ms) / 1000)
        except asyncio.CancelledError:
            await self._stop(ids)
            raise

    async def halt(self) -> None:
        if not self._http.is_open or not self._ids:
            return
        try:
            await self._stop(self._ids)
        except BackendError as exc:
            log.warning("backend.halt_failed", backend=self.name, error=str(exc))

    async def devices(self) -> list[DeviceInfo]:
        if not self._token:
            return []
        hubs = await self._fetch_hubs()
        return [
            DeviceInfo(
                backend=self.name,
                device_id=str(shocker.id),
                name=f"{hub.name} / {shocker.name}",
                connected=not shocker.isPaused,
            )
            for hub in hubs
            for shocker in hub.shockers
        ]

    def _scale(self, intensity: float) -> int:
        return min(round(intensity * 100), self._max_intensity)

    def _clamp(self, duration_ms: int) -> int:
        return max(MIN_DURATION_MS, min(duration_ms, self._max_duration))

    async def _fetch_token_info(self) -> _TokenSelf:
        status, body = await self._http.request("GET", SELF_INFO_PATH)
        if status == 401:
            raise BackendError(self.name, "api token rejected (http 401)")
        if status != 200:
            raise BackendError(self.name, f"token check failed: http {status}: {_problem(body)}")
        return _TokenSelf.model_validate(body)

    async def _targets(self) -> list[UUID]:
        if not self._ids:
            await self._load_targets()
        if not self._ids:
            raise BackendError(self.name, "no shockers available for this token")
        return self._ids

    async def _load_targets(self) -> None:
        if self._cfg.shockers:
            self._ids = list(self._cfg.shockers)
            return
        hubs = await self._fetch_hubs()
        self._ids = [shocker.id for hub in hubs for shocker in hub.shockers]
        if not self._ids:
            log.warning("backend.no_shockers", backend=self.name)

    async def _fetch_hubs(self) -> list[_Hub]:
        status, body = await self._http.request("GET", OWN_SHOCKERS_PATH)
        if status != 200:
            raise BackendError(
                self.name, f"listing shockers failed: http {status}: {_problem(body)}"
            )
        return _OwnShockersResponse.model_validate(body).data or []

    async def _control(
        self, ids: list[UUID], control_type: str, *, intensity: int, duration: int
    ) -> None:
        body = {
            "shocks": [
                {
                    "id": str(shocker_id),
                    "type": control_type,
                    "intensity": intensity,
                    "duration": duration,
                    "exclusive": self._cfg.exclusive,
                }
                for shocker_id in ids
            ],
            "customName": "haptic-bridge",
        }
        status, response = await self._http.request("POST", CONTROL_PATH, json_body=body)
        if status != 200:
            raise BackendError(self.name, f"control rejected: http {status}: {_problem(response)}")

    async def _stop(self, ids: list[UUID]) -> None:
        await self._control(ids, "Stop", intensity=0, duration=MIN_DURATION_MS)


def _problem(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("title", "detail", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return str(body)[:200] if body is not None else "no body"
