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


def test_pauses_cold_managed_torrent() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    decision = classify_cleanup(
        _torrent(),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "pause"
    assert "cold" in decision.reason


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


def test_deletes_paused_managed_torrent_only_after_pause_delay() -> None:
    from seed_agent.policies.cleanup import classify_cleanup

    now = datetime.now(UTC)
    decision = classify_cleanup(
        _torrent(
            state="paused",
            metadata={"paused_at": now - timedelta(hours=30)},
            last_activity_at=now - timedelta(days=10),
        ),
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
    )

    assert decision.action == "delete"
    assert "paused" in decision.reason
