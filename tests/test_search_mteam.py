from datetime import UTC, datetime

import httpx
import pytest

from seed_agent.config import SearchConfig
from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    ReleaseCandidate,
    ResourceIntent,
    TorrentCandidate,
)
from seed_agent.search.mteam import MTeamSearchProvider, resolve_mteam_release_download_url
from seed_agent.sites.mteam import MTeamApiResponseError


def _intent(**overrides: object) -> ResourceIntent:
    data: dict[str, object] = {
        "intent_id": "douban_wanted:call-me-by-your-name",
        "source": IntentSource.DOUBAN_WANTED,
        "raw_text": "请以你的名字呼唤我 Call Me by Your Name 2017",
        "kind": IntentKind.MOVIE,
        "title": "请以你的名字呼唤我 Call Me by Your Name",
        "year": 2017,
        "resolution": None,
        "requested_at": datetime(2026, 5, 21, tzinfo=UTC),
        "state": IntentState.NORMALIZED,
    }
    data.update(overrides)
    return ResourceIntent(**data)


@pytest.mark.asyncio
async def test_mteam_search_provider_keeps_non_matching_candidates_for_review() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        return [
            TorrentCandidate(
                site="mt",
                title="Call Me by Your Name 2017 2160p BluRay REMUX AVC DTS-HD MA 5.1",
                source_url="https://kp.m-team.cc/detail/26799731",
                download_url="mteam-api://torrent/26799731",
                size_bytes=66 * 1024**3,
                seeders=12,
                leechers=3,
                discount=Discount.NORMAL,
                metadata={
                    "mteam_torrent_id": "26799731",
                    "download_url_source": "mteam_api_deferred",
                },
            ),
            TorrentCandidate(
                site="mt",
                title="Call Me by Your Name 2017 1080p WEB-DL",
                source_url="https://kp.m-team.cc/detail/99",
                download_url="mteam-api://torrent/99",
                size_bytes=8 * 1024**3,
                seeders=100,
                leechers=1,
                discount=Discount.FREE,
                metadata={"mteam_torrent_id": "99", "download_url_source": "mteam_api_deferred"},
            ),
        ]

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(max_results_per_site=10),
        default_resolution="2160p",
        fetch_candidates=fake_fetch_candidates,
    )

    releases = await provider.search(_intent())

    assert len(releases) == 2
    assert releases[0].title.endswith("REMUX AVC DTS-HD MA 5.1")
    assert releases[1].title.endswith("1080p WEB-DL")
    assert releases[0].download_url == "mteam-api://torrent/26799731"
    assert releases[0].metadata["download_url_source"] == "mteam_api_deferred"
    assert releases[0].release_id == "mt:https://kp.m-team.cc/detail/26799731"
    options = calls[0]["options"]
    assert options.keyword == "请以你的名字呼唤我 Call Me by Your Name 2017 2160p"
    assert calls[0]["api_key"] == "secret-api-key"


@pytest.mark.asyncio
async def test_mteam_search_provider_propagates_rate_limit() -> None:
    calls: list[dict[str, object]] = []

    async def fail_fetch_candidates(**kwargs):
        calls.append(kwargs)
        raise MTeamApiResponseError(
            endpoint="torrent/search",
            code="1",
            message="請求過於頻繁",
        )

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        fetch_candidates=fail_fetch_candidates,
    )

    intent = _intent(metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}})
    with pytest.raises(MTeamApiResponseError) as exc_info:
        await provider.search(intent)

    assert exc_info.value.rate_limited is True
    assert len(calls) == 1
    assert provider.search_diagnostics == [
        {
            "site": "mt",
            "intent_id": intent.intent_id,
            "request_budget": 3,
            "attempts": [
                {
                    "query_path": "douban_id",
                    "status": "api_error",
                    "code": "1",
                    "rate_limited": True,
                    "retriable": True,
                    "unavailable": False,
                }
            ],
            "requests_used": 1,
            "release_count": 0,
        }
    ]


@pytest.mark.asyncio
async def test_mteam_search_provider_propagates_network_error() -> None:
    calls: list[dict[str, object]] = []

    async def fail_fetch_candidates(**kwargs):
        calls.append(kwargs)
        raise httpx.ReadTimeout("mteam api unavailable")

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        fetch_candidates=fail_fetch_candidates,
    )

    intent = _intent(metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}})
    with pytest.raises(httpx.ReadTimeout):
        await provider.search(intent)

    assert len(calls) == 1
    assert provider.search_diagnostics == [
        {
            "site": "mt",
            "intent_id": intent.intent_id,
            "request_budget": 3,
            "attempts": [{"query_path": "douban_id", "status": "network_error"}],
            "requests_used": 1,
            "release_count": 0,
        }
    ]


@pytest.mark.asyncio
async def test_mteam_search_provider_propagates_unavailable_api_error() -> None:
    calls: list[dict[str, object]] = []

    async def fail_fetch_candidates(**kwargs):
        calls.append(kwargs)
        raise MTeamApiResponseError(
            endpoint="torrent/search",
            code="503",
            message="Service Unavailable",
            status_code=503,
        )

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        fetch_candidates=fail_fetch_candidates,
    )

    with pytest.raises(MTeamApiResponseError) as exc_info:
        await provider.search(_intent(metadata={"external_ids": {"douban": "26799731"}}))

    assert exc_info.value.unavailable is True
    assert exc_info.value.retriable is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_mteam_search_provider_falls_back_after_identifier_business_errors() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        options = kwargs["options"]
        if options.douban or options.imdb:
            raise MTeamApiResponseError(
                endpoint="torrent/search",
                code="1001",
                message="identifier query rejected",
            )
        return [
            TorrentCandidate(
                site="mt",
                title="Call Me by Your Name 2017 1080p WEB-DL",
                source_url="https://kp.m-team.cc/detail/99",
                download_url="mteam-api://torrent/99",
                size_bytes=8 * 1024**3,
                seeders=100,
                leechers=1,
                discount=Discount.NORMAL,
                metadata={
                    "mteam_torrent_id": "99",
                    "download_url_source": "mteam_api_deferred",
                },
            )
        ]

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        fetch_candidates=fake_fetch_candidates,
    )

    releases = await provider.search(
        _intent(metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}})
    )

    assert len(calls) == 3
    assert [release.discount for release in releases] == [Discount.NORMAL]
    assert [attempt["status"] for attempt in provider.search_diagnostics[0]["attempts"]] == [
        "api_error",
        "api_error",
        "ok",
    ]


@pytest.mark.asyncio
async def test_mteam_search_provider_prefers_douban_identifier_search() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        return [
            TorrentCandidate(
                site="mt",
                title="Call Me by Your Name 2017 2160p BluRay REMUX AVC DTS-HD MA 5.1",
                source_url="https://kp.m-team.cc/detail/26799731",
                download_url="mteam-api://torrent/26799731",
                size_bytes=66 * 1024**3,
                seeders=12,
                leechers=3,
                discount=Discount.NORMAL,
                metadata={
                    "mteam_torrent_id": "26799731",
                    "download_url_source": "mteam_api_deferred",
                },
            ),
            TorrentCandidate(
                site="mt",
                title="Call Me by Your Name 2017 1080p WEB-DL",
                source_url="https://kp.m-team.cc/detail/99",
                download_url="mteam-api://torrent/99",
                size_bytes=8 * 1024**3,
                seeders=100,
                leechers=1,
                discount=Discount.FREE,
                metadata={"mteam_torrent_id": "99", "download_url_source": "mteam_api_deferred"},
            ),
        ]

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        default_resolution=None,
        fetch_candidates=fake_fetch_candidates,
    )

    releases = await provider.search(
        _intent(metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}})
    )

    options = calls[0]["options"]
    assert options.douban == "26799731"
    assert options.imdb is None
    assert options.keyword is None
    assert options.mode == "movie"
    assert options.only_free is False
    assert len(calls) == 3
    assert calls[1]["options"].douban is None
    assert calls[1]["options"].imdb == "tt5726616"
    assert calls[2]["options"].douban is None
    assert calls[2]["options"].imdb is None
    assert calls[2]["options"].keyword == "请以你的名字呼唤我 Call Me by Your Name 2017"
    assert [release.title for release in releases] == [
        "Call Me by Your Name 2017 2160p BluRay REMUX AVC DTS-HD MA 5.1",
        "Call Me by Your Name 2017 1080p WEB-DL",
    ]


@pytest.mark.asyncio
async def test_mteam_search_provider_supplements_douban_with_imdb_and_keyword_results() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        options = kwargs["options"]
        if options.douban:
            return [
                TorrentCandidate(
                    site="mt",
                    title="Call Me by Your Name 2017 1080p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/99",
                    download_url="mteam-api://torrent/99",
                    size_bytes=8 * 1024**3,
                    seeders=100,
                    leechers=1,
                    discount=Discount.FREE,
                    metadata={
                        "mteam_torrent_id": "99",
                        "download_url_source": "mteam_api_deferred",
                    },
                )
            ]
        return [
            TorrentCandidate(
                site="mt",
                title="Call Me by Your Name 2017 2160p BluRay REMUX AVC DTS-HD MA 5.1",
                source_url="https://kp.m-team.cc/detail/26799731",
                download_url="mteam-api://torrent/26799731",
                size_bytes=66 * 1024**3,
                seeders=12,
                leechers=3,
                discount=Discount.NORMAL,
                metadata={
                    "mteam_torrent_id": "26799731",
                    "download_url_source": "mteam_api_deferred",
                },
            )
        ]

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        fetch_candidates=fake_fetch_candidates,
    )

    releases = await provider.search(
        _intent(metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}})
    )

    assert len(calls) == 3
    assert calls[0]["options"].douban == "26799731"
    assert calls[0]["options"].imdb is None
    assert calls[1]["options"].douban is None
    assert calls[1]["options"].imdb == "tt5726616"
    assert calls[2]["options"].douban is None
    assert calls[2]["options"].imdb is None
    assert calls[2]["options"].keyword == "请以你的名字呼唤我 Call Me by Your Name 2017"
    assert [release.title for release in releases] == [
        "Call Me by Your Name 2017 1080p WEB-DL",
        "Call Me by Your Name 2017 2160p BluRay REMUX AVC DTS-HD MA 5.1",
    ]


@pytest.mark.asyncio
async def test_mteam_search_provider_uses_imdb_identifier_when_douban_is_missing() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        return []

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        fetch_candidates=fake_fetch_candidates,
    )

    await provider.search(_intent(metadata={"external_ids": {"imdb": "tt5726616"}}))

    assert len(calls) == 2
    options = calls[0]["options"]
    assert options.douban is None
    assert options.imdb == "tt5726616"
    assert options.keyword is None
    assert calls[1]["options"].douban is None
    assert calls[1]["options"].imdb is None
    assert calls[1]["options"].keyword == "请以你的名字呼唤我 Call Me by Your Name 2017"


@pytest.mark.asyncio
async def test_mteam_search_provider_bounds_and_reports_query_paths() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        return []

    provider = MTeamSearchProvider(
        site="mteam",
        api_key="secret-api-key",
        search_config=SearchConfig(max_api_requests_per_intent=2),
        fetch_candidates=fake_fetch_candidates,
    )

    intent = _intent(metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}})
    await provider.search(intent)

    assert len(calls) == 2
    assert provider.search_diagnostics == [
        {
            "site": "mteam",
            "intent_id": intent.intent_id,
            "request_budget": 2,
            "attempts": [
                {"query_path": "douban_id", "status": "ok", "result_count": 0},
                {"query_path": "imdb_id", "status": "ok", "result_count": 0},
            ],
            "requests_used": 2,
            "release_count": 0,
        }
    ]


@pytest.mark.asyncio
async def test_mteam_search_provider_defaults_episode_intents_to_season_keyword() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        return []

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        default_resolution="2160p",
        fetch_candidates=fake_fetch_candidates,
    )

    await provider.search(
        _intent(
            kind=IntentKind.EPISODE,
            title="Severance",
            raw_text="Severance S02E03 2025",
            year=2025,
            season=2,
            episode=3,
        )
    )

    options = calls[0]["options"]
    assert options.keyword == "Severance 2025 S02 2160p"


@pytest.mark.asyncio
async def test_mteam_search_provider_can_search_episode_keywords() -> None:
    calls: list[dict[str, object]] = []

    async def fake_fetch_candidates(**kwargs):
        calls.append(kwargs)
        return []

    provider = MTeamSearchProvider(
        site="mt",
        api_key="secret-api-key",
        search_config=SearchConfig(),
        default_resolution="2160p",
        series_search_mode="episode",
        fetch_candidates=fake_fetch_candidates,
    )

    await provider.search(
        _intent(
            kind=IntentKind.EPISODE,
            title="Severance",
            raw_text="Severance S02E03 2025",
            year=2025,
            season=2,
            episode=3,
        )
    )

    options = calls[0]["options"]
    assert options.keyword == "Severance 2025 S02 E03 2160p"


@pytest.mark.asyncio
async def test_resolve_mteam_release_download_url_fetches_deferred_token(monkeypatch) -> None:
    from seed_agent.search import mteam as mteam_search

    async def fake_resolve_deferred_download_url(candidate, **kwargs):
        assert kwargs["api_key"] == "secret-api-key"
        return candidate.model_copy(
            update={
                "download_url": "https://dl.m-team.example/26799731?passkey=secret",
                "metadata": {
                    **candidate.metadata,
                    "download_url_source": "mteam_api",
                },
            }
        )

    monkeypatch.setattr(
        mteam_search,
        "resolve_deferred_download_url",
        fake_resolve_deferred_download_url,
    )

    release = ReleaseCandidate(
        release_id="mt:https://kp.m-team.cc/detail/26799731",
        site="mt",
        title="Call Me by Your Name 2017 2160p BluRay REMUX",
        source_url="https://kp.m-team.cc/detail/26799731",
        download_url="mteam-api://torrent/26799731",
        size_bytes=66 * 1024**3,
        seeders=12,
        leechers=3,
        discount=Discount.NORMAL,
        metadata={
            "mteam_torrent_id": "26799731",
            "download_url_source": "mteam_api_deferred",
        },
    )

    resolved = await resolve_mteam_release_download_url(
        release,
        api_key="secret-api-key",
    )

    assert resolved is not None
    assert resolved.discount == Discount.NORMAL
    assert resolved.download_url.startswith("https://dl.m-team.example/26799731")
    assert resolved.metadata["download_url_source"] == "mteam_api"


@pytest.mark.asyncio
async def test_mteam_detail_enrichment_updates_discount() -> None:
    from seed_agent.sites.mteam import enrich_candidates

    candidate = TorrentCandidate(
        site="mt",
        title="Risky Incomplete Torrent",
        source_url="https://kp.m-team.cc/detail/1206069",
        download_url="mteam-api://torrent/1206069",
        size_bytes=10 * 1024**3,
        seeders=0,
        leechers=0,
        discount=Discount.FREE,
        metadata={"mteam_torrent_id": "1206069"},
    )

    async def fake_fetch_detail(torrent_id: str):
        assert torrent_id == "1206069"
        return {
            "id": "1206069",
            "name": "Risky Incomplete Torrent",
            "size": 10 * 1024**3,
            "discount": "NORMAL",
            "status": {"seeders": 1, "leechers": 0},
        }

    enriched = await enrich_candidates(
        [candidate],
        cookie=None,
        api_key="secret",
        fetch_detail=fake_fetch_detail,
    )

    assert enriched[0].discount == Discount.NORMAL
    assert enriched[0].metadata["mteam_detail_enriched"] is True
