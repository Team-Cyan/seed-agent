from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from seed_agent.config import CategoryPolicyConfig, CleanupConfig
from seed_agent.models import ManagedTorrent
from seed_agent.policies.category_policy import PoolUsage


def _cleanup() -> CleanupConfig:
    return CleanupConfig(
        cold_after_days=7,
        min_upload_delta_gb=1,
        protect_hr=True,
        protect_manual=True,
        protect_media_library=True,
        pause_before_delete_hours=24,
        delete_after_no_upload_hours=2,
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
        "save_path": "/mnt/data",
        "metadata": {},
    }
    data.update(overrides)
    return ManagedTorrent(**data)


def _incomplete_torrent(**overrides: object) -> ManagedTorrent:
    data: dict[str, object] = {
        "state": "downloading",
        "uploaded_bytes": 2 * 1024**3,
        "downloaded_bytes": 5 * 1024**3,
        "completed_at": None,
        "metadata": {
            "amount_left_bytes": 5 * 1024**3,
            "recent_upload_gb": 0.2,
        },
    }
    data.update(overrides)
    return _torrent(**data)


def _policy(**overrides: object) -> CategoryPolicyConfig:
    data: dict[str, object] = {
        "name": "seed",
        "mode": "mutable",
        "budget_pool": "downloads",
        "delete_enabled": True,
        "over_budget_behavior": "add_paused",
        "tags": ["seed-agent", "seed"],
    }
    data.update(overrides)
    return CategoryPolicyConfig(**data)


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
        _policy(),
        execute=False,
    )

    assert downloader.calls == []
    assert len(decisions) == 1
    assert decisions[0].action == "qb.cleanup.keep"
    assert decisions[0].execute is False


@pytest.mark.asyncio
async def test_execute_prune_pauses_cold_incomplete_managed_torrent() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [_incomplete_torrent()],
        downloader,
        _cleanup(),
        _policy(),
        execute=True,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=11 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
    )

    assert downloader.calls == [("pause", "abcd1234", None)]
    assert len(decisions) == 1
    assert decisions[0].action == "qb.cleanup.pause"
    assert decisions[0].execute is True


@pytest.mark.asyncio
async def test_prune_decision_records_policy_and_pool_usage() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [_torrent()],
        downloader,
        _cleanup(),
        _policy(),
        execute=False,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=11 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
    )

    state = decisions[0].new_state
    assert state["category"] == "seed"
    assert state["category_mode"] == "mutable"
    assert state["budget_pool"] == "downloads"
    assert state["delete_enabled"] is True
    assert state["budget_pool_limit_tib"] == 10.0
    assert state["estimated_pool_usage_tib"] == 11.0
    assert state["over_budget_before_action"] is True


@pytest.mark.asyncio
async def test_prune_orders_mutable_torrents_by_eviction_rank() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
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
                state="downloading",
                uploaded_bytes=0,
                downloaded_bytes=5 * 1024**3,
                completed_at=None,
                metadata={
                    "amount_left_bytes": 5 * 1024**3,
                    "no_upload_since_at": datetime.now(UTC) - timedelta(hours=30),
                },
            ),
        ],
        downloader,
        _cleanup(),
        _policy(),
        execute=True,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=11 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
    )

    assert downloader.calls == [("delete", "drop", True)]
    assert [decision.target_id for decision in decisions] == ["drop", "keep"]


@pytest.mark.asyncio
async def test_execute_never_deletes_unmanaged_torrent() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [
            _torrent(
                category="movie",
                tags={"seed-agent", "movie"},
                state="paused",
                metadata={"paused_at": datetime.now(UTC) - timedelta(days=10)},
            )
        ],
        downloader,
        _cleanup(),
        _policy(name="movie", mode="add_only", budget_pool="media", delete_enabled=False),
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
            [_incomplete_torrent(hash="first"), _incomplete_torrent(hash="second")],
            downloader,
            _cleanup(),
            _policy(),
            execute=True,
            pool_usage=PoolUsage(
                pool_name="downloads",
                size_bytes=11 * 1024**4,
                max_size_bytes=10 * 1024**4,
            ),
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


@pytest.mark.asyncio
async def test_prune_keeps_cold_torrent_when_pool_is_not_over_budget() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [_incomplete_torrent()],
        downloader,
        _cleanup(),
        _policy(),
        execute=True,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=8 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
    )

    assert downloader.calls == []
    assert decisions[0].action == "qb.cleanup.keep"
    assert "space reclamation not required" in decisions[0].reason


@pytest.mark.asyncio
async def test_force_space_reclamation_pauses_cold_torrent_when_pool_is_not_over_budget() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()

    decisions = await prune_cold_torrents(
        [_incomplete_torrent()],
        downloader,
        _cleanup(),
        _policy(),
        execute=True,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=8 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
        force_space_reclamation=True,
    )

    assert downloader.calls == [("pause", "abcd1234", None)]
    assert decisions[0].action == "qb.cleanup.pause"
    assert decisions[0].new_state["force_space_reclamation"] is True
    assert decisions[0].new_state["space_reclamation_required"] is True


@pytest.mark.asyncio
async def test_completed_low_upload_requires_reclamation_keeps_under_budget_seed() -> None:
    from seed_agent.actions.qb import prune_cold_torrents

    downloader = DummyDownloader()
    now = datetime.now(UTC)

    decisions = await prune_cold_torrents(
        [
            _torrent(
                state="stalledUP",
                uploaded_bytes=int(0.2 * 1024**3),
                downloaded_bytes=50 * 1024**3,
                metadata={
                    "amount_left_bytes": 0,
                    "no_upload_since_at": now - timedelta(hours=80),
                },
            )
        ],
        downloader,
        CleanupConfig(
            **{
                **_cleanup().model_dump(),
                "delete_completed_low_upload_after_hours": 72,
                "completed_low_upload_min_ratio": 0.02,
                "completed_low_upload_min_gb": 1,
            }
        ),
        _policy(),
        execute=True,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=8 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
        completed_low_upload_requires_reclamation=True,
    )

    assert downloader.calls == []
    assert decisions[0].action == "qb.cleanup.keep"
    assert "space reclamation not required" in decisions[0].reason
    assert decisions[0].new_state["completed_low_upload_requires_reclamation"] is True
