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

    size_component = _score_size(candidate, scoring)
    total += size_component.score
    reasons.append(size_component.reason)

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
    if discount in discovery.discounts:
        return _ComponentScore(weight, f"discount {discount.value} accepted")
    if discount in {Discount.HALF, Discount.TWO_X_HALF}:
        return _ComponentScore(weight * 0.5, f"discount {discount.value} partial")
    if discount == Discount.NORMAL:
        return _ComponentScore(0.0, "discount normal not accepted", True)
    return _ComponentScore(0.0, f"discount {discount.value} not configured")


def _score_left_time(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["left_time"]
    left_time = candidate.left_time_minutes
    if left_time is None or left_time < discovery.min_left_time_minutes:
        reason = f"left_time {left_time} < min {discovery.min_left_time_minutes}"
        return _ComponentScore(0.0, reason, True)
    reason = f"left_time {left_time} >= min {discovery.min_left_time_minutes}"
    return _ComponentScore(weight, reason)


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
    cap = max(minimum * 2, 1)
    factor = min(leechers / cap, 1.0)
    score = weight * factor
    if factor >= 1.0:
        reason = f"leechers {leechers} >= 2x min {minimum}"
    else:
        reason = f"leechers {leechers} >= min {minimum}"
    return _ComponentScore(score, reason)


def _score_seeders(
    candidate: TorrentCandidate,
    discovery: DiscoveryConfig,
    scoring: ScoringConfig,
) -> _ComponentScore:
    weight = scoring.weights["seeders"]
    seeders = candidate.seeders
    maximum = discovery.max_seeders
    if seeders <= maximum:
        return _ComponentScore(weight, f"seeders {seeders} <= max {maximum}")
    ceiling = max(maximum * 2, maximum + 1)
    if seeders >= ceiling:
        return _ComponentScore(0.0, f"seeders {seeders} >= 2x max {maximum}")
    span = ceiling - maximum
    factor = max(0.0, 1.0 - ((seeders - maximum) / span))
    score = weight * factor
    return _ComponentScore(score, f"seeders {seeders} tapered above max {maximum}")


def _score_size(candidate: TorrentCandidate, scoring: ScoringConfig) -> _ComponentScore:
    weight = scoring.weights["size"]
    size_gib = candidate.size_bytes / GIB
    if 2 <= size_gib <= 80:
        return _ComponentScore(weight, f"size {size_gib:.1f} GiB preferred")
    if 80 < size_gib <= 150:
        return _ComponentScore(weight * 0.5, f"size {size_gib:.1f} GiB above preferred range")
    if size_gib < 2:
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
