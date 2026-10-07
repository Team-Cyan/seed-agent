import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from seed_agent.actions.intent import (
    add_intent,
    enqueue_intent,
    rank_intent,
    reject_intent,
    run_intent_once,
    search_intent,
    search_intents_batch,
)
from seed_agent.config import CategoryPolicyConfig, IntentConfig, SearchConfig
from seed_agent.intent.workflow import next_search_at, normalize_external_id
from seed_agent.models import IntentKind, IntentState, ReleaseCandidate, TorrentCandidate
from seed_agent.policies.intent_ranking import rank_releases
from seed_agent.search.mteam import MTeamSearchProvider
from seed_agent.sites.mteam import MTeamApiResponseError
from seed_agent.state import StateStore
from seed_agent.web.app import _want_searchable, _wants_payload

NOW = datetime(2026, 10, 7, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
CONFIG = IntentConfig(confirmation_threshold=0.5, auto_enqueue_threshold=0.5)
POLICY = CategoryPolicyConfig(
    name="movie",
    mode="add_only",
    budget_pool="media",
    delete_enabled=False,
    over_budget_behavior="reject",
    tags=["seed-agent"],
)


class Provider:
    def __init__(self, *, empty=False):
        self.empty = empty
        self.calls = []

    async def search(self, intent):
        self.calls.append(intent.intent_id)
        return [] if self.empty else [release(title=f"{intent.title} 2026")]


class FakeDownloader:
    def __init__(self):
        self.add_calls = 0

    async def add_url(self, *args, **kwargs):
        self.add_calls += 1
        return "a" * 40


def release(**updates):
    return ReleaseCandidate(
        release_id="mteam:fixture",
        site="mteam",
        title="Inception 2026",
        source_url="https://example.test/detail/1",
        download_url="mteam-api://torrent/1",
        size_bytes=1024,
        seeders=30,
        leechers=8,
    ).model_copy(update=updates)


async def batch(store, intent, providers, *, at=NOW):
    return await search_intents_batch(
        [intent],
        store,
        providers,
        CONFIG,
        SearchConfig(),
        source="test",
        searched_at=at,
    )


@pytest.mark.asyncio
async def test_daily_backlog_drains_and_empty_results_are_searched_again(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intents = [add_intent(f"Movie {n} 2026", store)[0] for n in range(23)]
    provider = Provider(empty=True)
    for _ in range(3):
        await run_intent_once(
            None,
            store,
            [provider],
            CONFIG,
            SearchConfig(),
            FakeDownloader(),
            POLICY,
            False,
            search_mode="daily",
            search_now=NOW,
            search_limit=10,
        )
        store = StateStore(tmp_path / "state.db")  # Durable across process restart.
    assert len(provider.calls) == 23
    assert set(provider.calls) == {i.intent_id for i in intents}
    assert store.list_due_intents(mode="daily", now=NOW) == []
    for intent in intents:
        add_intent(intent.raw_text, store)  # Source refresh cannot reset progress.
    assert store.list_due_intents(mode="daily", now=NOW) == []
    assert len(store.list_due_intents(mode="daily", now=NOW + timedelta(days=1))) == 23


@pytest.mark.asyncio
async def test_success_replaces_review_state_without_resetting_identity(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store, metadata={"external_ids": {"douban": "12345"}})
    await batch(store, intent, [Provider(empty=True)])
    assert store.get_intent(intent.intent_id)["state"] == "confirmation_required"
    await batch(store, intent, [Provider()], at=NOW + timedelta(days=1))
    assert store.get_intent(intent.intent_id)["state"] == "searched"
    assert store.find_intent_id_by_alias("douban:12345") == intent.intent_id


@pytest.mark.asyncio
async def test_cli_search_reports_the_persisted_review_state(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    updated, _, decision = await search_intent(
        intent.intent_id, store, [Provider()], IntentConfig()
    )
    assert updated.state == IntentState.CONFIRMATION_REQUIRED
    assert decision.new_state["state"] == updated.state.value
    assert store.list_want_search_runs()[0]["status"] == "searched"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["no_provider", "business_error", "partial_error"])
async def test_failed_search_preserves_snapshot_and_success_timestamp(tmp_path, failure):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent(
        "Inception 2026", store, metadata={"external_ids": {"douban": "12345", "imdb": "tt12345"}}
    )
    await batch(store, intent, [Provider()])

    async def fetch(**kwargs):
        if failure == "partial_error" and kwargs["options"].douban:
            return [
                TorrentCandidate(
                    site="mteam",
                    title="New Release 2026",
                    source_url="https://example.test/2",
                    download_url="mteam-api://torrent/2",
                    size_bytes=1024,
                    seeders=10,
                    leechers=2,
                )
            ]
        raise MTeamApiResponseError(endpoint="torrent/search", code="1001", message="denied")

    providers = (
        []
        if failure == "no_provider"
        else [
            MTeamSearchProvider(
                site="mteam",
                api_key="fixture",
                search_config=SearchConfig(),
                fetch_candidates=fetch,
            )
        ]
    )
    with pytest.raises((ValueError, MTeamApiResponseError)):
        await batch(store, intent, providers, at=NOW + timedelta(days=1))
    assert [r["release_id"] for r in store.list_release_candidates(intent.intent_id)] == [
        "mteam:fixture",
    ]
    progress = store.want_search_progress()[intent.intent_id]
    assert progress["last_status"] == "failed"
    assert progress["last_success_at"] == NOW.isoformat()
    assert store.list_due_intents(mode="daily", now=NOW + timedelta(days=1)) == []
    assert len(store.list_due_intents(mode="daily", now=NOW + timedelta(days=1, minutes=31))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", [IntentState.REJECTED, IntentState.VIEWED, IntentState.ENQUEUED, IntentState.FAILED]
)
async def test_terminal_search_and_rank_preserve_candidates(tmp_path, state):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    await batch(store, intent, [Provider()])
    store.update_intent_state(intent.intent_id, state)
    provider = Provider(empty=True)
    with pytest.raises(ValueError, match="terminal"):
        await search_intent(intent.intent_id, store, [provider], CONFIG)
    with pytest.raises(ValueError, match="terminal"):
        rank_intent(intent.intent_id, store, CONFIG, SearchConfig())
    assert provider.calls == []
    assert store.list_release_candidates(intent.intent_id)
    assert not _want_searchable({"state": state.value})
    assert not store.acquire_intent_enqueue_claim(intent.intent_id, "mteam:fixture", "owner")[
        "acquired"
    ]


@pytest.mark.asyncio
async def test_active_enqueue_prevents_reject_and_snapshot_replacement(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    await batch(store, intent, [Provider()])
    store.acquire_intent_enqueue_claim(intent.intent_id, "mteam:fixture", "owner")
    with pytest.raises(ValueError, match="enqueue_in_progress"):
        reject_intent(intent.intent_id, store)
    ranked = rank_releases(intent, [], CONFIG, SearchConfig())
    assert store.save_want_search_batch([(intent, ranked)], source="race") == 0
    assert store.list_release_candidates(intent.intent_id)


@pytest.mark.asyncio
async def test_reject_during_resolution_reports_conflict_and_preserves_claim(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    await batch(store, intent, [Provider()])

    async def resolve(candidate):
        with pytest.raises(ValueError, match="enqueue_in_progress"):
            reject_intent(intent.intent_id, store)
        return candidate.model_copy(update={"download_url": "https://example.test/fixture"})

    downloader = FakeDownloader()
    await enqueue_intent(
        intent.intent_id,
        store,
        downloader,
        POLICY,
        True,
        release_id="mteam:fixture",
        release_resolver=resolve,
    )
    assert downloader.add_calls == 1
    assert store.get_intent(intent.intent_id)["state"] == "enqueued"


@pytest.mark.asyncio
async def test_lost_claim_during_resolution_never_adds(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    await batch(store, intent, [Provider()])

    async def resolve(candidate):
        with store._connect() as conn:
            conn.execute("DELETE FROM intent_enqueue_claims")
        reject_intent(intent.intent_id, store)
        return candidate.model_copy(update={"download_url": "https://example.test/fixture"})

    downloader = FakeDownloader()
    with pytest.raises(ValueError, match="ownership expired or state changed"):
        await enqueue_intent(
            intent.intent_id,
            store,
            downloader,
            POLICY,
            True,
            release_id="mteam:fixture",
            release_resolver=resolve,
        )
    assert downloader.add_calls == 0
    assert store.get_intent(intent.intent_id)["state"] == "rejected"


@pytest.mark.asyncio
async def test_capacity_blocked_candidate_retries_without_tracker_search(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    downloader = FakeDownloader()
    provider = Provider()
    await run_intent_once(
        None,
        store,
        [provider],
        CONFIG,
        SearchConfig(),
        downloader,
        POLICY,
        True,
        paused=True,
        search_now=NOW,
        search_mode="daily",
    )
    assert downloader.add_calls == 0
    assert store.get_intent(intent.intent_id)["state"] == "searched"

    async def resolve(candidate):
        return candidate.model_copy(update={"download_url": "https://example.test/fixture"})

    await run_intent_once(
        None,
        store,
        [],
        CONFIG,
        SearchConfig(),
        downloader,
        POLICY,
        True,
        search_ingested=False,
        retry_ready=True,
        release_resolver=resolve,
    )
    assert len(provider.calls) == 1
    assert downloader.add_calls == 1
    assert store.get_intent(intent.intent_id)["state"] == "enqueued"


@pytest.mark.asyncio
async def test_failure_history_storage_error_does_not_mask_search_error(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)

    def broken_history(**kwargs):
        raise RuntimeError("history storage unavailable")

    monkeypatch.setattr(store, "record_want_search_run", broken_history)
    with pytest.raises(ValueError, match="no search providers configured"):
        await batch(store, intent, [])


@pytest.mark.parametrize(
    "ids,queries,subtitle,matched,conflict",
    [
        ({"douban": "https://movie.douban.com/subject/37116446/"}, [], "", True, False),
        ({}, [{"provider": "douban", "id": "37116446"}], "", True, False),
        ({}, [], "给阿嬷的情书 / Dear You", True, False),
        ({"douban": "99999"}, [{"provider": "douban", "id": "37116446"}], "", False, True),
        ({}, [], "", False, False),
    ],
)
def test_identity_and_subtitle_corroboration(ids, queries, subtitle, matched, conflict, tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent(
        "给阿嬷的情书 2026", store, metadata={"external_ids": {"douban": "37116446"}}
    )
    ranked = rank_releases(
        intent,
        [
            release(
                title="Dear You 2026",
                metadata={
                    "external_ids": ids,
                    "search_identity_queries": queries,
                    "mteam_subtitle": subtitle,
                },
            )
        ],
        CONFIG,
        SearchConfig(),
    )[0]
    assert ("external work identifier conflict" in ranked.risks) == conflict
    assert ("weak title match" not in ranked.risks) == matched
    assert ranked.accepted == matched
    assert ranked.score <= 70  # Identity replaces title evidence; it is not stacked.


def test_search_progress_uses_configured_local_boundary_and_legacy_history(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    store.record_want_search_run(
        intent_id=intent.intent_id,
        source="legacy",
        status="searched",
        search_enabled=True,
        results_count=0,
        searched_at=NOW - timedelta(days=1) + timedelta(hours=2),
    )
    progress = store.want_search_progress()[intent.intent_id]
    assert next_search_at(progress, now=NOW, hour=0) <= NOW
    assert next_search_at(progress, now=NOW, hour=2) > NOW
    assert normalize_external_id("imdb", "https://www.imdb.com/title/tt12345/") == "tt12345"
    assert normalize_external_id("douban", "https://example.test/subject/12345/") is None


@pytest.mark.asyncio
async def test_identifier_query_provenance_survives_deduplication(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent(
        "给阿嬷的情书 2026",
        store,
        metadata={
            "external_ids": {
                "douban": "37116446",
                "imdb": "tt41791573",
            }
        },
    )

    async def fetch(**kwargs):
        assert kwargs["options"].mode is None
        return [
            TorrentCandidate(
                site="mteam",
                title="Dear You 2026",
                source_url="https://example.test/1",
                download_url="mteam-api://torrent/1",
                size_bytes=100,
                seeders=30,
                leechers=8,
            )
        ]

    provider = MTeamSearchProvider(
        site="mteam", api_key="fixture", search_config=SearchConfig(), fetch_candidates=fetch
    )
    result = await batch(store, intent, [provider])
    ranked = result.results[0][1]
    assert len(ranked) == 1
    assert ranked[0].accepted
    assert "external work identifier matched" in ranked[0].reasons
    assert "title tokens matched" not in ranked[0].reasons
    assert ranked[0].release.metadata["search_identity_queries"] == [
        {"provider": "douban", "id": "37116446"},
        {"provider": "imdb", "id": "tt41791573"},
    ]
    saved = json.loads(store.list_release_candidates(intent.intent_id)[0]["release_json"])
    assert len(saved["release"]["metadata"]["search_identity_queries"]) == 2


@pytest.mark.asyncio
async def test_true_empty_success_clears_snapshot_and_manual_search_bypasses_cadence(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)
    await batch(store, intent, [Provider()])
    assert not store.list_due_intents(mode="daily", now=NOW)
    assert store.list_due_intents(mode="manual", now=NOW)
    await batch(store, intent, [Provider(empty=True)])
    assert store.list_release_candidates(intent.intent_id) == []
    assert store.want_search_progress()[intent.intent_id]["last_status"] == "searched"


def test_web_exposes_search_failure_and_cadence_without_erasing_candidates(tmp_path):
    store = StateStore(tmp_path / ".seed-agent/state.db")
    intent, _ = add_intent("Inception 2026", store)
    payload = _wants_payload(tmp_path)
    assert payload["items"][0]["search_status"] == "never_searched"
    assert payload["items"][0]["search_due"]
    store.record_want_search_run(
        intent_id=intent.intent_id,
        source="test",
        status="failed",
        search_enabled=True,
        results_count=0,
        message="provider unavailable",
    )
    row = _wants_payload(tmp_path)["items"][0]
    assert row["search_status"] == "failed"
    assert row["search_error"] == "provider unavailable"
    assert row["last_successful_search_at"] is None
    assert row["next_search_at"] is not None
    assert not row["search_due"]
    store.acquire_intent_enqueue_claim(intent.intent_id, "fixture", "owner")
    row = _wants_payload(tmp_path)["items"][0]
    assert not row["searchable"]
    assert row["search_skip_reason"] == "enqueue_in_progress"
    assert row["next_search_at"] is None
    normalized = json.loads(store.get_intent(intent.intent_id)["normalized_json"])
    assert normalized["state"] == "normalized"


def test_web_next_search_respects_active_tracker_backoff(tmp_path):
    store = StateStore(tmp_path / ".seed-agent/state.db")
    add_intent("Inception 2026", store)
    until = datetime.now().astimezone() + timedelta(hours=4)
    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/search",
        until=until.isoformat(),
        reason="request too frequent",
    )
    payload = _wants_payload(tmp_path)
    row = payload["items"][0]
    assert row["search_status"] == "skipped_backoff"
    assert row["search_skip_reason"] == "tracker_backoff"
    assert datetime.fromisoformat(row["next_search_at"]) == until
    assert not row["search_due"]
    assert payload["due_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"kind": IntentKind.SHOW, "metadata": {"media_type": "tv"}},
        {"year": 2027},
        {"resolution": "2160p"},
        {"metadata": {"external_ids": {"douban": "99999"}}},
    ],
)
async def test_source_matching_changes_discard_stale_search_results(tmp_path, change):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)

    class ChangingProvider(Provider):
        async def search(self, searched):
            store.upsert_intent(searched.model_copy(update=change))
            return await super().search(searched)

    result = await batch(store, intent, [ChangingProvider()])
    assert result.committed == 0
    assert result.results == []
    assert store.list_release_candidates(intent.intent_id) == []
    assert store.list_want_search_runs(intent_id=intent.intent_id) == []
    assert store.get_intent(intent.intent_id)["state"] == "normalized"


@pytest.mark.asyncio
async def test_source_bookkeeping_changes_do_not_discard_search(tmp_path):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store, metadata={"external_ids": {"douban": "12345"}})

    class RefreshingProvider(Provider):
        async def search(self, searched):
            store.upsert_intent(
                searched.model_copy(
                    update={
                        "metadata": {
                            **searched.metadata,
                            "source_label": "updated",
                            "external_ids": {"douban": "https://movie.douban.com/subject/12345/"},
                        }
                    }
                )
            )
            return await super().search(searched)

    result = await batch(store, intent, [RefreshingProvider()])
    assert result.committed == 1
    assert len(result.results) == 1


@pytest.mark.asyncio
async def test_commit_skipped_during_enqueue_cannot_drive_automatic_add(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2026", store)

    class ClaimedProvider(Provider):
        async def search(self, searched):
            store.acquire_intent_enqueue_claim(searched.intent_id, "fixture", "other-owner")
            return await super().search(searched)

    save = store.save_want_search_batch

    def commit_and_release(results, **kwargs):
        count = save(results, **kwargs)
        store.release_intent_enqueue_claim(intent.intent_id, "other-owner")
        return count

    monkeypatch.setattr(store, "save_want_search_batch", commit_and_release)
    downloader = FakeDownloader()
    result = await run_intent_once(
        None, store, [ClaimedProvider()], CONFIG, SearchConfig(), downloader, POLICY, True
    )
    assert result.searched == []
    assert result.enqueue_selected == []
    assert downloader.add_calls == 0
