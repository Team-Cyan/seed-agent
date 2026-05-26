from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

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
        _discover_site_candidates(site, config.config_dir, config.discovery)
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


async def _discover_site_candidates(
    site,
    config_dir: Path | None,
    discovery_config: DiscoveryConfig | None = None,
) -> list[TorrentCandidate]:
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
            options=_mteam_api_options(site.api_discovery, discovery_config),
            **api_kwargs,
        )

    return await fetch_rss_candidates(
        site.rss_url,
        site.name,
        cookie=cookie,
        api_key=api_key,
        site_type=site.type,
    )


def _mteam_api_options(
    api_discovery,
    discovery_config: DiscoveryConfig | None,
) -> MTeamApiDiscoveryOptions:
    data = api_discovery.model_dump()
    if data.get("min_seeders") is None:
        data["min_seeders"] = discovery_config.min_seeders if discovery_config else 0
    if data.get("min_leechers") is None:
        data["min_leechers"] = discovery_config.min_leechers if discovery_config else 0
    return MTeamApiDiscoveryOptions.model_validate(data)


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


def strategy_report(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    managed_torrents: Sequence[ManagedTorrent] | Iterable[ManagedTorrent],
    *,
    managed_summaries: Sequence[dict[str, Any]] | Iterable[dict[str, Any]] | None = None,
) -> dict[str, object]:
    scored_list = list(scored)
    managed_list = list(managed_torrents)
    summary_list = list(managed_summaries or [])

    return {
        "candidate_distribution": _candidate_distribution(scored_list),
        "runtime_outcomes": _runtime_outcomes(managed_list, summary_list),
    }


def _candidate_distribution(scored: Sequence[ScoreBreakdown]) -> dict[str, object]:
    return {
        "total_scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "rejected": sum(1 for item in scored if not item.accepted),
        "leechers": _score_bucket_counts(scored, _leecher_bucket),
        "seed_leecher_ratio": _score_bucket_counts(scored, _ratio_bucket),
        "size_gb": _score_bucket_counts(scored, _size_bucket),
        "score": _score_bucket_counts(scored, _score_bucket),
    }


def _runtime_outcomes(
    managed: Sequence[ManagedTorrent],
    summaries: Sequence[dict[str, Any]],
) -> dict[str, object]:
    uploaded_values = [
        torrent.uploaded_bytes / (1024**3) for torrent in managed if torrent.uploaded_bytes > 0
    ]
    evidence_summaries = [
        item for item in summaries if isinstance(item.get("candidate_evidence"), dict)
    ]
    return {
        "managed_torrents": len(managed),
        "with_candidate_evidence": len(evidence_summaries),
        "uploaded_count": len(uploaded_values),
        "avg_uploaded_gb": _average(uploaded_values),
        "by_state": _managed_state_counts(managed),
        "by_candidate_leechers": _evidence_outcome_buckets(
            evidence_summaries, _leecher_bucket_from_evidence
        ),
        "by_candidate_size_gb": _evidence_outcome_buckets(
            evidence_summaries, _size_bucket_from_evidence
        ),
        "by_candidate_score": _evidence_outcome_buckets(
            evidence_summaries, _score_bucket_from_evidence
        ),
    }


def _score_bucket_counts(
    scored: Sequence[ScoreBreakdown],
    bucket_fn,
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for item in scored:
        bucket = bucket_fn(item)
        entry = counts.setdefault(bucket, {"total": 0, "accepted": 0, "rejected": 0})
        entry["total"] += 1
        if item.accepted:
            entry["accepted"] += 1
        else:
            entry["rejected"] += 1
    return counts


def _evidence_outcome_buckets(
    summaries: Sequence[dict[str, Any]],
    bucket_fn,
) -> dict[str, dict[str, float | int]]:
    counts: dict[str, dict[str, float | int]] = {}
    uploads: dict[str, list[float]] = {}
    for item in summaries:
        evidence = item.get("candidate_evidence")
        if not isinstance(evidence, dict):
            continue
        bucket = bucket_fn(evidence)
        entry = counts.setdefault(
            bucket, {"total": 0, "uploaded_count": 0, "avg_uploaded_gb": 0.0}
        )
        entry["total"] = int(entry["total"]) + 1
        uploaded_gb = _as_float(item.get("uploaded_gb"))
        if uploaded_gb is not None and uploaded_gb > 0:
            entry["uploaded_count"] = int(entry["uploaded_count"]) + 1
            uploads.setdefault(bucket, []).append(uploaded_gb)
    for bucket, values in uploads.items():
        counts[bucket]["avg_uploaded_gb"] = _average(values)
    return counts


def _managed_state_counts(managed: Sequence[ManagedTorrent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for torrent in managed:
        counts[torrent.state] = counts.get(torrent.state, 0) + 1
    return counts


def _leecher_bucket(item: ScoreBreakdown) -> str:
    return _count_bucket(item.candidate.leechers)


def _ratio_bucket(item: ScoreBreakdown) -> str:
    ratio = item.candidate.seeders / max(item.candidate.leechers, 1)
    if ratio <= 4:
        return "0-4"
    if ratio <= 10:
        return "4-10"
    if ratio <= 20:
        return "10-20"
    return "20+"


def _size_bucket(item: ScoreBreakdown) -> str:
    return _size_value_bucket(item.candidate.size_bytes / (1024**3))


def _score_bucket(item: ScoreBreakdown) -> str:
    return _score_value_bucket(item.score)


def _leecher_bucket_from_evidence(evidence: dict[str, Any]) -> str:
    return _count_bucket(int(evidence.get("leechers") or 0))


def _size_bucket_from_evidence(evidence: dict[str, Any]) -> str:
    return _size_value_bucket(float(evidence.get("size_gb") or 0.0))


def _score_bucket_from_evidence(evidence: dict[str, Any]) -> str:
    return _score_value_bucket(int(evidence.get("score") or 0))


def _count_bucket(value: int) -> str:
    if value <= 4:
        return "0-4"
    if value <= 9:
        return "5-9"
    if value <= 24:
        return "10-24"
    return "25+"


def _size_value_bucket(size_gb: float) -> str:
    if size_gb < 20:
        return "0-20"
    if size_gb < 80:
        return "20-80"
    if size_gb < 150:
        return "80-150"
    return "150+"


def _score_value_bucket(score: int) -> str:
    if score <= 0:
        return "0"
    if score < 70:
        return "1-69"
    if score < 85:
        return "70-84"
    return "85-100"


def _average(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
