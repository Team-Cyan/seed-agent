from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from seed_agent.config import CleanupConfig
from seed_agent.models import ManagedTorrent


def _cleanup() -> CleanupConfig:
    return CleanupConfig(
        cold_after_days=7,
        min_upload_delta_gb=1,
        protect_hr=True,
        protect_manual=True,
        protect_media_library=True,
        pause_before_delete_hours=24,
    )


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


class DummyDownloader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    async def pause(self, hash: str) -> None:
        self.calls.append(("pause", hash, None))

    async def delete(self, hash: str, delete_files: bool) -> None:
        self.calls.append(("delete", hash, delete_files))


class FailingSecondDownloader(DummyDownloader):
    async def pause(self, hash: str) -> None:
        await super().pause(hash)
        if len(self.calls) == 2:
            raise RuntimeError("pause failed")


@pytest.mark.asyncio
async def test_dry_run_prune_does_not_call_downloader() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [_torrent()],
        downloader,
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        execute=False,
    )

    assert downloader.calls == []
    assert len(decisions) == 1
    assert decisions[0].action == "qb.cleanup.pause"
    assert decisions[0].execute is False


@pytest.mark.asyncio
async def test_execute_prune_pauses_cold_managed_torrent() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [_torrent()],
        downloader,
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        execute=True,
    )

    assert downloader.calls == [("pause", "abcd1234", None)]
    assert len(decisions) == 1
    assert decisions[0].action == "qb.cleanup.pause"
    assert decisions[0].execute is True


@pytest.mark.asyncio
async def test_execute_never_deletes_unmanaged_torrent() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [
            _torrent(
                category="other",
                tags={"unmanaged"},
                state="paused",
                metadata={"paused_at": datetime.now(UTC) - timedelta(days=10)},
            )
        ],
        downloader,
        _cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent", "pt-auto"},
        execute=True,
    )

    assert downloader.calls == []
    assert len(decisions) == 1
    assert decisions[0].action == "qb.cleanup.protect"


@pytest.mark.asyncio
async def test_execute_batch_failure_carries_prior_cleanup_decisions() -> None:
    from seed_agent.actions.qb import MutationBatchError, prune_cold_torrents

    downloader = FailingSecondDownloader()

    with pytest.raises(MutationBatchError) as raised:
        await prune_cold_torrents(
            [_torrent(hash="first"), _torrent(hash="second")],
            downloader,
            _cleanup(),
            managed_category="pt-auto",
            managed_tags={"seed-agent", "pt-auto"},
            execute=True,
        )

    decisions = raised.value.decisions
    assert downloader.calls == [("pause", "first", None), ("pause", "second", None)]
    assert [decision.action for decision in decisions] == [
        "qb.cleanup.pause",
        "qb.cleanup.pause.failed",
    ]
    assert decisions[0].target_id == "first"
    assert decisions[1].target_id == "second"
    assert "pause failed" in decisions[1].reason
