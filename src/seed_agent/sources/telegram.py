from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent

MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")


def parse_telegram_update(payload: dict[str, Any]) -> SourceIntentEvent | None:
    message = _message_payload(payload)
    if message is None:
        return None
    text = message.get("text") or message.get("caption")
    if not isinstance(text, str) or not text.strip():
        return None

    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    message_id = message.get("message_id")
    source_event_id = _source_event_id(payload.get("update_id"), chat_id, message_id)
    return SourceIntentEvent(
        source=IntentSource.TELEGRAM,
        raw_text=text,
        source_event_id=source_event_id,
        requested_at=_unix_datetime(message.get("date")),
        metadata={
            "source_adapter": "telegram",
            "chat_id": str(chat_id) if chat_id is not None else None,
            "message_id": str(message_id) if message_id is not None else None,
        },
    )


def _message_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in MESSAGE_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _source_event_id(
    update_id: object,
    chat_id: object,
    message_id: object,
) -> str | None:
    if chat_id is not None and message_id is not None:
        return f"telegram:{chat_id}:{message_id}"
    if update_id is not None:
        return f"telegram:update:{update_id}"
    return None


def _unix_datetime(value: object) -> datetime | None:
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=UTC)

