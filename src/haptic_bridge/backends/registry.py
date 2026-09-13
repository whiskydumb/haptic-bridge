from __future__ import annotations

from collections.abc import Callable
from typing import Any

from haptic_bridge.backends.base import DeviceBackend
from haptic_bridge.backends.dualsense import DualSenseBackend
from haptic_bridge.backends.lovense import LovenseBackend
from haptic_bridge.backends.mock import MockBackend
from haptic_bridge.backends.openshock import OpenShockBackend

BackendFactory = Callable[[dict[str, Any]], DeviceBackend]

FACTORIES: dict[str, BackendFactory] = {
    MockBackend.name: MockBackend.from_config,
    DualSenseBackend.name: DualSenseBackend.from_config,
    OpenShockBackend.name: OpenShockBackend.from_config,
    LovenseBackend.name: LovenseBackend.from_config,
}


def build_backends(raw: dict[str, dict[str, Any]]) -> list[DeviceBackend]:
    backends: list[DeviceBackend] = []
    for name, table in raw.items():
        factory = FACTORIES.get(name)
        if factory is None:
            raise ValueError(f"unknown backend {name!r}; known: {sorted(FACTORIES)}")
        if not table.get("enabled", True):
            continue
        backends.append(factory(table))
    return backends
