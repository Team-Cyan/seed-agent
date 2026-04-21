from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import ManagedTorrent, ScoreBreakdown, TorrentCandidate
from seed_agent.policies.scoring import score_candidate
from seed_agent.sites.rss import fetch_rss_candidates


async def discover_candidates(config: SeedAgentConfig) -> list[TorrentCandidate]:
    candidates: list[TorrentCandidate] = []

    for site in config.enabled_sites:
        cookie = _read_cookie(site.cookie_ref)
        site_candidates = await fetch_rss_candidates(site.rss_url, site.name, cookie=cookie)
        candidates.extend(site_candidates)

    return candidates


def score_candidates(
    candidates: Sequence[TorrentCandidate] | Iterable[TorrentCandidate],
    discovery_config: DiscoveryConfig,
    scoring_config: ScoringConfig,
) -> list[ScoreBreakdown]:
    return [
        score_candidate(candidate, discovery_config, scoring_config)
        for candidate in candidates
    ]


def daily_report(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    managed_torrents: Sequence[ManagedTorrent] | Iterable[ManagedTorrent],
) -> dict[str, object]:
    scored_list = list(scored)
    managed_list = list(managed_torrents)
    ordered = sorted(
        scored_list,
        key=lambda item: (-item.score, item.candidate_id),
    )

    return {
        "total_scored": len(scored_list),
        "accepted": sum(1 for item in scored_list if item.accepted),
        "rejected": sum(1 for item in scored_list if not item.accepted),
        "managed_torrents": len(managed_list),
        "top_candidates": [
            {
                "candidate_id": item.candidate_id,
                "score": item.score,
                "accepted": item.accepted,
                "title": item.candidate.title,
                "site": item.candidate.site,
            }
            for item in ordered[:3]
        ],
    }


def _read_cookie(cookie_ref: str | None) -> str | None:
    if not cookie_ref:
        return None

    path = Path(cookie_ref)
    try:
        if not path.is_file():
            return None
        cookie = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    return cookie or None
