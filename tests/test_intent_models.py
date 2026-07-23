from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
)


def _release(**overrides: object) -> ReleaseCandidate:
    data: dict[str, object] = {
        "release_id": "demo:https://tracker.example/details.php?id=42",
        "site": "demo",
        "title": "Inception 2010 1080p BluRay",
        "source_url": "https://tracker.example/details.php?id=42",
        "download_url": "https://tracker.example/download.php?id=42&passkey=secret",
        "size_bytes": 8 * 1024**3,
        "seeders": 40,
        "leechers": 12,
        "discount": "free",
        "published_at": datetime(2026, 4, 22, tzinfo=UTC),
        "metadata": {"resolution": "1080p"},
    }
    data.update(overrides)
    return ReleaseCandidate(**data)


def test_resource_intent_accepts_minimal_cli_request() -> None:
    requested_at = datetime(2026, 4, 22, tzinfo=UTC)

    intent = ResourceIntent(
        intent_id="cli:inception-2010-1080p",
        source=IntentSource.CLI,
        raw_text="Inception 2010 1080p",
        kind=IntentKind.MOVIE,
        title="Inception",
        year=2010,
        resolution="1080p",
        requested_at=requested_at,
    )

    assert intent.state == IntentState.RECEIVED
    assert intent.requested_at == requested_at
    assert intent.metadata == {}


def test_resource_intent_rejects_invalid_year_and_empty_title() -> None:
    with pytest.raises(ValidationError):
        ResourceIntent(
            intent_id="cli:bad",
            source=IntentSource.CLI,
            raw_text="bad",
            kind=IntentKind.MOVIE,
            title="",
            year=1200,
            requested_at=datetime(2026, 4, 22, tzinfo=UTC),
        )


def test_release_candidate_normalizes_discount_and_validates_counts() -> None:
    release = _release(discount="2xfree")

    assert release.discount == Discount.TWO_X_FREE

    with pytest.raises(ValidationError):
        _release(seeders=-1)


def test_ranked_release_validates_score_and_confidence_ranges() -> None:
    release = _release()

    ranked = RankedRelease(
        intent_id="cli:inception-2010-1080p",
        release=release,
        score=94,
        confidence=0.96,
        accepted=True,
        confirmation_required=False,
        reasons=["title exact match", "preferred resolution"],
        risks=[],
    )

    assert ranked.release.discount == Discount.FREE
    assert ranked.accepted is True

    uncapped = RankedRelease(
        intent_id="cli:uncapped",
        release=release,
        score=127,
        confidence=1.0,
        accepted=True,
        confirmation_required=False,
        reasons=[],
        risks=[],
    )
    assert uncapped.score == 127

    with pytest.raises(ValidationError):
        RankedRelease(
            intent_id="cli:bad",
            release=release,
            score=101,
            confidence=1.2,
            accepted=True,
            confirmation_required=False,
            reasons=[],
            risks=[],
        )
