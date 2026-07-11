from __future__ import annotations

from datetime import UTC, datetime, timedelta

from seed_agent.models import ManagedTorrent
from seed_agent.policies.eviction import rank_eviction_candidates
from seed_agent.policies.quality import (
    torrent_eviction_evidence,
    torrent_retention_quality_score,
)


def _torrent(**overrides: object) -> ManagedTorrent:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "hash": "abcd1234",
        "name": "Demo Torrent",
        "category": "seed",
        "tags": {"seed-agent", "seed"},
        "state": "uploading",
        "size_bytes": 10 * 1024**3,
        "uploaded_bytes": 10 * 1024**3,
        "downloaded_bytes": 10 * 1024**3,
        "added_at": now - timedelta(days=10),
        "completed_at": now - timedelta(days=10),
        "last_activity_at": now - timedelta(days=10),
        "save_path": "/downloads/seed",
        "metadata": {},
    }
    data.update(overrides)
    return ManagedTorrent(**data)


def test_rank_eviction_candidates_prefers_low_upload_density_large_cold_torrents() -> None:
    ranked = rank_eviction_candidates(
        [
            _torrent(
                hash="keep",
                size_bytes=20 * 1024**3,
                uploaded_bytes=200 * 1024**3,
                metadata={"recent_upload_gb": 40},
            ),
            _torrent(
                hash="drop",
                size_bytes=400 * 1024**3,
                uploaded_bytes=2 * 1024**3,
                metadata={"recent_upload_gb": 0.2},
            ),
        ]
    )

    assert ranked[0].hash == "drop"


def test_torrent_retention_quality_uses_recent_upload_density_over_total_size() -> None:
    active_small = _torrent(
        hash="active-small",
        size_bytes=20 * 1024**3,
        uploaded_bytes=20 * 1024**3,
        metadata={"recent_upload_1h_gb": 2.0, "recent_upload_24h_gb": 8.0},
    )
    idle_large = _torrent(
        hash="idle-large",
        size_bytes=400 * 1024**3,
        uploaded_bytes=200 * 1024**3,
        metadata={"recent_upload_1h_gb": 0.0, "recent_upload_24h_gb": 0.1},
    )

    assert torrent_retention_quality_score(active_small) > torrent_retention_quality_score(
        idle_large
    )


def test_eviction_evidence_exposes_stable_score_components() -> None:
    torrent = _torrent(
        metadata={
            "recent_upload_1h_gb": 1.0,
            "recent_upload_24h_gb": 5.0,
            "amount_left_bytes": 2 * 1024**3,
        }
    )

    evidence = torrent_eviction_evidence(torrent)

    assert evidence["evidence_sufficient"] is True
    assert evidence["evidence_points"] == 2
    assert evidence["amount_left_gib"] == 2.0
    assert isinstance(evidence["retention_quality_score"], float)
    assert isinstance(evidence["eviction_pressure_score"], float)
