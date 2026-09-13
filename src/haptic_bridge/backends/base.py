from __future__ import annotations

from typing import Protocol, runtime_checkable

from haptic_bridge.events import DeviceInfo, Pattern


class BackendError(Exception):
    def __init__(self, backend: str, message: str) -> None:
        super().__init__(f"{backend}: {message}")
        self.backend = backend


@runtime_checkable
class DeviceBackend(Protocol):
    name: str

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def play(self, pattern: Pattern) -> None: ...

    async def halt(self) -> None: ...

    async def devices(self) -> list[DeviceInfo]: ...
