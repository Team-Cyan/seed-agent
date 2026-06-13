from __future__ import annotations

import re

from seed_agent.config import IntentConfig, SearchConfig
from seed_agent.models import Discount, IntentKind, RankedRelease, ReleaseCandidate, ResourceIntent

TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+")
MOVIE_ONLY_QUALITY_KEYWORDS = {"remux"}


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
    media_class = _intent_media_class(intent)

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

    for keyword in search_config.required_keywords:
        if _is_movie_only_quality_keyword(keyword) and media_class != "movie":
            reasons.append(f"{media_class} quality keyword skipped: {keyword}")
            continue
        if _keyword_in_title(keyword, release.title):
            score += 8
            reasons.append(f"required keyword matched: {keyword}")
        else:
            risks.append(f"required keyword missing: {keyword}")
            score -= 25

    for keyword in search_config.preferred_keywords:
        if _keyword_in_title(keyword, release.title):
            score += 5
            reasons.append(f"preferred keyword matched: {keyword}")

    for keyword in search_config.excluded_keywords:
        if _keyword_in_title(keyword, release.title):
            risks.append(f"excluded keyword matched: {keyword}")
            score -= 25

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
    token = f"s{season:02d}"
    return any(item.startswith(token) for item in _tokens(title))


def _has_episode(title: str, episode: int) -> bool:
    token = f"e{episode:02d}"
    return any(token in item for item in _tokens(title))


def _requires_episode_match(intent: ResourceIntent, intent_config: IntentConfig) -> bool:
    if intent.episode is None:
        return False
    return intent_config.series_search_mode == "episode" or intent.season is None


def _intent_media_class(intent: ResourceIntent) -> str:
    metadata_type = _normalize_media_type(
        intent.metadata.get("media_type") or intent.metadata.get("kind")
    )
    if metadata_type is not None:
        return metadata_type
    if intent.kind == IntentKind.MOVIE:
        return "movie"
    if intent.kind in {IntentKind.SHOW, IntentKind.EPISODE}:
        return "show"
    return "movie"


def _normalize_media_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"anime", "animation", "动画"}:
        return "anime"
    if normalized in {"show", "tv", "episode", "series", "电视剧", "剧集"}:
        return "show"
    if normalized in {"movie", "film", "电影"}:
        return "movie"
    return None


def _is_movie_only_quality_keyword(keyword: str) -> bool:
    return _normalize_keyword(keyword) in MOVIE_ONLY_QUALITY_KEYWORDS


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value)}


def _keyword_in_title(keyword: str, title: str) -> bool:
    normalized_keyword = _normalize_keyword(keyword)
    normalized_title = " ".join(title.lower().replace(".", " ").replace("_", " ").split())
    return normalized_keyword in normalized_title


def _normalize_keyword(keyword: str) -> str:
    return " ".join(keyword.lower().split())
