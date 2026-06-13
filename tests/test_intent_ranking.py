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
        "required_keywords": [],
        "preferred_keywords": [],
        "excluded_keywords": [],
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


def test_rank_releases_applies_configured_keyword_preferences() -> None:
    ranked = rank_releases(
        _intent(resolution=None),
        [
            _release(
                release_id="demo:https://tracker.example/details.php?id=remux",
                title="Inception 2010 2160p BluRay Remux HDR",
                discount=Discount.NORMAL,
            ),
            _release(
                release_id="demo:https://tracker.example/details.php?id=web",
                title="Inception 2010 2160p WEB-DL",
                discount=Discount.FREE,
                seeders=100,
                leechers=20,
            ),
        ],
        _intent_config(default_resolution="2160p"),
        _search_config(required_keywords=["Remux"], preferred_keywords=["HDR"]),
    )

    assert ranked[0].release.release_id.endswith("remux")
    assert "required keyword matched: Remux" in ranked[0].reasons
    assert "preferred keyword matched: HDR" in ranked[0].reasons
    assert "required keyword missing: Remux" in ranked[1].risks


def test_rank_releases_keeps_remux_required_for_movies_only() -> None:
    ranked = rank_releases(
        _intent(resolution=None),
        [_release(title="Inception 2010 2160p WEB-DL HDR")],
        _intent_config(default_resolution="2160p"),
        _search_config(required_keywords=["Remux"], preferred_keywords=["HDR"]),
    )

    assert "required keyword missing: Remux" in ranked[0].risks
    assert ranked[0].score < 82


def test_rank_releases_does_not_require_remux_for_shows() -> None:
    ranked = rank_releases(
        _intent(
            kind=IntentKind.SHOW,
            title="Spider Noir",
            raw_text="Spider Noir 2026 S01 2160p",
            year=2026,
            season=1,
            resolution="2160p",
            metadata={"media_type": "tv"},
        ),
        [_release(title="Spider-Noir 2026 S01 2160p WEB-DL HDR", seeders=701, leechers=3)],
        _intent_config(default_resolution="2160p"),
        _search_config(required_keywords=["Remux"], preferred_keywords=["HDR"]),
    )

    assert "required keyword missing: Remux" not in ranked[0].risks
    assert any(reason == "show quality keyword skipped: Remux" for reason in ranked[0].reasons)
    assert ranked[0].score >= 82


def test_rank_releases_does_not_require_remux_for_anime() -> None:
    ranked = rank_releases(
        _intent(
            kind=IntentKind.SHOW,
            title="Frieren",
            raw_text="Frieren 2023 S01 1080p",
            year=2023,
            season=1,
            resolution="1080p",
            metadata={"media_type": "anime"},
        ),
        [_release(title="Frieren 2023 S01 1080p WEB-DL", seeders=80, leechers=4)],
        _intent_config(default_resolution="1080p"),
        _search_config(required_keywords=["Remux"]),
    )

    assert "required keyword missing: Remux" not in ranked[0].risks
    assert any(reason == "anime quality keyword skipped: Remux" for reason in ranked[0].reasons)
    assert ranked[0].score >= 82


def test_rank_releases_scores_mixed_chinese_english_title_by_best_alias() -> None:
    ranked = rank_releases(
        _intent(
            title="家政服务 The Housemaid",
            raw_text="家政服务 The Housemaid 2025",
            year=2025,
            resolution=None,
        ),
        [_release(title="The Housemaid 2025 1080p BluRay")],
        _intent_config(default_resolution=None),
        _search_config(),
    )

    assert ranked[0].score >= 88
    assert "title tokens matched" in ranked[0].reasons
    assert "weak title match" not in ranked[0].risks


def test_rank_releases_defaults_episode_intents_to_season_pack_matching() -> None:
    ranked = rank_releases(
        _intent(
            kind=IntentKind.EPISODE,
            title="Severance",
            raw_text="Severance S02E03 2025",
            year=2025,
            season=2,
            episode=3,
            resolution="2160p",
        ),
        [_release(title="Severance 2025 S02 2160p BluRay Remux")],
        _intent_config(default_resolution="2160p"),
        _search_config(required_keywords=["Remux"]),
    )

    assert "season matched" in ranked[0].reasons
    assert "episode missing" not in ranked[0].risks


def test_rank_releases_can_require_episode_when_configured() -> None:
    ranked = rank_releases(
        _intent(
            kind=IntentKind.EPISODE,
            title="Severance",
            raw_text="Severance S02E03 2025",
            year=2025,
            season=2,
            episode=3,
            resolution="2160p",
        ),
        [_release(title="Severance 2025 S02 2160p BluRay Remux")],
        _intent_config(default_resolution="2160p", series_search_mode="episode"),
        _search_config(required_keywords=["Remux"]),
    )

    assert "episode missing" in ranked[0].risks
