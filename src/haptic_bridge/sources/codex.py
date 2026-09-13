from __future__ import annotations

from typing import Any

from haptic_bridge.events import EventKind, HapticEvent
from haptic_bridge.sources.common import opt_str

SOURCE = "codex"

NOTIFY_KINDS: dict[str, EventKind] = {
    "agent-turn-complete": EventKind.DONE,
}

HOOK_KINDS: dict[str, EventKind] = {
    "Stop": EventKind.DONE,
    "PermissionRequest": EventKind.PERMISSION,
}


def parse(payload: dict[str, Any]) -> HapticEvent | None:
    if "type" in payload:
        kind = NOTIFY_KINDS.get(opt_str(payload.get("type")) or "")
        session = payload.get("thread-id")
        message = payload.get("last-assistant-message")
    else:
        kind = HOOK_KINDS.get(opt_str(payload.get("hook_event_name")) or "")
        session = payload.get("session_id")
        message = payload.get("last_assistant_message")
    if kind is None:
        return None
    return HapticEvent(
        kind=kind,
        source=SOURCE,
        session_id=opt_str(session, limit=128),
        message=opt_str(message),
    )
