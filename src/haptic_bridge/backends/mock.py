from __future__ import annotations

import asyncio
from typing import Any

import structlog
from pydantic import BaseModel
from structlog.typing import FilteringBoundLogger

from haptic_bridge.events import DeviceInfo, Pattern

log: FilteringBoundLogger = structlog.get_logger(__name__)


class MockConfig(BaseModel):
    enabled: bool = True
    realtime: bool = True


class MockBackend:
    name = "mock"

    def __init__(self, *, realtime: bool = True) -> None:
        self._realtime = realtime
        self.played: list[Pattern] = []
        self.halt_calls = 0

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> MockBackend:
        cfg = MockConfig.model_validate(raw)
        return cls(realtime=cfg.realtime)

    async def start(self) -> None:
        log.info("backend.ready", backend=self.name, realtime=self._realtime)

    async def close(self) -> None:
        return None

    async def play(self, pattern: Pattern) -> None:
        self.played.append(pattern)
        for pulse in pattern.pulses:
            log.info(
                "mock.pulse",
                intensity=pulse.intensity,
                duration_ms=pulse.duration_ms,
                pause_ms=pulse.pause_ms,
            )
            if self._realtime:
                await asyncio.sleep((pulse.duration_ms + pulse.pause_ms) / 1000)

    async def halt(self) -> None:
        self.halt_calls += 1

    async def devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(backend=self.name, device_id="mock-0", name="mock device", connected=True)
        ]
