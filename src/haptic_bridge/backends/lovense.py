from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from structlog.typing import FilteringBoundLogger

from haptic_bridge.backends.base import BackendError
from haptic_bridge.backends.httpclient import JsonHttp
from haptic_bridge.events import DeviceInfo, Pattern

log: FilteringBoundLogger = structlog.get_logger(__name__)

COMMAND_PATH = "/command"
MAX_STRENGTH = 20
API_VERSION = 1

ERROR_CODES: dict[int, str] = {
    400: "invalid command",
    401: "toy not found",
    402: "toy not connected",
    403: "toy does not support this command",
    404: "invalid parameter",
    500: "http server not started or disabled in the app",
    506: "server error",
}


class LovenseConfig(BaseModel):
    enabled: bool = True
    base_url: str = "https://127-0-0-1.lovense.club:30010"
    toys: list[str] = Field(default_factory=list)
    max_strength: int = Field(default=MAX_STRENGTH, ge=0, le=MAX_STRENGTH)
    timeout_s: float = Field(default=3.0, gt=0, le=60)


class _Toy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str = "toy"
    status: str = "0"


class LovenseBackend:
    name = "lovense"

    def __init__(self, config: LovenseConfig) -> None:
        self._cfg = config
        self._http = JsonHttp(self.name, config.base_url, timeout_s=config.timeout_s)

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> LovenseBackend:
        return cls(LovenseConfig.model_validate(raw))

    async def start(self) -> None:
        toys = await self._get_toys()
        connected = [toy.id for toy in toys if toy.status == "1"]
        log.info(
            "backend.connected", backend=self.name, toys=[t.id for t in toys], online=connected
        )

    async def close(self) -> None:
        await self.halt()
        await self._http.close()

    async def play(self, pattern: Pattern) -> None:
        try:
            for pulse in pattern.pulses:
                await self._function(f"Vibrate:{self._scale(pulse.intensity)}")
                await asyncio.sleep(pulse.duration_ms / 1000)
                await self._function("Stop")
                if pulse.pause_ms:
                    await asyncio.sleep(pulse.pause_ms / 1000)
        except asyncio.CancelledError:
            await self._function("Stop")
            raise

    async def halt(self) -> None:
        if not self._http.is_open:
            return
        try:
            await self._function("Stop")
        except BackendError as exc:
            log.warning("backend.halt_failed", backend=self.name, error=str(exc))

    async def devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                backend=self.name,
                device_id=toy.id,
                name=toy.name,
                connected=toy.status == "1",
            )
            for toy in await self._get_toys()
        ]

    def _scale(self, intensity: float) -> int:
        return min(round(intensity * MAX_STRENGTH), self._cfg.max_strength)

    async def _function(self, action: str) -> None:
        targets: list[str | None] = list(self._cfg.toys) or [None]
        for toy in targets:
            body: dict[str, Any] = {
                "command": "Function",
                "action": action,
                "timeSec": 0,
                "stopPrevious": 1,
                "apiVer": API_VERSION,
            }
            if toy is not None:
                body["toy"] = toy
            await self._command(body)

    async def _get_toys(self) -> list[_Toy]:
        response = await self._command({"command": "GetToys"})
        raw = response.get("data", {}).get("toys", {}) if isinstance(response, dict) else {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw else {}
            except json.JSONDecodeError as exc:
                raise BackendError(self.name, f"GetToys returned unreadable toys: {exc}") from exc
        if not isinstance(raw, dict):
            raise BackendError(self.name, "GetToys returned an unexpected toys shape")
        return [_Toy.model_validate({"id": toy_id, **info}) for toy_id, info in raw.items()]

    async def _command(self, body: dict[str, Any]) -> dict[str, Any]:
        status, response = await self._http.request("POST", COMMAND_PATH, json_body=body)
        if status != 200 or not isinstance(response, dict):
            raise BackendError(
                self.name, f"{body['command']}: http {status}: {str(response)[:200]}"
            )
        code = response.get("code")
        if code != 200:
            reason = (
                ERROR_CODES.get(int(code), response.get("type", "unknown")) if code else "no code"
            )
            raise BackendError(self.name, f"{body['command']}: app error {code}: {reason}")
        return response
