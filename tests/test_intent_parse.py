from datetime import UTC, datetime

import pytest

from seed_agent.intent.parse import parse_resource_intent
from seed_agent.models import IntentKind, IntentSource, IntentState

REQUESTED_AT = datetime(2026, 4, 22, tzinfo=UTC)


def test_parse_movie_request_with_year_and_resolution() -> None:
    intent = parse_resource_intent(
        "Inception 2010 1080p BluRay",
        requested_at=REQUESTED_AT,
    )

    assert intent.intent_id.startswith("cli:")
    assert intent.source == IntentSource.CLI
    assert intent.kind == IntentKind.MOVIE
    assert intent.title == "Inception"
    assert intent.year == 2010
    assert intent.resolution == "1080p"
    assert intent.quality == "BluRay"
    assert intent.state == IntentState.NORMALIZED
    assert intent.metadata["parser"] == "deterministic"


def test_parse_episode_request_with_season_episode_and_language_alias() -> None:
    intent = parse_resource_intent(
        "show Severance S02E03 2160p WEB-DL CHS",
        requested_at=REQUESTED_AT,
    )

    assert intent.kind == IntentKind.EPISODE
    assert intent.title == "Severance"
    assert intent.season == 2
    assert intent.episode == 3
    assert intent.resolution == "2160p"
    assert intent.quality == "WEB-DL"
    assert intent.language == "zh"


def test_parse_show_request_without_episode() -> None:
    intent = parse_resource_intent(
        "series Foundation S03 4k",
        requested_at=REQUESTED_AT,
    )

    assert intent.kind == IntentKind.SHOW
    assert intent.title == "Foundation"
    assert intent.season == 3
    assert intent.episode is None
    assert intent.resolution == "2160p"


def test_parse_unknown_request_keeps_title_and_raw_text() -> None:
    intent = parse_resource_intent(
        "some obscure documentary",
        source=IntentSource.FILE_INBOX,
        requested_at=REQUESTED_AT,
    )

    assert intent.source == IntentSource.FILE_INBOX
    assert intent.kind == IntentKind.UNKNOWN
    assert intent.title == "some obscure documentary"
    assert intent.raw_text == "some obscure documentary"


def test_parse_removes_sensitive_assignments_from_title() -> None:
    intent = parse_resource_intent(
        "movie Secret passkey=abc123 2020 1080p",
        requested_at=REQUESTED_AT,
    )

    assert intent.title == "Secret"
    assert "passkey=abc123" in intent.raw_text


def test_parse_uses_source_event_id_for_stable_identity() -> None:
    first = parse_resource_intent(
        "Inception 2010 1080p",
        source=IntentSource.TELEGRAM,
        source_event_id="chat-1:message-99",
        requested_at=REQUESTED_AT,
    )
    second = parse_resource_intent(
        "Inception 2010 2160p",
        source=IntentSource.TELEGRAM,
        source_event_id="chat-1:message-99",
        requested_at=REQUESTED_AT,
    )

    assert first.intent_id == second.intent_id
    assert first.metadata["source_event_id"] == "chat-1:message-99"


def test_parse_rejects_blank_text() -> None:
    with pytest.raises(ValueError, match="raw_text"):
        parse_resource_intent("   ", requested_at=REQUESTED_AT)
