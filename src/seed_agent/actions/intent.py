from __future__ import annotations

import json
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
    IntentSource,
    IntentState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
    ScoreBreakdown,
    TorrentCandidate,
)
from seed_agent.policies.category_policy import PoolUsage
from seed_agent.policies.intent_ranking import rank_releases
from seed_agent.search.base import SearchProvider
from seed_agent.sources.base import SourceIntentEvent
from seed_agent.sources.file_inbox import read_file_inbox
from seed_agent.state import StateStore

ReleaseDownloadResolver = Callable[[ReleaseCandidate], Awaitable[ReleaseCandidate | None]]


@dataclass(frozen=True)
class IntentRunResult:
    ingested: list[ResourceIntent] = field(default_factory=list)
    searched: list[ResourceIntent] = field(default_factory=list)
    ranked: list[RankedRelease] = field(default_factory=list)
    enqueue_selected: list[RankedRelease] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)


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
            if merged_metadata != persisted.metadata:
                persisted = persisted.model_copy(update={"metadata": merged_metadata})
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
            if merged_metadata != persisted.metadata:
                persisted = persisted.model_copy(update={"metadata": merged_metadata})
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


def _record_release_external_aliases(
    store: StateStore,
    intent: ResourceIntent,
    releases: list[ReleaseCandidate],
) -> ResourceIntent:
    merged_ids = _dict_metadata(intent.metadata.get("external_ids"))
    for release in releases:
        release_ids = _dict_metadata(release.metadata.get("external_ids"))
        if release_ids:
            merged_ids.update(release_ids)
    if not merged_ids:
        return intent
    aliases = [f"{provider}:{value}" for provider, value in merged_ids.items() if value]
    existing_ids = {
        existing_id
        for alias in aliases
        if (existing_id := store.find_intent_id_by_alias(alias)) is not None
    }
    existing_ids.add(intent.intent_id)
    canonical_id = _canonical_intent_id(store, existing_ids) or intent.intent_id
    for duplicate_id in sorted(existing_ids):
        if duplicate_id != canonical_id:
            store.merge_intents(canonical_id, duplicate_id)
    for alias in aliases:
        store.upsert_intent_alias(alias, canonical_id)
    row = store.get_intent(canonical_id)
    if row is None:
        return intent
    canonical = ResourceIntent.model_validate(json.loads(str(row["normalized_json"])))
    if merged_ids != canonical.metadata.get("external_ids"):
        updated = canonical.model_copy(
            update={"metadata": _merge_metadata(canonical.metadata, {"external_ids": merged_ids})}
        )
        store.upsert_intent(
            updated,
            selected_release_id=row["selected_release_id"],
        )
        return updated
    return canonical


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
) -> tuple[ResourceIntent, list[RankedRelease], Decision]:
    intent = _load_intent(store, intent_id)
    releases: list[ReleaseCandidate] = []
    for provider in providers:
        releases.extend(await provider.search(intent))
    canonical_intent = _record_release_external_aliases(store, intent, releases)
    ranked = [_unranked_candidate(canonical_intent.intent_id, release) for release in releases]
    store.save_ranked_releases(ranked)
    store.update_intent_state(canonical_intent.intent_id, IntentState.SEARCHED)
    updated_intent = canonical_intent.model_copy(update={"state": IntentState.SEARCHED})
    return updated_intent, ranked, _search_decision(canonical_intent, ranked)


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
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    paused: bool = False,
    pool_usage: PoolUsage | None = None,
    pause_reasons: list[str] | None = None,
    release_resolver: ReleaseDownloadResolver | None = None,
) -> tuple[ResourceIntent, RankedRelease, list[Decision]]:
    intent, selected_release_id = _load_intent_with_selected(store, intent_id)
    ranked = _enqueueable_release(
        intent,
        selected_release_id,
        store.list_release_candidates(intent.intent_id),
    )
    if execute and (release_resolver is not None or _requires_download_resolution(ranked.release)):
        if release_resolver is None:
            raise ValueError("selected release download URL could not be resolved")
        resolved_release = await release_resolver(ranked.release)
        if resolved_release is None:
            raise ValueError("selected release download URL could not be resolved")
        ranked = ranked.model_copy(update={"release": resolved_release})
        store.save_ranked_releases([ranked])
    decisions = await enqueue_candidates(
        [_score_breakdown_from_ranked(ranked)],
        downloader,
        policy,
        execute,
        paused=paused,
        pool_usage=pool_usage,
        pause_reasons=pause_reasons,
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
) -> IntentRunResult:
    ingested_pairs = ingest_inbox(inbox_path, store) if inbox_path is not None else []
    ingested_pairs.extend(ingest_events(source_events, store))
    ingested = [item[0] for item in ingested_pairs]
    decisions = [item[1] for item in ingested_pairs]
    pending_search = _dedupe_intents_by_id(ingested)
    searched: list[ResourceIntent] = []
    ranked_releases: list[RankedRelease] = []
    enqueue_selected: list[RankedRelease] = []
    provider_list = list(providers)
    for intent in pending_search:
        searched_intent, _, search_decision = await search_intent(
            intent.intent_id,
            store,
            provider_list,
        )
        searched.append(searched_intent)
        decisions.append(search_decision)

        _, ranked, rank_decision = rank_intent(
            searched_intent.intent_id,
            store,
            intent_config,
            search_config,
        )
        ranked_releases.extend(ranked)
        decisions.append(rank_decision)

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
