from __future__ import annotations

import re

from seed_agent.config import IntentConfig, SearchConfig
from seed_agent.models import Discount, RankedRelease, ReleaseCandidate, ResourceIntent

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def rank_releases(
    intent: ResourceIntent,
    releases: list[ReleaseCandidate],
    intent_config: IntentConfig,
    search_config: SearchConfig,
) -> list[RankedRelease]:
    scored = [
        _rank_one(intent, release, intent_config, search_config)
        for release in releases
    ]
    ordered = sorted(
        scored,
        key=lambda item: (-item.score, -item.confidence, item.release.release_id),
    )
    if not ordered:
        return []
    top_score = ordered[0].confidence
    for index, ranked in enumerate(ordered):
        close_to_top = index > 0 and top_score - ranked.confidence <= intent_config.ambiguity_gap
        confirmation_required = ranked.confirmation_required or close_to_top
        if close_to_top and "close to top candidate" not in ranked.risks:
            ranked = ranked.model_copy(
                update={
                    "confirmation_required": confirmation_required,
                    "risks": [*ranked.risks, "close to top candidate"],
                }
            )
            ordered[index] = ranked
    if (
        len(ordered) > 1
        and ordered[0].confidence - ordered[1].confidence <= intent_config.ambiguity_gap
    ):
        ordered[0] = ordered[0].model_copy(
            update={
                "confirmation_required": True,
                "risks": [*ordered[0].risks, "ambiguous top candidates"],
            }
        )
    return ordered


def _rank_one(
    intent: ResourceIntent,
    release: ReleaseCandidate,
    intent_config: IntentConfig,
    search_config: SearchConfig,
) -> RankedRelease:
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    title_score = _title_score(intent.title, release.title)
    score += title_score
    if title_score >= 30:
        reasons.append("title tokens matched")
    else:
        risks.append("weak title match")

    if intent.year is not None:
        if str(intent.year) in _tokens(release.title):
            score += 12
            reasons.append("year matched")
        else:
            risks.append("year missing")

    if intent.season is not None:
        if _has_season(release.title, intent.season):
            score += 8
            reasons.append("season matched")
        else:
            risks.append("season missing")

    if intent.episode is not None:
        if _has_episode(release.title, intent.episode):
            score += 8
            reasons.append("episode matched")
        else:
            risks.append("episode missing")

    if intent.resolution is not None:
        if intent.resolution.lower() in _tokens(release.title):
            score += 12
            reasons.append("resolution matched")
        else:
            risks.append("resolution missing")

    site_bonus = min(max(search_config.site_priority.get(release.site, 0), 0), 10)
    if site_bonus:
        score += site_bonus
        reasons.append(f"site priority +{site_bonus}")

    if search_config.prefer_free and release.discount in {Discount.FREE, Discount.TWO_X_FREE}:
        score += 8
        reasons.append("free discount preferred")

    if release.seeders >= 10:
        score += 7
        reasons.append("healthy seeders")
    if release.leechers >= 5:
        score += 6
        reasons.append("active leechers")

    if search_config.reject_hr_by_default and bool(release.metadata.get("hr")):
        risks.append("H&R risk")
        score -= 20

    score = max(0, min(score, 100))
    confidence = round(score / 100, 4)
    accepted = confidence >= intent_config.confirmation_threshold and not risks
    confirmation_required = confidence < intent_config.auto_enqueue_threshold or bool(risks)

    return RankedRelease(
        intent_id=intent.intent_id,
        release=release,
        score=score,
        confidence=confidence,
        accepted=accepted,
        confirmation_required=confirmation_required,
        reasons=reasons,
        risks=risks,
    )


def _title_score(intent_title: str, release_title: str) -> int:
    intent_tokens = _tokens(intent_title)
    if not intent_tokens:
        return 0
    release_tokens = _tokens(release_title)
    matched = len(intent_tokens.intersection(release_tokens))
    return round(45 * (matched / len(intent_tokens)))


def _has_season(title: str, season: int) -> bool:
    token = f"s{season:02d}"
    return any(item.startswith(token) for item in _tokens(title))


def _has_episode(title: str, episode: int) -> bool:
    token = f"e{episode:02d}"
    return any(token in item for item in _tokens(title))


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value)}
