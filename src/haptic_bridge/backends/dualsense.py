from __future__ import annotations

import asyncio
from typing import Any

import structlog
from pydantic import BaseModel
from structlog.typing import FilteringBoundLogger

from haptic_bridge.backends.base import BackendError
from haptic_bridge.events import DeviceInfo, Pattern

log: FilteringBoundLogger = structlog.get_logger(__name__)

MOTOR_MAX = 255


class DualSenseConfig(BaseModel):
    enabled: bool = True
    lightbar: bool = True


class DualSenseBackend:
    name = "dualsense"

    def __init__(self, *, lightbar: bool = True) -> None:
        self._lightbar = lightbar
        self._ds: Any | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> DualSenseBackend:
        cfg = DualSenseConfig.model_validate(raw)
        return cls(lightbar=cfg.lightbar)

    async def start(self) -> None:
        self._connect()

    async def close(self) -> None:
        await self.halt()
        if self._ds is not None:
            self._ds.close()
            self._ds = None

    async def play(self, pattern: Pattern) -> None:
        ds = self._ensure_connected()
        async with self._lock:
            try:
                if self._lightbar and pattern.color is not None:
                    ds.light.setColorI(*pattern.color)
                for pulse in pattern.pulses:
                    self._set_motors(ds, pulse.intensity)
                    await asyncio.sleep(pulse.duration_ms / 1000)
                    self._set_motors(ds, 0.0)
                    if pulse.pause_ms:
                        await asyncio.sleep(pulse.pause_ms / 1000)
            finally:
                self._set_motors(ds, 0.0)

    async def halt(self) -> None:
        if self._ds is not None:
            self._set_motors(self._ds, 0.0)

    async def devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                backend=self.name,
                device_id="dualsense-0",
                name="DualSense Wireless Controller",
                connected=self._ds is not None,
            )
        ]

    def _connect(self) -> None:
        try:
            from pydualsense import pydualsense
        except ImportError as exc:
            raise BackendError(
                self.name, "pydualsense is not installed; run: uv sync --extra dualsense"
            ) from exc
        ds = pydualsense()
        try:
            ds.init()
        except Exception as exc:
            raise BackendError(self.name, f"cannot open controller: {exc}") from exc
        self._ds = ds
        log.info("backend.connected", backend=self.name)

    def _ensure_connected(self) -> Any:
        if self._ds is None:
            self._connect()
        return self._ds

    @staticmethod
    def _set_motors(ds: Any, intensity: float) -> None:
        level = round(intensity * MOTOR_MAX)
        ds.setLeftMotor(level)
        ds.setRightMotor(level)
