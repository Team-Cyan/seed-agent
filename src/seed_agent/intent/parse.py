from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from seed_agent.audit import redact_sensitive_text
from seed_agent.models import IntentKind, IntentSource, IntentState, ResourceIntent

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|21\d{2})\b")
RESOLUTION_RE = re.compile(r"\b(720p|1080p|2160p|4320p|4k|8k)\b", re.IGNORECASE)
EPISODE_RE = re.compile(r"\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b", re.IGNORECASE)
SEASON_RE = re.compile(r"\bS(?P<season>\d{1,2})\b", re.IGNORECASE)
SEASON_WORD_RE = re.compile(r"\bSeason[ ._-]*(?P<season>\d{1,2})(?!\d)", re.IGNORECASE)
CHINESE_SEASON_RE = re.compile(r"第\s*(?P<season>[一二三四五六七八九十0-9]{1,3})\s*季")
QUALITY_RE = re.compile(r"\b(BluRay|WEB[-_. ]?DL|WEBRip|HDRip|Remux|DVDRip)\b", re.IGNORECASE)
LANGUAGE_RE = re.compile(r"\b(zh|chi|chs|cht|cn|en|eng|jpn|jp)\b", re.IGNORECASE)
KIND_PREFIX_RE = re.compile(r"^\s*(?P<kind>movie|film|show|series|episode)\s+", re.IGNORECASE)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"\b[\w.-]*(passkey|password|passphrase|token|secret|cookie|auth)"
    r"[\w.-]*\s*(?:=|:)\s*\S+",
    re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")


def parse_resource_intent(
    raw_text: str,
    *,
    source: IntentSource = IntentSource.CLI,
    requested_at: datetime | None = None,
    source_event_id: str | None = None,
) -> ResourceIntent:
    text = _normalize_space(raw_text)
    if not text:
        raise ValueError("raw_text must not be empty")

    safe_text = redact_sensitive_text(text)
    event_identity = source_event_id or text
    requested = requested_at or datetime.now(UTC)
    kind_prefix = _kind_prefix(safe_text)
    working = KIND_PREFIX_RE.sub("", safe_text, count=1)

    year = _first_int(YEAR_RE, working)
    resolution = _first_match(RESOLUTION_RE, working)
    if resolution is not None:
        resolution = resolution.lower().replace("4k", "2160p").replace("8k", "4320p")
    episode_match = EPISODE_RE.search(working)
    season = int(episode_match.group("season")) if episode_match is not None else None
    episode = int(episode_match.group("episode")) if episode_match is not None else None
    if season is None:
        season = _first_named_int(SEASON_RE, working, "season")
    if season is None:
        season = _first_named_int(SEASON_WORD_RE, working, "season")
    if season is None:
        season = _first_chinese_season(working)
    quality = _first_match(QUALITY_RE, working)
    if quality is not None:
        quality = quality.replace("_", "-").replace(" ", "-")
    language = _normalize_language(_first_match(LANGUAGE_RE, working))

    title = _title_from_text(working)
    kind = _kind(kind_prefix, year=year, season=season, episode=episode)
    return ResourceIntent(
        intent_id=_intent_id(source, event_identity),
        source=source,
        raw_text=safe_text,
        kind=kind,
        title=title,
        year=year,
        season=season,
        episode=episode,
        resolution=resolution,
        quality=quality,
        language=language,
        requested_at=requested,
        state=IntentState.NORMALIZED,
        metadata={
            "parser": "deterministic",
            "source_event_id": source_event_id,
            "kind_prefix": kind_prefix.value if kind_prefix is not None else None,
        },
    )


def _intent_id(source: IntentSource, event_identity: str) -> str:
    digest = hashlib.sha256(f"{source.value}\n{event_identity}".encode()).hexdigest()[:16]
    return f"{source.value}:{digest}"


def _kind_prefix(value: str) -> IntentKind | None:
    match = KIND_PREFIX_RE.search(value)
    if match is None:
        return None
    raw = match.group("kind").lower()
    if raw in {"movie", "film"}:
        return IntentKind.MOVIE
    if raw in {"show", "series"}:
        return IntentKind.SHOW
    return IntentKind.EPISODE


def _kind(
    prefix: IntentKind | None,
    *,
    year: int | None,
    season: int | None,
    episode: int | None,
) -> IntentKind:
    if prefix is not None:
        if prefix == IntentKind.SHOW and episode is not None:
            return IntentKind.EPISODE
        return prefix
    if episode is not None:
        return IntentKind.EPISODE
    if season is not None:
        return IntentKind.SHOW
    if year is not None:
        return IntentKind.MOVIE
    return IntentKind.UNKNOWN


def _title_from_text(value: str) -> str:
    title = value
    for pattern in (
        SENSITIVE_ASSIGNMENT_RE,
        EPISODE_RE,
        SEASON_RE,
        SEASON_WORD_RE,
        CHINESE_SEASON_RE,
        YEAR_RE,
        RESOLUTION_RE,
        QUALITY_RE,
        LANGUAGE_RE,
    ):
        title = pattern.sub(" ", title)
    title = title.replace(".", " ").replace("_", " ").replace("-", " ")
    title = _normalize_space(title)
    return title or value


def _first_match(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    if match is None:
        return None
    return match.group(0)


def _first_int(pattern: re.Pattern[str], value: str) -> int | None:
    match = pattern.search(value)
    if match is None:
        return None
    return int(match.group(0))


def _first_named_int(pattern: re.Pattern[str], value: str, name: str) -> int | None:
    match = pattern.search(value)
    if match is None:
        return None
    return int(match.group(name))


def _first_chinese_season(value: str) -> int | None:
    match = CHINESE_SEASON_RE.search(value)
    if match is None:
        return None
    raw = match.group("season")
    if raw.isdigit():
        return int(raw)
    numerals = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if raw == "十":
        return 10
    if "十" not in raw:
        return numerals.get(raw)
    tens, _, ones = raw.partition("十")
    tens_value = numerals.get(tens, 1) if tens else 1
    ones_value = numerals.get(ones, 0) if ones else 0
    return tens_value * 10 + ones_value


def _normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"chi", "chs", "cht", "cn"}:
        return "zh"
    if normalized == "eng":
        return "en"
    if normalized in {"jpn", "jp"}:
        return "jp"
    return normalized


def _normalize_space(value: str) -> str:
    return SPACE_RE.sub(" ", value.strip())
