from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from seed_agent.models import Discount
from seed_agent.sites.rss import fetch_rss_candidates, parse_rss_candidates

FIXTURE = Path(__file__).parent / "fixtures" / "nexusphp-rss.xml"


def test_parse_rss_candidates_from_fixture() -> None:
    candidates = parse_rss_candidates(FIXTURE.read_text(encoding="utf-8"), site="nexusphp")

    assert len(candidates) == 2

    first = candidates[0]
    second = candidates[1]

    assert first.site == "nexusphp"
    assert first.discount == Discount.FREE
    assert first.seeders == 12
    assert first.leechers == 24
    assert first.left_time_minutes == 240
    assert first.hr is False
    assert first.download_url == "https://tracker.example/download.php?id=1001&passkey=download-secret"
    assert first.source_url == "https://tracker.example/details.php?id=1001&passkey=source-secret"
    assert first.metadata["nx_custom_field"] == "alpha"
    assert first.discount == Discount.FREE
    assert first.published_at is not None

    assert second.discount == Discount.NORMAL
    assert second.metadata["nx_custom_field"] == "beta"
    assert second.download_url == "https://tracker.example/download.php?id=1002&passkey=download-secret"
    assert second.hr is True


def test_parse_rss_candidates_skips_missing_enclosure_item() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Missing Enclosure</title>
          <link>https://tracker.example/details.php?id=2001&amp;passkey=source-secret</link>
          <seeders>8</seeders>
          <leechers>2</leechers>
          <size>111111111</size>
          <discount>freeleech</discount>
          <left_time_minutes>90</left_time_minutes>
        </item>
      </channel>
    </rss>
    """

    candidates = parse_rss_candidates(xml, site="nexusphp")

    assert candidates == []


def test_parse_rss_candidates_skips_missing_size_item() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Missing Size</title>
          <link>https://tracker.example/details.php?id=2002&amp;passkey=source-secret</link>
          <enclosure
            url="https://tracker.example/download.php?id=2002&amp;passkey=download-secret"
          />
          <seeders>5</seeders>
          <leechers>4</leechers>
          <discount>freeleech</discount>
          <left_time_minutes>45</left_time_minutes>
        </item>
      </channel>
    </rss>
    """

    candidates = parse_rss_candidates(xml, site="nexusphp")

    assert candidates == []


def test_parse_rss_candidates_does_not_promote_namespaced_hr() -> None:
    xml = """
    <rss version="2.0" xmlns:nx="https://example.invalid/nexusphp">
      <channel>
        <item>
          <title>Namespaced HR Only</title>
          <link>https://tracker.example/details.php?id=2003&amp;passkey=source-secret</link>
          <enclosure
            url="https://tracker.example/download.php?id=2003&amp;passkey=download-secret"
          />
          <seeders>7</seeders>
          <leechers>3</leechers>
          <size>333333333</size>
          <discount>freeleech</discount>
          <left_time_minutes>60</left_time_minutes>
          <nx:hr>true</nx:hr>
        </item>
      </channel>
    </rss>
    """

    candidates = parse_rss_candidates(xml, site="nexusphp")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.hr is False
    assert candidate.metadata["nx_hr"] == "true"


def test_parse_rss_candidates_maps_freeleech_discount() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Freeleech Torrent</title>
          <link>https://tracker.example/details.php?id=2004&amp;passkey=source-secret</link>
          <enclosure
            url="https://tracker.example/download.php?id=2004&amp;passkey=download-secret"
          />
          <seeders>7</seeders>
          <leechers>3</leechers>
          <size>333333333</size>
          <discount>freeleech</discount>
          <left_time_minutes>60</left_time_minutes>
        </item>
      </channel>
    </rss>
    """

    candidates = parse_rss_candidates(xml, site="nexusphp")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.discount == Discount.FREE
    assert "raw_discount" not in candidate.metadata


def test_parse_rss_candidates_preserves_unknown_discount_metadata() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Unknown Discount Torrent</title>
          <link>https://tracker.example/details.php?id=2005&amp;passkey=source-secret</link>
          <enclosure
            url="https://tracker.example/download.php?id=2005&amp;passkey=download-secret"
          />
          <seeders>7</seeders>
          <leechers>3</leechers>
          <size>333333333</size>
          <discount>mysterybonus</discount>
          <left_time_minutes>60</left_time_minutes>
        </item>
      </channel>
    </rss>
    """

    candidates = parse_rss_candidates(xml, site="nexusphp")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.discount == Discount.NORMAL
    assert candidate.metadata["raw_discount"] == "mysterybonus"
    assert candidate.metadata["discount_reason"] == "unknown_label"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_rss_candidates_uses_httpx_async_client() -> None:
    xml = FIXTURE.read_text(encoding="utf-8")
    route = respx.get("https://tracker.example/rss.php").mock(
        return_value=httpx.Response(200, text=xml)
    )

    candidates = await fetch_rss_candidates(
        "https://tracker.example/rss.php",
        site="nexusphp",
        cookie="session=abc123",
    )

    assert route.called
    assert len(candidates) == 2
    assert candidates[0].download_url.endswith("passkey=download-secret")
