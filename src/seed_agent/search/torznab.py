from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from defusedxml import ElementTree

from seed_agent.models import Discount, ReleaseCandidate, ResourceIntent, safe_url_identity

FetchTorznabXml = Callable[[str, dict[str, str]], Awaitable[str]]


class TorznabSearchProvider:
    def __init__(
        self,
        *,
        url: str,
        site: str,
        api_key: str | None = None,
        max_results: int = 20,
        fetcher: FetchTorznabXml | None = None,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be >= 1")
        self.url = url
        self.site = site
        self.api_key = api_key
        self.max_results = max_results
        self.fetcher = fetcher or _fetch_torznab_xml

    async def search(self, intent: ResourceIntent) -> list[ReleaseCandidate]:
        params = {"t": "search", "q": _query(intent)}
        if self.api_key:
            params["apikey"] = self.api_key
        xml = await self.fetcher(self.url, params)
        releases = parse_torznab_releases(xml, site=self.site)
        return releases[: self.max_results]


async def _fetch_torznab_xml(url: str, params: dict[str, str]) -> str:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text


def parse_torznab_releases(xml: str, *, site: str) -> list[ReleaseCandidate]:
    root = ElementTree.fromstring(xml)
    releases: list[ReleaseCandidate] = []
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        release = _release_from_item(item, site=site)
        if release is not None:
            releases.append(release)
    return releases


def _release_from_item(item: ElementTree.Element, *, site: str) -> ReleaseCandidate | None:
    title = _child_text(item, "title")
    source_url = _child_text(item, "guid") or _child_text(item, "link")
    download_url = _enclosure_url(item) or _child_text(item, "link")
    if not title or not source_url or not download_url:
        return None
    attrs = _torznab_attrs(item)
    seeders = _int_value(attrs.get("seeders")) or 0
    leechers = _int_value(attrs.get("leechers"))
    if leechers is None:
        peers = _int_value(attrs.get("peers"))
        leechers = max((peers or 0) - seeders, 0)
    size = _int_value(attrs.get("size"))
    if size is None:
        size = _int_value(_enclosure_attr(item, "length")) or 0
    return ReleaseCandidate(
        release_id=f"{site}:{safe_url_identity(source_url)}",
        site=site,
        title=title,
        source_url=source_url,
        download_url=download_url,
        size_bytes=size,
        seeders=seeders,
        leechers=leechers,
        discount=Discount.NORMAL,
        published_at=_published_at(_child_text(item, "pubDate")),
        metadata={"torznab_attrs": attrs},
    )


def _query(intent: ResourceIntent) -> str:
    terms = [intent.title]
    if intent.year is not None:
        terms.append(str(intent.year))
    if intent.season is not None:
        terms.append(f"S{intent.season:02d}")
    if intent.episode is not None:
        terms.append(f"E{intent.episode:02d}")
    if intent.resolution is not None:
        terms.append(intent.resolution)
    return " ".join(_dedupe_terms(terms))


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        normalized = " ".join(str(term).split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _torznab_attrs(item: ElementTree.Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for child in item:
        if _local_name(child.tag) != "attr":
            continue
        name = child.attrib.get("name")
        value = child.attrib.get("value")
        if name and value is not None:
            attrs[str(name)] = str(value)
    return attrs


def _child_text(item: ElementTree.Element, name: str) -> str | None:
    for child in item:
        if _local_name(child.tag) == name and child.text:
            text = child.text.strip()
            if text:
                return text
    return None


def _enclosure_url(item: ElementTree.Element) -> str | None:
    return _enclosure_attr(item, "url")


def _enclosure_attr(item: ElementTree.Element, name: str) -> str | None:
    for child in item:
        if _local_name(child.tag) != "enclosure":
            continue
        value = child.attrib.get(name)
        if value:
            return value.strip()
    return None


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
