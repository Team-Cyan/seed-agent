from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any

import feedparser
import httpx

from seed_agent.models import Discount, TorrentCandidate

from . import mteam as mteam_site

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
    "nexusphp": {
        "seeders": ("nexusphp_seeders",),
        "leechers": ("nexusphp_leechers",),
        "size": ("nexusphp_size",),
        "left_time_minutes": ("nexusphp_left_time_minutes",),
        "download_url": ("nexusphp_download_url",),
        "discount": ("nexusphp_discount",),
    },
    "mteam": {},
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


@dataclass(frozen=True)
class SiteProfile:
    site_type: str
    require_size: bool = True
    require_peer_stats: bool = True


SITE_PROFILES = {
    "nexusphp": SiteProfile(site_type="nexusphp"),
    # M-Team RSS exposes title/detail/download reliably, but peer stats and size are
    # not part of the feed shape. Keep the candidate usable and annotate sparsity.
    "mteam": SiteProfile(site_type="mteam", require_size=False, require_peer_stats=False),
    "torznab": SiteProfile(site_type="torznab", require_size=False, require_peer_stats=False),
}


def parse_rss_candidates(
    xml: str,
    site: str,
    *,
    site_type: str = "nexusphp",
) -> list[TorrentCandidate]:
    feed = feedparser.parse(xml)
    candidates: list[TorrentCandidate] = []

    for entry in feed.entries:
        candidate = _parse_entry(entry, site, site_type=site_type)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


async def fetch_rss_candidates(
    url: str,
    site: str,
    cookie: str | None = None,
    api_key: str | None = None,
    *,
    site_type: str = "nexusphp",
) -> list[TorrentCandidate]:
    headers: dict[str, str] = {}
    if cookie:
        headers["Cookie"] = cookie
    headers["User-Agent"] = "seed-agent/0.1 (+https://github.com/Team-Cyan/seed-agent)"

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    candidates = parse_rss_candidates(response.text, site, site_type=site_type)
    if site_type == "mteam":
        try:
            return await mteam_site.enrich_candidates(
                candidates,
                cookie=cookie,
                api_key=api_key,
            )
        except Exception:
            return candidates
    return candidates


def _parse_entry(entry: Any, site: str, *, site_type: str) -> TorrentCandidate | None:
    profile = _site_profile(site_type)
    metadata = _entry_metadata(entry, site_type=site_type)
    _promote_common_metadata(entry, metadata)

    title = _first_text(entry, "title", site_type=site_type)
    source_url = _first_text(entry, "link", site_type=site_type)
    download_url = _download_url(entry, site_type=site_type)
    if title is None or source_url is None or download_url is None:
        metadata["rss_missing_fields"] = {
            "title": title is None,
            "link": source_url is None,
            "download_url": download_url is None,
        }
        return None

    size_bytes = _first_int(entry, "size", site_type=site_type)
    if size_bytes is None:
        metadata["rss_missing_fields"] = {
            **metadata.get("rss_missing_fields", {}),
            "size": True,
        }
        if profile.require_size:
            return None
        size_bytes = 0
        metadata["rss_sparse_candidate"] = True

    seeders = _first_int(entry, "seeders", site_type=site_type)
    leechers = _first_int(entry, "leechers", site_type=site_type)
    if seeders is None or leechers is None:
        metadata["rss_missing_fields"] = {
            **metadata.get("rss_missing_fields", {}),
            "seeders": seeders is None,
            "leechers": leechers is None,
        }
        if profile.require_peer_stats:
            return None
        seeders = seeders or 0
        leechers = leechers or 0
        metadata["rss_sparse_candidate"] = True

    left_time_minutes = _first_int(entry, "left_time_minutes", site_type=site_type)
    hr = _first_bool(entry, "hr", site_type=site_type)
    discount = _normalize_discount(_first_text(entry, "discount", site_type=site_type), metadata)
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


def _download_url(entry: Any, *, site_type: str) -> str | None:
    explicit_download_url = _first_text(entry, "download_url", site_type=site_type)
    if explicit_download_url is not None:
        return explicit_download_url
    enclosures = getattr(entry, "enclosures", None) or entry.get("enclosures", [])
    for enclosure in enclosures:
        href = _link_href(enclosure)
        if href:
            return href
    for link in getattr(entry, "links", None) or entry.get("links", []):
        href = _link_href(link)
        if not href:
            continue
        rel = str(_link_value(link, "rel") or "").strip().lower()
        content_type = str(_link_value(link, "type") or "").strip().lower()
        if rel == "enclosure" or content_type == "application/x-bittorrent":
            return href
    return None


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


def _first_text(entry: Any, field: str, site_type: str | None = None) -> str | None:
    value = _first_value(entry, field, site_type=site_type)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_int(entry: Any, field: str, site_type: str | None = None) -> int | None:
    value = _first_value(entry, field, site_type=site_type)
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


def _first_bool(entry: Any, field: str, site_type: str | None = None) -> bool:
    value = _first_value(entry, field, site_type=site_type)
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


def _entry_metadata(entry: Any, *, site_type: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in entry.items():
        if key not in _recognized_entry_keys(site_type=site_type):
            metadata[key] = value
    return metadata


def _first_value(entry: Any, field: str, site_type: str | None = None) -> Any:
    for key in _field_aliases(field, site_type=site_type):
        if key in entry:
            return entry[key]
    return None


def _field_aliases(field: str, site_type: str | None = None) -> tuple[str, ...]:
    aliases = list(EXPLICIT_FIELD_ALIASES.get(field, (field,)))
    if site_type is not None:
        aliases.extend(SITE_FIELD_ALIASES.get(site_type, {}).get(field, ()))
    return tuple(dict.fromkeys(aliases))


def _recognized_entry_keys(*, site_type: str) -> set[str]:
    keys = set(KNOWN_ENTRY_KEYS)
    for aliases in EXPLICIT_FIELD_ALIASES.values():
        keys.update(aliases)
    for aliases in SITE_FIELD_ALIASES.get(site_type, {}).values():
        keys.update(aliases)
    return keys


def _site_profile(site_type: str) -> SiteProfile:
    return SITE_PROFILES.get(site_type, SITE_PROFILES["nexusphp"])


def _promote_common_metadata(entry: Any, metadata: dict[str, Any]) -> None:
    tags = []
    for tag in entry.get("tags", []) or []:
        term = getattr(tag, "term", None)
        if isinstance(term, str) and term.strip():
            tags.append(term.strip())
    if tags:
        metadata["categories"] = tags

    comments_url = _first_text(entry, "comments")
    if comments_url is not None:
        metadata["comments_url"] = comments_url


def _link_href(link: Any) -> str | None:
    return _link_value(link, "href") or _link_value(link, "url")


def _link_value(link: Any, key: str) -> str | None:
    if isinstance(link, dict):
        value = link.get(key)
    else:
        value = getattr(link, key, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None
