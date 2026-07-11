from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

from seed_agent.config import SearchConfig
from seed_agent.models import (
    IntentKind,
    ReleaseCandidate,
    ResourceIntent,
    TorrentCandidate,
    safe_url_identity,
)
from seed_agent.sites.mteam import (
    MTeamApiDiscoveryOptions,
    MTeamApiResponseError,
    fetch_api_candidates,
    resolve_deferred_download_url,
)

FetchMTeamCandidates = Callable[..., Awaitable[list[TorrentCandidate]]]


class MTeamSearchProvider:
    def __init__(
        self,
        *,
        site: str,
        api_key: str,
        search_config: SearchConfig,
        default_resolution: str | None = None,
        series_search_mode: Literal["season", "episode"] = "season",
        api_key_header: str = "x-api-key",
        cookie: str | None = None,
        api_options: MTeamApiDiscoveryOptions | None = None,
        fetch_candidates: FetchMTeamCandidates = fetch_api_candidates,
    ) -> None:
        self.site = site
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.cookie = cookie
        self.search_config = search_config
        self.default_resolution = default_resolution
        self.series_search_mode = series_search_mode
        self.api_options = api_options or _default_intent_api_options()
        self.fetch_candidates = fetch_candidates
        self.search_diagnostics: list[dict[str, Any]] = []

    async def search(self, intent: ResourceIntent) -> list[ReleaseCandidate]:
        option_sequence = _api_option_sequence_for_intent(
            self.api_options,
            intent,
            self.search_config,
            self.default_resolution,
            self.series_search_mode,
        )[: self.search_config.max_api_requests_per_intent]
        releases: list[ReleaseCandidate] = []
        seen_release_ids: set[str] = set()
        diagnostic: dict[str, Any] = {
            "site": self.site,
            "intent_id": intent.intent_id,
            "request_budget": self.search_config.max_api_requests_per_intent,
            "attempts": [],
        }
        for options in option_sequence:
            attempt = {"query_path": _query_path(options), "status": "started"}
            diagnostic["attempts"].append(attempt)
            try:
                candidates = await self.fetch_candidates(
                    site=self.site,
                    api_key=self.api_key,
                    api_key_header=self.api_key_header,
                    cookie=self.cookie,
                    options=options,
                )
            except MTeamApiResponseError as exc:
                attempt.update(
                    {
                        "status": "api_error",
                        "rate_limited": exc.rate_limited,
                    }
                )
                break
            except (httpx.TimeoutException, httpx.NetworkError):
                attempt["status"] = "network_error"
                break
            attempt.update({"status": "ok", "result_count": len(candidates)})
            for candidate in candidates:
                release = _release_from_candidate(candidate)
                if release.release_id in seen_release_ids:
                    continue
                releases.append(release)
                seen_release_ids.add(release.release_id)
                if len(releases) >= self.search_config.max_results_per_site:
                    break
            if len(releases) >= self.search_config.max_results_per_site:
                break
        diagnostic["requests_used"] = len(diagnostic["attempts"])
        diagnostic["release_count"] = len(releases)
        self.search_diagnostics.append(diagnostic)
        return releases


def _query_path(options: MTeamApiDiscoveryOptions) -> str:
    if options.douban:
        return "douban_id"
    if options.imdb:
        return "imdb_id"
    return "title_year"


async def resolve_mteam_release_download_url(
    release: ReleaseCandidate,
    *,
    api_key: str,
    api_key_header: str = "x-api-key",
) -> ReleaseCandidate | None:
    resolved = await resolve_deferred_download_url(
        _candidate_from_release(release),
        api_key=api_key,
        api_key_header=api_key_header,
    )
    if resolved is None:
        return None
    return release.model_copy(
        update={
            "download_url": resolved.download_url,
            "metadata": resolved.metadata,
        }
    )


def _search_keyword(
    intent: ResourceIntent,
    search_config: SearchConfig,
    default_resolution: str | None,
    series_search_mode: Literal["season", "episode"],
) -> str:
    terms = [intent.title]
    if intent.year is not None:
        terms.append(str(intent.year))
    if intent.season is not None:
        terms.append(f"S{intent.season:02d}")
    if intent.episode is not None and (series_search_mode == "episode" or intent.season is None):
        terms.append(f"E{intent.episode:02d}")
    resolution = intent.resolution or default_resolution
    if resolution is not None:
        terms.append(resolution)
    return " ".join(_dedupe_terms(terms))


def _default_intent_api_options() -> MTeamApiDiscoveryOptions:
    return MTeamApiDiscoveryOptions(
        mode="movie",
        only_free=False,
        discount=None,
        sort_field="seeders",
        sort_order="desc",
        max_seeders=0,
        min_seeders=0,
        min_leechers=0,
    )


def _api_options_for_intent(
    base_options: MTeamApiDiscoveryOptions,
    intent: ResourceIntent,
    search_config: SearchConfig,
    default_resolution: str | None,
    series_search_mode: Literal["season", "episode"],
) -> MTeamApiDiscoveryOptions:
    return _api_option_sequence_for_intent(
        base_options,
        intent,
        search_config,
        default_resolution,
        series_search_mode,
    )[0]


def _api_option_sequence_for_intent(
    base_options: MTeamApiDiscoveryOptions,
    intent: ResourceIntent,
    search_config: SearchConfig,
    default_resolution: str | None,
    series_search_mode: Literal["season", "episode"],
) -> list[MTeamApiDiscoveryOptions]:
    external_ids = _external_ids(intent)
    identifier_updates: dict[str, object] = {
        "mode": _mode_for_intent(intent),
        "only_free": False,
        "discount": None,
        "keyword": None,
        "imdb": None,
        "douban": None,
    }
    options: list[MTeamApiDiscoveryOptions] = []
    if external_ids.get("douban"):
        options.append(
            base_options.model_copy(
                update={
                    **identifier_updates,
                    "douban": external_ids["douban"],
                }
            )
        )
    if external_ids.get("imdb"):
        options.append(
            base_options.model_copy(
                update={
                    **identifier_updates,
                    "imdb": external_ids["imdb"],
                }
            )
        )
    if options:
        options.append(
            base_options.model_copy(
                update={
                    "mode": _mode_for_intent(intent),
                    "keyword": _search_keyword(
                        intent,
                        search_config,
                        default_resolution,
                        series_search_mode,
                    ),
                    "imdb": None,
                    "douban": None,
                    "only_free": False,
                    "discount": None,
                }
            )
        )
        return options
    return [
        base_options.model_copy(
            update={
                "mode": _mode_for_intent(intent),
                "keyword": _search_keyword(
                    intent,
                    search_config,
                    default_resolution,
                    series_search_mode,
                ),
                "imdb": None,
                "douban": None,
            }
        )
    ]


def _external_ids(intent: ResourceIntent) -> dict[str, str]:
    raw = intent.metadata.get("external_ids")
    if not isinstance(raw, dict):
        return {}
    ids: dict[str, str] = {}
    for provider in ("douban", "imdb"):
        value = raw.get(provider)
        if value is not None and str(value).strip():
            ids[provider] = str(value).strip()
    return ids


def _mode_for_intent(intent: ResourceIntent) -> str:
    media_type = str(intent.metadata.get("media_type") or intent.metadata.get("kind") or "").lower()
    if intent.kind in {IntentKind.SHOW, IntentKind.EPISODE} or media_type == "tv":
        return "tvshow"
    return "movie"


def _release_from_candidate(candidate: TorrentCandidate) -> ReleaseCandidate:
    return ReleaseCandidate(
        release_id=f"{candidate.site}:{safe_url_identity(candidate.source_url)}",
        site=candidate.site,
        title=candidate.title,
        source_url=candidate.source_url,
        download_url=candidate.download_url,
        size_bytes=candidate.size_bytes,
        seeders=candidate.seeders,
        leechers=candidate.leechers,
        discount=candidate.discount,
        published_at=candidate.published_at,
        metadata={
            **candidate.metadata,
            "hr": candidate.hr,
            "left_time_minutes": candidate.left_time_minutes,
        },
    )


def _candidate_from_release(release: ReleaseCandidate) -> TorrentCandidate:
    return TorrentCandidate(
        site=release.site,
        title=release.title,
        source_url=release.source_url,
        download_url=release.download_url,
        size_bytes=release.size_bytes,
        seeders=release.seeders,
        leechers=release.leechers,
        discount=release.discount,
        left_time_minutes=release.metadata.get("left_time_minutes"),
        hr=bool(release.metadata.get("hr", False)),
        published_at=release.published_at,
        metadata=release.metadata,
    )


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = " ".join(str(term).split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped
