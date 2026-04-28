from __future__ import annotations

from seed_agent.config import DiscoveryConfig, ScoringConfig
from seed_agent.models import Discount, TorrentCandidate
from seed_agent.policies.scoring import score_candidate


def make_candidate(**overrides: object) -> TorrentCandidate:
    data: dict[str, object] = {
        "site": "demo",
        "title": "Free Hot Torrent",
        "source_url": "https://tracker.example/details.php?id=1",
        "download_url": "https://tracker.example/download.php?id=1",
        "size_bytes": 10 * 1024 * 1024 * 1024,
        "seeders": 20,
        "leechers": 30,
        "discount": "free",
        "left_time_minutes": 240,
        "hr": False,
    }
    data.update(overrides)
    return TorrentCandidate(**data)


def discovery(**overrides: object) -> DiscoveryConfig:
    data: dict[str, object] = {
        "discounts": ["free", "2xfree"],
        "min_left_time_minutes": 120,
        "min_leechers": 8,
        "max_seeders": 80,
        "allow_hr": False,
    }
    data.update(overrides)
    return DiscoveryConfig(**data)


def scoring(**overrides: object) -> ScoringConfig:
    data: dict[str, object] = {
        "min_score_to_enqueue": 70,
        "weights": {
            "discount": 30,
            "leechers": 25,
            "seeders": 15,
            "left_time": 15,
            "size": 10,
            "site_history": 5,
        },
    }
    data.update(overrides)
    return ScoringConfig(**data)


def test_high_confidence_free_candidate_is_accepted() -> None:
    result = score_candidate(make_candidate(), discovery(), scoring())

    assert result.accepted is True
    assert result.score >= 70
    assert "discount free accepted" in result.reasons
    assert any(reason.startswith("score ") for reason in result.reasons)


def test_hr_candidate_is_rejected_when_config_disallows_it() -> None:
    result = score_candidate(make_candidate(hr=True), discovery(), scoring())

    assert result.accepted is False
    assert result.score == 0
    assert "hr protected by config" in result.reasons


def test_low_leecher_candidate_is_rejected() -> None:
    result = score_candidate(make_candidate(leechers=7), discovery(), scoring())

    assert result.accepted is False
    assert result.score == 0
    assert "leechers 7 < min 8" in result.reasons


def test_leecher_minimum_gets_full_contribution() -> None:
    leecher_only = scoring(
        weights={
            "discount": 0,
            "leechers": 100,
            "seeders": 0,
            "left_time": 0,
            "size": 0,
            "site_history": 0,
        }
    )
    at_min = score_candidate(make_candidate(leechers=8), discovery(), leecher_only)
    above_min = score_candidate(make_candidate(leechers=16), discovery(), leecher_only)

    assert at_min.score == 100
    assert above_min.score == 100
    assert "leechers 8 >= min 8" in at_min.reasons


def test_zero_min_leechers_does_not_drop_leecher_score_to_zero() -> None:
    result = score_candidate(
        make_candidate(leechers=0),
        discovery(min_leechers=0),
        scoring(
            min_score_to_enqueue=1,
            weights={
                "discount": 0,
                "leechers": 100,
                "seeders": 0,
                "left_time": 0,
                "size": 0,
                "site_history": 0,
            },
        ),
    )

    assert result.accepted is True
    assert result.score == 100
    assert "leechers 0 >= min 0" in result.reasons


def test_seeder_taper_reduces_score_for_very_high_seeder_count() -> None:
    low_seeders = score_candidate(make_candidate(seeders=20), discovery(), scoring())
    high_seeders = score_candidate(make_candidate(seeders=160), discovery(), scoring())

    assert low_seeders.score > high_seeders.score
    assert "seeders 160 >= 2x max 80" in high_seeders.reasons
    assert "seeders 20 <= max 80" in low_seeders.reasons


def test_site_history_score_is_clamped_between_zero_and_one() -> None:
    low_history = score_candidate(
        make_candidate(metadata={"site_history_score": -4.0}),
        discovery(),
        scoring(),
    )
    high_history = score_candidate(
        make_candidate(metadata={"site_history_score": 3.5}),
        discovery(),
        scoring(),
    )

    assert high_history.score > low_history.score
    assert high_history.score - low_history.score == 5
    assert "site_history 1.0" in high_history.reasons
    assert "site_history 0.0" in low_history.reasons


def test_size_outside_preferred_range_reduces_size_contribution() -> None:
    preferred = score_candidate(
        make_candidate(size_bytes=10 * 1024 * 1024 * 1024),
        discovery(),
        scoring(),
    )
    small = score_candidate(
        make_candidate(size_bytes=1 * 1024 * 1024 * 1024),
        discovery(),
        scoring(),
    )
    large = score_candidate(
        make_candidate(size_bytes=100 * 1024 * 1024 * 1024),
        discovery(),
        scoring(),
    )

    assert preferred.score > large.score > small.score
    assert "size 10.0 GiB preferred" in preferred.reasons
    assert "size 1.0 GiB below preferred range" in small.reasons
    assert "size 100.0 GiB above preferred range" in large.reasons


def test_normal_discount_not_in_config_is_rejected() -> None:
    result = score_candidate(
        make_candidate(discount=Discount.NORMAL, metadata={"discount_raw": "mystery"}),
        discovery(discounts=["free"]),
        scoring(),
    )

    assert result.accepted is False
    assert result.score == 0
    assert "discount normal not accepted" in result.reasons


def test_missing_left_time_has_clear_reason() -> None:
    result = score_candidate(
        make_candidate(left_time_minutes=None),
        discovery(),
        scoring(),
    )

    assert result.accepted is False
    assert result.score == 0
    assert "left_time missing" in result.reasons


def test_mteam_api_missing_left_time_does_not_hard_reject() -> None:
    result = score_candidate(
        make_candidate(
            site="mt",
            left_time_minutes=None,
            metadata={
                "mteam_discovery_mode": "api",
                "left_time_source": "mteam_api_missing",
            },
        ),
        discovery(),
        scoring(),
    )

    assert result.accepted is True
    assert result.score >= 70
    assert "left_time unavailable for mteam api discovery" in result.reasons
