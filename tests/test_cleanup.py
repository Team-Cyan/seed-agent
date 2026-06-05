from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from seed_agent.config import CleanupConfig
from seed_agent.models import ManagedTorrent


def _cleanup(**overrides: object) -> CleanupConfig:
    data: dict[str, object] = {
        "cold_after_days": 7,
        "min_upload_delta_gb": 1,
        "protect_hr": True,
        "protect_manual": True,
        "protect_media_library": True,
        "pause_before_delete_hours": 24,
    }
    data.update(overrides)
    return CleanupConfig(**data)


def _torrent(**overrides: object) -> ManagedTorrent:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "hash": "abcd1234",
        "name": "Demo Torrent",
        "category": "pt-auto",
        "tags": {"seed-agent", "pt-auto"},
        "state": "uploading",
        "size_bytes": 10 * 1024**3,
        "uploaded_bytes": 10 * 1024**3,
        "downloaded_bytes": 10 * 1024**3,
        "added_at": now - timedelta(days=10),
        "completed_at": now - timedelta(days=10),
        "last_activity_at": now - timedelta(days=10),
        "save_path": "/mnt/data",
        "metadata": {},
    }
    data.update(overrides)
    return ManagedTorrent(**data)


def test_protects_unmanaged_torrent() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(category="other", tags={"unrelated"}),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "protect"
    assert "unmanaged" in decision.reason


def test_tag_alone_does_not_grant_cleanup_management() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(category="movie", tags={"seed-agent", "seed"}),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "protect"
    assert "unmanaged" in decision.reason


@pytest.mark.parametrize(
    ("metadata",),
    [
        ({"recent_upload_gb": 0.25},),
        ({"upload_delta_gb": 0.5},),
    ],
)
def test_cold_managed_torrent_with_insufficient_recent_upload_enters_observation(
    metadata: dict[str, object],
) -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(metadata=metadata),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


@pytest.mark.parametrize(
    ("metadata",),
    [
        ({"recent_upload_gb": 1.25},),
        ({"upload_delta_gb": 1.5},),
    ],
)
def test_cold_managed_torrent_with_meaningful_recent_upload_is_kept(
    metadata: dict[str, object],
) -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(metadata=metadata),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_currently_uploading_torrent_is_kept_even_with_stale_no_upload_marker() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(
            state="uploading",
            metadata={
                "upspeed_bps": 1024,
                "recent_upload_gb": 0,
                "no_upload_since_at": (
                    datetime.now(UTC) - timedelta(hours=12)
                ).isoformat(),
            },
        ),
        _cleanup(delete_after_no_upload_hours=2),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "currently uploading" in decision.reason


def test_completed_seed_is_kept_when_free_window_cannot_survive_next_check() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            last_activity_at=now - timedelta(minutes=10),
            metadata={
                "free_window_expires_at": (now + timedelta(minutes=20)).isoformat(),
                "free_window_min_remaining_minutes": 30,
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_managed_torrent_keeps_when_free_window_survives_next_check() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            last_activity_at=now - timedelta(minutes=10),
            metadata={
                "free_window_expires_at": (now + timedelta(minutes=90)).isoformat(),
                "free_window_min_remaining_minutes": 30,
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


@pytest.mark.parametrize(
    ("metadata", "cleanup_overrides", "reason_fragment"),
    [
        ({"hr": True}, {"protect_hr": True}, "hr"),
        ({"manual": True}, {"protect_manual": True}, "manual"),
        ({"media_library": True}, {"protect_media_library": True}, "media library"),
    ],
)
def test_protects_hr_manual_and_media_library_when_configured(
    metadata: dict[str, object],
    cleanup_overrides: dict[str, object],
    reason_fragment: str,
) -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(metadata=metadata),
        _cleanup(**cleanup_overrides),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "protect"
    assert reason_fragment in decision.reason.lower()


def test_keeps_stopped_completed_seed_after_pause_delay() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="stopped",
            metadata={"paused_at": now - timedelta(hours=30)},
            last_activity_at=now - timedelta(days=10),
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        space_reclamation_required=True,
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_keeps_stopped_managed_torrent_when_space_reclamation_is_not_required() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="stopped",
            metadata={"paused_at": now - timedelta(hours=30)},
            last_activity_at=now - timedelta(days=10),
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_keeps_active_seed_while_no_upload_observation_window_is_young() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="stalledUP",
            last_activity_at=now,
            metadata={
                "amount_left_bytes": 0,
                "recent_upload_gb": 0.0,
                "no_upload_since_at": now - timedelta(hours=1),
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_keeps_active_seed_after_no_upload_observation_window() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="stalledUP",
            last_activity_at=now,
            metadata={
                "amount_left_bytes": 0,
                "recent_upload_gb": 0.0,
                "no_upload_since_at": now - timedelta(hours=3),
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        space_reclamation_required=True,
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_keeps_cold_completed_seed_when_space_reclamation_is_required() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="stalledUP",
            last_activity_at=now - timedelta(days=10),
            metadata={
                "amount_left_bytes": 0,
                "recent_upload_gb": 0.0,
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        space_reclamation_required=True,
    )

    assert decision.action == "keep"
    assert "completed seed" in decision.reason


def test_deletes_incomplete_zero_upload_torrent_after_observation_window() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="downloading",
            uploaded_bytes=0,
            downloaded_bytes=5 * 1024**3,
            last_activity_at=now,
            metadata={
                "amount_left_bytes": 5 * 1024**3,
                "no_upload_since_at": now - timedelta(hours=3),
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        space_reclamation_required=True,
    )

    assert decision.action == "delete"
    assert "zero total upload" in decision.reason


def test_keeps_zero_upload_torrent_when_space_reclamation_is_not_required() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="downloading",
            uploaded_bytes=0,
            downloaded_bytes=5 * 1024**3,
            last_activity_at=now,
            metadata={
                "amount_left_bytes": 5 * 1024**3,
                "no_upload_since_at": now - timedelta(hours=3),
            },
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "keep"
    assert "space reclamation not required" in decision.reason
