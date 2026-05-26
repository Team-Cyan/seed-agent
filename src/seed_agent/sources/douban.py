from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from seed_agent.models import IntentSource
from seed_agent.sources.base import SourceIntentEvent

DOUBAN_WISH_PAGE_SIZE = 15
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
IMDB_ID_RE = re.compile(r"\btt\d{6,12}\b", re.IGNORECASE)


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
                event = _enrich_event_from_subject(event, fetch)
            event_id = event.source_event_id or event.raw_text
            if event_id in seen_ids:
                continue
            events.append(event)
            seen_ids.add(event_id)
    return events


def build_douban_wish_url(user_name_or_url: str, *, start: int = 0) -> str:
    user_name = quote(_douban_user_name(user_name_or_url), safe="")
    return f"https://movie.douban.com/people/{user_name}/wish?start={start}"


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
        _clean_text(_strip_tags(date_match.group("date")))
        if date_match is not None
        else None
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


def _enrich_event_from_subject(event: SourceIntentEvent, fetch: Any) -> SourceIntentEvent:
    douban_id = _event_douban_id(event)
    if douban_id is None:
        return event
    try:
        html = fetch(build_douban_mobile_subject_url(douban_id))
    except Exception:
        return event
    media_type = _media_type_from_subject_html(html)
    imdb_id = _imdb_id_from_html(html)
    if media_type is None and imdb_id is None:
        return event
    external_ids = dict(event.metadata.get("external_ids") or {})
    if imdb_id is not None:
        external_ids["imdb"] = imdb_id
    metadata = {
        **event.metadata,
        "subject_adapter": "douban_mobile_subject",
        "subject_mobile_url": build_douban_mobile_subject_url(douban_id),
        "external_ids": external_ids,
    }
    if media_type is not None:
        metadata["kind"] = media_type
        metadata["media_type"] = media_type
    return replace(event, metadata=metadata)


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


def _media_type_from_subject_html(html: str) -> str | None:
    title_match = SUBJECT_TITLE_RE.search(html)
    if title_match is None:
        return None
    title = _clean_text(_strip_tags(title_match.group("title")))
    if "电视剧" in title or "剧集" in title:
        return "tv"
    if "动画" in title or "动漫" in title:
        return "anime"
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
        "animation": "anime",
        "动画": "anime",
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
    if "动画" in haystack or "anime" in haystack.lower():
        return "anime"
    if EPISODE_COUNT_RE.search(haystack) or any(
        token in haystack for token in ("电视剧", "剧集", "季")
    ):
        return "tv"
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
