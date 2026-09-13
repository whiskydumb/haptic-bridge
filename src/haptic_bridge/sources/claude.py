from __future__ import annotations

from typing import Any

from haptic_bridge.events import EventKind, HapticEvent
from haptic_bridge.sources.common import opt_str

SOURCE = "claude"

NOTIFICATION_KINDS: dict[str, EventKind] = {
    "permission_prompt": EventKind.PERMISSION,
    "idle_prompt": EventKind.INPUT,
    "agent_needs_input": EventKind.INPUT,
    "elicitation_dialog": EventKind.INPUT,
    "elicitation_url_dialog": EventKind.INPUT,
}

EVENT_KINDS: dict[str, EventKind] = {
    "PermissionRequest": EventKind.PERMISSION,
    "Elicitation": EventKind.INPUT,
    "Stop": EventKind.DONE,
}


def parse(payload: dict[str, Any]) -> HapticEvent | None:
    hook_event = opt_str(payload.get("hook_event_name"))
    if hook_event == "Notification":
        kind = NOTIFICATION_KINDS.get(opt_str(payload.get("notification_type")) or "")
    else:
        kind = EVENT_KINDS.get(hook_event or "")
    if kind is None:
        return None
    message = payload.get("message") or payload.get("last_assistant_message")
    return HapticEvent(
        kind=kind,
        source=SOURCE,
        session_id=opt_str(payload.get("session_id"), limit=128),
        message=opt_str(message),
    )
