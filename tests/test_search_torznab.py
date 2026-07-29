from __future__ import annotations

from datetime import UTC, datetime

import pytest
from defusedxml.common import EntitiesForbidden

from seed_agent.models import IntentKind, IntentSource, IntentState, ResourceIntent
from seed_agent.search.torznab import TorznabSearchProvider, parse_torznab_releases


def _intent(**overrides: object) -> ResourceIntent:
    data: dict[str, object] = {
        "intent_id": "cli:inception-2010-1080p",
        "source": IntentSource.CLI,
        "raw_text": "Inception 2010 1080p",
        "kind": IntentKind.MOVIE,
        "title": "Inception",
        "year": 2010,
        "resolution": "1080p",
        "requested_at": datetime(2026, 4, 22, tzinfo=UTC),
        "state": IntentState.NORMALIZED,
    }
    data.update(overrides)
    return ResourceIntent(**data)


def _xml() -> str:
    return """
    <rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
      <channel>
        <item>
          <title>Inception 2010 1080p BluRay</title>
          <guid>https://indexer.example/details/1?apikey=source-secret</guid>
          <link>https://indexer.example/details/1?apikey=source-secret</link>
          <enclosure
            url="https://indexer.example/download/1?apikey=download-secret"
            length="8589934592"
            type="application/x-bittorrent" />
          <pubDate>Wed, 22 Apr 2026 00:00:00 +0000</pubDate>
          <torznab:attr name="seeders" value="40" />
          <torznab:attr name="peers" value="52" />
          <torznab:attr name="size" value="8589934592" />
        </item>
        <item>
          <title>Inception 2010 2160p Remux</title>
          <guid>https://indexer.example/details/2</guid>
          <link>https://indexer.example/download/2</link>
          <torznab:attr name="seeders" value="10" />
          <torznab:attr name="leechers" value="2" />
        </item>
      </channel>
    </rss>
    """


def test_parse_torznab_releases_reads_attrs_and_redacts_release_identity() -> None:
    releases = parse_torznab_releases(_xml(), site="torznab-demo")

    assert len(releases) == 2
    assert releases[0].title == "Inception 2010 1080p BluRay"
    assert releases[0].size_bytes == 8589934592
    assert releases[0].seeders == 40
    assert releases[0].leechers == 12
    assert releases[0].published_at == datetime(2026, 4, 22, tzinfo=UTC)
    assert releases[0].download_url.endswith("apikey=download-secret")
    assert releases[0].release_id == "torznab-demo:https://indexer.example/details/1"
    assert "apikey" not in releases[0].release_id
    assert releases[0].metadata["torznab_attrs"]["peers"] == "52"


def test_parse_torznab_releases_rejects_entity_definitions() -> None:
    xml = """<?xml version="1.0"?>
    <!DOCTYPE rss [<!ENTITY payload "expanded">]>
    <rss><channel><item><title>&payload;</title></item></channel></rss>
    """

    with pytest.raises(EntitiesForbidden):
        parse_torznab_releases(xml, site="torznab-demo")


@pytest.mark.asyncio
async def test_torznab_search_provider_builds_search_params_and_limits_results() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    async def fake_fetcher(url: str, params: dict[str, str]) -> str:
        calls.append((url, params))
        return _xml()

    provider = TorznabSearchProvider(
        url="https://indexer.example/api",
        site="torznab-demo",
        api_key="secret-api-key",
        max_results=1,
        fetcher=fake_fetcher,
    )

    releases = await provider.search(_intent())

    assert [release.title for release in releases] == ["Inception 2010 1080p BluRay"]
    assert calls == [
        (
            "https://indexer.example/api",
            {"t": "search", "q": "Inception 2010 1080p", "apikey": "secret-api-key"},
        )
    ]


def test_torznab_search_provider_rejects_invalid_max_results() -> None:
    with pytest.raises(ValueError, match="max_results"):
        TorznabSearchProvider(url="https://indexer.example/api", site="demo", max_results=0)
