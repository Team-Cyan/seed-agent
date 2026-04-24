from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from pathlib import Path

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import ManagedTorrent, ScoreBreakdown, TorrentCandidate
from seed_agent.policies.scoring import score_candidate
from seed_agent.sites.rss import fetch_rss_candidates


async def discover_candidates(config: SeedAgentConfig) -> list[TorrentCandidate]:
    tasks = [
        fetch_rss_candidates(
            site.rss_url,
            site.name,
            cookie=_read_cookie(site.cookie_ref, config.config_dir),
            api_key=_read_secret(site.api_key_ref, config.config_dir),
            site_type=site.type,
        )
        for site in config.enabled_sites
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    candidates: list[TorrentCandidate] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        candidates.extend(result)

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


def _read_cookie(cookie_ref: str | None, config_dir: Path | None = None) -> str | None:
    return _read_secret(cookie_ref, config_dir)


def _read_secret(secret_ref: str | None, config_dir: Path | None = None) -> str | None:
    if not secret_ref:
        return None

    path = Path(secret_ref)
    if not path.is_absolute() and config_dir is not None:
        path = config_dir / path
    try:
        if not path.is_file():
            return None
        secret = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    return secret or None
