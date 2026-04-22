from datetime import UTC, datetime

from seed_agent.config import IntentConfig, SearchConfig
from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    ReleaseCandidate,
    ResourceIntent,
)
from seed_agent.policies.intent_ranking import rank_releases


def _intent(**overrides: object) -> ResourceIntent:
    data: dict[str, object] = {
        "intent_id": "cli:inception-2010-1080p",
        "source": IntentSource.CLI,
        "raw_text": "Inception 2010 1080p",
        "kind": IntentKind.MOVIE,
        "title": "Inception",
        "year": 2010,
        "resolution": "1080p",
        "requested_at": datetime(2026, 4, 22, tzinfo=UTC),
        "state": IntentState.NORMALIZED,
    }
    data.update(overrides)
    return ResourceIntent(**data)


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
        "discount": Discount.FREE,
        "published_at": datetime(2026, 4, 22, tzinfo=UTC),
        "metadata": {},
    }
    data.update(overrides)
    return ReleaseCandidate(**data)


def _intent_config(**overrides: object) -> IntentConfig:
    data: dict[str, object] = {
        "confirmation_threshold": 0.82,
        "auto_enqueue_threshold": 0.94,
        "ambiguity_gap": 0.08,
        "default_resolution": "1080p",
        "preferred_languages": ["zh", "en"],
        "inbox_ref": "local/inbox/intents.jsonl",
    }
    data.update(overrides)
    return IntentConfig(**data)


def _search_config(**overrides: object) -> SearchConfig:
    data: dict[str, object] = {
        "site_priority": {"demo": 10},
        "max_results_per_site": 20,
        "prefer_free": True,
        "reject_hr_by_default": True,
    }
    data.update(overrides)
    return SearchConfig(**data)


def test_rank_releases_accepts_clear_high_confidence_match() -> None:
    ranked = rank_releases(
        _intent(),
        [_release()],
        _intent_config(),
        _search_config(),
    )

    assert len(ranked) == 1
    assert ranked[0].accepted is True
    assert ranked[0].confirmation_required is False
    assert ranked[0].score >= 94
    assert "title tokens matched" in ranked[0].reasons
    assert "free discount preferred" in ranked[0].reasons
    assert ranked[0].risks == []


def test_rank_releases_flags_missing_resolution_for_confirmation() -> None:
    ranked = rank_releases(
        _intent(),
        [_release(title="Inception 2010 720p BluRay")],
        _intent_config(),
        _search_config(),
    )

    assert ranked[0].accepted is False
    assert ranked[0].confirmation_required is True
    assert "resolution missing" in ranked[0].risks


def test_rank_releases_penalizes_hr_risk() -> None:
    ranked = rank_releases(
        _intent(),
        [_release(metadata={"hr": True})],
        _intent_config(),
        _search_config(),
    )

    assert ranked[0].accepted is False
    assert ranked[0].confirmation_required is True
    assert "H&R risk" in ranked[0].risks


def test_rank_releases_marks_close_top_candidates_as_ambiguous() -> None:
    ranked = rank_releases(
        _intent(),
        [
            _release(
                release_id="demo:https://tracker.example/details.php?id=1",
                title="Inception 2010 1080p BluRay",
            ),
            _release(
                release_id="demo:https://tracker.example/details.php?id=2",
                title="Inception 2010 1080p WEB-DL",
                seeders=38,
                leechers=11,
            ),
        ],
        _intent_config(),
        _search_config(),
    )

    assert len(ranked) == 2
    assert ranked[0].confirmation_required is True
    assert "ambiguous top candidates" in ranked[0].risks
    assert ranked[1].confirmation_required is True
    assert "close to top candidate" in ranked[1].risks


def test_rank_releases_orders_by_score() -> None:
    ranked = rank_releases(
        _intent(resolution=None),
        [
            _release(
                release_id="demo:https://tracker.example/details.php?id=low",
                title="Inception 2010 720p",
                discount=Discount.NORMAL,
                seeders=2,
                leechers=0,
            ),
            _release(
                release_id="demo:https://tracker.example/details.php?id=high",
                title="Inception 2010 1080p",
                discount=Discount.FREE,
                seeders=20,
                leechers=5,
            ),
        ],
        _intent_config(),
        _search_config(),
    )

    assert [item.release.release_id for item in ranked] == [
        "demo:https://tracker.example/details.php?id=high",
        "demo:https://tracker.example/details.php?id=low",
    ]
