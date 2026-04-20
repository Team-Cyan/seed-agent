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

    assert second.discount == Discount.NORMAL
    assert second.metadata["nx_custom_field"] == "beta"
    assert second.download_url == "https://tracker.example/download.php?id=1002&passkey=download-secret"


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
