from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from seed_agent.config import DiscoveryConfig, ScoringConfig
from seed_agent.models import Discount, ScoreBreakdown, TorrentCandidate

GIB = 1024**3


@dataclass(frozen=True)
class _ComponentScore:
    score: float
    reason: str
    hard_reject: bool = False


def score_candidate(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> ScoreBreakdown:
    reasons: list[str] = []
    hard_reject = False
    total = 0.0

    if candidate.hr and not discovery.allow_hr:
        reasons.append("hr protected by config")
        hard_reject = True

    discount_component = _score_discount(candidate, discovery, scoring)
    total += discount_component.score
    reasons.append(discount_component.reason)
    hard_reject = hard_reject or discount_component.hard_reject

    left_time_component = _score_left_time(candidate, discovery, scoring)
    total += left_time_component.score
    reasons.append(left_time_component.reason)
    hard_reject = hard_reject or left_time_component.hard_reject

    leecher_component = _score_leechers(candidate, discovery, scoring)
    total += leecher_component.score
    reasons.append(leecher_component.reason)
    hard_reject = hard_reject or leecher_component.hard_reject

    seeder_component = _score_seeders(candidate, discovery, scoring)
    total += seeder_component.score
    reasons.append(seeder_component.reason)
    hard_reject = hard_reject or seeder_component.hard_reject

    size_component = _score_size(candidate, discovery, scoring)
    total += size_component.score
    reasons.append(size_component.reason)
    hard_reject = hard_reject or size_component.hard_reject

    site_history_component = _score_site_history(candidate, scoring)
    total += site_history_component.score
    reasons.append(site_history_component.reason)

    score = 0 if hard_reject else _clamp_score(total)
    if score >= scoring.min_score_to_enqueue:
        threshold_reason = f"score {score} >= threshold {scoring.min_score_to_enqueue}"
    else:
        threshold_reason = f"score {score} < threshold {scoring.min_score_to_enqueue}"
    reasons.append(threshold_reason)

    accepted = not hard_reject and score >= scoring.min_score_to_enqueue
    if hard_reject:
        score = 0

    return ScoreBreakdown(
        candidate_id=candidate.stable_id,
        score=score,
        accepted=accepted,
        reasons=reasons,
        candidate=candidate,
    )


def _score_discount(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["discount"]
    discount = candidate.discount
    if not discovery.allow_non_free and discount not in {
        Discount.FREE,
        Discount.TWO_X_FREE,
    }:
        return _ComponentScore(
            0.0,
            f"discount {discount.value} rejected by free-only policy",
            True,
        )
    if discount in discovery.discounts:
        return _ComponentScore(weight, f"discount {discount.value} accepted")
    if discount in {Discount.HALF, Discount.TWO_X_HALF}:
        if discovery.allow_non_free:
            return _ComponentScore(weight * 0.5, f"discount {discount.value} allowed partial")
        return _ComponentScore(0.0, f"discount {discount.value} not accepted", True)
    if discount == Discount.NORMAL:
        if discovery.allow_non_free:
            return _ComponentScore(0.0, "discount normal allowed without discount credit")
        return _ComponentScore(0.0, "discount normal not accepted", True)
    return _ComponentScore(0.0, f"discount {discount.value} not configured")


def _score_left_time(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["left_time"]
    left_time = candidate.left_time_minutes
    if left_time is None:
        if candidate.metadata.get("left_time_source") == "mteam_api_unlimited":
            return _ComponentScore(weight, "left_time unlimited for mteam api discovery")
        if _allows_missing_left_time(candidate, discovery):
            return _ComponentScore(0.0, "left_time unavailable for mteam api discovery")
        return _ComponentScore(0.0, "left_time missing", True)
    if left_time < discovery.min_left_time_minutes:
        reason = f"left_time {left_time} < min {discovery.min_left_time_minutes}"
        return _ComponentScore(0.0, reason, True)
    reason = f"left_time {left_time} >= min {discovery.min_left_time_minutes}"
    return _ComponentScore(weight, reason)


def _allows_missing_left_time(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
) -> bool:
    return (
        candidate.metadata.get("mteam_discovery_mode") == "api"
        and candidate.metadata.get("left_time_source") == "mteam_api_missing"
        and candidate.discount in discovery.discounts
    )


def _score_leechers(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["leechers"]
    leechers = candidate.leechers
    minimum = discovery.min_leechers
    if leechers < minimum:
        return _ComponentScore(0.0, f"leechers {leechers} < min {minimum}", True)
    maximum = discovery.max_leechers
    if maximum is not None and leechers > maximum:
        return _ComponentScore(0.0, f"leechers {leechers} > max {maximum}", True)
    multiplier = discovery.leecher_score_full_at_multiplier
    if minimum <= 0 or multiplier <= 1:
        return _ComponentScore(weight, f"leechers {leechers} >= min {minimum}")
    full_score_at = max(minimum, int(round(minimum * multiplier)))
    if leechers >= full_score_at:
        return _ComponentScore(weight, f"leechers {leechers} >= full-score {full_score_at}")
    factor = max(0.0, min(1.0, leechers / full_score_at))
    return _ComponentScore(
        weight * factor,
        f"leechers {leechers} between min {minimum} and full-score {full_score_at}",
    )


def _score_seeders(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["seeders"]
    seeders = candidate.seeders
    minimum = discovery.min_seeders
    if minimum is not None and seeders < minimum:
        return _ComponentScore(0.0, f"seeders {seeders} < min {minimum}", True)
    target = discovery.target_seed_leecher_ratio
    if target <= 0:
        return _ComponentScore(weight, "seeder_leecher_ratio disabled")
    ratio = seeders / max(candidate.leechers, 1)
    if ratio <= target:
        return _ComponentScore(weight, f"seeder_leecher_ratio {ratio:.2f} <= target {target:.2f}")
    ceiling = max(target * 2, target + 1)
    if ratio >= ceiling:
        return _ComponentScore(
            0.0,
            f"seeder_leecher_ratio {ratio:.2f} >= 2x target {target:.2f}",
        )
    span = ceiling - target
    factor = max(0.0, 1.0 - ((ratio - target) / span))
    score = weight * factor
    return _ComponentScore(
        score,
        f"seeder_leecher_ratio {ratio:.2f} tapered above target {target:.2f}",
    )


def _score_size(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["size"]
    size_gib = candidate.size_bytes / GIB
    if discovery.min_size_gb is not None and size_gib < discovery.min_size_gb:
        return _ComponentScore(
            0.0,
            f"size {size_gib:.1f} GiB < min {discovery.min_size_gb:.1f} GiB",
            True,
        )
    if discovery.max_size_gb is not None and size_gib > discovery.max_size_gb:
        return _ComponentScore(
            0.0,
            f"size {size_gib:.1f} GiB > max {discovery.max_size_gb:.1f} GiB",
            True,
        )

    preferred_min = discovery.preferred_size_min_gb
    if preferred_min is None:
        preferred_min = 2.0
    preferred_max = discovery.preferred_size_max_gb
    if preferred_max is None:
        preferred_max = 80.0
    partial_max = max(preferred_max, discovery.size_partial_max_gb)
    if preferred_min <= size_gib <= preferred_max:
        return _ComponentScore(weight, f"size {size_gib:.1f} GiB preferred")
    if preferred_max < size_gib <= partial_max:
        return _ComponentScore(weight * 0.5, f"size {size_gib:.1f} GiB above preferred range")
    if size_gib < preferred_min:
        return _ComponentScore(0.0, f"size {size_gib:.1f} GiB below preferred range")
    return _ComponentScore(0.0, f"size {size_gib:.1f} GiB above preferred range")


def _score_site_history(candidate: TorrentCandidate, scoring: ScoringConfig) -> _ComponentScore:
    weight = scoring.weights["site_history"]
    raw_value = candidate.metadata.get("site_history_score", 0.5)
    score = _coerce_history_score(raw_value)
    return _ComponentScore(weight * score, f"site_history {score:.1f}")


def _coerce_history_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(score, 1.0))


def _clamp_score(value: float) -> int:
    return max(0, min(int(round(value)), 100))
