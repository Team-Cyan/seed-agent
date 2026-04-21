from pathlib import Path

from seed_agent.models import LifecycleState
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


def test_state_store_creates_parent_directory_for_nested_path(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "state.sqlite3"

    StateStore(path)

    assert path.parent.exists()
