from __future__ import annotations

from datetime import UTC, datetime, timedelta

from seed_agent.models import ManagedTorrent
from seed_agent.policies.eviction import rank_eviction_candidates


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
