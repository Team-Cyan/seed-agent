from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seed_agent.config import IntentConfig, SearchConfig
from seed_agent.intent.parse import parse_resource_intent
from seed_agent.models import (
    Decision,
    IntentSource,
    IntentState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
)
from seed_agent.policies.intent_ranking import rank_releases
from seed_agent.search.base import SearchProvider
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
    for event in _read_jsonl(path):
        raw_text = _event_text(event)
        if raw_text is None:
            continue
        source_event_id = _event_id(event)
        ingested.append(
            add_intent(
                raw_text,
                store,
                source=source,
                requested_at=_event_requested_at(event) or requested_at,
                source_event_id=source_event_id,
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
    row = store.get_intent(intent_id)
    if row is None:
        raise ValueError(f"unknown intent: {intent_id}")
    return ResourceIntent.model_validate(json.loads(str(row["normalized_json"])))


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


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            yield loaded


def _event_text(event: dict[str, Any]) -> str | None:
    for key in ("raw_text", "text", "message", "title"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _event_id(event: dict[str, Any]) -> str | None:
    for key in ("source_event_id", "event_id", "id"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _event_requested_at(event: dict[str, Any]) -> datetime | None:
    value = event.get("requested_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
