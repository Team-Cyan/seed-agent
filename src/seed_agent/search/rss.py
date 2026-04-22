from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from seed_agent.models import ReleaseCandidate, ResourceIntent, TorrentCandidate, safe_url_identity
from seed_agent.sites.rss import fetch_rss_candidates

FetchCandidates = Callable[[str, str, str | None], Awaitable[list[TorrentCandidate]]]
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


class RssSearchProvider:
    def __init__(
        self,
        *,
        url: str,
        site: str,
        cookie: str | None = None,
        max_results: int = 20,
        fetcher: FetchCandidates = fetch_rss_candidates,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be >= 1")
        self.url = url
        self.site = site
        self.cookie = cookie
        self.max_results = max_results
        self.fetcher = fetcher

    async def search(self, intent: ResourceIntent) -> list[ReleaseCandidate]:
        candidates = await self.fetcher(self.url, self.site, self.cookie)
        releases: list[ReleaseCandidate] = []
        for candidate in candidates:
            if not _matches_intent(candidate, intent):
                continue
            releases.append(_release_from_candidate(candidate))
            if len(releases) >= self.max_results:
                break
        return releases


def _matches_intent(candidate: TorrentCandidate, intent: ResourceIntent) -> bool:
    intent_tokens = _tokens(intent.title)
    if not intent_tokens:
        return False
    candidate_tokens = _tokens(candidate.title)
    if not intent_tokens.issubset(candidate_tokens):
        return False
    if intent.year is not None and str(intent.year) not in candidate_tokens:
        return False
    if intent.season is not None:
        season_token = f"s{intent.season:02d}"
        if not any(token.startswith(season_token) for token in candidate_tokens):
            return False
    if intent.episode is not None:
        episode_token = f"e{intent.episode:02d}"
        if not any(episode_token in token for token in candidate_tokens):
            return False
    if intent.resolution is not None and intent.resolution.lower() not in candidate_tokens:
        return False
    return True


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


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value)}
