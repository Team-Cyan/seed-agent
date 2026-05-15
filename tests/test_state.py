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
