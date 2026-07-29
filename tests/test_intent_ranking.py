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
        "quality_tag_scores": {},
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


def test_rank_releases_applies_quality_tag_scores_once_per_group() -> None:
    ranked = rank_releases(
        _intent(resolution=None),
        [
            _release(
                release_id="demo:https://tracker.example/details.php?id=tagged",
                title="Inception 2010 1080p BluRay Blu-ray Blue-Ray Dolby Vision DoVi WEB-DL",
                discount=Discount.NORMAL,
                seeders=0,
                leechers=0,
            ),
        ],
        _intent_config(default_resolution="1080p"),
        _search_config(
            site_priority={},
            prefer_free=False,
            quality_tag_scores={"bluray": 20, "dolby_vision": 15, "webdl": -10},
        ),
    )

    assert ranked[0].score == 94
    assert ranked[0].reasons.count("quality tag score +20: Blu-ray") == 1
    assert ranked[0].reasons.count("quality tag score +15: Dolby Vision") == 1
    assert ranked[0].reasons.count("quality tag score -10: WEB-DL") == 1


def test_rank_releases_preserves_score_above_100() -> None:
    ranked = rank_releases(
        _intent(),
        [_release(title="Inception 2010 1080p WEB-DL Dolby Vision Atmos DDP")],
        _intent_config(),
        _search_config(
            quality_tag_scores={
                "webdl": 8,
                "dolby_vision": 12,
                "atmos": 5,
                "ddp": 8,
            }
        ),
    )

    assert ranked[0].score == 133
    assert ranked[0].confidence == 1.0


def test_rank_releases_uses_raw_score_for_ambiguity_gap() -> None:
    ranked = rank_releases(
        _intent(),
        [
            _release(
                release_id="demo:https://tracker.example/details.php?id=high",
                title="Inception 2010 1080p WEB-DL Dolby Vision Atmos DDP",
            ),
            _release(
                release_id="demo:https://tracker.example/details.php?id=lower",
                title="Inception 2010 1080p WEB-DL DDP",
            ),
        ],
        _intent_config(),
        _search_config(
            quality_tag_scores={
                "webdl": 8,
                "dolby_vision": 12,
                "atmos": 5,
                "ddp": 8,
            }
        ),
    )

    assert [item.score for item in ranked] == [133, 116]
    assert "ambiguous top candidates" not in ranked[0].risks
    assert "close to top candidate" not in ranked[1].risks


def test_rank_releases_reads_quality_tags_from_mteam_metadata() -> None:
    ranked = rank_releases(
        _intent(resolution=None),
        [
            _release(
                title="Inception 2010 1080p",
                discount=Discount.NORMAL,
                seeders=0,
                leechers=0,
                metadata={"mteam_tags": ["杜比视界", "Dolby Atmos"]},
            )
        ],
        _intent_config(default_resolution="1080p"),
        _search_config(
            site_priority={},
            prefer_free=False,
            quality_tag_scores={"dolby_vision": 15, "atmos": 8},
        ),
    )

    assert "quality tag score +15: Dolby Vision" in ranked[0].reasons
    assert "quality tag score +8: Dolby Atmos" in ranked[0].reasons
    assert ranked[0].score == 92


def test_rank_releases_lets_tv_and_anime_use_the_same_quality_tag_scores() -> None:
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
        [_release(title="Frieren 2023 S01 1080p WEB-DL HEVC FLAC", seeders=80, leechers=4)],
        _intent_config(default_resolution="1080p"),
        _search_config(quality_tag_scores={"webdl": 10, "hevc": 6, "flac": 4}),
    )

    assert "quality tag score +10: WEB-DL" in ranked[0].reasons
    assert "quality tag score +6: HEVC / H.265" in ranked[0].reasons
    assert "quality tag score +4: FLAC" in ranked[0].reasons
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
        _search_config(quality_tag_scores={"remux": 20}),
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
        _search_config(quality_tag_scores={"remux": 20}),
    )

    assert "episode missing" in ranked[0].risks


def test_rank_releases_does_not_match_episode_or_season_prefixes() -> None:
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
        [_release(title="Severance 2025 S020E030 2160p WEB-DL")],
        _intent_config(default_resolution="2160p", series_search_mode="episode"),
        _search_config(),
    )

    assert "season missing" in ranked[0].risks
    assert "episode missing" in ranked[0].risks
