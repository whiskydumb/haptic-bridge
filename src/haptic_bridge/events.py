from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field


class EventKind(StrEnum):
    PERMISSION = "permission"
    INPUT = "input"
    DONE = "done"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class HapticEvent:
    kind: EventKind
    source: str
    session_id: str | None = None
    message: str | None = None
    pattern: str | None = None


Channel = Annotated[int, Field(ge=0, le=255)]
Rgb = tuple[Channel, Channel, Channel]


class Pulse(BaseModel):
    intensity: float = Field(ge=0.0, le=1.0)
    duration_ms: int = Field(ge=50, le=30_000)
    pause_ms: int = Field(default=0, ge=0, le=30_000)


class Pattern(BaseModel):
    pulses: list[Pulse] = Field(min_length=1)
    color: Rgb | None = None

    def capped(self, max_intensity: float) -> Pattern:
        pulses = [
            pulse.model_copy(update={"intensity": min(pulse.intensity, max_intensity)})
            for pulse in self.pulses
        ]
        return self.model_copy(update={"pulses": pulses})


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    backend: str
    device_id: str
    name: str
    connected: bool
