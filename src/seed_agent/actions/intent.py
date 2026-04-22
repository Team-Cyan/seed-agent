from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seed_agent.intent.parse import parse_resource_intent
from seed_agent.models import Decision, IntentSource, ResourceIntent
from seed_agent.state import StateStore


def add_intent(
    raw_text: str,
    store: StateStore,
    *,
    source: IntentSource = IntentSource.CLI,
    requested_at: datetime | None = None,
    source_event_id: str | None = None,
) -> tuple[ResourceIntent, Decision]:
    intent = parse_resource_intent(
        raw_text,
        source=source,
        requested_at=requested_at,
        source_event_id=source_event_id,
    )
    existed = store.get_intent(intent.intent_id) is not None
    store.upsert_intent(intent)
    return intent, _ingest_decision(intent, existed=existed)


def ingest_inbox(
    path: Path,
    store: StateStore,
    *,
    source: IntentSource = IntentSource.FILE_INBOX,
    requested_at: datetime | None = None,
) -> list[tuple[ResourceIntent, Decision]]:
    if not path.is_file():
        return []

    ingested: list[tuple[ResourceIntent, Decision]] = []
    for event in _read_jsonl(path):
        raw_text = _event_text(event)
        if raw_text is None:
            continue
        source_event_id = _event_id(event)
        ingested.append(
            add_intent(
                raw_text,
                store,
                source=source,
                requested_at=_event_requested_at(event) or requested_at,
                source_event_id=source_event_id,
            )
        )
    return ingested


def _ingest_decision(intent: ResourceIntent, *, existed: bool) -> Decision:
    return Decision(
        action="intent.ingest",
        target_id=intent.intent_id,
        execute=True,
        reason="intent already existed" if existed else "intent ingested",
        new_state={
            "intent_id": intent.intent_id,
            "source": intent.source.value,
            "title": intent.title,
            "kind": intent.kind.value,
            "state": intent.state.value,
            "existed": existed,
        },
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
