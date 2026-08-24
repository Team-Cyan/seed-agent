import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from seed_agent.actions.intent import (
    add_intent,
    enqueue_intent,
    ingest_events,
    ingest_inbox,
    rank_intent,
    run_intent_once,
    search_intent,
)
from seed_agent.config import CategoryPolicyConfig, IntentConfig, SearchConfig
from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    RankedRelease,
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


@pytest.mark.asyncio
async def test_enqueue_intent_runtime_gate_skips_download_url_resolution(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Backrooms 2026 2160p", store)
    release_id = "mteam:https://kp.m-team.cc/detail/1208776"
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id=release_id,
                    site="mteam",
                    title="Backrooms 2026 2160p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/1208776",
                    download_url="mteam-api://torrent/1208776",
                    size_bytes=20 * 1024**3,
                    seeders=100,
                    leechers=1,
                    discount=Discount.FREE,
                    metadata={
                        "mteam_torrent_id": "1208776",
                        "download_url_source": "mteam_api_deferred",
                    },
                ),
                score=115,
                confidence=0.95,
                accepted=True,
                confirmation_required=False,
                reasons=["title tokens matched"],
                risks=[],
            )
        ]
    )
    resolver_calls = 0

    async def release_resolver(release: ReleaseCandidate) -> ReleaseCandidate:
        nonlocal resolver_calls
        resolver_calls += 1
        return release.model_copy(
            update={"download_url": "https://tracker.example/download?id=1208776"}
        )

    def enqueue_context_resolver(*_args):
        return True, None, ["active downloads 1 >= max 1"]

    _updated, _selected, decisions = await enqueue_intent(
        intent.intent_id,
        store,
        _UnusedDownloader(),
        _policy(),
        True,
        release_resolver=release_resolver,
        enqueue_context_resolver=enqueue_context_resolver,
        release_id=release_id,
    )

    assert resolver_calls == 0
    assert [item.action for item in decisions] == ["qb.enqueue.rejected"]
    assert decisions[0].new_state["pause_reasons"] == ["active downloads 1 >= max 1"]


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
        "隐秘的角落 第三季 2020",
        store,
        source=IntentSource.DOUBAN_WANTED,
        source_event_id="douban:33404425",
        requested_at=REQUESTED_AT,
        metadata={"media_type": "tv", "douban_user_name": "example-user"},
    )

    assert decision.new_state["existed"] is True
    assert refreshed.state == IntentState.CONFIRMATION_REQUIRED
    assert refreshed.kind == IntentKind.SHOW
    assert refreshed.season == 3
    assert refreshed.metadata["media_type"] == "tv"
    assert refreshed.metadata["douban_user_name"] == "example-user"


def test_add_intent_refreshes_missing_year_from_later_source_metadata(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")

    first, _ = add_intent(
        "无职转生",
        store,
        source=IntentSource.DOUBAN_WANTED,
        source_event_id="douban:99999998",
        requested_at=REQUESTED_AT,
    )
    refreshed, _ = add_intent(
        "无职转生 2026",
        store,
        source=IntentSource.DOUBAN_WANTED,
        source_event_id="douban:99999998",
        requested_at=REQUESTED_AT,
        metadata={"media_type": "tv"},
    )

    assert first.year is None
    assert refreshed.year == 2026
    assert refreshed.kind == IntentKind.SHOW


def test_rank_intent_replaces_episode_candidates_excluded_in_season_mode(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent(
        "House of the Dragon Season 3 2026",
        store,
        requested_at=REQUESTED_AT,
        metadata={"media_type": "tv"},
    )
    episode = ReleaseCandidate(
        release_id="mteam:episode",
        site="mteam",
        title="House of the Dragon 2026 S03E01 2160p WEB-DL",
        source_url="https://example.invalid/episode",
        download_url="https://example.invalid/download/episode",
        size_bytes=1,
        seeders=1,
        leechers=1,
        discount=Discount.FREE,
    )
    season = episode.model_copy(
        update={
            "release_id": "mteam:season",
            "title": "House of the Dragon 2026 S03 2160p WEB-DL",
        }
    )
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=episode,
                score=0,
                confidence=0,
                accepted=False,
                confirmation_required=True,
                reasons=[],
                risks=[],
            ),
            RankedRelease(
                intent_id=intent.intent_id,
                release=season,
                score=0,
                confidence=0,
                accepted=False,
                confirmation_required=True,
                reasons=[],
                risks=[],
            ),
        ],
        replace_intent_id=intent.intent_id,
    )

    _, ranked, _ = rank_intent(
        intent.intent_id,
        store,
        IntentConfig(series_search_mode="season"),
        SearchConfig(),
    )

    assert [item.release.release_id for item in ranked] == ["mteam:season"]
    rows = store.list_release_candidates(intent.intent_id)
    assert [row["release_id"] for row in rows] == ["mteam:season"]


@pytest.mark.asyncio
async def test_search_intent_excludes_episode_candidates_in_season_mode(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent(
        "House of the Dragon Season 3 2026",
        store,
        requested_at=REQUESTED_AT,
        metadata={"media_type": "tv"},
    )

    class Provider:
        async def search(self, _intent: ResourceIntent) -> list[ReleaseCandidate]:
            return [
                ReleaseCandidate(
                    release_id="mteam:episode",
                    site="mteam",
                    title="House of the Dragon 2026 S03E01 2160p WEB-DL",
                    source_url="https://example.invalid/episode",
                    download_url="https://example.invalid/download/episode",
                    size_bytes=1,
                    seeders=1,
                    leechers=1,
                    discount=Discount.FREE,
                ),
                ReleaseCandidate(
                    release_id="mteam:season",
                    site="mteam",
                    title="House of the Dragon 2026 S03 2160p WEB-DL",
                    source_url="https://example.invalid/season",
                    download_url="https://example.invalid/download/season",
                    size_bytes=1,
                    seeders=1,
                    leechers=1,
                    discount=Discount.FREE,
                ),
            ]

    _, ranked, _ = await search_intent(
        intent.intent_id,
        store,
        [Provider()],
        IntentConfig(series_search_mode="season"),
    )

    assert [item.release.release_id for item in ranked] == ["mteam:season"]
    rows = store.list_release_candidates(intent.intent_id)
    assert [row["release_id"] for row in rows] == ["mteam:season"]


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
                "douban_user_name": "example-user",
                "media_type": "anime",
                "external_ids": {"douban": "35797709"},
                "source_config_id": "douban-me",
                "source_label": "豆瓣-我",
            },
        )
    ]

    ingested = ingest_events(events, store)

    assert len(ingested) == 1
    assert ingested[0][0].metadata["douban_user_name"] == "example-user"
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
async def test_search_intent_does_not_merge_from_candidate_external_ids(
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

    searched, ranked, _ = await search_intent(
        newer.intent_id,
        store,
        [FakeProvider()],
        IntentConfig(),
    )

    assert searched.intent_id == newer.intent_id
    assert ranked[0].intent_id == newer.intent_id
    assert store.get_intent(newer.intent_id)["state"] == IntentState.SEARCHED.value
    assert store.get_intent(older.intent_id)["state"] == IntentState.RECEIVED.value
    assert store.list_release_candidates(older.intent_id) == []
    assert [row["intent_id"] for row in store.list_release_candidates(newer.intent_id)] == [
        newer.intent_id
    ]


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
async def test_run_intent_once_searches_preexisting_normalized_intents_in_batches(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    first, _ = add_intent("Inception 2010", store, requested_at=REQUESTED_AT)
    second, _ = add_intent("Arrival 2016", store, requested_at=REQUESTED_AT)

    class EmptyProvider:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search(self, intent):
            self.calls.append(intent.intent_id)
            return []

    provider = EmptyProvider()
    result = await run_intent_once(
        None,
        store,
        [provider],
        IntentConfig(),
        SearchConfig(),
        _UnusedDownloader(),
        _policy(),
        execute=False,
        source_events=[],
        search_limit=1,
        run_id="sched-test",
    )

    assert [intent.intent_id for intent in result.searched] == [first.intent_id]
    assert provider.calls == [first.intent_id]
    assert (
        store.get_intent(first.intent_id)["state"]
        == IntentState.CONFIRMATION_REQUIRED.value
    )
    assert store.get_intent(second.intent_id)["state"] == IntentState.NORMALIZED.value
    history = store.list_want_search_runs(intent_id=first.intent_id)
    assert history[0]["run_id"] == "sched-test"


@pytest.mark.asyncio
async def test_run_intent_once_does_not_persist_partial_search_batch(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    first, _ = add_intent("Inception 2010", store, requested_at=REQUESTED_AT)
    second, _ = add_intent("Arrival 2016", store, requested_at=REQUESTED_AT)

    class FailingProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def search(self, intent):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("injected provider failure")
            return []

    with pytest.raises(RuntimeError, match="injected provider failure"):
        await run_intent_once(
            None,
            store,
            [FailingProvider()],
            IntentConfig(),
            SearchConfig(),
            _UnusedDownloader(),
            _policy(),
            execute=False,
            source_events=[],
            run_id="sched-test",
        )

    assert store.get_intent(first.intent_id)["state"] == IntentState.NORMALIZED.value
    assert store.get_intent(second.intent_id)["state"] == IntentState.NORMALIZED.value
    assert store.list_release_candidates(first.intent_id) == []
    assert store.list_release_candidates(second.intent_id) == []
    assert store.list_want_search_runs(intent_id=first.intent_id) == []
    assert store.list_want_search_runs(intent_id=second.intent_id) == []


@pytest.mark.asyncio
async def test_run_intent_once_does_not_merge_from_release_metadata(
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

    searched_id = result.ingested[0].intent_id
    assert searched_id != older.intent_id
    assert [intent.intent_id for intent in result.searched] == [searched_id]
    assert [ranked.intent_id for ranked in result.ranked] == [searched_id]
    assert store.get_intent(searched_id)["state"] == IntentState.CONFIRMATION_REQUIRED.value
    assert store.get_intent(older.intent_id)["state"] == IntentState.RECEIVED.value


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_state", [IntentState.ENQUEUED, IntentState.REJECTED])
async def test_run_intent_once_does_not_research_terminal_intents(
    tmp_path: Path,
    terminal_state: IntentState,
) -> None:
    store = StateStore(tmp_path / "state.db")
    event = SourceIntentEvent(
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Inception 2010",
        source_event_id="douban:1292720",
        requested_at=REQUESTED_AT,
        metadata={"external_ids": {"douban": "1292720"}},
    )
    intent = ingest_events([event], store)[0][0]
    store.update_intent_state(intent.intent_id, terminal_state)

    class FailingProvider:
        async def search(self, intent):
            raise AssertionError("terminal intent must not be searched")

    result = await run_intent_once(
        None,
        store,
        [FailingProvider()],
        IntentConfig(),
        SearchConfig(),
        _UnusedDownloader(),
        _policy(),
        execute=True,
        source_events=[event],
    )

    assert result.searched == []
    assert result.ranked == []
    assert result.enqueue_selected == []
    assert store.get_intent(intent.intent_id)["state"] == terminal_state.value


@pytest.mark.asyncio
async def test_search_intent_replaces_previous_search_snapshot(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    intent = ResourceIntent(
        intent_id="cli:inception",
        source=IntentSource.CLI,
        raw_text="Inception 2010",
        kind=IntentKind.MOVIE,
        title="Inception",
        year=2010,
        requested_at=REQUESTED_AT,
    )
    store.upsert_intent(intent)

    class Provider:
        def __init__(self) -> None:
            self.release_id = "old"

        async def search(self, intent):
            return [
                ReleaseCandidate(
                    release_id=self.release_id,
                    site="demo",
                    title=f"Inception 2010 {self.release_id}",
                    source_url=f"https://tracker.example/{self.release_id}",
                    download_url=f"https://tracker.example/{self.release_id}.torrent",
                    size_bytes=1,
                    seeders=1,
                    leechers=1,
                    discount=Discount.NORMAL,
                )
            ]

    provider = Provider()
    await search_intent(intent.intent_id, store, [provider], IntentConfig())
    provider.release_id = "new"
    await search_intent(intent.intent_id, store, [provider], IntentConfig())

    assert [row["release_id"] for row in store.list_release_candidates(intent.intent_id)] == ["new"]


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
