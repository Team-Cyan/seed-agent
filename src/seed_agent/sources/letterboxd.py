from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent


def read_letterboxd_watchlist_csv(
    path: Path,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    return parse_letterboxd_watchlist_csv(
        path.read_text(encoding="utf-8-sig"),
        source_config_id=source_config_id,
        label=label,
    )


def parse_letterboxd_watchlist_csv(
    csv_text: str,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    rows = csv.DictReader(csv_text.splitlines())
    events: list[SourceIntentEvent] = []
    for row in rows:
        event = _event_from_row(row, source_config_id=source_config_id, label=label)
        if event is not None:
            events.append(event)
    return events


def _event_from_row(
    row: dict[str, str],
    *,
    source_config_id: str | None,
    label: str | None,
) -> SourceIntentEvent | None:
    title = _first_text(row, ("Name", "Title", "Film", "Film Name"))
    if title is None:
        return None
    year = _normalize_year(_first_text(row, ("Year", "Release Year")))
    uri = _first_text(row, ("Letterboxd URI", "URL", "Uri"))
    raw_text = " ".join(part for part in (title, year) if part)
    metadata: dict[str, object] = {
        "source_adapter": "letterboxd_watchlist_csv",
        "media_type": "movie",
    }
    if uri:
        metadata["url"] = uri
    if source_config_id:
        metadata["source_config_id"] = source_config_id
    if label:
        metadata["source_label"] = f"Letterboxd-{label}"
    requested_at = _parse_date(_first_text(row, ("Date", "Watched Date", "Created")))
    return SourceIntentEvent(
        source=IntentSource.LETTERBOXD,
        raw_text=raw_text,
        source_event_id=f"letterboxd:{uri}" if uri else None,
        requested_at=requested_at,
        metadata=metadata,
    )


def _first_text(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    normalized = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = normalized.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _normalize_year(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) == 4 and text.isdigit():
        return text
    return None


def _parse_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
