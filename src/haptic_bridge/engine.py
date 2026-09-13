from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from structlog.typing import FilteringBoundLogger

from haptic_bridge.backends.base import BackendError, DeviceBackend
from haptic_bridge.config import EngineConfig
from haptic_bridge.events import DeviceInfo, EventKind, HapticEvent, Pattern

log: FilteringBoundLogger = structlog.get_logger(__name__)

DispatchStatus = Literal["played", "suppressed", "ignored"]


@dataclass(frozen=True, slots=True)
class Dispatch:
    status: DispatchStatus
    reason: str | None = None
    pattern: str | None = None
    backends: tuple[str, ...] = ()


class HapticEngine:
    def __init__(
        self,
        config: EngineConfig,
        patterns: dict[str, Pattern],
        events: dict[EventKind, str],
        backends: list[DeviceBackend],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._patterns = patterns
        self._events = events
        self._backends = backends
        self._clock = clock
        self._enabled = True
        self._last_fired: dict[tuple[str, EventKind], float] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def backend_names(self) -> list[str]:
        return [backend.name for backend in self._backends]

    @property
    def pattern_names(self) -> list[str]:
        return sorted(self._patterns)

    async def start(self) -> None:
        for backend in self._backends:
            try:
                await backend.start()
            except BackendError as exc:
                log.warning("backend.unavailable", backend=backend.name, error=str(exc))

    async def close(self) -> None:
        await self.halt()
        for backend in self._backends:
            try:
                await backend.close()
            except Exception:
                log.exception("backend.close_failed", backend=backend.name)

    async def handle(self, event: HapticEvent) -> Dispatch:
        if not self._enabled:
            return Dispatch("suppressed", reason="halted")
        pattern_name = event.pattern or self._events.get(event.kind)
        if pattern_name is None:
            return Dispatch("ignored", reason=f"no pattern mapped for kind={event.kind}")
        pattern = self._patterns.get(pattern_name)
        if pattern is None:
            return Dispatch("ignored", reason=f"unknown pattern {pattern_name!r}")
        if self._in_cooldown(event):
            return Dispatch("suppressed", reason="cooldown", pattern=pattern_name)
        self._last_fired[(event.source, event.kind)] = self._clock()
        capped = pattern.capped(self._config.max_intensity)
        for backend in self._backends:
            self._launch(backend, capped)
        log.info(
            "event.dispatched",
            kind=event.kind,
            source=event.source,
            pattern=pattern_name,
            session_id=event.session_id,
        )
        return Dispatch("played", pattern=pattern_name, backends=tuple(self.backend_names))

    async def halt(self) -> None:
        self._enabled = False
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()
        for backend in self._backends:
            try:
                await backend.halt()
            except Exception:
                log.exception("backend.halt_failed", backend=backend.name)
        log.warning("engine.halted")

    def resume(self) -> None:
        self._enabled = True
        log.info("engine.resumed")

    async def wait_idle(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def devices(self) -> list[DeviceInfo]:
        found: list[DeviceInfo] = []
        for backend in self._backends:
            try:
                found.extend(await backend.devices())
            except Exception:
                log.exception("backend.devices_failed", backend=backend.name)
        return found

    def _in_cooldown(self, event: HapticEvent) -> bool:
        last = self._last_fired.get((event.source, event.kind))
        if last is None:
            return False
        return (self._clock() - last) * 1000 < self._config.cooldown_ms

    def _launch(self, backend: DeviceBackend, pattern: Pattern) -> None:
        previous = self._tasks.get(backend.name)
        if previous is not None and not previous.done():
            previous.cancel()
        self._tasks[backend.name] = asyncio.create_task(
            self._play(backend, pattern), name=f"play:{backend.name}"
        )

    @staticmethod
    async def _play(backend: DeviceBackend, pattern: Pattern) -> None:
        try:
            await backend.play(pattern)
        except BackendError as exc:
            log.warning("backend.play_skipped", backend=backend.name, error=str(exc))
        except Exception:
            log.exception("backend.play_failed", backend=backend.name)
