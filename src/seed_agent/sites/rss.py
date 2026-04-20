from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any

import feedparser
import httpx

from seed_agent.models import Discount, TorrentCandidate

KNOWN_ENTRY_KEYS = {
    "title",
    "title_detail",
    "links",
    "link",
    "published",
    "published_parsed",
    "enclosures",
    "seeders",
    "leechers",
    "size",
    "discount",
    "left_time_minutes",
    "hr",
}

KNOWN_DISCOUNT_ALIASES = {
    "free": "free",
    "2xfree": "2xfree",
    "2x_free": "2xfree",
    "50%": "50%",
    "half": "50%",
    "2x50%": "2x50%",
    "normal": "normal",
    "none": "normal",
}

KNOWN_TRUE_VALUES = {"true", "yes", "1", "hr"}


def parse_rss_candidates(xml: str, site: str) -> list[TorrentCandidate]:
    feed = feedparser.parse(xml)
    candidates: list[TorrentCandidate] = []

    for entry in feed.entries:
        candidate = _parse_entry(entry, site)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


async def fetch_rss_candidates(
    url: str,
    site: str,
    cookie: str | None = None,
) -> list[TorrentCandidate]:
    headers: dict[str, str] = {}
    if cookie:
        headers["Cookie"] = cookie

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    return parse_rss_candidates(response.text, site)


def _parse_entry(entry: Any, site: str) -> TorrentCandidate | None:
    metadata = _entry_metadata(entry)

    title = _first_text(entry, "title")
    source_url = _first_text(entry, "link")
    download_url = _download_url(entry) or source_url
    if title is None or source_url is None or download_url is None:
        metadata["rss_missing_fields"] = {
            "title": title is None,
            "link": source_url is None,
            "download_url": download_url is None,
        }
        return None

    size_bytes = _first_int(entry, "size")
    if size_bytes is None:
        size_bytes = _first_int_from_enclosure(entry, "length")
    if size_bytes is None:
        size_bytes = 0

    seeders = _first_int(entry, "seeders") or 0
    leechers = _first_int(entry, "leechers") or 0
    left_time_minutes = _first_int(entry, "left_time_minutes")
    hr = _first_bool(entry, "hr")
    discount = _normalize_discount(_first_text(entry, "discount"), metadata)
    published_at = _parse_published_at(entry)

    try:
        return TorrentCandidate(
            site=site,
            title=title,
            source_url=source_url,
            download_url=download_url,
            size_bytes=size_bytes,
            seeders=seeders,
            leechers=leechers,
            discount=discount,
            left_time_minutes=left_time_minutes,
            hr=hr,
            published_at=published_at,
            metadata=metadata,
        )
    except Exception as exc:
        metadata["rss_parse_error"] = str(exc)
        return None


def _download_url(entry: Any) -> str | None:
    enclosures = getattr(entry, "enclosures", None) or entry.get("enclosures", [])
    if not enclosures:
        return None
    first = enclosures[0]
    if isinstance(first, dict):
        return first.get("href") or first.get("url")
    return getattr(first, "href", None) or getattr(first, "url", None)


def _parse_published_at(entry: Any) -> datetime | None:
    published_parsed = entry.get("published_parsed")
    if isinstance(published_parsed, struct_time):
        return datetime(*published_parsed[:6], tzinfo=UTC)

    published = _first_text(entry, "published")
    if published is None:
        return None

    try:
        dt = parsedate_to_datetime(published)
    except (TypeError, ValueError):
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _first_text(entry: Any, field: str) -> str | None:
    value = _first_value(entry, field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_int(entry: Any, field: str) -> int | None:
    value = _first_value(entry, field)
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def _first_int_from_enclosure(entry: Any, field: str) -> int | None:
    enclosures = getattr(entry, "enclosures", None) or entry.get("enclosures", [])
    if not enclosures:
        return None
    first = enclosures[0]
    if isinstance(first, dict):
        value = first.get(field)
    else:
        value = getattr(first, field, None)
    if value is None:
        return None
    return _first_int({"_value": value}, "_value")


def _first_bool(entry: Any, field: str) -> bool:
    value = _first_value(entry, field)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in KNOWN_TRUE_VALUES


def _normalize_discount(raw_discount: str | None, metadata: dict[str, Any]) -> Discount | str:
    if raw_discount is None:
        return Discount.NORMAL

    normalized = raw_discount.strip().lower()
    if not normalized:
        return Discount.NORMAL

    alias = KNOWN_DISCOUNT_ALIASES.get(normalized)
    if alias is None:
        metadata["rss_discount_raw"] = raw_discount
        return Discount.NORMAL
    return alias


def _entry_metadata(entry: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in entry.items():
        if key not in KNOWN_ENTRY_KEYS:
            metadata[key] = value
    return metadata


def _first_value(entry: Any, field: str) -> Any:
    if field in entry:
        return entry[field]

    for key, value in entry.items():
        if _matches_field_key(key, field):
            return value

    return None


def _matches_field_key(key: str, field: str) -> bool:
    if key == field:
        return True
    if key.endswith(f"_{field}") or key.endswith(f":{field}"):
        return True
    if key.rsplit("_", 1)[-1] == field:
        return True
    if key.rsplit(":", 1)[-1] == field:
        return True
    return False
