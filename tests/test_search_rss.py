from datetime import UTC, datetime

import pytest

from seed_agent.models import Discount, IntentKind, IntentSource, IntentState, ResourceIntent
from seed_agent.search.rss import RssSearchProvider
from seed_agent.sites.rss import parse_rss_candidates


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
    <rss version="2.0">
      <channel>
        <item>
          <title>Inception 2010 1080p BluRay</title>
          <link>https://tracker.example/details.php?id=1&amp;passkey=source-secret</link>
          <enclosure url="https://tracker.example/download.php?id=1&amp;passkey=download-secret" />
          <seeders>40</seeders>
          <leechers>12</leechers>
          <size>8589934592</size>
          <discount>free</discount>
        </item>
        <item>
          <title>Inception 2010 2160p Remux</title>
          <link>https://tracker.example/details.php?id=2&amp;passkey=source-secret</link>
          <enclosure url="https://tracker.example/download.php?id=2&amp;passkey=download-secret" />
          <seeders>20</seeders>
          <leechers>3</leechers>
          <size>34359738368</size>
          <discount>normal</discount>
        </item>
        <item>
          <title>Different Movie 2010 1080p</title>
          <link>https://tracker.example/details.php?id=3&amp;passkey=source-secret</link>
          <enclosure url="https://tracker.example/download.php?id=3&amp;passkey=download-secret" />
          <seeders>80</seeders>
          <leechers>1</leechers>
          <size>8589934592</size>
          <discount>free</discount>
        </item>
      </channel>
    </rss>
    """


@pytest.mark.asyncio
async def test_rss_search_provider_filters_by_intent_tokens_and_resolution() -> None:
    calls: list[tuple[str, str, str | None, str | None]] = []

    async def fake_fetcher(
        url: str, site: str, cookie: str | None, api_key: str | None, site_type: str
    ):
        calls.append((url, site, cookie, api_key))
        assert site_type == "nexusphp"
        return parse_rss_candidates(_xml(), site=site, site_type=site_type)

    provider = RssSearchProvider(
        url="https://tracker.example/rss.php",
        site="demo",
        site_type="nexusphp",
        cookie="session=abc",
        fetcher=fake_fetcher,
    )

    releases = await provider.search(_intent())

    assert calls == [("https://tracker.example/rss.php", "demo", "session=abc", None)]
    assert len(releases) == 1
    assert releases[0].title == "Inception 2010 1080p BluRay"
    assert releases[0].discount == Discount.FREE
    assert releases[0].metadata["hr"] is False
    assert releases[0].release_id == "demo:https://tracker.example/details.php?id=1"
    assert "passkey" not in releases[0].release_id
    assert releases[0].download_url.endswith("passkey=download-secret")


@pytest.mark.asyncio
async def test_rss_search_provider_matches_episode_tokens() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Severance S02E03 2160p WEB-DL</title>
          <link>https://tracker.example/details.php?id=10</link>
          <enclosure url="https://tracker.example/download.php?id=10" />
          <seeders>40</seeders>
          <leechers>12</leechers>
          <size>8589934592</size>
          <discount>free</discount>
        </item>
        <item>
          <title>Severance S02E04 2160p WEB-DL</title>
          <link>https://tracker.example/details.php?id=11</link>
          <enclosure url="https://tracker.example/download.php?id=11" />
          <seeders>40</seeders>
          <leechers>12</leechers>
          <size>8589934592</size>
          <discount>free</discount>
        </item>
      </channel>
    </rss>
    """

    async def fake_fetcher(
        url: str, site: str, cookie: str | None, api_key: str | None, site_type: str
    ):
        return parse_rss_candidates(xml, site=site, site_type=site_type)

    provider = RssSearchProvider(
        url="https://tracker.example/rss.php",
        site="demo",
        site_type="nexusphp",
        fetcher=fake_fetcher,
    )
    releases = await provider.search(
        _intent(
            raw_text="show Severance S02E03 2160p",
            title="Severance",
            kind=IntentKind.EPISODE,
            year=None,
            season=2,
            episode=3,
            resolution="2160p",
        )
    )

    assert [release.title for release in releases] == ["Severance S02E03 2160p WEB-DL"]


@pytest.mark.asyncio
async def test_rss_search_provider_respects_max_results() -> None:
    async def fake_fetcher(
        url: str, site: str, cookie: str | None, api_key: str | None, site_type: str
    ):
        return parse_rss_candidates(_xml(), site=site, site_type=site_type)

    provider = RssSearchProvider(
        url="https://tracker.example/rss.php",
        site="demo",
        site_type="nexusphp",
        max_results=1,
        fetcher=fake_fetcher,
    )
    releases = await provider.search(_intent(year=2010, resolution=None))

    assert len(releases) == 1


def test_rss_search_provider_rejects_invalid_max_results() -> None:
    with pytest.raises(ValueError, match="max_results"):
        RssSearchProvider(url="https://tracker.example/rss.php", site="demo", max_results=0)


@pytest.mark.asyncio
async def test_rss_search_provider_supports_mteam_sparse_candidates() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Inception 2010 1080p BluRay x264</title>
          <link>https://kp.m-team.cc/detail/123456</link>
          <category>Movie/Blu-Ray</category>
          <enclosure
            url="https://rss.m-team.cc/api/rss/dlv2?tid=123456&amp;uid=305694&amp;sign=redacted"
            type="application/x-bittorrent"
          />
        </item>
      </channel>
    </rss>
    """

    async def fake_fetcher(
        url: str, site: str, cookie: str | None, api_key: str | None, site_type: str
    ):
        return parse_rss_candidates(xml, site=site, site_type=site_type)

    provider = RssSearchProvider(
        url="https://rss.m-team.cc/api/rss/fetch?dl=1",
        site="mt",
        site_type="mteam",
        api_key="secret-api-key",
        fetcher=fake_fetcher,
    )

    releases = await provider.search(_intent())

    assert len(releases) == 1
    assert releases[0].site == "mt"
    assert releases[0].size_bytes == 0
    assert releases[0].seeders == 0
    assert releases[0].leechers == 0
    assert releases[0].metadata["categories"] == ["Movie/Blu-Ray"]
