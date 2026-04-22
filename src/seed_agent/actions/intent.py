from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from seed_agent.actions.qb import enqueue_candidates
from seed_agent.config import IntentConfig, SearchConfig
from seed_agent.downloaders.base import Downloader
from seed_agent.intent.parse import parse_resource_intent
from seed_agent.models import (
    Decision,
    IntentSource,
    IntentState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
    ScoreBreakdown,
    TorrentCandidate,
)
from seed_agent.policies.intent_ranking import rank_releases
from seed_agent.search.base import SearchProvider
from seed_agent.sources.file_inbox import read_file_inbox
from seed_agent.state import StateStore


def add_intent(
    raw_text: str,
    store: StateStore,
    *,
    source: IntentSource = IntentSource.CLI,
    requested_at: datetime | None = None,
    source_event_id: str | None = None,
) -> tuple[ResourceIntent, Decision]:
    intent = parse_resource_intent(
        raw_text,
        source=source,
        requested_at=requested_at,
        source_event_id=source_event_id,
    )
    existed = store.get_intent(intent.intent_id) is not None
    store.upsert_intent(intent)
    return intent, _ingest_decision(intent, existed=existed)


def ingest_inbox(
    path: Path,
    store: StateStore,
    *,
    source: IntentSource = IntentSource.FILE_INBOX,
    requested_at: datetime | None = None,
) -> list[tuple[ResourceIntent, Decision]]:
    if not path.is_file():
        return []

    ingested: list[tuple[ResourceIntent, Decision]] = []
    for event in read_file_inbox(path):
        ingested.append(
            add_intent(
                event.raw_text,
                store,
                source=source if source != IntentSource.FILE_INBOX else event.source,
                requested_at=event.requested_at or requested_at,
                source_event_id=event.source_event_id,
            )
        )
    return ingested


async def search_intent(
    intent_id: str,
    store: StateStore,
    providers: Iterable[SearchProvider],
) -> tuple[ResourceIntent, list[RankedRelease], Decision]:
    intent = _load_intent(store, intent_id)
    releases: list[ReleaseCandidate] = []
    for provider in providers:
        releases.extend(await provider.search(intent))
    ranked = [_unranked_candidate(intent.intent_id, release) for release in releases]
    store.save_ranked_releases(ranked)
    store.update_intent_state(intent.intent_id, IntentState.SEARCHED)
    return intent, ranked, _search_decision(intent, ranked)


def rank_intent(
    intent_id: str,
    store: StateStore,
    intent_config: IntentConfig,
    search_config: SearchConfig,
) -> tuple[ResourceIntent, list[RankedRelease], Decision]:
    intent = _load_intent(store, intent_id)
    releases = _stored_releases(store.list_release_candidates(intent.intent_id))
    ranked = rank_releases(intent, releases, intent_config, search_config)
    store.save_ranked_releases(ranked)
    next_state = _ranked_state(ranked)
    store.update_intent_state(intent.intent_id, next_state)
    return intent, ranked, _rank_decision(intent, ranked, next_state)


def confirm_intent(
    intent_id: str,
    release_id: str,
    store: StateStore,
) -> tuple[ResourceIntent, RankedRelease, Decision]:
    intent = _load_intent(store, intent_id)
    ranked = _find_ranked_release(store.list_release_candidates(intent.intent_id), release_id)
    if ranked is None:
        raise ValueError(f"unknown release for intent: {release_id}")
    store.update_intent_state(
        intent.intent_id,
        IntentState.CONFIRMED,
        selected_release_id=ranked.release.release_id,
    )
    updated = intent.model_copy(update={"state": IntentState.CONFIRMED})
    return updated, ranked, _confirm_decision(intent, ranked)


def reject_intent(intent_id: str, store: StateStore) -> tuple[ResourceIntent, Decision]:
    intent = _load_intent(store, intent_id)
    store.update_intent_state(intent.intent_id, IntentState.REJECTED)
    updated = intent.model_copy(update={"state": IntentState.REJECTED})
    return updated, _reject_decision(intent)


async def enqueue_intent(
    intent_id: str,
    store: StateStore,
    downloader: Downloader,
    category: str,
    tags: Iterable[str],
    execute: bool,
) -> tuple[ResourceIntent, RankedRelease, list[Decision]]:
    intent, selected_release_id = _load_intent_with_selected(store, intent_id)
    ranked = _enqueueable_release(
        intent,
        selected_release_id,
        store.list_release_candidates(intent.intent_id),
    )
    decisions = await enqueue_candidates(
        [_score_breakdown_from_ranked(ranked)],
        downloader,
        category,
        list(tags),
        execute,
    )
    updated = intent
    if execute and any(decision.action == "qb.enqueue" for decision in decisions):
        store.update_intent_state(
            intent.intent_id,
            IntentState.ENQUEUED,
            selected_release_id=ranked.release.release_id,
        )
        updated = intent.model_copy(update={"state": IntentState.ENQUEUED})
    return updated, ranked, decisions


def review_intents(
    store: StateStore,
    *,
    states: Iterable[IntentState] = (
        IntentState.NORMALIZED,
        IntentState.SEARCHED,
        IntentState.CONFIRMATION_REQUIRED,
    ),
) -> list[tuple[ResourceIntent, list[RankedRelease]]]:
    reviewable: list[tuple[ResourceIntent, list[RankedRelease]]] = []
    for state in states:
        for row in store.list_intents_by_state(state):
            intent = ResourceIntent.model_validate(json.loads(str(row["normalized_json"])))
            ranked = _stored_ranked(store.list_release_candidates(intent.intent_id))
            reviewable.append((intent, ranked))
    return reviewable


def _ingest_decision(intent: ResourceIntent, *, existed: bool) -> Decision:
    return Decision(
        action="intent.ingest",
        target_id=intent.intent_id,
        execute=True,
        reason="intent already existed" if existed else "intent ingested",
        new_state={
            "intent_id": intent.intent_id,
            "source": intent.source.value,
            "title": intent.title,
            "kind": intent.kind.value,
            "state": intent.state.value,
            "existed": existed,
        },
    )


def _load_intent(store: StateStore, intent_id: str) -> ResourceIntent:
    intent, _ = _load_intent_with_selected(store, intent_id)
    return intent


def _load_intent_with_selected(
    store: StateStore,
    intent_id: str,
) -> tuple[ResourceIntent, str | None]:
    row = store.get_intent(intent_id)
    if row is None:
        raise ValueError(f"unknown intent: {intent_id}")
    intent = ResourceIntent.model_validate(json.loads(str(row["normalized_json"])))
    selected = row["selected_release_id"]
    return intent, str(selected) if selected is not None else None


def _unranked_candidate(intent_id: str, release: ReleaseCandidate) -> RankedRelease:
    return RankedRelease(
        intent_id=intent_id,
        release=release,
        score=0,
        confidence=0,
        accepted=False,
        confirmation_required=True,
        reasons=["release candidate found"],
        risks=[],
    )


def _stored_releases(rows: list[dict[str, Any]]) -> list[ReleaseCandidate]:
    releases: list[ReleaseCandidate] = []
    for row in rows:
        payload = json.loads(str(row["release_json"]))
        if isinstance(payload, dict) and "release" in payload:
            releases.append(ReleaseCandidate.model_validate(payload["release"]))
        elif isinstance(payload, dict):
            releases.append(ReleaseCandidate.model_validate(payload))
    return releases


def _stored_ranked(rows: list[dict[str, Any]]) -> list[RankedRelease]:
    ranked: list[RankedRelease] = []
    for row in rows:
        payload = json.loads(str(row["release_json"]))
        if isinstance(payload, dict) and "release" in payload:
            ranked.append(RankedRelease.model_validate(payload))
    return ranked


def _find_ranked_release(rows: list[dict[str, Any]], release_id: str) -> RankedRelease | None:
    for ranked in _stored_ranked(rows):
        if ranked.release.release_id == release_id:
            return ranked
    return None


def _enqueueable_release(
    intent: ResourceIntent,
    selected_release_id: str | None,
    rows: list[dict[str, Any]],
) -> RankedRelease:
    ranked = _stored_ranked(rows)
    if intent.state == IntentState.REJECTED:
        raise ValueError(f"intent is rejected: {intent.intent_id}")
    if selected_release_id is not None:
        selected = next(
            (item for item in ranked if item.release.release_id == selected_release_id),
            None,
        )
        if selected is None:
            raise ValueError(f"selected release is missing: {selected_release_id}")
        return selected
    for item in ranked:
        if item.accepted and not item.confirmation_required:
            return item
    if ranked:
        raise ValueError("intent requires confirmation before enqueue")
    raise ValueError("intent has no release candidates")


def _score_breakdown_from_ranked(ranked: RankedRelease) -> ScoreBreakdown:
    release = ranked.release
    candidate = TorrentCandidate(
        site=release.site,
        title=release.title,
        source_url=release.source_url,
        download_url=release.download_url,
        size_bytes=release.size_bytes,
        seeders=release.seeders,
        leechers=release.leechers,
        discount=release.discount,
        left_time_minutes=None,
        hr=bool(release.metadata.get("hr", False)),
        published_at=release.published_at,
        metadata=release.metadata,
    )
    return ScoreBreakdown(
        candidate_id=release.release_id,
        score=ranked.score,
        accepted=True,
        reasons=[*ranked.reasons, "selected for intent enqueue"],
        candidate=candidate,
    )


def _ranked_state(ranked: list[RankedRelease]) -> IntentState:
    if not ranked:
        return IntentState.CONFIRMATION_REQUIRED
    if ranked[0].confirmation_required:
        return IntentState.CONFIRMATION_REQUIRED
    return IntentState.SEARCHED


def _search_decision(intent: ResourceIntent, ranked: list[RankedRelease]) -> Decision:
    return Decision(
        action="intent.search",
        target_id=intent.intent_id,
        execute=True,
        reason="release candidates searched",
        old_state={"state": intent.state.value},
        new_state={
            "state": IntentState.SEARCHED.value,
            "candidate_count": len(ranked),
            "sites": sorted({item.release.site for item in ranked}),
        },
    )


def _rank_decision(
    intent: ResourceIntent,
    ranked: list[RankedRelease],
    next_state: IntentState,
) -> Decision:
    top = ranked[0] if ranked else None
    return Decision(
        action="intent.rank",
        target_id=intent.intent_id,
        execute=True,
        reason="release candidates ranked" if ranked else "no release candidates to rank",
        old_state={"state": intent.state.value},
        new_state={
            "state": next_state.value,
            "candidate_count": len(ranked),
            "top_release_id": top.release.release_id if top is not None else None,
            "top_score": top.score if top is not None else None,
            "confirmation_required": top.confirmation_required if top is not None else True,
        },
        confirmation_required=top.confirmation_required if top is not None else True,
    )


def _confirm_decision(intent: ResourceIntent, ranked: RankedRelease) -> Decision:
    return Decision(
        action="intent.confirm",
        target_id=intent.intent_id,
        execute=True,
        reason="intent release confirmed",
        old_state={"state": intent.state.value},
        new_state={
            "state": IntentState.CONFIRMED.value,
            "selected_release_id": ranked.release.release_id,
            "release_title": ranked.release.title,
            "site": ranked.release.site,
            "score": ranked.score,
            "confidence": ranked.confidence,
        },
        confirmation_required=False,
        confirmation_received=True,
    )


def _reject_decision(intent: ResourceIntent) -> Decision:
    return Decision(
        action="intent.reject",
        target_id=intent.intent_id,
        execute=True,
        reason="intent rejected by operator",
        old_state={"state": intent.state.value},
        new_state={"state": IntentState.REJECTED.value},
        confirmation_required=False,
        confirmation_received=True,
    )

