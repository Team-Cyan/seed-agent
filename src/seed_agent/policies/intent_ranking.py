from __future__ import annotations

import re

from seed_agent.config import IntentConfig, SearchConfig
from seed_agent.models import Discount, IntentKind, RankedRelease, ReleaseCandidate, ResourceIntent
from seed_agent.quality_tags import (
    QUALITY_TAG_GROUPS,
    matching_quality_tag_groups,
    quality_tag_texts,
)

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+")
SEASON_TOKEN_RE = re.compile(r"(?<![a-z0-9])s0*\d{1,2}(?!\d)", re.IGNORECASE)
EPISODE_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])(?:s0*\d{1,2}[ ._-]*e0*\d{1,3}|e0*\d{1,3}|\d{1,2}x\d{1,3})(?!\d)",
    re.IGNORECASE,
)
SEASON_TOKEN_WITH_NUMBER_RE = re.compile(
    r"(?<![a-z0-9])s0*(?P<season>\d{1,2})(?!\d)[ ._-]*(?P<number>\d{1,4})(?![a-z0-9])",
    re.IGNORECASE,
)


def rank_releases(
    intent: ResourceIntent,
    releases: list[ReleaseCandidate],
    intent_config: IntentConfig,
    search_config: SearchConfig,
) -> list[RankedRelease]:
    scored = [
        _rank_one(intent, release, intent_config, search_config)
        for release in filter_releases(intent, releases, intent_config)
    ]
    ordered = sorted(
        scored,
        key=lambda item: (-item.score, -item.confidence, item.release.release_id),
    )
    if not ordered:
        return []
    top_score = ordered[0].score
    ambiguity_gap = round(intent_config.ambiguity_gap * 100)
    for index, ranked in enumerate(ordered):
        close_to_top = index > 0 and top_score - ranked.score <= ambiguity_gap
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
        and ordered[0].score - ordered[1].score <= ambiguity_gap
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

    if _requires_season_pack(intent, intent_config):
        reasons.append("full season pack title")

    if _requires_episode_match(intent, intent_config):
        if _has_episode(release.title, intent.episode):
            score += 8
            reasons.append("episode matched")
        else:
            risks.append("episode missing")

    effective_resolution = intent.resolution or intent_config.default_resolution
    if effective_resolution is not None:
        if effective_resolution.lower() in _tokens(release.title):
            score += 12
            reasons.append("resolution matched")
        else:
            risks.append("resolution missing")

    quality_tag_adjustment = _quality_tag_score_adjustment(release, search_config)
    score += quality_tag_adjustment[0]
    reasons.extend(quality_tag_adjustment[1])

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

    score = max(0, score)
    confidence = round(min(score, 100) / 100, 4)
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
    title_variants = _title_token_variants(intent_title)
    if not title_variants:
        return 0
    release_tokens = _tokens(release_title)
    return max(
        _title_token_score(intent_tokens, release_tokens)
        for intent_tokens in title_variants
    )


def _title_token_score(intent_tokens: set[str], release_tokens: set[str]) -> int:
    matched = len(intent_tokens.intersection(release_tokens))
    return round(45 * (matched / len(intent_tokens)))


def _title_token_variants(title: str) -> list[set[str]]:
    full_tokens = _tokens(title)
    variants = [full_tokens] if full_tokens else []
    latin_tokens = {match.group(0).lower() for match in LATIN_TOKEN_RE.finditer(title)}
    cjk_tokens = {match.group(0).lower() for match in CJK_TOKEN_RE.finditer(title)}
    for token_set in (latin_tokens, cjk_tokens):
        if token_set and token_set not in variants:
            variants.append(token_set)
    return variants


def _has_season(title: str, season: int) -> bool:
    return re.search(rf"(?<![a-z])s0*{season}(?!\d)", title, re.IGNORECASE) is not None


def _has_episode(title: str, episode: int) -> bool:
    return re.search(rf"(?<![a-z])e0*{episode}(?!\d)", title, re.IGNORECASE) is not None


def _requires_episode_match(intent: ResourceIntent, intent_config: IntentConfig) -> bool:
    if intent.episode is None:
        return False
    return intent_config.series_search_mode == "episode" or intent.season is None


def _requires_season_pack(intent: ResourceIntent, intent_config: IntentConfig) -> bool:
    media_type = str(intent.metadata.get("media_type") or "").lower()
    is_series = (
        intent.kind in {IntentKind.SHOW, IntentKind.EPISODE}
        or media_type in {"tv", "anime"}
    )
    return is_series and intent_config.series_search_mode == "season"


def _is_season_pack(title: str) -> bool:
    return (
        SEASON_TOKEN_RE.search(title) is not None
        and EPISODE_TOKEN_RE.search(title) is None
        and not _has_numbered_episode_after_season(title)
    )


def _has_numbered_episode_after_season(title: str) -> bool:
    """Recognize compact release names such as ``S01.01-06`` and ``S01.101``.

    M-Team titles are not consistent about including an ``E`` before an episode.
    Keep the number immediately attached to the season marker so that unrelated
    years and resolutions (for example ``S01.1080p``) are not treated as episodes.
    """

    for match in SEASON_TOKEN_WITH_NUMBER_RE.finditer(title):
        season = int(match.group("season"))
        number = match.group("number")
        if _is_episode_number(number):
            return True
        if _is_compact_season_episode(number, season):
            return True
    return False


def _is_episode_number(value: str) -> bool:
    return 1 <= int(value) <= 99


def _is_compact_season_episode(value: str, season: int) -> bool:
    season_prefix = str(season)
    if not value.startswith(season_prefix):
        return False
    episode = value.removeprefix(season_prefix)
    return len(episode) >= 2 and _is_episode_number(episode)


def _is_candidate_eligible(
    intent: ResourceIntent,
    release: ReleaseCandidate,
    intent_config: IntentConfig,
) -> bool:
    if not _requires_season_pack(intent, intent_config):
        return True
    return _is_season_pack(release.title)


def filter_releases(
    intent: ResourceIntent,
    releases: list[ReleaseCandidate],
    intent_config: IntentConfig,
) -> list[ReleaseCandidate]:
    return [
        release
        for release in releases
        if _is_candidate_eligible(intent, release, intent_config)
    ]


def _quality_tag_score_adjustment(
    release: ReleaseCandidate,
    search_config: SearchConfig,
) -> tuple[int, list[str]]:
    if not search_config.quality_tag_scores:
        return 0, []
    matched_keys = {
        group.key
        for group in matching_quality_tag_groups(
            quality_tag_texts(release.title, release.metadata)
        )
    }
    score = 0
    reasons: list[str] = []
    for key, adjustment in search_config.quality_tag_scores.items():
        if adjustment == 0 or key not in matched_keys:
            continue
        group = QUALITY_TAG_GROUPS[key]
        score += adjustment
        sign = "+" if adjustment > 0 else ""
        reasons.append(f"quality tag score {sign}{adjustment}: {group.label}")
    return score, reasons


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value)}
