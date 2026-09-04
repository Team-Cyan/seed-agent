from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from seed_agent.actions.qb import enqueue_candidates
from seed_agent.config import CategoryPolicyConfig, IntentConfig, SearchConfig
from seed_agent.downloaders.base import Downloader
from seed_agent.intent.parse import parse_resource_intent
from seed_agent.models import (
    Decision,
    IntentKind,
    IntentSource,
    IntentState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
    ScoreBreakdown,
    TorrentCandidate,
)
from seed_agent.observability import get_logger, log_context, log_event
from seed_agent.policies.category_policy import PoolUsage
from seed_agent.policies.intent_ranking import filter_releases, rank_releases
from seed_agent.search.base import SearchProvider
from seed_agent.sources.base import SourceIntentEvent
from seed_agent.sources.file_inbox import read_file_inbox
from seed_agent.state import StateStore

ReleaseDownloadResolver = Callable[[ReleaseCandidate], Awaitable[ReleaseCandidate | None]]
IntentPolicyResolver = Callable[[ResourceIntent], CategoryPolicyConfig]
IntentEnqueueContextResolver = Callable[
    [ResourceIntent, CategoryPolicyConfig, ScoreBreakdown],
    tuple[bool, PoolUsage | None, list[str]],
]
logger = get_logger("intent")


@dataclass(frozen=True)
class IntentRunResult:
    ingested: list[ResourceIntent] = field(default_factory=list)
    searched: list[ResourceIntent] = field(default_factory=list)
    ranked: list[RankedRelease] = field(default_factory=list)
    enqueue_selected: list[RankedRelease] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)


@dataclass(frozen=True)
class IntentSearchBatchResult:
    results: list[tuple[ResourceIntent, list[RankedRelease]]] = field(default_factory=list)
    committed: int = 0
    diagnostics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def add_intent(
    raw_text: str,
    store: StateStore,
    *,
    source: IntentSource = IntentSource.CLI,
    requested_at: datetime | None = None,
    source_event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[ResourceIntent, Decision]:
    intent = parse_resource_intent(
        raw_text,
        source=source,
        requested_at=requested_at,
        source_event_id=source_event_id,
    )
    if metadata:
        intent = intent.model_copy(update={"metadata": _merge_metadata(intent.metadata, metadata)})
    intent = _apply_source_media_shape(intent)
    aliases = _intent_aliases(intent)
    alias_intent_ids = {
        existing_id
        for alias in aliases
        if (existing_id := store.find_intent_id_by_alias(alias)) is not None
    }
    existing = store.get_intent(intent.intent_id)
    if existing is not None:
        alias_intent_ids.add(intent.intent_id)
    canonical_id = _canonical_intent_id(store, alias_intent_ids)
    if canonical_id is not None:
        for duplicate_id in sorted(alias_intent_ids):
            if duplicate_id != canonical_id:
                store.merge_intents(canonical_id, duplicate_id)
        existing = store.get_intent(canonical_id)
        if existing is None:
            existing = store.get_intent(intent.intent_id)
        if existing is not None:
            persisted = ResourceIntent.model_validate(json.loads(str(existing["normalized_json"])))
            merged_metadata = _merge_metadata(persisted.metadata, intent.metadata)
            refreshed = _refresh_source_intent(persisted, intent, merged_metadata)
            if refreshed != persisted:
                persisted = refreshed
                store.upsert_intent(
                    persisted,
                    selected_release_id=existing["selected_release_id"],
                )
            _persist_intent_aliases_and_evidence(store, persisted, intent, source_event_id, aliases)
            return persisted, _ingest_decision(persisted, existed=True)
    existed = existing is not None
    if existing is not None:
        persisted = ResourceIntent.model_validate(json.loads(str(existing["normalized_json"])))
        if metadata:
            merged_metadata = _merge_metadata(persisted.metadata, metadata)
            refreshed = _refresh_source_intent(persisted, intent, merged_metadata)
            if refreshed != persisted:
                persisted = refreshed
                store.upsert_intent(
                    persisted,
                    selected_release_id=existing["selected_release_id"],
                )
        _persist_intent_aliases_and_evidence(store, persisted, intent, source_event_id, aliases)
        return persisted, _ingest_decision(persisted, existed=True)
    store.upsert_intent(intent)
    _persist_intent_aliases_and_evidence(store, intent, intent, source_event_id, aliases)
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
                metadata=event.metadata,
            )
        )
    return ingested


def _persist_intent_aliases_and_evidence(
    store: StateStore,
    canonical_intent: ResourceIntent,
    evidence_intent: ResourceIntent,
    source_event_id: str | None,
    aliases: list[str],
) -> None:
    for alias in aliases:
        store.upsert_intent_alias(alias, canonical_intent.intent_id)
    store.upsert_intent_source_evidence(
        intent_id=canonical_intent.intent_id,
        source=evidence_intent.source.value,
        raw_text=evidence_intent.raw_text,
        source_event_id=source_event_id,
        requested_at=evidence_intent.requested_at.isoformat(),
        metadata=evidence_intent.metadata,
    )


def _intent_aliases(intent: ResourceIntent) -> list[str]:
    aliases: list[str] = []
    external_ids = intent.metadata.get("external_ids")
    if isinstance(external_ids, dict):
        for provider in ("douban", "imdb"):
            value = external_ids.get(provider)
            if value is not None and str(value).strip():
                aliases.append(f"{provider}:{str(value).strip()}")
    source_event_id = intent.metadata.get("source_event_id")
    if isinstance(source_event_id, str) and source_event_id.startswith(("douban:", "imdb:")):
        aliases.append(source_event_id)
    return _dedupe_strings(aliases)


def _canonical_intent_id(store: StateStore, intent_ids: set[str]) -> str | None:
    rows: list[dict[str, Any]] = []
    for intent_id in intent_ids:
        row = store.get_intent(intent_id)
        if row is not None:
            rows.append(row)
    if not rows:
        return None
    rows.sort(key=_intent_order_key)
    return str(rows[0]["intent_id"])


def _intent_order_key(row: dict[str, Any]) -> tuple[str, str]:
    requested_at = ""
    try:
        normalized = json.loads(str(row.get("normalized_json") or "{}"))
    except json.JSONDecodeError:
        normalized = {}
    if isinstance(normalized, dict):
        requested_at = str(normalized.get("requested_at") or "")
    return (requested_at or str(row.get("created_at") or ""), str(row.get("intent_id") or ""))


def _merge_metadata(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = {**existing, **incoming}
    external_ids = {
        **_dict_metadata(existing.get("external_ids")),
        **_dict_metadata(incoming.get("external_ids")),
    }
    if external_ids:
        merged["external_ids"] = external_ids
    return merged


def _apply_source_media_shape(intent: ResourceIntent) -> ResourceIntent:
    """Make trusted source media classification part of the structured intent."""
    media_type = str(intent.metadata.get("media_type") or "").lower()
    if intent.kind == IntentKind.EPISODE:
        return intent
    if media_type in {"tv", "anime"}:
        return intent.model_copy(update={"kind": IntentKind.SHOW})
    if media_type == "movie":
        return intent.model_copy(update={"kind": IntentKind.MOVIE})
    return intent


def _refresh_source_intent(
    persisted: ResourceIntent,
    incoming: ResourceIntent,
    merged_metadata: dict[str, Any],
) -> ResourceIntent:
    """Repair missing parser fields when a trusted source is refreshed."""
    updates: dict[str, Any] = {"metadata": merged_metadata}
    if persisted.year is None and incoming.year is not None:
        updates["year"] = incoming.year
    if persisted.season is None and incoming.season is not None:
        updates["season"] = incoming.season
    if persisted.episode is None and incoming.episode is not None:
        updates["episode"] = incoming.episode
    return _apply_source_media_shape(persisted.model_copy(update=updates))


def _dict_metadata(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def ingest_events(
    events: Iterable[SourceIntentEvent],
    store: StateStore,
) -> list[tuple[ResourceIntent, Decision]]:
    ingested: list[tuple[ResourceIntent, Decision]] = []
    for event in events:
        ingested.append(
            add_intent(
                event.raw_text,
                store,
                source=event.source,
                requested_at=event.requested_at,
                source_event_id=event.source_event_id,
                metadata=event.metadata,
            )
        )
    return ingested


async def search_intent(
    intent_id: str,
    store: StateStore,
    providers: Iterable[SearchProvider],
    intent_config: IntentConfig,
) -> tuple[ResourceIntent, list[RankedRelease], Decision]:
    intent = _load_intent(store, intent_id)
    releases: list[ReleaseCandidate] = []
    for provider in providers:
        releases.extend(await provider.search(intent))
    releases = filter_releases(intent, releases, intent_config)
    ranked = [_unranked_candidate(intent.intent_id, release) for release in releases]
    store.save_ranked_releases(ranked, replace_intent_id=intent.intent_id)
    store.update_intent_state(intent.intent_id, IntentState.SEARCHED)
    updated_intent = intent.model_copy(update={"state": IntentState.SEARCHED})
    return updated_intent, ranked, _search_decision(intent, ranked)


def rank_intent(
    intent_id: str,
    store: StateStore,
    intent_config: IntentConfig,
    search_config: SearchConfig,
) -> tuple[ResourceIntent, list[RankedRelease], Decision]:
    intent = _load_intent(store, intent_id)
    releases = _stored_releases(store.list_release_candidates(intent.intent_id))
    ranked = rank_releases(intent, releases, intent_config, search_config)
    store.save_ranked_releases(ranked, replace_intent_id=intent.intent_id)
    next_state = _ranked_state(ranked)
    store.update_intent_state(intent.intent_id, next_state)
    return intent, ranked, _rank_decision(intent, ranked, next_state)


def reject_intent(intent_id: str, store: StateStore) -> tuple[ResourceIntent, Decision]:
    intent = _load_intent(store, intent_id)
    store.update_intent_state(intent.intent_id, IntentState.REJECTED)
    updated = intent.model_copy(update={"state": IntentState.REJECTED})
    return updated, _reject_decision(intent)


async def enqueue_intent(
    intent_id: str,
    store: StateStore,
    downloader: Downloader,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    paused: bool = False,
    pool_usage: PoolUsage | None = None,
    pause_reasons: list[str] | None = None,
    release_resolver: ReleaseDownloadResolver | None = None,
    policy_resolver: IntentPolicyResolver | None = None,
    enqueue_context_resolver: IntentEnqueueContextResolver | None = None,
    release_id: str | None = None,
) -> tuple[ResourceIntent, RankedRelease, list[Decision]]:
    intent, selected_release_id = _load_intent_with_selected(store, intent_id)
    selected_policy = policy_resolver(intent) if policy_resolver is not None else policy
    effective_release_id = (
        release_id
        if release_id is not None
        else selected_release_id
        if intent.state == IntentState.ENQUEUED
        else None
    )
    ranked = _enqueueable_release(
        intent,
        effective_release_id,
        store.list_release_candidates(intent.intent_id),
    )
    if execute and intent.state == IntentState.ENQUEUED:
        if selected_release_id and ranked.release.release_id != selected_release_id:
            raise ValueError(f"intent already enqueued with release: {selected_release_id}")
        return intent, ranked, [_enqueue_skip_decision(intent, ranked, "already enqueued")]

    claim_owner_id: str | None = None
    if execute:
        claim_owner_id = f"intent-enqueue:{uuid.uuid4().hex}"
        claim = store.acquire_intent_enqueue_claim(
            intent.intent_id,
            ranked.release.release_id,
            claim_owner_id,
            ttl_seconds=3600,
        )
        if not claim["acquired"]:
            status = str(claim.get("status") or "in_progress")
            if status == "already_enqueued":
                refreshed, _ = _load_intent_with_selected(store, intent.intent_id)
                return (
                    refreshed,
                    ranked,
                    [_enqueue_skip_decision(refreshed, ranked, "already enqueued")],
                )
            if status == "already_viewed":
                refreshed, _ = _load_intent_with_selected(store, intent.intent_id)
                return (
                    refreshed,
                    ranked,
                    [_enqueue_skip_decision(refreshed, ranked, "already viewed")],
                )
            if status == "in_progress":
                return (
                    intent,
                    ranked,
                    [_enqueue_skip_decision(intent, ranked, "enqueue already in progress")],
                )
            raise ValueError(f"unable to claim intent enqueue: {status}")

    try:
        score_breakdown = _score_breakdown_from_ranked(ranked)
        if enqueue_context_resolver is not None:
            paused, pool_usage, pause_reasons = enqueue_context_resolver(
                intent,
                selected_policy,
                score_breakdown,
            )
        if execute and (
            not paused
            and (release_resolver is not None or _requires_download_resolution(ranked.release))
        ):
            if release_resolver is None:
                raise ValueError("selected release download URL could not be resolved")
            resolved_release = await release_resolver(ranked.release)
            if resolved_release is None:
                raise ValueError("selected release download URL could not be resolved")
            ranked = ranked.model_copy(update={"release": resolved_release})
            store.save_ranked_releases([ranked])
            score_breakdown = _score_breakdown_from_ranked(ranked)
        decisions = await enqueue_candidates(
            [score_breakdown],
            downloader,
            selected_policy,
            execute,
            paused=paused,
            pool_usage=pool_usage,
            pause_reasons=pause_reasons,
        )
    except Exception:
        if claim_owner_id is not None:
            store.release_intent_enqueue_claim(intent.intent_id, claim_owner_id)
        raise
    updated = intent
    if execute and any(decision.action == "qb.enqueue" for decision in decisions):
        if claim_owner_id is None:
            raise RuntimeError("intent enqueue claim was not acquired before state commit")
        if not store.complete_intent_enqueue_claim(
            intent.intent_id,
            ranked.release.release_id,
            claim_owner_id,
        ):
            raise RuntimeError("intent enqueue claim was lost before state commit")
        # A user may have marked the item viewed after an expired claim and
        # before this enqueue completed. The store preserves that terminal
        # state, so reload it instead of returning a stale enqueued state.
        updated, _ = _load_intent_with_selected(store, intent.intent_id)
    elif claim_owner_id is not None:
        store.release_intent_enqueue_claim(intent.intent_id, claim_owner_id)
    return updated, ranked, decisions


async def run_intent_once(
    inbox_path: Path | None,
    store: StateStore,
    providers: Iterable[SearchProvider],
    intent_config: IntentConfig,
    search_config: SearchConfig,
    downloader: Downloader,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    paused: bool = False,
    pool_usage: PoolUsage | None = None,
    pause_reasons: list[str] | None = None,
    source_events: Iterable[SourceIntentEvent] = (),
    release_resolver: ReleaseDownloadResolver | None = None,
    policy_resolver: IntentPolicyResolver | None = None,
    enqueue_context_resolver: IntentEnqueueContextResolver | None = None,
    search_ingested: bool = True,
    search_limit: int | None = None,
    search_source: str = "intent-run-once",
    run_id: str | None = None,
) -> IntentRunResult:
    ingested_pairs = ingest_inbox(inbox_path, store) if inbox_path is not None else []
    ingested_pairs.extend(ingest_events(source_events, store))
    ingested = [item[0] for item in ingested_pairs]
    decisions = [item[1] for item in ingested_pairs]
    pending_search = _normalized_intents(store) if search_ingested else []
    if search_limit is not None:
        pending_search = pending_search[: max(search_limit, 0)]
    searched: list[ResourceIntent] = []
    ranked_releases: list[RankedRelease] = []
    enqueue_selected: list[RankedRelease] = []
    batch = await search_intents_batch(
        pending_search,
        store,
        providers,
        intent_config,
        search_config,
        source=search_source,
        run_id=run_id,
    )
    for intent, ranked in batch.results:
        next_state = _ranked_state(ranked)
        searched_intent = intent.model_copy(update={"state": next_state})
        searched.append(searched_intent)
        decisions.append(_search_decision(intent, ranked))
        ranked_releases.extend(ranked)
        decisions.append(_rank_decision(intent, ranked, next_state))

        if ranked and ranked[0].accepted and not ranked[0].confirmation_required:
            _, selected, enqueue_decisions = await enqueue_intent(
                searched_intent.intent_id,
                store,
                downloader,
                policy,
                execute,
                paused=paused,
                pool_usage=pool_usage,
                pause_reasons=pause_reasons,
                release_resolver=release_resolver,
                policy_resolver=policy_resolver,
                enqueue_context_resolver=enqueue_context_resolver,
            )
            enqueue_selected.append(selected)
            decisions.extend(enqueue_decisions)

    return IntentRunResult(
        ingested=ingested,
        searched=searched,
        ranked=ranked_releases,
        enqueue_selected=enqueue_selected,
        decisions=decisions,
    )


async def search_intents_batch(
    intents: Iterable[ResourceIntent],
    store: StateStore,
    providers: Iterable[SearchProvider],
    intent_config: IntentConfig,
    search_config: SearchConfig,
    *,
    source: str,
    run_id: str | None = None,
) -> IntentSearchBatchResult:
    """Search and rank a batch before atomically replacing its persisted state."""
    results: list[tuple[ResourceIntent, list[RankedRelease]]] = []
    provider_list = list(providers)
    unique_intents = _dedupe_intents_by_id(intents)
    summaries: dict[str, dict[str, Any]] = {}
    diagnostic_offsets = {
        id(provider): len(getattr(provider, "search_diagnostics", []))
        for provider in provider_list
        if isinstance(getattr(provider, "search_diagnostics", None), list)
    }
    started = time.monotonic()
    current_intent_id: str | None = None
    stage = "search"
    log_event(
        logger,
        logging.INFO,
        "intent.search_batch.started",
        source=source,
        run_id=run_id,
        intent_count=len(unique_intents),
        provider_count=len(provider_list),
    )
    try:
        for intent in unique_intents:
            current_intent_id = intent.intent_id
            stage = "search"
            log_event(
                logger,
                logging.DEBUG,
                "intent.search.started",
                source=source,
                intent_id=intent.intent_id,
                kind=intent.kind.value,
                media_type=intent.metadata.get("media_type"),
                external_id_providers=sorted(
                    str(provider)
                    for provider in _dict_metadata(intent.metadata.get("external_ids"))
                    if provider in {"douban", "imdb"}
                ),
            )
            releases: list[ReleaseCandidate] = []
            for provider in provider_list:
                provider_name = type(provider).__name__
                log_event(
                    logger,
                    logging.DEBUG,
                    "intent.search.provider_started",
                    intent_id=intent.intent_id,
                    provider=provider_name,
                )
                with log_context(run_id=run_id, intent_id=intent.intent_id, source=source):
                    provider_releases = await provider.search(intent)
                releases.extend(provider_releases)
                log_event(
                    logger,
                    logging.DEBUG,
                    "intent.search.provider_completed",
                    intent_id=intent.intent_id,
                    provider=provider_name,
                    release_count=len(provider_releases),
                )
            stage = "rank"
            with log_context(run_id=run_id, intent_id=intent.intent_id, source=source):
                ranked = rank_releases(intent, releases, intent_config, search_config)
            results.append((intent, ranked))
            summaries[intent.intent_id] = {
                "kind": intent.kind.value,
                "media_type": intent.metadata.get("media_type"),
                "series_search_mode": intent_config.series_search_mode,
                "release_count": len(releases),
                "ranked_count": len(ranked),
                "filtered_count": len(releases) - len(ranked),
                "accepted_count": sum(item.accepted for item in ranked),
            }
            log_event(
                logger,
                logging.INFO,
                "intent.search.completed",
                intent_id=intent.intent_id,
                source=source,
                run_id=run_id,
                **summaries[intent.intent_id],
            )
        diagnostics = _provider_search_diagnostics(provider_list, diagnostic_offsets)
        stage = "persist"
        current_intent_id = None
        committed = store.save_want_search_batch(
            results,
            source=source,
            run_id=run_id,
            history_payloads={
                intent.intent_id: {
                    "provider_diagnostics": diagnostics.get(intent.intent_id, []),
                    "search_summary": summaries[intent.intent_id],
                }
                for intent, _ in results
            },
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "intent.search_batch.failed",
            source=source,
            run_id=run_id,
            completed_intents=len(results),
            total_intents=len(unique_intents),
            intent_id=current_intent_id,
            stage=stage,
            error_type=type(exc).__name__,
            error=str(exc),
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        raise
    log_event(
        logger,
        logging.INFO,
        "intent.search_batch.persisted",
        source=source,
        run_id=run_id,
        requested_intents=len(unique_intents),
        committed_intents=committed,
        diagnostic_intents=len(diagnostics),
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    return IntentSearchBatchResult(
        results=results,
        committed=committed,
        diagnostics=diagnostics,
    )


def _provider_search_diagnostics(
    providers: list[SearchProvider],
    offsets: dict[int, int],
) -> dict[str, list[dict[str, Any]]]:
    """Return a redaction-safe per-intent diagnostic summary for durable history."""
    by_intent: dict[str, list[dict[str, Any]]] = {}
    for provider in providers:
        rows = getattr(provider, "search_diagnostics", None)
        if not isinstance(rows, list):
            continue
        for row in rows[offsets.get(id(provider), 0) :]:
            if not isinstance(row, dict):
                continue
            intent_id = row.get("intent_id")
            if not isinstance(intent_id, str) or not intent_id:
                continue
            attempts = row.get("attempts")
            safe_attempts = []
            if isinstance(attempts, list):
                for attempt in attempts:
                    if not isinstance(attempt, dict):
                        continue
                    safe_attempts.append(
                        {
                            key: attempt[key]
                            for key in (
                                "query_path",
                                "status",
                                "result_count",
                                "code",
                                "rate_limited",
                                "retriable",
                                "unavailable",
                            )
                            if key in attempt
                        }
                    )
            by_intent.setdefault(intent_id, []).append(
                {
                    "provider": type(provider).__name__,
                    "site": row.get("site"),
                    "request_budget": row.get("request_budget"),
                    "requests_used": row.get("requests_used"),
                    "release_count": row.get("release_count"),
                    "attempts": safe_attempts,
                }
            )
    return by_intent


def _normalized_intents(store: StateStore) -> list[ResourceIntent]:
    return [
        ResourceIntent.model_validate(json.loads(str(row["normalized_json"])))
        for row in store.list_intents_by_state(IntentState.NORMALIZED)
    ]


def _dedupe_intents_by_id(intents: Iterable[ResourceIntent]) -> list[ResourceIntent]:
    unique: list[ResourceIntent] = []
    seen: set[str] = set()
    for intent in intents:
        if intent.intent_id in seen:
            continue
        unique.append(intent)
        seen.add(intent.intent_id)
    return unique


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
    release_id: str | None,
    rows: list[dict[str, Any]],
) -> RankedRelease:
    ranked = _stored_ranked(rows)
    if intent.state == IntentState.REJECTED:
        raise ValueError(f"intent is rejected: {intent.intent_id}")
    if intent.state == IntentState.VIEWED:
        raise ValueError(f"intent is already viewed: {intent.intent_id}")
    if release_id is not None:
        selected = next(
            (item for item in ranked if item.release.release_id == release_id),
            None,
        )
        if selected is None:
            raise ValueError(f"unknown release for intent: {release_id}")
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


def _enqueue_skip_decision(
    intent: ResourceIntent,
    ranked: RankedRelease,
    reason: str,
) -> Decision:
    return Decision(
        action="qb.enqueue.skip",
        target_id=ranked.release.release_id,
        execute=True,
        reason=reason,
        old_state={"intent_state": intent.state.value},
        new_state={
            "intent_id": intent.intent_id,
            "release_id": ranked.release.release_id,
            "mutated": False,
        },
    )


def _requires_download_resolution(release: ReleaseCandidate) -> bool:
    return (
        release.download_url.startswith("mteam-api://")
        or release.metadata.get("download_url_source") == "mteam_api_deferred"
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


def _reject_decision(intent: ResourceIntent) -> Decision:
    return Decision(
        action="intent.reject",
        target_id=intent.intent_id,
        execute=True,
        reason="intent rejected by operator",
        old_state={"state": intent.state.value},
        new_state={"state": IntentState.REJECTED.value},
        confirmation_required=False,
    )
