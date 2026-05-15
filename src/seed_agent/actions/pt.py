from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from pathlib import Path

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import ManagedTorrent, ScoreBreakdown, TorrentCandidate
from seed_agent.policies.scoring import score_candidate
from seed_agent.sites.mteam import (
    MTeamApiDiscoveryOptions,
    has_deferred_download_url,
    resolve_deferred_download_url,
)
from seed_agent.sites.mteam import (
    fetch_api_candidates as fetch_mteam_api_candidates,
)
from seed_agent.sites.rss import fetch_rss_candidates


class SiteDiscoveryConfigError(RuntimeError):
    pass


async def discover_candidates(config: SeedAgentConfig) -> list[TorrentCandidate]:
    tasks = [
        _discover_site_candidates(site, config.config_dir)
        for site in config.enabled_sites
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    candidates: list[TorrentCandidate] = []
    for result in results:
        if isinstance(result, SiteDiscoveryConfigError):
            raise result
        if isinstance(result, Exception):
            continue
        candidates.extend(result)

    return candidates


async def _discover_site_candidates(site, config_dir: Path | None) -> list[TorrentCandidate]:
    cookie = _read_cookie(site.cookie_ref, config_dir)
    api_key = _read_secret(site.api_key_ref, config_dir)

    if site.type == "mteam" and site.discovery_mode == "api" and site.api_discovery is not None:
        if not api_key:
            raise SiteDiscoveryConfigError(
                f"missing api_key_ref secret for site {site.name}: {site.api_key_ref}"
            )
        api_kwargs = {}
        if site.auth_header != "x-api-key":
            api_kwargs["api_key_header"] = site.auth_header
        return await fetch_mteam_api_candidates(
            site=site.name,
            api_key=api_key,
            cookie=cookie,
            options=MTeamApiDiscoveryOptions.model_validate(site.api_discovery.model_dump()),
            **api_kwargs,
        )

    return await fetch_rss_candidates(
        site.rss_url,
        site.name,
        cookie=cookie,
        api_key=api_key,
        site_type=site.type,
    )


def score_candidates(
    candidates: Sequence[TorrentCandidate] | Iterable[TorrentCandidate],
    discovery_config: DiscoveryConfig,
    scoring_config: ScoringConfig,
) -> list[ScoreBreakdown]:
    return [
        score_candidate(candidate, discovery_config, scoring_config)
        for candidate in candidates
    ]


async def resolve_deferred_download_urls(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    config: SeedAgentConfig,
) -> list[ScoreBreakdown]:
    scored_list = list(scored)
    api_keys = {
        site.name: _read_secret(site.api_key_ref, config.config_dir)
        for site in config.enabled_sites
        if site.type == "mteam"
    }
    resolved: list[ScoreBreakdown] = []
    for item in scored_list:
        candidate = item.candidate
        if not item.accepted or not has_deferred_download_url(candidate):
            resolved.append(item)
            continue

        api_key = api_keys.get(candidate.site)
        if not api_key:
            resolved.append(_reject_unresolved_download_url(item, "missing mteam api key"))
            continue

        resolved_candidate = await resolve_deferred_download_url(
            candidate,
            api_key=api_key,
        )
        if resolved_candidate is None:
            resolved.append(
                _reject_unresolved_download_url(item, "download_url unavailable from mteam api")
            )
            continue
        resolved.append(item.model_copy(update={"candidate": resolved_candidate}))
    return resolved


def _reject_unresolved_download_url(item: ScoreBreakdown, reason: str) -> ScoreBreakdown:
    return item.model_copy(
        update={
            "score": 0,
            "accepted": False,
            "reasons": [*item.reasons, reason],
        }
    )


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
        base_dir = config_dir.parent if config_dir.name == "config" else config_dir
        path = base_dir / path
    try:
        if not path.is_file():
            return None
        secret = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    return secret or None
