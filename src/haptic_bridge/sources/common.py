from __future__ import annotations

MAX_TEXT_LEN = 500


def opt_str(value: object, *, limit: int = MAX_TEXT_LEN) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
