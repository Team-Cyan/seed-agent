from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from html import unescape
from io import StringIO
from pathlib import Path
from typing import Any

import httpx

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent

IMDB_ID_RE = re.compile(r"\btt\d{6,12}\b", re.IGNORECASE)
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(?P<payload>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def read_imdb_watchlist_csv(
    path: Path,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    if not path.is_file():
        return []
    return parse_imdb_watchlist_csv(
        path.read_text(encoding="utf-8-sig"),
        source_config_id=source_config_id,
        label=label,
    )


def fetch_imdb_watchlist(
    url: str,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
    fetcher: Any | None = None,
) -> list[SourceIntentEvent]:
    html = (fetcher or _fetch_url)(url)
    return parse_imdb_watchlist_html(html, source_config_id=source_config_id, label=label)


def parse_imdb_watchlist_csv(
    csv_text: str,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    reader = csv.DictReader(StringIO(csv_text))
    events: list[SourceIntentEvent] = []
    for row in reader:
        event = _event_from_csv_row(row, source_config_id=source_config_id, label=label)
        if event is not None:
            events.append(event)
    return events


def parse_imdb_watchlist_html(
    html: str,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    events: list[SourceIntentEvent] = []
    for item in _next_data_title_items(html):
        event = _event_from_next_item(item, source_config_id=source_config_id, label=label)
        if event is not None:
            events.append(event)
    if events:
        return events
    for imdb_id, title in _fallback_title_links(html):
        event = _event_from_fields(
            imdb_id=imdb_id,
            title=title,
            year=None,
            title_type=None,
            genres="",
            requested_at=None,
            url=f"https://www.imdb.com/title/{imdb_id}/",
            source_adapter="imdb_watchlist_public",
            source_config_id=source_config_id,
            label=label,
        )
        if event is not None:
            events.append(event)
    return events


def _event_from_csv_row(
    row: dict[str, str],
    *,
    source_config_id: str | None,
    label: str | None,
) -> SourceIntentEvent | None:
    imdb_id = _normalize_imdb_id(_first_text(row, ("Const", "IMDb ID", "imdb_id", "ID")))
    if imdb_id is None:
        imdb_id = _imdb_id_from_text(_first_text(row, ("URL", "Link", "Title URL")) or "")
    title = _first_text(row, ("Title", "Name", "title"))
    if imdb_id is None or title is None:
        return None
    return _event_from_fields(
        imdb_id=imdb_id,
        title=title,
        year=_first_text(row, ("Year", "Release Year", "year")),
        title_type=_first_text(row, ("Title Type", "Type", "titleType")),
        genres=_first_text(row, ("Genres", "Genre", "genres")) or "",
        requested_at=_parse_date(_first_text(row, ("Created", "Date Added", "Added", "created"))),
        url=_first_text(row, ("URL", "Link", "Title URL")),
        source_adapter="imdb_watchlist_csv",
        source_config_id=source_config_id,
        label=label,
    )


def _event_from_next_item(
    item: dict[str, Any],
    *,
    source_config_id: str | None,
    label: str | None,
) -> SourceIntentEvent | None:
    title_data = item.get("title") if isinstance(item.get("title"), dict) else item
    imdb_id = _normalize_imdb_id(
        _nested_text(title_data, ("id",))
        or _nested_text(title_data, ("titleId",))
        or _nested_text(item, ("id",))
    )
    title = (
        _nested_text(title_data, ("titleText", "text"))
        or _nested_text(title_data, ("originalTitleText", "text"))
        or _nested_text(title_data, ("title",))
        or _nested_text(item, ("title", "titleText", "text"))
    )
    year = (
        _nested_text(title_data, ("releaseYear", "year"))
        or _nested_text(title_data, ("year",))
        or _nested_text(item, ("year",))
    )
    title_type = (
        _nested_text(title_data, ("titleType", "id"))
        or _nested_text(title_data, ("titleType", "text"))
        or _nested_text(item, ("titleType",))
    )
    created = _nested_text(item, ("created",)) or _nested_text(item, ("dateAdded",))
    if imdb_id is None or title is None:
        return None
    return _event_from_fields(
        imdb_id=imdb_id,
        title=title,
        year=year,
        title_type=title_type,
        genres=" ".join(_iter_genres(title_data)),
        requested_at=_parse_date(created),
        url=f"https://www.imdb.com/title/{imdb_id}/",
        source_adapter="imdb_watchlist_public",
        source_config_id=source_config_id,
        label=label,
    )


def _event_from_fields(
    *,
    imdb_id: str,
    title: str,
    year: str | int | None,
    title_type: str | None,
    genres: str,
    requested_at: datetime | None,
    url: str | None,
    source_adapter: str,
    source_config_id: str | None,
    label: str | None,
) -> SourceIntentEvent | None:
    clean_title = _clean_text(title)
    if not clean_title:
        return None
    year_text = _normalize_year(year)
    raw_text = f"{clean_title} {year_text}" if year_text is not None else clean_title
    metadata = {
        "source_adapter": source_adapter,
        "url": url or f"https://www.imdb.com/title/{imdb_id}/",
        "kind": _media_type(title_type, genres),
        "media_type": _media_type(title_type, genres),
        "title_type": title_type,
        "genres": genres,
        "external_ids": {"imdb": imdb_id},
    }
    if source_config_id:
        metadata["source_config_id"] = source_config_id
    if label:
        metadata["source_label"] = f"IMDb-{label}"
    return SourceIntentEvent(
        source=IntentSource.IMDB_WATCHLIST,
        raw_text=raw_text,
        source_event_id=f"imdb:{imdb_id}",
        requested_at=requested_at,
        metadata=metadata,
    )


def _next_data_title_items(html: str) -> list[dict[str, Any]]:
    match = NEXT_DATA_RE.search(html)
    if match is None:
        return []
    try:
        payload = json.loads(unescape(match.group("payload")))
    except json.JSONDecodeError:
        return []
    return [
        item
        for item in _walk_dicts(payload)
        if isinstance(item.get("title"), dict)
        and _normalize_imdb_id(_nested_text(item["title"], ("id",))) is not None
    ]


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _fallback_title_links(html: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    pattern = re.compile(
        r'<a[^>]+href=["\']/title/(?P<id>tt\d{6,12})/[^"\']*["\'][^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        imdb_id = _normalize_imdb_id(match.group("id"))
        title = _clean_text(_strip_tags(match.group("title")))
        if imdb_id is not None and title:
            links.append((imdb_id, title))
    return links


def _iter_genres(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if "genre" in value:
            yield str(value["genre"])
        if "text" in value and str(value.get("id", "")).lower() == "genre":
            yield str(value["text"])
        for child in value.values():
            yield from _iter_genres(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_genres(child)


def _media_type(title_type: str | None, genres: str) -> str:
    type_key = str(title_type or "").strip().lower()
    genre_key = genres.lower()
    if type_key in {"tvseries", "tvminiseries", "tvepisode", "tvshort", "tv"}:
        return "anime" if "animation" in genre_key else "tv"
    return "movie"


def _nested_text(value: Any, keys: tuple[str, ...]) -> str | None:
    current = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if current is None:
        return None
    text = str(current).strip()
    return text or None


def _first_text(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    normalized = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = normalized.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _normalize_imdb_id(value: str | None) -> str | None:
    if not value:
        return None
    match = IMDB_ID_RE.search(value)
    if match is None:
        return None
    return match.group(0).lower()


def _imdb_id_from_text(value: str) -> str | None:
    return _normalize_imdb_id(value)


def _normalize_year(value: str | int | None) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", str(value))
    return match.group(1) if match is not None else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _clean_text(value: str) -> str:
    return " ".join(unescape(value).split())


def _strip_tags(value: str) -> str:
    return TAG_RE.sub("", value)


def _fetch_url(url: str) -> str:
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.text
