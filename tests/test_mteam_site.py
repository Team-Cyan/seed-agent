from __future__ import annotations

import base64
import hashlib
import hmac

import httpx
import pytest
import respx

from seed_agent.models import TorrentCandidate
from seed_agent.sites.mteam import (
    MTeamApiClient,
    enrich_candidates,
    extract_torrent_id,
)


def _candidate(**overrides: object) -> TorrentCandidate:
    data: dict[str, object] = {
        "site": "mt",
        "title": "Inception 2010 1080p BluRay",
        "source_url": "https://kp.m-team.cc/detail/1171443",
        "download_url": "https://rss.m-team.cc/api/rss/dlv2?tid=1171443",
        "size_bytes": 0,
        "seeders": 0,
        "leechers": 0,
        "metadata": {"rss_sparse_candidate": True},
    }
    data.update(overrides)
    return TorrentCandidate(**data)


def test_extract_torrent_id_from_detail_path() -> None:
    assert extract_torrent_id("https://kp.m-team.cc/detail/1171443") == "1171443"


def test_extract_torrent_id_from_query_string() -> None:
    assert extract_torrent_id("https://kp.m-team.cc/details.php?id=42&foo=bar") == "42"


def test_extract_torrent_id_returns_none_for_unknown_shape() -> None:
    assert extract_torrent_id("https://kp.m-team.cc/browse/adult") is None


@pytest.mark.asyncio
async def test_enrich_candidates_merges_mteam_detail() -> None:
    async def fake_fetch_detail(torrent_id: str) -> dict[str, object] | None:
        assert torrent_id == "1171443"
        return {
            "_auth_mode": "api_key",
            "size": 12_345_678_901,
            "status": {
                "seeders": 15,
                "leechers": 3,
                "timesCompleted": 28,
            },
        }

    enriched = await enrich_candidates(
        [_candidate()],
        cookie="session=abc",
        fetch_detail=fake_fetch_detail,
    )

    assert len(enriched) == 1
    candidate = enriched[0]
    assert candidate.size_bytes == 12_345_678_901
    assert candidate.seeders == 15
    assert candidate.leechers == 3
    assert candidate.metadata["times_completed"] == 28
    assert candidate.metadata["mteam_detail_enriched"] is True
    assert candidate.metadata["mteam_detail_auth_mode"] == "api_key"
    assert "rss_sparse_candidate" not in candidate.metadata
    assert "rss_missing_fields" not in candidate.metadata


@pytest.mark.asyncio
async def test_enrich_candidates_skips_when_cookie_missing() -> None:
    candidate = _candidate()
    enriched = await enrich_candidates([candidate], cookie=None)

    assert enriched == [candidate]


@pytest.mark.asyncio
async def test_enrich_candidates_accepts_api_key_without_cookie() -> None:
    async def fake_fetch_detail(torrent_id: str) -> dict[str, object] | None:
        assert torrent_id == "1171443"
        return {
            "_auth_mode": "api_key",
            "size": 9_999,
            "status": {"seeders": 7, "leechers": 2, "timesCompleted": 11},
        }

    enriched = await enrich_candidates(
        [_candidate()],
        cookie=None,
        api_key="secret-api-key",
        fetch_detail=fake_fetch_detail,
    )

    assert enriched[0].size_bytes == 9_999
    assert enriched[0].metadata["mteam_detail_auth_mode"] == "api_key"
    assert "rss_sparse_candidate" not in enriched[0].metadata


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_fetches_signed_detail() -> None:
    route = respx.get("https://api.m-team.cc/api/torrent/detail").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "message": "ok",
                "data": {
                    "id": 1171443,
                    "size": 999,
                    "status": {"seeders": 2, "leechers": 1, "timesCompleted": 4},
                },
            },
        )
    )

    client = MTeamApiClient(cookie="session=abc", visitor_id="visitor-1")
    detail = await client.fetch_torrent_detail("1171443")

    assert route.called
    request = route.calls[0].request
    assert request.headers["Cookie"] == "session=abc"
    assert request.headers["visitorId"] == "visitor-1"
    assert request.headers["version"] == "1.1.4"
    assert request.headers["webVersion"] == "1140"
    assert request.url.params["id"] == "1171443"
    timestamp = request.url.params["_timestamp"]
    expected_signature = base64.b64encode(
        hmac.new(
            MTeamApiClient.SECRET.encode("utf-8"),
            f"GET&/api/torrent/detail&{timestamp}".encode(),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")
    assert request.url.params["_sgin"] == expected_signature
    assert detail is not None
    assert detail["size"] == 999
    assert detail["_auth_mode"] == "cookie"


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_fetches_detail_with_api_key() -> None:
    route = respx.post("https://api.m-team.cc/api/torrent/detail").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "message": "ok",
                "data": {
                    "id": "1171443",
                    "size": "1234",
                    "status": {"seeders": "9", "leechers": "4", "timesCompleted": "21"},
                },
            },
        )
    )

    client = MTeamApiClient(api_key="secret-api-key")
    detail = await client.fetch_torrent_detail("1171443")

    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "secret-api-key"
    assert request.url.params["id"] == "1171443"
    assert detail is not None
    assert detail["size"] == "1234"
    assert detail["_auth_mode"] == "api_key"


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_returns_none_for_unauthorized_response() -> None:
    respx.get("https://api.m-team.cc/api/torrent/detail").mock(
        return_value=httpx.Response(
            200,
            json={"code": 401, "message": "Full authentication is required", "data": None},
        )
    )

    client = MTeamApiClient(cookie="session=abc", visitor_id="visitor-1")

    assert await client.fetch_torrent_detail("1171443") is None
