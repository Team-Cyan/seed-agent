from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
import respx

from seed_agent.models import TorrentCandidate
from seed_agent.sites.mteam import (
    MTeamApiClient,
    MTeamApiDiscoveryOptions,
    _merge_detail,
    enrich_candidates,
    extract_torrent_id,
    fetch_api_candidates,
    resolve_deferred_download_url,
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
@respx.mock
async def test_mteam_api_client_discovers_free_candidates_with_sorting() -> None:
    search_route = respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 1171443,
                            "name": "Inception 2010 1080p BluRay",
                            "discountEndTime": "2099-01-01T00:00:00+00:00",
                            "size": "1234567890",
                            "medium": 10,
                            "standard": 1,
                            "videoCodec": 16,
                            "audioCodec": 3,
                            "labelsNew": ["中字"],
                            "status": {
                                "discount": "FREE",
                                "seeders": 15,
                                "leechers": 3,
                                "timesCompleted": 28,
                            },
                            "createdDate": "2026-04-24T01:02:03+00:00",
                        }
                    ]
                },
            },
        )
    )
    token_route = respx.post("https://api.m-team.cc/api/torrent/genDlToken").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": "https://dl.m-team.cc/download.php?id=1171443&passkey=secret",
            },
        )
    )

    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=0,
            max_seeders=200,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert search_route.called
    search_request = search_route.calls[0].request
    assert search_request.headers["x-api-key"] == "secret-api-key"
    assert json.loads(search_request.content.decode("utf-8")) == {
        "mode": "adult",
        "visible": 1,
        "pageNumber": 1,
        "pageSize": 50,
        "sortDirection": "DESC",
        "sortField": "TIMES_COMPLETED",
        "discount": "FREE",
    }
    assert not token_route.called

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.site == "mt"
    assert candidate.download_url == "mteam-api://torrent/1171443"
    assert candidate.discount.value == "free"
    assert candidate.left_time_minutes is not None
    assert candidate.left_time_minutes > 0
    assert candidate.seeders == 15
    assert candidate.leechers == 3
    assert candidate.metadata["mteam_discovery_mode"] == "api"
    assert candidate.metadata["download_url_source"] == "mteam_api_deferred"
    assert candidate.metadata["mteam_torrent_id"] == "1171443"
    assert candidate.metadata["times_completed"] == 28
    assert candidate.metadata["mteam_tags"] == [
        "WEB-DL",
        "1080p",
        "H.265/HEVC",
        "DTS",
        "中字",
    ]
    assert candidate.metadata["mteam_raw_tags"] == {
        "medium": "10",
        "standard": "1",
        "video_codec": "16",
        "audio_codec": "3",
        "labels_new": ["中字"],
    }


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_uses_custom_api_key_header() -> None:
    search_route = respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(200, json={"code": "0", "data": {"data": []}})
    )

    client = MTeamApiClient(api_key="secret-api-key", api_key_header="x-custom-key")
    await client.discover_torrents(site="mt", options=MTeamApiDiscoveryOptions())

    request = search_route.calls[0].request
    assert request.headers["x-custom-key"] == "secret-api-key"
    assert "x-api-key" not in request.headers


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_zero_max_seeders_does_not_block_popular_torrents() -> None:
    respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 111591,
                            "name": "joymii hardcore solo lesbian 2014 mp4 1080P MegaPack",
                            "size": 93781377024,
                            "discount": "FREE",
                            "status": {
                                "seeders": 307,
                                "leechers": 18,
                                "timesCompleted": 16685,
                            },
                        }
                    ]
                },
            },
        )
    )

    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="leechers",
            sort_order="desc",
            page_size=50,
            min_seeders=1,
            max_seeders=0,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert [candidate.title for candidate in candidates] == [
        "joymii hardcore solo lesbian 2014 mp4 1080P MegaPack"
    ]


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_discovers_multiple_pages() -> None:
    route = respx.post("https://api.m-team.cc/api/torrent/search").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "code": "0",
                    "data": {
                        "data": [
                            {
                                "id": 111,
                                "name": "Already Seen Candidate",
                                "size": 10 * 1024**3,
                                "discount": "FREE",
                                "status": {
                                    "seeders": 10,
                                    "leechers": 5,
                                    "timesCompleted": 12,
                                },
                            }
                        ]
                    },
                },
            ),
            httpx.Response(
                200,
                json={
                    "code": "0",
                    "data": {
                        "data": [
                            {
                                "id": 222,
                                "name": "Second Page Candidate",
                                "size": 11 * 1024**3,
                                "discount": "FREE",
                                "status": {
                                    "seeders": 8,
                                    "leechers": 6,
                                    "timesCompleted": 9,
                                },
                            }
                        ]
                    },
                },
            ),
        ]
    )

    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="leechers",
            sort_order="desc",
            page_size=50,
            max_pages=2,
            min_seeders=1,
            max_seeders=0,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert route.call_count == 2
    requested_pages = [
        json.loads(call.request.content.decode("utf-8"))["pageNumber"] for call in route.calls
    ]
    assert requested_pages == [1, 2]
    assert [candidate.title for candidate in candidates] == [
        "Already Seen Candidate",
        "Second Page Candidate",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_resolve_deferred_download_url_fetches_mteam_token() -> None:
    route = respx.post("https://api.m-team.cc/api/torrent/genDlToken").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": "https://dl.m-team.cc/download.php?id=1171443&passkey=secret",
            },
        )
    )

    resolved = await resolve_deferred_download_url(
        _candidate(
            download_url="mteam-api://torrent/1171443",
            metadata={
                "mteam_discovery_mode": "api",
                "download_url_source": "mteam_api_deferred",
                "mteam_torrent_id": "1171443",
            },
        ),
        api_key="secret-api-key",
    )

    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "secret-api-key"
    assert request.content.decode("utf-8") == "id=1171443"
    assert resolved is not None
    assert resolved.download_url == "https://dl.m-team.cc/download.php?id=1171443&passkey=secret"
    assert resolved.metadata["download_url_source"] == "mteam_api"


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_sends_openapi_search_filters() -> None:
    route = respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(200, json={"code": "0", "data": {"data": []}})
    )

    client = MTeamApiClient(api_key="secret-api-key")
    await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="movie",
            page_number=2,
            only_free=False,
            discount="_2X_FREE",
            sort_field="leechers",
            sort_order="asc",
            page_size=100,
            last_id=123,
            keyword="inception",
            categories=[401, 419],
            imdb="tt1375666",
            douban="3541415",
            dmm_code="ABC-123",
            author=42,
            sources=[8],
            mediums=[10],
            standards=[1, 6],
            video_codecs=[1, 16],
            audio_codecs=[6],
            teams=[9],
            processings=[2],
            countries=[1],
            labels=3,
            labels_new=["DIY"],
            visible=1,
            only_fav=True,
            offer=False,
            hot=True,
            upload_date_start="2026-04-01T00:00:00+00:00",
            upload_date_end="2026-04-30T00:00:00+00:00",
            dmm_field="maker",
            dmm_keyword="demo",
            min_seeders=0,
            max_seeders=200,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert route.called
    assert json.loads(route.calls[0].request.content.decode("utf-8")) == {
        "mode": "movie",
        "visible": 1,
        "pageNumber": 2,
        "pageSize": 100,
        "sortDirection": "ASC",
        "sortField": "LEECHERS",
        "lastId": 123,
        "keyword": "inception",
        "categories": [401, 419],
        "imdb": "tt1375666",
        "douban": "3541415",
        "dmmCode": "ABC-123",
        "author": 42,
        "sources": [8],
        "mediums": [10],
        "standards": [1, 6],
        "videoCodecs": [1, 16],
        "audioCodecs": [6],
        "teams": [9],
        "processings": [2],
        "countries": [1],
        "labels": 3,
        "labelsNew": ["DIY"],
        "onlyFav": True,
        "offer": False,
        "hot": True,
        "uploadDateStart": "2026-04-01T00:00:00+00:00",
        "uploadDateEnd": "2026-04-30T00:00:00+00:00",
        "dmmField": "maker",
        "dmmKeyword": "demo",
        "discount": "_2X_FREE",
    }


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_marks_missing_discount_expiry() -> None:
    respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 1171443,
                            "name": "Inception 2010 1080p BluRay",
                            "discount": "FREE",
                            "size": "1234567890",
                            "status": {
                                "seeders": 15,
                                "leechers": 3,
                                "timesCompleted": 28,
                            },
                        }
                    ]
                },
            },
        )
    )
    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=0,
            max_seeders=200,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert candidates[0].left_time_minutes is None
    assert candidates[0].metadata["left_time_source"] == "mteam_api_missing"


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_marks_open_ended_discount_as_unlimited() -> None:
    respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 1171443,
                            "name": "Open Ended Free Torrent",
                            "size": "1234567890",
                            "status": {
                                "discount": "FREE",
                                "discountEndTime": None,
                                "seeders": 15,
                                "leechers": 3,
                                "timesCompleted": 28,
                            },
                        }
                    ]
                },
            },
        )
    )
    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=0,
            max_seeders=200,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert candidates[0].left_time_minutes is None
    assert candidates[0].metadata["left_time_source"] == "mteam_api_unlimited"


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_filters_out_candidates_below_thresholds() -> None:
    search_route = respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 1,
                            "name": "Too Cold",
                            "discount": "FREE",
                            "size": "1000",
                            "status": {"seeders": 1, "leechers": 0, "timesCompleted": 0},
                        }
                    ]
                },
            },
        )
    )

    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=5,
            max_seeders=200,
            min_leechers=1,
            min_times_completed=1,
        ),
    )

    assert search_route.called
    assert candidates == []


@pytest.mark.asyncio
async def test_fetch_api_candidates_reuses_detail_enrichment() -> None:
    async def fake_discover(
        *, site: str, options: MTeamApiDiscoveryOptions
    ) -> list[TorrentCandidate]:
        assert site == "mt"
        assert options.sort_field == "downloads"
        return [_candidate(metadata={"mteam_discovery_mode": "api"})]

    async def fake_fetch_detail(torrent_id: str) -> dict[str, object] | None:
        assert torrent_id == "1171443"
        return {
            "_auth_mode": "api_key",
            "size": 9_999,
            "status": {"seeders": 7, "leechers": 2, "timesCompleted": 11},
        }

    candidates = await fetch_api_candidates(
        site="mt",
        api_key="secret-api-key",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=0,
            max_seeders=200,
            min_leechers=0,
            min_times_completed=0,
        ),
        discover=fake_discover,
        fetch_detail=fake_fetch_detail,
    )

    assert candidates[0].size_bytes == 9_999
    assert candidates[0].metadata["mteam_detail_enriched"] is True


@pytest.mark.asyncio
async def test_fetch_api_candidates_skips_detail_enrichment_by_default() -> None:
    async def fake_discover(
        *, site: str, options: MTeamApiDiscoveryOptions
    ) -> list[TorrentCandidate]:
        return [
            _candidate(
                site=site,
                metadata={
                    "mteam_discovery_mode": "api",
                    "mteam_torrent_id": "1171443",
                },
            )
        ]

    candidates = await fetch_api_candidates(
        site="mt",
        api_key="secret-api-key",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="leechers",
            sort_order="desc",
            page_size=50,
            max_pages=5,
            min_seeders=0,
            max_seeders=0,
            min_leechers=0,
            min_times_completed=0,
        ),
        discover=fake_discover,
    )

    assert candidates[0].size_bytes == 0
    assert "mteam_detail_enriched" not in candidates[0].metadata


def test_merge_detail_upgrades_open_ended_free_window() -> None:
    candidate = _candidate(
        discount="free",
        left_time_minutes=None,
        metadata={
            "mteam_discovery_mode": "api",
            "left_time_source": "mteam_api_missing",
        },
    )

    merged = _merge_detail(
        candidate,
        {
            "_auth_mode": "api_key",
            "size": 9999,
            "status": {
                "discount": "FREE",
                "discountEndTime": None,
                "seeders": 7,
                "leechers": 2,
                "timesCompleted": 11,
            },
        },
    )

    assert merged.left_time_minutes is None
    assert merged.metadata["mteam_discovery_mode"] == "api"
    assert merged.metadata["left_time_source"] == "mteam_api_unlimited"


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
