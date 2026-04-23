import json
from datetime import UTC, datetime
from pathlib import Path

from seed_agent.actions.intent import add_intent, ingest_inbox
from seed_agent.models import IntentKind, IntentSource, IntentState
from seed_agent.state import StateStore

REQUESTED_AT = datetime(2026, 4, 22, tzinfo=UTC)


def test_add_intent_parses_and_persists_cli_text(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    intent, decision = add_intent(
        "Inception 2010 1080p",
        store,
        requested_at=REQUESTED_AT,
    )
    row = store.get_intent(intent.intent_id)

    assert intent.source == IntentSource.CLI
    assert intent.kind == IntentKind.MOVIE
    assert intent.title == "Inception"
    assert intent.state == IntentState.NORMALIZED
    assert decision.action == "intent.ingest"
    assert decision.target_id == intent.intent_id
    assert decision.new_state["existed"] is False
    assert row is not None
    assert row["state"] == IntentState.NORMALIZED.value


def test_add_intent_is_idempotent_for_same_source_event(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    first, first_decision = add_intent(
        "Inception 2010 1080p",
        store,
        source=IntentSource.TELEGRAM,
        source_event_id="chat-1:message-99",
        requested_at=REQUESTED_AT,
    )
    second, second_decision = add_intent(
        "Inception 2010 2160p",
        store,
        source=IntentSource.TELEGRAM,
        source_event_id="chat-1:message-99",
        requested_at=REQUESTED_AT,
    )

    assert first.intent_id == second.intent_id
    assert first_decision.new_state["existed"] is False
    assert second_decision.new_state["existed"] is True
    rows = store.list_intents_by_state(IntentState.NORMALIZED)
    assert [row["intent_id"] for row in rows] == [first.intent_id]


def test_ingest_inbox_reads_jsonl_events_and_skips_invalid_lines(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    inbox = tmp_path / "intents.jsonl"
    inbox.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "1",
                        "text": "Inception 2010 1080p",
                        "requested_at": "2026-04-22T00:00:00+00:00",
                    }
                ),
                "not-json",
                json.dumps({"id": "2", "message": "show Severance S02E03 2160p"}),
                json.dumps({"id": "3"}),
            ]
        ),
        encoding="utf-8",
    )

    ingested = ingest_inbox(inbox, store, requested_at=REQUESTED_AT)

    assert len(ingested) == 2
    intents = [item[0] for item in ingested]
    assert [intent.source for intent in intents] == [
        IntentSource.FILE_INBOX,
        IntentSource.FILE_INBOX,
    ]
    assert intents[0].title == "Inception"
    assert intents[1].kind == IntentKind.EPISODE
    assert len(store.list_intents_by_state(IntentState.NORMALIZED)) == 2


def test_ingest_inbox_missing_file_returns_empty_list(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    assert ingest_inbox(tmp_path / "missing.jsonl", store) == []


def test_add_intent_preserves_existing_advanced_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    intent, _ = add_intent(
        "Inception 2010 1080p",
        store,
        source=IntentSource.FILE_INBOX,
        source_event_id="event-1",
        requested_at=REQUESTED_AT,
    )
    updated = store.update_intent_state(intent.intent_id, IntentState.REJECTED)
    repeated, decision = add_intent(
        "Inception 2010 2160p",
        store,
        source=IntentSource.FILE_INBOX,
        source_event_id="event-1",
        requested_at=REQUESTED_AT,
    )
    row = store.get_intent(intent.intent_id)

    assert updated is True
    assert repeated.intent_id == intent.intent_id
    assert repeated.state == IntentState.REJECTED
    assert decision.new_state["existed"] is True
    assert row is not None
    assert row["state"] == IntentState.REJECTED.value
