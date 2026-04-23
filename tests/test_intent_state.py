import json
from datetime import UTC, datetime
from pathlib import Path

from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
)
from seed_agent.state import StateStore


def _intent(**overrides: object) -> ResourceIntent:
    data: dict[str, object] = {
        "intent_id": "cli:inception-2010-1080p",
        "source": IntentSource.CLI,
        "raw_text": "Inception 2010 1080p",
        "kind": IntentKind.MOVIE,
        "title": "Inception",
        "year": 2010,
        "resolution": "1080p",
        "requested_at": datetime(2026, 4, 22, tzinfo=UTC),
        "state": IntentState.RECEIVED,
    }
    data.update(overrides)
    return ResourceIntent(**data)


def _release(**overrides: object) -> ReleaseCandidate:
    data: dict[str, object] = {
        "release_id": "demo:https://tracker.example/details.php?id=42",
        "site": "demo",
        "title": "Inception 2010 1080p BluRay",
        "source_url": "https://tracker.example/details.php?id=42",
        "download_url": "https://tracker.example/download.php?id=42&passkey=secret",
        "size_bytes": 8 * 1024**3,
        "seeders": 40,
        "leechers": 12,
        "discount": Discount.FREE,
        "published_at": datetime(2026, 4, 22, tzinfo=UTC),
    }
    data.update(overrides)
    return ReleaseCandidate(**data)


def _ranked(**overrides: object) -> RankedRelease:
    data: dict[str, object] = {
        "intent_id": "cli:inception-2010-1080p",
        "release": _release(),
        "score": 94,
        "confidence": 0.96,
        "accepted": True,
        "confirmation_required": False,
        "reasons": ["title exact match"],
        "risks": [],
    }
    data.update(overrides)
    return RankedRelease(**data)


def test_state_store_upserts_and_lists_intents(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    intent = _intent()

    store.upsert_intent(intent)
    row = store.get_intent(intent.intent_id)

    assert row is not None
    assert row["source"] == IntentSource.CLI.value
    assert row["state"] == IntentState.RECEIVED.value
    assert row["selected_release_id"] is None
    normalized = json.loads(row["normalized_json"])
    assert normalized["title"] == "Inception"

    store.upsert_intent(
        _intent(state=IntentState.CONFIRMATION_REQUIRED),
        selected_release_id="demo:https://tracker.example/details.php?id=42",
    )
    updated = store.get_intent(intent.intent_id)

    assert updated is not None
    assert updated["state"] == IntentState.CONFIRMATION_REQUIRED.value
    assert updated["selected_release_id"] == "demo:https://tracker.example/details.php?id=42"
    assert updated["created_at"] == row["created_at"]
    assert updated["updated_at"] >= row["updated_at"]
    assert [item["intent_id"] for item in store.list_intents_by_state(IntentState.RECEIVED)] == []
    assert [
        item["intent_id"]
        for item in store.list_intents_by_state(IntentState.CONFIRMATION_REQUIRED)
    ] == [intent.intent_id]


def test_state_store_updates_intent_state_without_losing_normalized_payload(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    intent = _intent(metadata={"parser": "deterministic"})
    store.upsert_intent(intent)

    updated = store.update_intent_state(intent.intent_id, IntentState.CONFIRMED)
    row = store.get_intent(intent.intent_id)

    assert updated is True
    assert row is not None
    assert row["state"] == IntentState.CONFIRMED.value
    normalized = json.loads(row["normalized_json"])
    assert normalized["metadata"] == {"parser": "deterministic"}
    assert normalized["state"] == IntentState.CONFIRMED.value


def test_state_store_update_missing_intent_returns_false(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    assert store.update_intent_state("missing", IntentState.CONFIRMED) is False


def test_state_store_saves_ranked_releases_ordered_by_score(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    intent = _intent()
    store.upsert_intent(intent)

    store.save_ranked_releases(
        [
            _ranked(
                release=_release(
                    release_id="demo:https://tracker.example/details.php?id=low",
                    title="Inception 720p",
                ),
                score=70,
                confidence=0.72,
                confirmation_required=True,
            ),
            _ranked(
                release=_release(
                    release_id="demo:https://tracker.example/details.php?id=high",
                    title="Inception 1080p",
                ),
                score=94,
                confidence=0.96,
            ),
        ]
    )

    rows = store.list_release_candidates(intent.intent_id)

    assert [row["release_id"] for row in rows] == [
        "demo:https://tracker.example/details.php?id=high",
        "demo:https://tracker.example/details.php?id=low",
    ]
    assert rows[0]["accepted"] == 1
    assert rows[0]["confirmation_required"] == 0
    saved = json.loads(rows[0]["release_json"])
    assert saved["release"]["title"] == "Inception 1080p"


def test_state_store_replaces_ranked_release_without_duplicate_rows(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    intent = _intent()
    store.upsert_intent(intent)

    store.save_ranked_releases([_ranked(score=80, confidence=0.8)])
    store.save_ranked_releases([_ranked(score=95, confidence=0.97)])
    rows = store.list_release_candidates(intent.intent_id)

    assert len(rows) == 1
    assert rows[0]["score"] == 95
    assert rows[0]["confidence"] == 0.97


def test_state_store_keeps_same_release_for_multiple_intents(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    first = _intent()
    second = _intent(
        intent_id="cli:inception-2010-2160p",
        raw_text="Inception 2010 2160p",
        resolution="2160p",
    )
    shared_release = _release(release_id="demo:https://tracker.example/details.php?id=shared")
    store.upsert_intent(first)
    store.upsert_intent(second)

    store.save_ranked_releases(
        [
            _ranked(intent_id=first.intent_id, release=shared_release),
            _ranked(intent_id=second.intent_id, release=shared_release),
        ]
    )

    first_rows = store.list_release_candidates(first.intent_id)
    second_rows = store.list_release_candidates(second.intent_id)

    assert [row["release_id"] for row in first_rows] == [shared_release.release_id]
    assert [row["release_id"] for row in second_rows] == [shared_release.release_id]


def test_state_store_clears_stale_paused_runtime_when_torrent_is_active(tmp_path: Path) -> None:
    from seed_agent.models import ManagedTorrent

    store = StateStore(tmp_path / "state.sqlite3")
    store.mark_torrent_paused("abcd1234", datetime(2026, 4, 1, tzinfo=UTC))
    active = ManagedTorrent(
        hash="abcd1234",
        name="Demo Torrent",
        category="pt-auto",
        tags={"seed-agent"},
        state="uploading",
        size_bytes=10 * 1024**3,
        uploaded_bytes=1,
        downloaded_bytes=1,
        added_at=datetime(2026, 4, 1, tzinfo=UTC),
        last_activity_at=datetime(2026, 4, 2, tzinfo=UTC),
    )

    enriched = store.apply_torrent_runtime([active])

    assert "paused_at" not in enriched[0].metadata
    assert store.get_torrent_runtime("abcd1234") is None
