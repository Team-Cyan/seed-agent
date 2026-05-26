import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from seed_agent.actions.intent import (
    add_intent,
    ingest_events,
    ingest_inbox,
    run_intent_once,
    search_intent,
)
from seed_agent.config import CategoryPolicyConfig, IntentConfig, SearchConfig
from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    ReleaseCandidate,
    ResourceIntent,
)
from seed_agent.sources.base import SourceIntentEvent
from seed_agent.state import StateStore

REQUESTED_AT = datetime(2026, 4, 22, tzinfo=UTC)


class _UnusedDownloader:
    pass


def _policy() -> CategoryPolicyConfig:
    return CategoryPolicyConfig(
        name="seed",
        mode="mutable",
        budget_pool="downloads",
        delete_enabled=True,
        over_budget_behavior="add_paused",
        tags=["seed-agent"],
    )


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


def test_add_intent_persists_source_metadata(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    intent, _ = add_intent(
        "请以你的名字呼唤我 2017",
        store,
        source=IntentSource.MANUAL,
        source_event_id="manual-1",
        requested_at=REQUESTED_AT,
        metadata={"media_type": "movie", "source_label": "Manual"},
    )
    row = store.get_intent(intent.intent_id)

    assert intent.metadata["media_type"] == "movie"
    assert intent.metadata["source_label"] == "Manual"
    assert intent.metadata["parser"] == "deterministic"
    assert row is not None
    assert "Manual" in row["normalized_json"]


def test_add_intent_refreshes_metadata_without_resetting_existing_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    intent, _ = add_intent(
        "隐秘的角落 2020",
        store,
        source=IntentSource.DOUBAN_WANTED,
        source_event_id="douban:33404425",
        requested_at=REQUESTED_AT,
        metadata={"media_type": "movie"},
    )
    store.update_intent_state(intent.intent_id, IntentState.CONFIRMATION_REQUIRED)
    refreshed, decision = add_intent(
        "隐秘的角落 2020",
        store,
        source=IntentSource.DOUBAN_WANTED,
        source_event_id="douban:33404425",
        requested_at=REQUESTED_AT,
        metadata={"media_type": "tv", "douban_user_name": "LancerC"},
    )

    assert decision.new_state["existed"] is True
    assert refreshed.state == IntentState.CONFIRMATION_REQUIRED
    assert refreshed.metadata["media_type"] == "tv"
    assert refreshed.metadata["douban_user_name"] == "LancerC"


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


def test_ingest_events_persists_source_event_metadata(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    events = [
        SourceIntentEvent(
            source=IntentSource.DOUBAN_WANTED,
            raw_text="葬送的芙莉莲 2023",
            source_event_id="douban:35797709",
            requested_at=REQUESTED_AT,
            metadata={
                "source_adapter": "douban_wanted_public",
                "douban_user_name": "LancerC",
                "media_type": "anime",
                "external_ids": {"douban": "35797709"},
                "source_config_id": "douban-me",
                "source_label": "豆瓣-我",
            },
        )
    ]

    ingested = ingest_events(events, store)

    assert len(ingested) == 1
    assert ingested[0][0].metadata["douban_user_name"] == "LancerC"
    assert ingested[0][0].metadata["media_type"] == "anime"
    assert store.find_intent_id_by_alias("douban:35797709") == ingested[0][0].intent_id
    evidence = store.list_intent_source_evidence(ingested[0][0].intent_id)
    assert evidence[0]["source_label"] == "豆瓣-我"


def test_ingest_events_merges_duplicate_douban_sources_as_evidence(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    events = [
        SourceIntentEvent(
            source=IntentSource.DOUBAN_WANTED,
            raw_text="肖申克的救赎 1994",
            source_event_id="douban:1292052",
            requested_at=datetime(2025, 1, 1, tzinfo=UTC),
            metadata={
                "media_type": "movie",
                "external_ids": {"douban": "1292052"},
                "source_config_id": "douban-me",
                "source_label": "豆瓣-我",
            },
        ),
        SourceIntentEvent(
            source=IntentSource.DOUBAN_WANTED,
            raw_text="肖申克的救赎 1994",
            source_event_id="douban:1292052",
            requested_at=datetime(2025, 1, 3, tzinfo=UTC),
            metadata={
                "media_type": "movie",
                "external_ids": {"douban": "1292052"},
                "source_config_id": "douban-partner",
                "source_label": "豆瓣-老婆",
            },
        ),
    ]

    ingested = ingest_events(events, store)

    assert len({item[0].intent_id for item in ingested}) == 1
    rows = store.list_intents_by_state(IntentState.NORMALIZED)
    assert [row["intent_id"] for row in rows] == [ingested[0][0].intent_id]
    evidence = store.list_intent_source_evidence(ingested[0][0].intent_id)
    assert [item["source_label"] for item in evidence] == ["豆瓣-我", "豆瓣-老婆"]


def test_ingest_events_merges_douban_and_imdb_aliases_without_resetting_state(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    douban_event = SourceIntentEvent(
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Call Me by Your Name 2017",
        source_event_id="douban:26799731",
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        metadata={
            "media_type": "movie",
            "external_ids": {"douban": "26799731", "imdb": "tt5726616"},
            "source_config_id": "douban-me",
            "source_label": "豆瓣-我",
        },
    )
    imdb_event = SourceIntentEvent(
        source=IntentSource.IMDB_WATCHLIST,
        raw_text="Call Me by Your Name 2017",
        source_event_id="imdb:tt5726616",
        requested_at=datetime(2025, 1, 5, tzinfo=UTC),
        metadata={
            "media_type": "movie",
            "external_ids": {"imdb": "tt5726616"},
            "source_config_id": "imdb-weekend",
            "source_label": "IMDb-周末清单",
        },
    )

    first = ingest_events([douban_event], store)[0][0]
    store.update_intent_state(first.intent_id, IntentState.SEARCHED)
    second = ingest_events([imdb_event], store)[0][0]
    row = store.get_intent(first.intent_id)

    assert second.intent_id == first.intent_id
    assert row is not None
    assert row["state"] == IntentState.SEARCHED.value
    assert store.find_intent_id_by_alias("douban:26799731") == first.intent_id
    assert store.find_intent_id_by_alias("imdb:tt5726616") == first.intent_id
    evidence = store.list_intent_source_evidence(first.intent_id)
    assert [item["source_label"] for item in evidence] == ["豆瓣-我", "IMDb-周末清单"]


def test_ingest_events_records_duplicate_evidence_from_incoming_source(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    events = [
        SourceIntentEvent(
            source=IntentSource.DOUBAN_WANTED,
            raw_text="Call Me by Your Name 2017",
            source_event_id="douban:26799731",
            requested_at=datetime(2025, 1, 1, tzinfo=UTC),
            metadata={
                "media_type": "movie",
                "external_ids": {"douban": "26799731", "imdb": "tt5726616"},
                "source_config_id": "douban-me",
                "source_label": "豆瓣-我",
            },
        ),
        SourceIntentEvent(
            source=IntentSource.IMDB_WATCHLIST,
            raw_text="Call Me by Your Name 2017",
            source_event_id="imdb:tt5726616",
            requested_at=datetime(2025, 1, 5, tzinfo=UTC),
            metadata={
                "media_type": "movie",
                "external_ids": {"imdb": "tt5726616"},
                "source_config_id": "imdb-weekend",
                "source_label": "IMDb-周末清单",
            },
        ),
    ]

    canonical = ingest_events(events, store)[0][0]

    evidence = store.list_intent_source_evidence(canonical.intent_id)
    assert [item["source"] for item in evidence] == [
        IntentSource.DOUBAN_WANTED.value,
        IntentSource.IMDB_WATCHLIST.value,
    ]
    assert evidence[1]["raw_text"] == "Call Me by Your Name 2017"
    assert evidence[1]["source_event_id"] == "imdb:tt5726616"
    assert evidence[1]["requested_at"].startswith("2025-01-05")
    assert evidence[1]["metadata"]["source_config_id"] == "imdb-weekend"


@pytest.mark.asyncio
async def test_search_intent_saves_candidates_on_canonical_after_release_id_merge(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    older = ResourceIntent(
        intent_id="douban_wanted:older",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Call Me by Your Name 2017",
        kind=IntentKind.MOVIE,
        title="Call Me by Your Name",
        year=2017,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        metadata={"external_ids": {"douban": "26799731"}},
    )
    newer = ResourceIntent(
        intent_id="imdb_watchlist:newer",
        source=IntentSource.IMDB_WATCHLIST,
        raw_text="Call Me by Your Name 2017",
        kind=IntentKind.MOVIE,
        title="Call Me by Your Name",
        year=2017,
        requested_at=datetime(2025, 1, 5, tzinfo=UTC),
        metadata={"external_ids": {"imdb": "tt5726616"}},
    )
    store.upsert_intent(older)
    store.upsert_intent(newer)
    store.upsert_intent_alias("douban:26799731", older.intent_id)
    store.upsert_intent_alias("imdb:tt5726616", newer.intent_id)

    class FakeProvider:
        async def search(self, intent):
            assert intent.intent_id == newer.intent_id
            return [
                ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/1",
                    site="mt",
                    title="Call Me by Your Name 2017 2160p BluRay REMUX",
                    source_url="https://kp.m-team.cc/detail/1",
                    download_url="mteam-api://torrent/1",
                    size_bytes=66 * 1024**3,
                    seeders=10,
                    leechers=2,
                    discount=Discount.NORMAL,
                    metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}},
                )
            ]

    searched, ranked, _ = await search_intent(newer.intent_id, store, [FakeProvider()])

    assert searched.intent_id == older.intent_id
    assert ranked[0].intent_id == older.intent_id
    assert store.get_intent(newer.intent_id) is None
    assert store.get_intent(older.intent_id)["state"] == IntentState.SEARCHED.value
    assert [row["intent_id"] for row in store.list_release_candidates(older.intent_id)] == [
        older.intent_id
    ]
    assert store.list_release_candidates(newer.intent_id) == []


@pytest.mark.asyncio
async def test_run_intent_once_searches_canonical_duplicate_only_once(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    events = [
        SourceIntentEvent(
            source=IntentSource.DOUBAN_WANTED,
            raw_text="Inception 2010",
            source_event_id="douban:1292720",
            requested_at=datetime(2025, 1, 1, tzinfo=UTC),
            metadata={"external_ids": {"douban": "1292720"}},
        ),
        SourceIntentEvent(
            source=IntentSource.DOUBAN_WANTED,
            raw_text="Inception 2010",
            source_event_id="douban:1292720",
            requested_at=datetime(2025, 1, 3, tzinfo=UTC),
            metadata={"external_ids": {"douban": "1292720"}},
        ),
    ]

    class CountingProvider:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search(self, intent):
            self.calls.append(intent.intent_id)
            return [
                ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/1",
                    site="mt",
                    title="Inception 2010 BluRay",
                    source_url="https://kp.m-team.cc/detail/1",
                    download_url="mteam-api://torrent/1",
                    size_bytes=40 * 1024**3,
                    seeders=10,
                    leechers=2,
                    discount=Discount.NORMAL,
                )
            ]

    provider = CountingProvider()
    result = await run_intent_once(
        None,
        store,
        [provider],
        IntentConfig(confirmation_threshold=1.0, auto_enqueue_threshold=1.0),
        SearchConfig(),
        _UnusedDownloader(),
        _policy(),
        execute=False,
        source_events=events,
    )

    assert len(result.ingested) == 2
    assert len({intent.intent_id for intent in result.ingested}) == 1
    assert len(result.searched) == 1
    assert provider.calls == [result.ingested[0].intent_id]


@pytest.mark.asyncio
async def test_run_intent_once_ranks_canonical_after_release_id_merge(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    older = ResourceIntent(
        intent_id="douban_wanted:older",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Call Me by Your Name 2017",
        kind=IntentKind.MOVIE,
        title="Call Me by Your Name",
        year=2017,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        metadata={"external_ids": {"douban": "26799731"}},
    )
    store.upsert_intent(older)
    store.upsert_intent_alias("douban:26799731", older.intent_id)
    imdb_event = SourceIntentEvent(
        source=IntentSource.IMDB_WATCHLIST,
        raw_text="Call Me by Your Name 2017",
        source_event_id="imdb:tt5726616",
        requested_at=datetime(2025, 1, 5, tzinfo=UTC),
        metadata={"external_ids": {"imdb": "tt5726616"}},
    )

    class MappingProvider:
        async def search(self, intent):
            return [
                ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/1",
                    site="mt",
                    title="Call Me by Your Name 2017 BluRay",
                    source_url="https://kp.m-team.cc/detail/1",
                    download_url="mteam-api://torrent/1",
                    size_bytes=44 * 1024**3,
                    seeders=10,
                    leechers=2,
                    discount=Discount.NORMAL,
                    metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}},
                )
            ]

    result = await run_intent_once(
        None,
        store,
        [MappingProvider()],
        IntentConfig(confirmation_threshold=1.0, auto_enqueue_threshold=1.0),
        SearchConfig(),
        _UnusedDownloader(),
        _policy(),
        execute=False,
        source_events=[imdb_event],
    )

    assert [intent.intent_id for intent in result.searched] == [older.intent_id]
    assert [ranked.intent_id for ranked in result.ranked] == [older.intent_id]
    assert store.get_intent("imdb_watchlist:tt5726616") is None
    assert store.get_intent(older.intent_id)["state"] == IntentState.CONFIRMATION_REQUIRED.value


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
