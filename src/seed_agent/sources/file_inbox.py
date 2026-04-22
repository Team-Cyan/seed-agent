from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent


def read_file_inbox(path: Path) -> list[SourceIntentEvent]:
    if not path.is_file():
        return []
    return [_event_from_mapping(event) for event in _read_jsonl(path) if _event_text(event)]


def _event_from_mapping(event: dict[str, Any]) -> SourceIntentEvent:
    raw_text = _event_text(event)
    if raw_text is None:
        raise ValueError("inbox event is missing text")
    return SourceIntentEvent(
        source=IntentSource.FILE_INBOX,
        raw_text=raw_text,
        source_event_id=_event_id(event),
        requested_at=_event_requested_at(event),
        metadata={"source_adapter": "file_inbox"},
    )


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            yield loaded


def _event_text(event: dict[str, Any]) -> str | None:
    for key in ("raw_text", "text", "message", "title"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _event_id(event: dict[str, Any]) -> str | None:
    for key in ("source_event_id", "event_id", "id"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _event_requested_at(event: dict[str, Any]) -> datetime | None:
    value = event.get("requested_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed

