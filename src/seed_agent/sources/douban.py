from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx

from seed_agent.models import IntentSource
from seed_agent.observability import get_logger, log_event
from seed_agent.sources.base import SourceIntentEvent

DOUBAN_WISH_PAGE_SIZE = 15
DOUBAN_SUBJECT_CLASSIFICATION_VERSION = 2
logger = get_logger("source.douban")
SUBJECT_URL_RE = re.compile(
    r"https?://movie\.douban\.com/subject/(?P<id>\d+)/?",
    re.IGNORECASE,
)
ITEM_RE = re.compile(
    r'<div[^>]+class="[^"]*\bitem\b[^"]*"[^>]*>(?P<body>.*?)</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
TITLE_RE = re.compile(
    r'<li[^>]+class="title"[^>]*>.*?'
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
EM_RE = re.compile(r"<em[^>]*>(?P<title>.*?)</em>", re.IGNORECASE | re.DOTALL)
INTRO_RE = re.compile(
    r'<li[^>]+class="intro"[^>]*>(?P<intro>.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)
DATE_RE = re.compile(
    r'<span[^>]+class="[^"]*\bdate\b[^"]*"[^>]*>(?P<date>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|21\d{2})\b")
EPISODE_COUNT_RE = re.compile(r"\b\d+\s*集\b")
SUBJECT_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<payload>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
IMDB_ID_RE = re.compile(r"\btt\d{6,12}\b", re.IGNORECASE)
RSS_SEASON_RE = re.compile(
    r"(?:\bS\d{1,2}\b|\bSeason[ ._-]*\d{1,2}\b|第\s*[一二三四五六七八九十0-9]{1,3}\s*季)",
    re.IGNORECASE,
)


def read_douban_wanted(
    path: Path,
    *,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    if not path.is_file():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    items = _items(loaded)
    events: list[SourceIntentEvent] = []
    for item in items:
        event = _event_from_item(item, source_config_id=source_config_id, label=label)
        if event is not None:
            events.append(event)
    return events


def fetch_douban_wanted_user(
    user_name_or_url: str,
    *,
    max_pages: int = 1,
    fetcher: Any | None = None,
    enrich_subjects: bool = True,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    fetch = fetcher or _fetch_url
    events: list[SourceIntentEvent] = []
    seen_ids: set[str] = set()
    user_name = _douban_user_name(user_name_or_url)
    for page in range(max_pages):
        html = fetch(build_douban_wish_url(user_name_or_url, start=page * DOUBAN_WISH_PAGE_SIZE))
        for event in parse_douban_wish_html(
            html,
            user_name=user_name,
            source_config_id=source_config_id,
            label=label,
        ):
            if enrich_subjects:
                event = enrich_douban_wanted_event(event, fetcher=fetch)
            event_id = event.source_event_id or event.raw_text
            if event_id in seen_ids:
                continue
            events.append(event)
            seen_ids.add(event_id)
    return events


def fetch_douban_interest_rss(
    user_name_or_url: str,
    *,
    fetcher: Any | None = None,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    """Read recent film wishes from Douban's personal-interest RSS feed.

    The feed is deliberately treated as an incremental signal rather than a
    full Want List snapshot: Douban currently exposes only its latest items.
    """
    html = (fetcher or _fetch_url)(build_douban_interest_rss_url(user_name_or_url))
    return parse_douban_interest_rss(
        html,
        user_name=_douban_user_name(user_name_or_url),
        source_config_id=source_config_id,
        label=label,
    )


def build_douban_wish_url(user_name_or_url: str, *, start: int = 0) -> str:
    user_name = quote(_douban_user_name(user_name_or_url), safe="")
    return f"https://movie.douban.com/people/{user_name}/wish?start={start}"


def build_douban_interest_rss_url(user_name_or_url: str) -> str:
    user_name = quote(_douban_user_name(user_name_or_url), safe="")
    return f"https://www.douban.com/feed/people/{user_name}/interests"


def build_douban_mobile_subject_url(douban_id: str) -> str:
    return f"https://m.douban.com/movie/subject/{quote(douban_id, safe='')}/"


def parse_douban_wish_html(
    html: str,
    *,
    user_name: str | None = None,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    events: list[SourceIntentEvent] = []
    for item in _html_items(html):
        event = _event_from_html_item(
            item,
            user_name=user_name,
            source_config_id=source_config_id,
            label=label,
        )
        if event is not None:
            events.append(event)
    return events


def parse_douban_interest_rss(
    rss_xml: str,
    *,
    user_name: str | None = None,
    source_config_id: str | None = None,
    label: str | None = None,
) -> list[SourceIntentEvent]:
    """Parse only movie/TV ``想看`` entries from the interests RSS feed."""
    try:
        root = ElementTree.fromstring(rss_xml)
    except ElementTree.ParseError as exc:
        raise ValueError("Douban interests RSS is not valid XML") from exc

    events: list[SourceIntentEvent] = []
    seen_ids: set[str] = set()
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title") or "")
        if not title.startswith("想看"):
            continue
        url = _clean_text(item.findtext("link") or "")
        subject_match = SUBJECT_URL_RE.search(url)
        if subject_match is None:
            continue
        douban_id = subject_match.group("id")
        if douban_id in seen_ids:
            continue
        subject_title = _clean_title(title.removeprefix("想看"))
        if not subject_title:
            continue
        requested_at = _parse_rss_date(item.findtext("pubDate"))
        metadata = {
            "source_adapter": "douban_interest_rss",
            "url": f"https://movie.douban.com/subject/{douban_id}/",
            "douban_user_name": user_name,
            "external_ids": {"douban": douban_id},
        }
        # A season marker is source evidence, not a title heuristic: the parser
        # can extract it deterministically, and this keeps a season-only item
        # on the TV path even if later subject enrichment fails.
        if RSS_SEASON_RE.search(subject_title):
            metadata["kind"] = "tv"
            metadata["media_type"] = "tv"
        if user_name:
            metadata["douban_rss_url"] = build_douban_interest_rss_url(user_name)
        metadata.update(_source_metadata("douban", source_config_id, label))
        events.append(
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text=subject_title,
                source_event_id=f"douban:{douban_id}",
                requested_at=requested_at,
                metadata=metadata,
            )
        )
        seen_ids.add(douban_id)
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


def _html_items(html: str) -> list[str]:
    items = [match.group("body") for match in ITEM_RE.finditer(html)]
    if items:
        return items
    return [html]


def _event_from_html_item(
    item: str,
    *,
    user_name: str | None,
    source_config_id: str | None,
    label: str | None,
) -> SourceIntentEvent | None:
    title_match = TITLE_RE.search(item)
    if title_match is None:
        return None
    href = unescape(title_match.group("href"))
    subject_match = SUBJECT_URL_RE.search(href)
    if subject_match is None:
        return None
    raw_title = title_match.group("title")
    em_match = EM_RE.search(raw_title)
    title_html = em_match.group("title") if em_match is not None else raw_title
    title = _clean_title(_strip_tags(title_html))
    if not title:
        return None
    intro_match = INTRO_RE.search(item)
    intro = _clean_text(_strip_tags(intro_match.group("intro"))) if intro_match is not None else ""
    date_match = DATE_RE.search(item)
    wish_date = (
        _clean_text(_strip_tags(date_match.group("date"))) if date_match is not None else None
    )
    year_match = YEAR_RE.search(intro)
    year = year_match.group(1) if year_match is not None else None
    raw_text = f"{title} {year}" if year else title
    douban_id = subject_match.group("id")
    media_type = _infer_media_type(title=title, intro=intro)
    metadata = {
        "source_adapter": "douban_wanted_public",
        "url": f"https://movie.douban.com/subject/{douban_id}/",
        "douban_user_name": user_name,
        "kind": media_type,
        "media_type": media_type,
        "intro": intro,
        "douban_wish_date": wish_date,
        "external_ids": {"douban": douban_id},
    }
    metadata.update(_source_metadata("douban", source_config_id, label))
    return SourceIntentEvent(
        source=IntentSource.DOUBAN_WANTED,
        raw_text=raw_text,
        source_event_id=f"douban:{douban_id}",
        requested_at=_parse_wish_date(wish_date),
        metadata=metadata,
    )


def _event_from_item(
    item: dict[str, Any],
    *,
    source_config_id: str | None,
    label: str | None,
) -> SourceIntentEvent | None:
    title = _first_text(item, ("title", "name", "subject"))
    if title is None:
        return None
    year = _first_text(item, ("year", "pub_year"))
    raw_text = f"{title} {year}" if year is not None else title
    douban_id = _first_text(item, ("id", "douban_id", "subject_id"))
    intro = _first_text(item, ("intro", "description", "summary")) or ""
    media_type = _normalize_media_type(_first_text(item, ("media_type", "kind", "type")))
    if media_type is None:
        media_type = _infer_media_type(title=title, intro=intro)
    metadata = {
        "source_adapter": "douban_wanted",
        "url": _first_text(item, ("url", "subject_url")),
        "kind": media_type,
        "media_type": media_type,
        "intro": intro,
        "external_ids": {"douban": douban_id} if douban_id is not None else {},
    }
    metadata.update(_source_metadata("douban", source_config_id, label))
    return SourceIntentEvent(
        source=IntentSource.DOUBAN_WANTED,
        raw_text=raw_text,
        source_event_id=f"douban:{douban_id}" if douban_id is not None else None,
        requested_at=_parse_wish_date(_first_text(item, ("requested_at", "date", "wish_date"))),
        metadata=metadata,
    )


def enrich_douban_wanted_event(
    event: SourceIntentEvent,
    *,
    fetcher: Any | None = None,
) -> SourceIntentEvent:
    """Best-effort Douban subject enrichment that never discards a list item."""
    return _enrich_event_from_subject(event, fetcher or _fetch_url)


def _enrich_event_from_subject(event: SourceIntentEvent, fetch: Any) -> SourceIntentEvent:
    douban_id = _event_douban_id(event)
    if douban_id is None:
        return event
    try:
        html = fetch(build_douban_mobile_subject_url(douban_id))
    except Exception as exc:
        log_event(logger, logging.WARNING, "douban.subject_lookup.failed",
                  douban_id=douban_id, error_type=type(exc).__name__, error=str(exc))
        return replace(
            event,
            metadata={**event.metadata, "subject_lookup_status": "failed"},
        )
    media_type, year = _subject_metadata_from_html(html)
    log_event(logger, logging.DEBUG, "douban.subject_lookup.completed",
              douban_id=douban_id, media_type=media_type, year=year,
              classification_version=DOUBAN_SUBJECT_CLASSIFICATION_VERSION)
    imdb_id = _imdb_id_from_html(html)
    raw_text = _with_year(event.raw_text, year)
    if media_type is None and imdb_id is None and raw_text == event.raw_text:
        return replace(
            event,
            metadata={
                **event.metadata,
            "subject_adapter": "douban_mobile_subject",
            "subject_mobile_url": build_douban_mobile_subject_url(douban_id),
            "subject_lookup_status": "success",
            "subject_media_classification_version": DOUBAN_SUBJECT_CLASSIFICATION_VERSION,
        },
        )
    external_ids = dict(event.metadata.get("external_ids") or {})
    if imdb_id is not None:
        external_ids["imdb"] = imdb_id
    metadata = {
        **event.metadata,
        "subject_adapter": "douban_mobile_subject",
        "subject_mobile_url": build_douban_mobile_subject_url(douban_id),
        "subject_lookup_status": "success",
        "subject_media_classification_version": DOUBAN_SUBJECT_CLASSIFICATION_VERSION,
        "external_ids": external_ids,
    }
    if media_type is not None:
        metadata["kind"] = media_type
        metadata["media_type"] = media_type
    return replace(event, raw_text=raw_text, metadata=metadata)


def _imdb_id_from_html(html: str) -> str | None:
    match = IMDB_ID_RE.search(_strip_tags(html))
    if match is None:
        return None
    return match.group(0).lower()


def _source_metadata(
    provider: str,
    source_config_id: str | None,
    label: str | None,
) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if source_config_id:
        metadata["source_config_id"] = source_config_id
    if label:
        metadata["source_label"] = f"豆瓣-{label}" if provider == "douban" else label
    return metadata


def _event_douban_id(event: SourceIntentEvent) -> str | None:
    if event.source_event_id and event.source_event_id.startswith("douban:"):
        return event.source_event_id.removeprefix("douban:")
    url = event.metadata.get("url")
    if isinstance(url, str):
        match = SUBJECT_URL_RE.search(url)
        if match is not None:
            return match.group("id")
    return None


def _subject_metadata_from_html(html: str) -> tuple[str | None, str | None]:
    structured_media_type, structured_year = _structured_subject_metadata(html)
    return structured_media_type or _media_type_from_subject_html(html), structured_year


def _structured_subject_metadata(html: str) -> tuple[str | None, str | None]:
    for match in LD_JSON_RE.finditer(html):
        try:
            payload = json.loads(unescape(match.group("payload").strip()))
        except json.JSONDecodeError:
            continue
        for item in _iter_json_objects(payload):
            media_type = _json_ld_media_type(item)
            year = _normalize_year(item.get("datePublished") or item.get("dateCreated"))
            if media_type is not None or year is not None:
                return media_type, year
    return None, None


def _iter_json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_objects(child)


def _json_ld_media_type(item: dict[str, Any]) -> str | None:
    raw_type = item.get("@type")
    values = raw_type if isinstance(raw_type, list) else [raw_type]
    types = {str(value).strip().lower() for value in values if value is not None}
    genres = item.get("genre")
    genre_values = genres if isinstance(genres, list) else [genres]
    is_animation = any(
        "animation" in str(value).lower() for value in genre_values if value is not None
    )
    if types.intersection({"tvseries", "tvminiseries", "tvepisode", "tvshow"}):
        return "anime" if is_animation else "tv"
    if types.intersection({"movie", "film"}):
        return "movie"
    return None


def _with_year(raw_text: str, year: str | None) -> str:
    if year is None or YEAR_RE.search(raw_text):
        return raw_text
    return f"{raw_text} {year}"


def _media_type_from_subject_html(html: str) -> str | None:
    title_match = SUBJECT_TITLE_RE.search(html)
    if title_match is None:
        return None
    title = _clean_text(_strip_tags(title_match.group("title")))
    if "电视剧" in title or "剧集" in title:
        return "tv"
    return None


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _fetch_url(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 seed-agent"}
    if urlparse(url).netloc == "m.douban.com":
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148 seed-agent"
            )
        }
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=20.0,
        headers=headers,
    )
    response.raise_for_status()
    return response.text


def _douban_user_name(user_name_or_url: str) -> str:
    value = user_name_or_url.strip().rstrip("/")
    if not value:
        raise ValueError("douban user_name must not be empty")
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if "people" in parts:
            index = parts.index("people")
            if index + 1 < len(parts):
                return parts[index + 1]
        raise ValueError("douban profile URL must contain /people/<user>")
    return value


def _strip_tags(value: str) -> str:
    return unescape(TAG_RE.sub(" ", value))


def _clean_title(value: str) -> str:
    cleaned = value.replace("/", " ")
    return " ".join(cleaned.split())


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    aliases = {
        "anime": "anime",
        # Animation is a genre, not proof that a work is a serial. Explicit
        # anime metadata remains trusted; generic animation defaults to movie
        # until subject data establishes a TV series.
        "animation": "movie",
        "动画": "movie",
        "movie": "movie",
        "film": "movie",
        "电影": "movie",
        "tv": "tv",
        "show": "tv",
        "series": "tv",
        "电视剧": "tv",
        "剧集": "tv",
    }
    return aliases.get(normalized)


def _infer_media_type(*, title: str, intro: str) -> str:
    haystack = f"{title} {intro}"
    is_animation = "动画" in haystack or "anime" in haystack.lower()
    is_series = EPISODE_COUNT_RE.search(haystack) or any(
        token in haystack for token in ("电视剧", "剧集", "季")
    )
    if is_series:
        return "anime" if is_animation else "tv"
    return "movie"


def _parse_wish_date(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_rss_date(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_year(value: object) -> str | None:
    if value is None:
        return None
    match = YEAR_RE.search(str(value))
    return match.group(1) if match is not None else None
