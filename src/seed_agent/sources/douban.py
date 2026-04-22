from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent


def read_douban_wanted(path: Path) -> list[SourceIntentEvent]:
    if not path.is_file():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    items = _items(loaded)
    events: list[SourceIntentEvent] = []
    for item in items:
        event = _event_from_item(item)
        if event is not None:
            events.append(event)
    return events


def _items(loaded: Any) -> list[dict[str, Any]]:
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    if not isinstance(loaded, dict):
        return []
    for key in ("items", "wanted", "subjects"):
        value = loaded.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _event_from_item(item: dict[str, Any]) -> SourceIntentEvent | None:
    title = _first_text(item, ("title", "name", "subject"))
    if title is None:
        return None
    year = _first_text(item, ("year", "pub_year"))
    raw_text = f"{title} {year}" if year is not None else title
    douban_id = _first_text(item, ("id", "douban_id", "subject_id"))
    return SourceIntentEvent(
        source=IntentSource.DOUBAN_WANTED,
        raw_text=raw_text,
        source_event_id=f"douban:{douban_id}" if douban_id is not None else None,
        metadata={
            "source_adapter": "douban_wanted",
            "url": _first_text(item, ("url", "subject_url")),
            "kind": _first_text(item, ("kind", "type")),
        },
    )


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None
