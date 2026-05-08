from datetime import UTC, datetime, timedelta
from pathlib import Path

from seed_agent.models import LifecycleState, ManagedTorrent
from seed_agent.state import StateStore


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
