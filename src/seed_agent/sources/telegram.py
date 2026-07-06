from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent

MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")
FetchTelegramUpdates = Callable[[str, dict[str, object]], dict[str, Any]]


def poll_telegram_updates(
    *,
    bot_token: str,
    offset: int | None = None,
    timeout_seconds: int = 0,
    allowed_chat_ids: set[str] | None = None,
    fetcher: FetchTelegramUpdates | None = None,
) -> list[SourceIntentEvent]:
    params: dict[str, object] = {"timeout": max(timeout_seconds, 0)}
    if offset is not None:
        params["offset"] = offset
    payload = (fetcher or _fetch_updates)(bot_token, params)
    updates = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(updates, list):
        return []
    events: list[SourceIntentEvent] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        event = parse_telegram_update(update)
        if event is None:
            continue
        chat_id = event.metadata.get("chat_id")
        if allowed_chat_ids and str(chat_id) not in allowed_chat_ids:
            continue
        events.append(event)
    return events


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


def _fetch_updates(bot_token: str, params: dict[str, object]) -> dict[str, Any]:
    response = httpx.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}
