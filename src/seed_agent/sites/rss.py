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
    "download_url",
}

EXPLICIT_FIELD_ALIASES = {
    "seeders": ("seeders",),
    "leechers": ("leechers",),
    "size": ("size",),
    "left_time_minutes": ("left_time_minutes",),
    "download_url": ("download_url",),
    "discount": ("discount",),
}

SITE_FIELD_ALIASES = {
    "seeders": ("nexusphp_seeders",),
    "leechers": ("nexusphp_leechers",),
    "size": ("nexusphp_size",),
    "left_time_minutes": ("nexusphp_left_time_minutes",),
    "download_url": ("nexusphp_download_url",),
    "discount": ("nexusphp_discount",),
}

KNOWN_DISCOUNT_ALIASES = {
    "free": "free",
    "freeleech": "free",
    "free_leech": "free",
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

    title = _first_text(entry, "title", site=site)
    source_url = _first_text(entry, "link", site=site)
    download_url = _download_url(entry, site=site)
    if title is None or source_url is None or download_url is None:
        metadata["rss_missing_fields"] = {
            "title": title is None,
            "link": source_url is None,
            "download_url": download_url is None,
        }
        return None

    size_bytes = _first_int(entry, "size", site=site)
    if size_bytes is None:
        metadata["rss_missing_fields"] = {
            **metadata.get("rss_missing_fields", {}),
            "size": True,
        }
        return None

    seeders = _first_int(entry, "seeders", site=site)
    leechers = _first_int(entry, "leechers", site=site)
    if seeders is None or leechers is None:
        metadata["rss_missing_fields"] = {
            **metadata.get("rss_missing_fields", {}),
            "seeders": seeders is None,
            "leechers": leechers is None,
        }
        return None

    left_time_minutes = _first_int(entry, "left_time_minutes", site=site)
    hr = _first_bool(entry, "hr", site=site)
    discount = _normalize_discount(_first_text(entry, "discount", site=site), metadata)
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


def _download_url(entry: Any, site: str) -> str | None:
    explicit_download_url = _first_text(entry, "download_url", site=site)
    if explicit_download_url is not None:
        return explicit_download_url
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


def _first_text(entry: Any, field: str, site: str | None = None) -> str | None:
    value = _first_value(entry, field, site=site)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_int(entry: Any, field: str, site: str | None = None) -> int | None:
    value = _first_value(entry, field, site=site)
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


def _first_bool(entry: Any, field: str, site: str | None = None) -> bool:
    value = _first_value(entry, field, site=site)
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
        metadata["raw_discount"] = raw_discount
        metadata["discount_reason"] = "unknown_label"
        return Discount.NORMAL
    return alias


def _entry_metadata(entry: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in entry.items():
        if key not in _recognized_entry_keys():
            metadata[key] = value
    return metadata


def _first_value(entry: Any, field: str, site: str | None = None) -> Any:
    for key in _field_aliases(field, site=site):
        if key in entry:
            return entry[key]
    return None


def _field_aliases(field: str, site: str | None = None) -> tuple[str, ...]:
    aliases = list(EXPLICIT_FIELD_ALIASES.get(field, (field,)))
    if site is not None:
        aliases.extend(SITE_FIELD_ALIASES.get(field, ()))
    return tuple(dict.fromkeys(aliases))


def _recognized_entry_keys() -> set[str]:
    keys = set(KNOWN_ENTRY_KEYS)
    for aliases in EXPLICIT_FIELD_ALIASES.values():
        keys.update(aliases)
    for aliases in SITE_FIELD_ALIASES.values():
        keys.update(aliases)
    return keys
