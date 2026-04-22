from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent


def parse_wechat_bridge_event(payload: dict[str, Any]) -> SourceIntentEvent | None:
    text = _first_text(payload, ("text", "content", "message"))
    if text is None:
        return None
    event_id = _first_text(payload, ("source_event_id", "msg_id", "message_id", "id"))
    sender = _first_text(payload, ("from_user", "sender", "user"))
    return SourceIntentEvent(
        source=IntentSource.WECHAT_BRIDGE,
        raw_text=text,
        source_event_id=f"wechat:{event_id}" if event_id is not None else None,
        requested_at=_requested_at(payload),
        metadata={
            "source_adapter": "wechat_bridge",
            "sender": sender,
        },
    )


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _requested_at(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("requested_at")
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    unix_value = payload.get("timestamp") or payload.get("create_time")
    if isinstance(unix_value, int | float):
        return datetime.fromtimestamp(unix_value, tz=UTC)
    return None

