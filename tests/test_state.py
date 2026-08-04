import json
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest

from seed_agent.actions.intent import add_intent
from seed_agent.models import LifecycleState, ManagedTorrent
from seed_agent.state import StateStore


def test_state_store_forces_private_database_lock_and_wal_permissions(tmp_path: Path) -> None:
    existing_path = tmp_path / "existing" / "state.db"
    existing_path.parent.mkdir()
    lock_path = Path(f"{existing_path}.access.lock")
    lock_path.touch(mode=0o644)
    with sqlite3.connect(existing_path) as seed_conn:
        seed_conn.execute("PRAGMA journal_mode=WAL")
        seed_conn.execute("CREATE TABLE permission_probe (value INTEGER)")
        seed_conn.execute("INSERT INTO permission_probe VALUES (1)")
        seed_conn.commit()
        wal_path = Path(f"{existing_path}-wal")
        shm_path = Path(f"{existing_path}-shm")
        journal_path = Path(f"{existing_path}-journal")
        journal_path.touch(mode=0o644)
        assert wal_path.is_file()
        assert shm_path.is_file()
        for path in (existing_path, lock_path, wal_path, shm_path, journal_path):
            os.chmod(path, 0o644)

        store = StateStore(existing_path)

        for path in (existing_path, lock_path, wal_path, shm_path, journal_path):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

        with store._connect():  # noqa: SLF001 - verify modes before every connection
            pass
        assert stat.S_IMODE(wal_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(shm_path.stat().st_mode) == 0o600

    fresh_path = tmp_path / "fresh" / "state.db"
    StateStore(fresh_path)
    assert stat.S_IMODE(fresh_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(f"{fresh_path}.access.lock").stat().st_mode) == 0o600


def test_state_store_upserts_candidate_and_updates_existing_row(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.sqlite3"
    store = StateStore(path)

    store.upsert_candidate(
        stable_id="demo:https://tracker.example/details.php?id=42",
        title="Demo Torrent",
        site="demo",
        state=LifecycleState.SCORED,
        score=87,
        torrent_hash=None,
    )
    first = store.get_candidate("demo:https://tracker.example/details.php?id=42")

    assert first is not None
    first_seen_at = first["first_seen_at"]
    updated_at = first["updated_at"]
    assert first["state"] == LifecycleState.SCORED.value
    assert first["torrent_hash"] is None

    store.upsert_candidate(
        stable_id="demo:https://tracker.example/details.php?id=42",
        title="Demo Torrent",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=91,
        torrent_hash="abc123",
    )
    second = store.get_candidate("demo:https://tracker.example/details.php?id=42")

    assert second is not None
    assert second["state"] == LifecycleState.ENQUEUED.value
    assert second["torrent_hash"] == "abc123"
    assert second["score"] == 91
    assert second["first_seen_at"] == first_seen_at
    assert second["updated_at"] >= updated_at
    assert second["updated_at"] >= second["first_seen_at"]


def test_state_store_lists_candidates_by_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:one",
        title="One",
        site="demo",
        state=LifecycleState.SCORED,
        score=10,
        torrent_hash=None,
    )
    store.upsert_candidate(
        stable_id="demo:two",
        title="Two",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=20,
        torrent_hash="deadbeef",
    )

    scored = store.list_by_state(LifecycleState.SCORED)
    enqueued = store.list_by_state(LifecycleState.ENQUEUED)

    assert [row["stable_id"] for row in scored] == ["demo:one"]
    assert [row["stable_id"] for row in enqueued] == ["demo:two"]


def test_state_store_preserves_existing_score_and_hash_when_incoming_values_are_missing(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:one",
        title="One",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=91,
        torrent_hash="deadbeef",
    )

    store.upsert_candidate(
        stable_id="demo:one",
        title="One",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=None,
        torrent_hash=None,
    )
    row = store.get_candidate("demo:one")

    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value
    assert row["score"] == 91
    assert row["torrent_hash"] == "deadbeef"


def test_candidate_state_cannot_regress_during_concurrent_upserts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import state as state_module

    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:one",
        title="One",
        site="demo",
        state=LifecycleState.DISCOVERED,
        score=None,
        torrent_hash=None,
    )
    entered = Event()
    release = Event()
    original = state_module._monotonic_values

    def controlled(current, incoming_state, incoming_score, incoming_torrent_hash):
        if incoming_state == LifecycleState.ENQUEUED:
            entered.set()
            assert release.wait(timeout=5)
        return original(current, incoming_state, incoming_score, incoming_torrent_hash)

    monkeypatch.setattr(state_module, "_monotonic_values", controlled)
    enqueued = Thread(
        target=store.upsert_candidate,
        kwargs={
            "stable_id": "demo:one",
            "title": "One",
            "site": "demo",
            "state": LifecycleState.ENQUEUED,
            "score": 90,
            "torrent_hash": "hash-one",
        },
    )
    scored = Thread(
        target=store.upsert_candidate,
        kwargs={
            "stable_id": "demo:one",
            "title": "One",
            "site": "demo",
            "state": LifecycleState.SCORED,
            "score": 80,
            "torrent_hash": None,
        },
    )
    enqueued.start()
    assert entered.wait(timeout=5)
    scored.start()
    release.set()
    enqueued.join(timeout=5)
    scored.join(timeout=5)

    row = store.get_candidate("demo:one")
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value
    assert row["torrent_hash"] == "hash-one"


def test_state_store_persists_candidate_free_window_expiry(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.upsert_candidate(
        stable_id="demo:one",
        title="One",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=91,
        torrent_hash="deadbeef",
        free_window_expires_at="2026-05-08T12:00:00+00:00",
    )
    row = store.get_candidate("demo:one")

    assert row is not None
    assert row["free_window_expires_at"] == "2026-05-08T12:00:00+00:00"


def test_state_store_lists_and_updates_candidates_by_torrent_hash(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:one",
        title="One",
        site="demo",
        state=LifecycleState.SCORED,
        score=10,
        torrent_hash="deadbeef",
    )

    rows = store.list_by_torrent_hash("deadbeef")
    assert [row["stable_id"] for row in rows] == ["demo:one"]

    updated = store.update_by_torrent_hash("deadbeef", LifecycleState.PAUSED)
    row = store.get_candidate("demo:one")

    assert updated == 1
    assert row is not None
    assert row["state"] == LifecycleState.PAUSED.value


def test_state_store_persists_candidate_snapshot_fields(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.upsert_candidate(
        stable_id="demo:snapshot",
        title="Snapshot Torrent",
        site="demo",
        state=LifecycleState.SCORED,
        score=88,
        torrent_hash="hash123",
        size_bytes=12 * 1024**3,
        seeders=42,
        leechers=9,
        discount="free",
        left_time_minutes=180,
        score_reasons=["discount 30.0", "leechers 25.0"],
    )

    row = store.get_candidate("demo:snapshot")

    assert row is not None
    assert row["size_bytes"] == 12 * 1024**3
    assert row["seeders"] == 42
    assert row["leechers"] == 9
    assert row["discount"] == "free"
    assert row["left_time_minutes"] == 180
    assert row["score_reasons"] == ["discount 30.0", "leechers 25.0"]
    linked = store.list_by_torrent_hash("hash123")
    assert linked[0]["score_reasons"] == ["discount 30.0", "leechers 25.0"]


def test_state_store_preserves_immutable_enqueue_snapshot(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.record_candidate_enqueue_snapshot(
        stable_id="demo:snapshot",
        torrent_hash="hash-one",
        seeders=20,
        leechers=10,
        size_bytes=40 * 1024**3,
        published_at="2026-08-04T01:00:00+00:00",
        candidate_age_minutes=90,
        score=88,
        score_reasons=["enqueue preflight accepted"],
    )
    store.record_candidate_enqueue_snapshot(
        stable_id="demo:snapshot",
        torrent_hash="hash-two",
        seeders=200,
        leechers=1,
        size_bytes=50 * 1024**3,
        published_at=None,
        candidate_age_minutes=None,
        score=1,
        score_reasons=["later overwrite"],
    )

    snapshot = store.get_candidate_enqueue_snapshot("demo:snapshot")

    assert snapshot is not None
    assert snapshot["torrent_hash"] == "hash-one"
    assert snapshot["seeders"] == 20
    assert snapshot["leechers"] == 10
    assert snapshot["seed_leecher_ratio"] == 2.0
    assert snapshot["candidate_age_minutes"] == 90
    assert snapshot["score"] == 88
    assert snapshot["score_reasons"] == ["enqueue preflight accepted"]


def test_state_store_preserves_candidate_snapshot_when_unset(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.upsert_candidate(
        stable_id="demo:snapshot",
        title="Snapshot Torrent",
        site="demo",
        state=LifecycleState.SCORED,
        score=88,
        torrent_hash=None,
        size_bytes=12,
        seeders=4,
        leechers=2,
        discount="free",
        left_time_minutes=100,
        score_reasons=["initial"],
    )
    store.upsert_candidate(
        stable_id="demo:snapshot",
        title="Snapshot Torrent",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=88,
        torrent_hash="hash123",
    )

    row = store.get_candidate("demo:snapshot")

    assert row is not None
    assert row["size_bytes"] == 12
    assert row["seeders"] == 4
    assert row["leechers"] == 2
    assert row["discount"] == "free"
    assert row["left_time_minutes"] == 100
    assert row["score_reasons"] == ["initial"]


def test_state_store_migrates_candidate_snapshot_columns(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    store = StateStore(path)
    with store._connect() as conn:  # type: ignore[attr-defined]
        conn.execute("DROP TABLE candidates")
        conn.execute(
            """
            CREATE TABLE candidates (
              stable_id TEXT PRIMARY KEY,
              site TEXT NOT NULL,
              title TEXT NOT NULL,
              state TEXT NOT NULL,
              score INTEGER,
              torrent_hash TEXT,
              free_window_expires_at TEXT,
              first_seen_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )

    migrated = StateStore(path)
    migrated.upsert_candidate(
        stable_id="demo:migrated",
        title="Migrated Torrent",
        site="demo",
        state=LifecycleState.SCORED,
        score=70,
        torrent_hash=None,
        seeders=7,
        score_reasons=["migrated"],
    )

    row = migrated.get_candidate("demo:migrated")

    assert row is not None
    assert row["seeders"] == 7
    assert row["score_reasons"] == ["migrated"]


def test_state_store_prunes_stale_unqueued_candidates_only(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    old = datetime.now(UTC) - timedelta(days=45)
    store.upsert_candidate(
        stable_id="demo:old-scored",
        title="Old Scored",
        site="demo",
        state=LifecycleState.SCORED,
        score=10,
        torrent_hash=None,
    )
    store.upsert_candidate(
        stable_id="demo:old-enqueued",
        title="Old Enqueued",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=90,
        torrent_hash="deadbeef",
    )
    with store._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE candidates SET updated_at = ?, first_seen_at = ?",
            (old.isoformat(), old.isoformat()),
        )

    deleted = store.prune_stale_candidates(retention_days=30)

    assert deleted == 1
    assert store.get_candidate("demo:old-scored") is None
    assert store.get_candidate("demo:old-enqueued") is not None


def test_state_store_creates_parent_directory_for_nested_path(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "state.sqlite3"

    StateStore(path)

    assert path.parent.exists()


def test_state_store_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    store = StateStore(path)

    with store._connect() as conn:  # type: ignore[attr-defined]
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()

    assert journal_mode is not None
    assert journal_mode[0].lower() == "wal"
    assert busy_timeout is not None
    assert int(busy_timeout[0]) == 30_000


def test_state_store_applies_recent_upload_snapshot_and_clears_stale_pause(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.mark_torrent_paused("abcd1234", datetime(2026, 4, 1, tzinfo=UTC))
    store._upsert_torrent_runtime(  # type: ignore[attr-defined]
        "abcd1234",
        uploaded_bytes=10 * 1024**3,
        downloaded_bytes=5 * 1024**3,
        upspeed_bps=0,
        dlspeed_bps=0,
        seen_at=datetime(2026, 4, 1, tzinfo=UTC).isoformat(),
    )

    active = ManagedTorrent(
        hash="abcd1234",
        name="Demo Torrent",
        category="pt-auto",
        tags={"seed-agent"},
        state="uploading",
        size_bytes=10 * 1024**3,
        uploaded_bytes=13 * 1024**3,
        downloaded_bytes=5 * 1024**3,
        added_at=datetime(2026, 4, 1, tzinfo=UTC),
        last_activity_at=datetime(2026, 4, 2, tzinfo=UTC),
        metadata={"upspeed_bps": 1024},
    )

    enriched = store.apply_torrent_runtime([active])

    assert enriched[0].metadata["recent_upload_gb"] == 3.0
    assert "paused_at" not in enriched[0].metadata
    runtime = store.get_torrent_runtime("abcd1234")
    assert runtime is not None
    assert runtime["paused_at"] is None
    assert runtime["uploaded_bytes"] == 13 * 1024**3
    assert runtime["no_upload_since_at"] is None


def test_state_store_tracks_no_upload_observation_start(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    seen_at = datetime(2026, 4, 1, tzinfo=UTC)
    store._upsert_torrent_runtime(  # type: ignore[attr-defined]
        "abcd1234",
        uploaded_bytes=10 * 1024**3,
        downloaded_bytes=5 * 1024**3,
        upspeed_bps=0,
        dlspeed_bps=0,
        seen_at=seen_at.isoformat(),
    )

    idle = ManagedTorrent(
        hash="abcd1234",
        name="Demo Torrent",
        category="pt-auto",
        tags={"seed-agent"},
        state="stalledUP",
        size_bytes=10 * 1024**3,
        uploaded_bytes=10 * 1024**3,
        downloaded_bytes=10 * 1024**3,
        added_at=seen_at,
        last_activity_at=seen_at,
        metadata={"amount_left_bytes": 0},
    )

    enriched = store.apply_torrent_runtime([idle])

    assert enriched[0].metadata["recent_upload_gb"] == 0.0
    assert enriched[0].metadata["no_upload_since_at"] == seen_at
    runtime = store.get_torrent_runtime("abcd1234")
    assert runtime is not None
    assert runtime["no_upload_since_at"] == seen_at.isoformat()


def test_state_store_starts_zero_upload_observation_at_torrent_added_at(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    added_at = datetime(2026, 4, 1, tzinfo=UTC)
    torrent = ManagedTorrent(
        hash="zero-upload",
        name="Zero Upload",
        category="pt-auto",
        tags={"seed-agent"},
        state="downloading",
        size_bytes=10 * 1024**3,
        uploaded_bytes=0,
        downloaded_bytes=1 * 1024**3,
        added_at=added_at,
        last_activity_at=added_at + timedelta(hours=3),
        metadata={"amount_left_bytes": 9 * 1024**3},
    )

    enriched = store.apply_torrent_runtime([torrent])

    assert enriched[0].metadata["no_upload_since_at"] == added_at
    runtime = store.get_torrent_runtime("zero-upload")
    assert runtime is not None
    assert runtime["no_upload_since_at"] == added_at.isoformat()


def test_state_store_enriches_runtime_with_candidate_discount(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        "mteam:https://kp.m-team.cc/detail/1",
        "Paid Torrent",
        "mteam",
        LifecycleState.ENQUEUED,
        score=88,
        torrent_hash="paid-hash",
        discount="normal",
    )
    torrent = ManagedTorrent(
        hash="paid-hash",
        name="Paid Torrent",
        category="pt-auto",
        tags={"seed-agent"},
        state="downloading",
        size_bytes=10 * 1024**3,
        uploaded_bytes=0,
        downloaded_bytes=1 * 1024**3,
        added_at=datetime(2026, 4, 1, tzinfo=UTC),
        last_activity_at=datetime(2026, 4, 1, tzinfo=UTC),
        metadata={"amount_left_bytes": 9 * 1024**3},
    )

    enriched = store.apply_torrent_runtime([torrent])

    assert enriched[0].metadata["discount"] == "normal"
    assert enriched[0].metadata["discount_source"] == "candidate_state"


def test_state_store_stamps_first_seen_pause_timestamp_for_paused_torrent(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    paused = ManagedTorrent(
        hash="paused-first-seen",
        name="Paused Torrent",
        category="pt-auto",
        tags={"seed-agent"},
        state="pausedUP",
        size_bytes=10 * 1024**3,
        uploaded_bytes=5 * 1024**3,
        downloaded_bytes=5 * 1024**3,
        added_at=datetime(2026, 4, 1, tzinfo=UTC),
        last_activity_at=datetime(2026, 4, 1, tzinfo=UTC),
        metadata={},
    )

    enriched = store.apply_torrent_runtime([paused])

    paused_at = enriched[0].metadata.get("paused_at")
    assert isinstance(paused_at, datetime)
    runtime = store.get_torrent_runtime("paused-first-seen")
    assert runtime is not None
    assert runtime["paused_at"] is not None


def test_state_store_reconciles_missing_live_torrents(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:gone",
        title="Gone Torrent",
        site="demo",
        state=LifecycleState.SEEDING,
        score=90,
        torrent_hash="gone-hash",
    )
    store.upsert_candidate(
        stable_id="demo:present",
        title="Present Torrent",
        site="demo",
        state=LifecycleState.SEEDING,
        score=80,
        torrent_hash="present-hash",
    )
    store.upsert_candidate(
        stable_id="demo:scored",
        title="Scored Torrent",
        site="demo",
        state=LifecycleState.SCORED,
        score=70,
        torrent_hash="scored-hash",
    )

    reconciled = store.reconcile_missing_torrents(
        {"present-hash"},
        reason="test live qB list did not include torrent",
        min_age_minutes=0,
    )

    assert reconciled == 1
    gone = store.get_candidate("demo:gone")
    present = store.get_candidate("demo:present")
    scored = store.get_candidate("demo:scored")
    assert gone is not None
    assert present is not None
    assert scored is not None
    assert gone["state"] == LifecycleState.DELETED.value
    assert present["state"] == LifecycleState.SEEDING.value
    assert scored["state"] == LifecycleState.SCORED.value
    runtime = store.get_torrent_runtime("gone-hash")
    assert runtime is not None
    assert runtime["missing_from_qb_at"] is not None
    assert runtime["missing_from_qb_reason"] == "test live qB list did not include torrent"


def test_state_store_does_not_reconcile_freshly_linked_torrents_as_missing(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:fresh",
        title="Fresh Torrent",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=90,
        torrent_hash="fresh-hash",
    )

    reconciled = store.reconcile_missing_torrents(set())

    assert reconciled == 0
    row = store.get_candidate("demo:fresh")
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value


def test_state_store_marks_deleted_torrent_present_when_seen_live(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:live-again",
        title="Live Again",
        site="demo",
        state=LifecycleState.DELETED,
        score=90,
        torrent_hash="live-hash",
    )

    updated = store.mark_present_by_torrent_hash("live-hash", LifecycleState.SEEDING)

    assert updated == 1
    row = store.get_candidate("demo:live-again")
    assert row is not None
    assert row["state"] == LifecycleState.SEEDING.value


def test_state_store_clears_missing_marker_when_torrent_reappears(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.upsert_candidate(
        stable_id="demo:gone",
        title="Gone Torrent",
        site="demo",
        state=LifecycleState.SEEDING,
        score=90,
        torrent_hash="gone-hash",
    )
    store.reconcile_missing_torrents({"other-hash"}, min_age_minutes=0)

    torrent = ManagedTorrent(
        hash="gone-hash",
        name="Gone Torrent",
        category="seed",
        tags={"seed-agent"},
        state="uploading",
        size_bytes=10 * 1024**3,
        uploaded_bytes=1 * 1024**3,
        downloaded_bytes=10 * 1024**3,
        added_at=datetime(2026, 4, 1, tzinfo=UTC),
        last_activity_at=datetime(2026, 4, 2, tzinfo=UTC),
        metadata={"upspeed_bps": 1024},
    )

    store.apply_torrent_runtime([torrent])

    runtime = store.get_torrent_runtime("gone-hash")
    assert runtime is not None
    assert runtime["missing_from_qb_at"] is None
    assert runtime["missing_from_qb_reason"] is None


def test_state_store_site_history_scores_fall_back_for_low_sample_site(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    for index in range(2):
        torrent_hash = f"low-sample-{index}"
        store.upsert_candidate(
            stable_id=f"demo:low-sample-{index}",
            title=f"Low Sample {index}",
            site="demo",
            state=LifecycleState.SEEDING,
            score=80,
            torrent_hash=torrent_hash,
        )
        store._upsert_torrent_runtime(  # type: ignore[attr-defined]
            torrent_hash,
            uploaded_bytes=5 * 1024**3,
            downloaded_bytes=10 * 1024**3,
            seen_at=datetime.now(UTC).isoformat(),
        )

    history = store.site_history_scores(min_samples=3)

    assert history["demo"]["samples"] == 2
    assert history["demo"]["applied"] is False
    assert history["demo"]["confidence"] == "low_sample"
    assert history["demo"]["score"] == 0.5


def test_state_store_site_history_scores_join_runtime_and_tracker_signals(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    now = datetime.now(UTC).isoformat()
    fixtures = [
        ("productive", LifecycleState.SEEDING, 4 * 1024**3, 10 * 1024**3, None, None),
        ("idle", LifecycleState.SEEDING, 0, 10 * 1024**3, now, None),
        ("missing", LifecycleState.DELETED, 0, 10 * 1024**3, None, now),
    ]
    for suffix, state, uploaded, downloaded, no_upload_since_at, missing_at in fixtures:
        torrent_hash = f"history-{suffix}"
        store.upsert_candidate(
            stable_id=f"demo:{suffix}",
            title=f"History {suffix}",
            site="demo",
            state=state,
            score=80,
            torrent_hash=torrent_hash,
        )
        store._upsert_torrent_runtime(  # type: ignore[attr-defined]
            torrent_hash,
            uploaded_bytes=uploaded,
            downloaded_bytes=downloaded,
            no_upload_since_at=no_upload_since_at,
            missing_from_qb_at=missing_at,
            seen_at=now,
        )
    store.record_tracker_api_event(
        site="demo",
        endpoint="torrent/search",
        event="response_error",
        rate_limited=True,
        created_at=datetime.now(UTC),
    )
    store.set_tracker_backoff(
        site="demo",
        endpoint="torrent/search",
        until=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        reason="rate limited",
    )
    store.set_tracker_backoff(
        site="demo",
        endpoint="torrent/detail",
        until=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        reason="expired rate limit",
    )

    history = store.site_history_scores(min_samples=3)

    assert history["demo"]["samples"] == 3
    assert history["demo"]["applied"] is True
    assert history["demo"]["confidence"] == "sufficient"
    assert history["demo"]["productive_count"] == 1
    assert history["demo"]["no_upload_count"] == 1
    assert history["demo"]["missing_count"] == 1
    assert history["demo"]["rate_limited_events"] == 1
    assert history["demo"]["active_backoffs"] == 1
    assert history["demo"]["throttle_penalty"] == 0.07
    assert history["demo"]["score"] == 0.41


def test_state_store_applies_runtime_with_batched_sqlite_access(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    torrents = [
        ManagedTorrent(
            hash=f"hash-{index}",
            name=f"Torrent {index}",
            category="seed",
            tags={"seed"},
            state="stalledUP",
            size_bytes=10 * 1024**3,
            uploaded_bytes=10 * 1024**3,
            downloaded_bytes=10 * 1024**3,
            added_at=datetime(2026, 4, 1, tzinfo=UTC),
            last_activity_at=datetime(2026, 4, 1, tzinfo=UTC),
            metadata={},
        )
        for index in range(8)
    ]

    connect_count = 0
    original_connect = store._connect  # type: ignore[attr-defined]

    def counted_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return original_connect(*args, **kwargs)

    store._connect = counted_connect  # type: ignore[method-assign]

    enriched = store.apply_torrent_runtime(torrents)

    assert len(enriched) == 8
    assert connect_count <= 4


def test_state_store_records_scheduler_run_and_events(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.start_scheduler_run(
        run_id="sched-test",
        command="schedule-run",
        config="config/config.yaml",
        execute=True,
        interval_minutes=60,
        prune_enabled=True,
        intent_enabled=True,
        intent_execute=False,
        backoff_active=False,
        backoff_until=None,
        summary={"phase": "startup"},
    )
    store.record_scheduler_event(
        run_id="sched-test",
        phase="pt_discovery",
        event="warning",
        message="rate limited",
        payload={"rate_limited": True},
    )
    store.finish_scheduler_run(
        run_id="sched-test",
        status="rate_limited",
        summary={
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "discovery_warnings": [{"rate_limited": True}],
            "intent": {"ingested": 1, "searched": 0, "ranked": 0},
            "schedule_backoff": {"active": True, "until": "2026-07-05T00:00:00+08:00"},
        },
    )

    runs = store.list_scheduler_runs()
    events = store.list_scheduler_run_events(run_id="sched-test")

    assert runs[0]["run_id"] == "sched-test"
    assert runs[0]["status"] == "rate_limited"
    assert runs[0]["backoff_active"] == 1
    assert runs[0]["warning_count"] == 1
    assert runs[0]["intent_ingested"] == 1
    assert events[0]["phase"] == "pt_discovery"
    assert events[0]["event"] == "warning"


def test_latest_completed_scheduler_run_finds_flag_beyond_first_hundred(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    started = datetime(2026, 7, 1, tzinfo=UTC)
    columns = (
        "run_id, started_at, finished_at, status, command, execute, "
        "prune_enabled, intent_enabled, intent_execute, backoff_active, "
        "warning_count, summary_json"
    )
    rows: list[tuple[object, ...]] = [
        (
            "matching-old-run",
            started.isoformat(),
            (started + timedelta(minutes=1)).isoformat(),
            "success",
            "schedule-run",
            0,
            0,
            1,
            0,
            0,
            0,
            json.dumps({"intent_refresh_enabled": True}),
        )
    ]
    for index in range(125):
        newer = started + timedelta(minutes=index + 2)
        rows.append(
            (
                f"newer-run-{index:03d}",
                newer.isoformat(),
                (newer + timedelta(seconds=30)).isoformat(),
                "success",
                "schedule-run",
                0,
                0,
                1,
                0,
                0,
                0,
                json.dumps({"intent_refresh_enabled": False}),
            )
        )
    rows.append(
        (
            "unfinished-matching-run",
            (started + timedelta(days=1)).isoformat(),
            None,
            "running",
            "schedule-run",
            0,
            0,
            1,
            0,
            0,
            0,
            json.dumps({"intent_refresh_enabled": True}),
        )
    )
    with store._connect() as conn:  # noqa: SLF001 - seed a large scheduler history
        conn.executemany(
            f"INSERT INTO scheduler_runs ({columns}) VALUES ({', '.join('?' for _ in range(12))})",
            rows,
        )

    match = store.latest_completed_scheduler_run(summary_flag="intent_refresh_enabled")

    assert match is not None
    assert match["run_id"] == "matching-old-run"
    with pytest.raises(ValueError, match="summary_flag"):
        store.latest_completed_scheduler_run(summary_flag="unsafe.flag")


def test_state_store_records_tracker_backoff_and_api_events(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/search",
        until="2026-07-05T00:00:00+08:00",
        reason="request too frequent",
        source="schedule",
        run_id="sched-test",
    )
    store.record_tracker_api_event(
        site="mteam",
        endpoint="torrent/search",
        event="response_error",
        run_id="sched-test",
        api_code="1",
        rate_limited=True,
        message="請求過於頻繁",
    )

    backoff = store.get_tracker_backoff("mteam", "torrent/search")
    events = store.list_tracker_api_events()

    assert backoff is not None
    assert backoff["active"] == 1
    assert backoff["run_id"] == "sched-test"
    assert events[0]["site"] == "mteam"
    assert events[0]["rate_limited"] == 1


def test_state_store_backoff_activity_compares_actual_instants_across_offsets(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/search",
        until="2026-07-29T16:00:00+08:00",
        reason="request too frequent",
    )

    assert store.has_active_tracker_backoff(
        now=datetime(2026, 7, 29, 7, 59, tzinfo=UTC),
    )
    assert not store.has_active_tracker_backoff(
        now=datetime(2026, 7, 29, 9, 0, tzinfo=UTC),
    )


def test_state_store_creates_metrics_covering_indexes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    with store._connect() as conn:  # noqa: SLF001 - inspect migrated schema
        scheduler_indexes = {
            str(row[1]) for row in conn.execute("PRAGMA index_list(scheduler_runs)")
        }
        tracker_indexes = {
            str(row[1]) for row in conn.execute("PRAGMA index_list(tracker_api_events)")
        }

    assert "idx_scheduler_runs_status" in scheduler_indexes
    assert "idx_scheduler_runs_finished_at" in scheduler_indexes
    assert "idx_tracker_api_events_event" in tracker_indexes


def test_state_store_records_want_search_runs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.record_want_search_run(
        intent_id="douban_wanted:1",
        source="schedule",
        status="skipped_backoff",
        search_enabled=False,
        results_count=0,
        run_id="sched-test",
        backoff_active=True,
        backoff_until="2026-07-05T00:00:00+08:00",
        message="M-Team backoff active",
    )

    rows = store.list_want_search_runs(intent_id="douban_wanted:1")

    assert rows[0]["intent_id"] == "douban_wanted:1"
    assert rows[0]["status"] == "skipped_backoff"
    assert rows[0]["backoff_active"] == 1


def test_scheduler_lease_rejects_second_owner_and_allows_expired_takeover(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    now = datetime(2026, 7, 11, tzinfo=UTC)

    first = store.acquire_scheduler_lease("owner-a", ttl_seconds=60, now=now)
    blocked = store.acquire_scheduler_lease(
        "owner-b",
        ttl_seconds=60,
        now=now + timedelta(seconds=30),
    )
    takeover = store.acquire_scheduler_lease(
        "owner-b",
        ttl_seconds=60,
        now=now + timedelta(seconds=61),
    )

    assert first["acquired"] is True
    assert blocked["acquired"] is False
    assert blocked["owner_id"] == "owner-a"
    assert takeover["acquired"] is True
    assert takeover["owner_id"] == "owner-b"
    assert store.release_scheduler_lease("owner-a") is False
    assert store.release_scheduler_lease("owner-b") is True
    assert store.get_scheduler_lease() is None


def test_scheduler_trigger_only_queues_while_waiting_and_is_consumed_once(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    store.begin_scheduler_cycle()
    rejected = store.request_scheduler_trigger(source="web")

    assert rejected["queued"] is False
    assert store.get_scheduler_trigger() is None
    assert store.get_scheduler_control()["phase"] == "running"  # type: ignore[index]

    store.mark_scheduler_waiting()
    queued = store.request_scheduler_trigger(source="web")

    assert queued["queued"] is True
    assert store.get_scheduler_trigger()["source"] == "web"  # type: ignore[index]

    consumed = store.consume_scheduler_trigger()

    assert consumed is not None
    assert consumed["source"] == "web"
    assert store.consume_scheduler_trigger() is None
    assert store.get_scheduler_control()["phase"] == "running"  # type: ignore[index]


def test_state_store_clears_active_tracker_backoffs_without_deleting_history(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/search",
        until="2026-07-18T00:00:00+08:00",
        reason="request too frequent",
    )

    cleared = store.clear_tracker_backoffs(site="mteam")
    row = store.get_tracker_backoff("mteam", "torrent/search")

    assert cleared == 1
    assert row is not None
    assert row["active"] == 0
    assert row["reason"] == "request too frequent"


def test_intent_enqueue_claim_blocks_parallel_owner_and_commits_atomically(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    intent, _ = add_intent("Inception 2010 1080p", store)
    now = datetime(2026, 7, 13, tzinfo=UTC)

    first = store.acquire_intent_enqueue_claim(
        intent.intent_id,
        "release-a",
        "owner-a",
        ttl_seconds=60,
        now=now,
    )
    blocked = store.acquire_intent_enqueue_claim(
        intent.intent_id,
        "release-a",
        "owner-b",
        ttl_seconds=60,
        now=now + timedelta(seconds=30),
    )
    takeover = store.acquire_intent_enqueue_claim(
        intent.intent_id,
        "release-a",
        "owner-b",
        ttl_seconds=60,
        now=now + timedelta(seconds=61),
    )

    assert first["acquired"] is True
    assert blocked["acquired"] is False
    assert blocked["status"] == "in_progress"
    assert takeover["acquired"] is True
    assert store.complete_intent_enqueue_claim(
        intent.intent_id,
        "release-a",
        "owner-b",
    )
    row = store.get_intent(intent.intent_id)
    assert row is not None
    assert row["state"] == "enqueued"
    assert row["selected_release_id"] == "release-a"

    already_enqueued = store.acquire_intent_enqueue_claim(
        intent.intent_id,
        "release-a",
        "owner-c",
    )
    assert already_enqueued == {
        "acquired": False,
        "status": "already_enqueued",
        "selected_release_id": "release-a",
    }
