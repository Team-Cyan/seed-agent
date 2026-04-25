from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from seed_agent.actions.intent import (
    add_intent,
    confirm_intent,
    enqueue_intent,
    ingest_inbox,
    rank_intent,
    reject_intent,
    review_intents,
    run_intent_once,
    search_intent,
)
from seed_agent.actions.pt import daily_report as build_daily_report
from seed_agent.actions.pt import discover_candidates, score_candidates
from seed_agent.actions.qb import MutationBatchError, enqueue_candidates, prune_cold_torrents
from seed_agent.audit import AuditLogger, redact_payload
from seed_agent.config import (
    CategoryPolicyConfig,
    SeedAgentConfig,
    load_config,
    load_downloader_secret,
)
from seed_agent.downloaders.qbittorrent import QbittorrentClient
from seed_agent.models import (
    Decision,
    IntentSource,
    LifecycleState,
    ManagedTorrent,
    RankedRelease,
    ResourceIntent,
    ScoreBreakdown,
    TorrentCandidate,
    safe_url_identity,
)
from seed_agent.policies.category_policy import usage_by_pool
from seed_agent.search.rss import RssSearchProvider
from seed_agent.state import StateStore

app = typer.Typer(help="AI-first PT and downloader operations toolkit.")
DEFAULT_CONFIG = Path("config/example.yaml")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Seed Agent CLI."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def discover(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _run(discover_candidates(loaded))
    payload = {
        "command": "discover",
        "config": str(config),
        "discovered": len(candidates),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
    }
    _print_json(payload)


@app.command(name="site-probe")
def site_probe(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _run(discover_candidates(loaded))

    summary_by_site: dict[str, dict[str, Any]] = {}
    for site in loaded.enabled_sites:
        summary_by_site[site.name] = {
            "site_type": site.type,
            "rss_url_configured": bool(site.rss_url),
            "access_mode": _site_access_mode(site, loaded.config_dir),
            "discovery_mode": _site_discovery_mode(site),
            "discovered": 0,
            "sparse": 0,
            "detail_enriched": 0,
            "sample_titles": [],
        }

    for candidate in candidates:
        site_summary = summary_by_site.setdefault(
            candidate.site,
            {
                "site_type": "unknown",
                "rss_url_configured": True,
                "access_mode": "anonymous",
                "discovery_mode": "rss",
                "discovered": 0,
                "sparse": 0,
                "detail_enriched": 0,
                "sample_titles": [],
            },
        )
        site_summary["discovered"] += 1
        if candidate.metadata.get("rss_sparse_candidate"):
            site_summary["sparse"] += 1
        if candidate.metadata.get("mteam_detail_enriched"):
            site_summary["detail_enriched"] += 1
        sample_titles = site_summary["sample_titles"]
        if len(sample_titles) < 3:
            sample_titles.append(candidate.title)

    payload = {
        "command": "site-probe",
        "config": str(config),
        "sites": summary_by_site,
    }
    _print_json(payload)


@app.command()
def score(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _run(discover_candidates(loaded))
    scored = score_candidates(candidates, loaded.discovery, loaded.scoring)
    payload = {
        "command": "score",
        "config": str(config),
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "rejected": sum(1 for item in scored if not item.accepted),
        "scores": [_score_summary(item) for item in scored],
    }
    _print_json(payload)


@app.command()
def enqueue(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    candidates = _run(discover_candidates(loaded))
    scored = score_candidates(candidates, loaded.discovery, loaded.scoring)
    downloader = build_downloader(loaded) if execute else _NullDownloader()
    batch_error = None
    try:
        decisions = _run(
            enqueue_candidates(
                scored,
                downloader,
                loaded.downloader.category,
                loaded.downloader.tags,
                execute,
            )
        )
    except MutationBatchError as exc:
        decisions = exc.decisions
        batch_error = exc
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "enqueue",
        "config": str(config),
        "execute": execute,
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "enqueued": sum(1 for item in decisions if item.action == "qb.enqueue"),
        "scores": [_score_summary(item) for item in scored],
        "decisions": [_decision_summary(item) for item in decisions],
    }
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _print_json(payload)
    _raise_if_batch_failed(batch_error)


@app.command(name="intent-add")
def intent_add(
    text: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    intent, decision = add_intent(text, store)
    _write_audit_decisions(loaded, [decision])
    payload = {
        "command": "intent-add",
        "config": str(config),
        "intent": _intent_summary(intent),
        "decision": _decision_summary(decision),
    }
    _print_json(payload)


@app.command(name="intent-inbox")
def intent_inbox(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    inbox_path = _resolve_path(loaded.intent.inbox_ref, loaded.config_dir)
    if inbox_path is None:
        intents_and_decisions = []
    else:
        intents_and_decisions = ingest_inbox(
            inbox_path,
            store,
            source=IntentSource.FILE_INBOX,
        )
    intents = [item[0] for item in intents_and_decisions]
    decisions = [item[1] for item in intents_and_decisions]
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "intent-inbox",
        "config": str(config),
        "inbox_ref": loaded.intent.inbox_ref,
        "ingested": len(intents),
        "intents": [_intent_summary(intent) for intent in intents],
        "decisions": [_decision_summary(decision) for decision in decisions],
    }
    _print_json(payload)


@app.command(name="intent-search")
def intent_search(
    intent_id: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    providers = _build_search_providers(loaded)
    try:
        intent, ranked, decision = _run(search_intent(intent_id, store, providers))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _write_audit_decisions(loaded, [decision])
    payload = {
        "command": "intent-search",
        "config": str(config),
        "intent": _intent_summary(intent),
        "found": len(ranked),
        "candidates": [_ranked_release_summary(item) for item in ranked],
        "decision": _decision_summary(decision),
    }
    _print_json(payload)


@app.command(name="intent-rank")
def intent_rank(
    intent_id: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    try:
        intent, ranked, decision = rank_intent(intent_id, store, loaded.intent, loaded.search)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _write_audit_decisions(loaded, [decision])
    payload = {
        "command": "intent-rank",
        "config": str(config),
        "intent": _intent_summary(intent),
        "ranked": len(ranked),
        "candidates": [_ranked_release_summary(item) for item in ranked],
        "decision": _decision_summary(decision),
    }
    _print_json(payload)


@app.command(name="intent-review")
def intent_review(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    reviewable = review_intents(store)
    payload = {
        "command": "intent-review",
        "config": str(config),
        "count": len(reviewable),
        "intents": [
            {
                "intent": _intent_summary(intent),
                "candidate_count": len(candidates),
                "candidates": [_ranked_release_summary(item) for item in candidates],
            }
            for intent, candidates in reviewable
        ],
    }
    _print_json(payload)


@app.command(name="intent-confirm")
def intent_confirm(
    intent_id: Annotated[str, typer.Argument()],
    release_id: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    try:
        intent, ranked, decision = confirm_intent(intent_id, release_id, store)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _write_audit_decisions(loaded, [decision])
    payload = {
        "command": "intent-confirm",
        "config": str(config),
        "intent": _intent_summary(intent),
        "selected": _ranked_release_summary(ranked),
        "decision": _decision_summary(decision),
    }
    _print_json(payload)


@app.command(name="intent-reject")
def intent_reject(
    intent_id: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    try:
        intent, decision = reject_intent(intent_id, store)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _write_audit_decisions(loaded, [decision])
    payload = {
        "command": "intent-reject",
        "config": str(config),
        "intent": _intent_summary(intent),
        "decision": _decision_summary(decision),
    }
    _print_json(payload)


@app.command(name="intent-enqueue")
def intent_enqueue(
    intent_id: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    downloader = build_downloader(loaded) if execute else _NullDownloader()
    default_policy = _default_category_policy(loaded)
    paused = _default_category_paused(loaded, downloader if execute else None)
    batch_error = None
    try:
        intent, ranked, decisions = _run(
            enqueue_intent(
                intent_id,
                store,
                downloader,
                default_policy,
                execute,
                paused=paused,
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except MutationBatchError as exc:
        intent = None
        ranked = None
        decisions = exc.decisions
        batch_error = exc
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "intent-enqueue",
        "config": str(config),
        "execute": execute,
        "intent": _intent_summary(intent) if intent is not None else None,
        "selected": _ranked_release_summary(ranked) if ranked is not None else None,
        "enqueued": sum(1 for item in decisions if item.action == "qb.enqueue"),
        "decisions": [_decision_summary(item) for item in decisions],
    }
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _print_json(payload)
    _raise_if_batch_failed(batch_error)


@app.command(name="intent-run-once")
def intent_run_once(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    providers = _build_search_providers(loaded)
    inbox_path = _resolve_path(loaded.intent.inbox_ref, loaded.config_dir)
    downloader = build_downloader(loaded) if execute else _NullDownloader()
    default_policy = _default_category_policy(loaded)
    paused = _default_category_paused(loaded, downloader if execute else None)
    batch_error = None
    try:
        result = _run(
            run_intent_once(
                inbox_path=inbox_path,
                store=store,
                providers=providers,
                intent_config=loaded.intent,
                search_config=loaded.search,
                downloader=downloader,
                policy=default_policy,
                execute=execute,
                paused=paused,
            )
        )
        decisions = result.decisions
    except MutationBatchError as exc:
        result = None
        decisions = exc.decisions
        batch_error = exc
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "intent-run-once",
        "config": str(config),
        "execute": execute,
        "ingested": len(result.ingested) if result is not None else 0,
        "searched": len(result.searched) if result is not None else 0,
        "ranked": len(result.ranked) if result is not None else 0,
        "enqueue_candidates": len(result.enqueue_selected) if result is not None else 0,
        "decisions": [_decision_summary(item) for item in decisions],
    }
    if result is not None:
        payload["intents"] = [_intent_summary(intent) for intent in result.searched]
        payload["selected"] = [
            _ranked_release_summary(item) for item in result.enqueue_selected
        ]
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _print_json(payload)
    _raise_if_batch_failed(batch_error)


@app.command()
def review(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    downloader = _maybe_build_downloader(loaded)
    if downloader is None:
        payload = {
            "command": "review",
            "config": str(config),
            "managed_torrents": [],
            "managed_count": 0,
            "note": "qB secret missing or unreadable",
        }
        _print_json(payload)
        return

    policy_lookup = _policy_lookup(loaded)
    torrents = _load_policy_torrents(downloader, loaded)
    torrents = store.apply_torrent_runtime(torrents)
    payload = {
        "command": "review",
        "config": str(config),
        "managed_count": len(torrents),
        "pool_usage": _pool_usage_summary(loaded, torrents),
        "managed_torrents": [
            _managed_torrent_summary(torrent, policy_lookup.get(torrent.category or ""))
            for torrent in torrents
        ],
    }
    _print_json(payload)


@app.command()
def prune(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    mutable_policies = [
        policy
        for policy in loaded.downloader.category_policies
        if policy.mode == "mutable" and policy.delete_enabled
    ]
    if execute:
        downloader = build_downloader(loaded)
    else:
        downloader = _maybe_build_downloader(loaded)
        if downloader is None:
            downloader = _NullDownloader()
    torrents = _load_policy_torrents(downloader, loaded, policies=mutable_policies)
    torrents = store.apply_torrent_runtime(torrents)
    batch_error = None
    decisions: list[Decision] = []
    torrents_by_category: dict[str, list[ManagedTorrent]] = {}
    for torrent in torrents:
        if torrent.category is None:
            continue
        torrents_by_category.setdefault(torrent.category, []).append(torrent)
    for policy in mutable_policies:
        category_torrents = torrents_by_category.get(policy.name, [])
        try:
            decisions.extend(
                _run(
                    prune_cold_torrents(
                        category_torrents,
                        downloader,
                        loaded.cleanup,
                        policy,
                        execute,
                    )
                )
            )
        except MutationBatchError as exc:
            decisions.extend(exc.decisions)
            batch_error = exc
            break
    _write_audit_decisions(loaded, decisions)
    if execute:
        _persist_prune_state(store, decisions)
    payload = {
        "command": "prune",
        "config": str(config),
        "execute": execute,
        "managed_count": len(torrents),
        "pool_usage": _pool_usage_summary(loaded, torrents),
        "decisions": [_decision_summary(item) for item in decisions],
    }
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _print_json(payload)
    _raise_if_batch_failed(batch_error)


@app.command(name="daily-report")
def daily_report_command(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _run(discover_candidates(loaded))
    scored = score_candidates(candidates, loaded.discovery, loaded.scoring)
    managed_torrents = _managed_torrents_for_report(loaded)
    policy_lookup = _policy_lookup(loaded)
    payload = {
        "command": "daily-report",
        "config": str(config),
        "report": build_daily_report(scored, managed_torrents),
        "pool_usage": _pool_usage_summary(loaded, managed_torrents),
        "managed_count": len(managed_torrents),
        "managed_torrents": [
            _managed_torrent_summary(torrent, policy_lookup.get(torrent.category or ""))
            for torrent in managed_torrents
        ],
    }
    _print_json(payload)


@app.command(name="run-once")
def run_once(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    default_policy = _default_category_policy(loaded)

    candidates = _run(discover_candidates(loaded))
    for candidate in candidates:
        store.upsert_candidate(
            candidate.stable_id,
            candidate.title,
            candidate.site,
            LifecycleState.DISCOVERED,
            score=None,
            torrent_hash=None,
        )

    scored = score_candidates(candidates, loaded.discovery, loaded.scoring)
    scored_by_id = {item.candidate_id: item for item in scored}
    for item in scored:
        store.upsert_candidate(
            item.candidate_id,
            item.candidate.title,
            item.candidate.site,
            LifecycleState.SCORED,
            score=item.score,
            torrent_hash=None,
        )

    downloader = build_downloader(loaded) if execute else _NullDownloader()
    paused = _default_category_paused(loaded, downloader if execute else None)
    batch_error = None
    try:
        decisions = _run(
            enqueue_candidates(
                scored,
                downloader,
                default_policy,
                execute,
                paused=paused,
            )
        )
    except MutationBatchError as exc:
        decisions = exc.decisions
        batch_error = exc
    _write_audit_decisions(loaded, decisions)

    if execute:
        _persist_enqueue_state(store, scored_by_id, decisions)

    payload = {
        "command": "run-once",
        "config": str(config),
        "execute": execute,
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "enqueued": sum(1 for item in decisions if item.action == "qb.enqueue"),
        "scores": [_score_summary(item) for item in scored],
        "decisions": [_decision_summary(item) for item in decisions],
    }
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _print_json(payload)
    _raise_if_batch_failed(batch_error)


def _run(value: Any) -> Any:
    return asyncio.run(value)


def _print_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True))


def _candidate_summary(candidate: TorrentCandidate) -> dict[str, Any]:
    return {
        "site": candidate.site,
        "title": candidate.title,
        "candidate_id": candidate.stable_id,
        "source_url": safe_url_identity(candidate.source_url),
        "size_gb": round(candidate.size_bytes / (1024**3), 2),
        "seeders": candidate.seeders,
        "leechers": candidate.leechers,
        "discount": candidate.discount.value,
        "left_time_minutes": candidate.left_time_minutes,
        "hr": candidate.hr,
        "sparse": bool(candidate.metadata.get("rss_sparse_candidate")),
        "detail_enriched": bool(candidate.metadata.get("mteam_detail_enriched")),
    }


def _score_summary(item: ScoreBreakdown) -> dict[str, Any]:
    summary = _candidate_summary(item.candidate)
    summary.update(
        {
            "score": item.score,
            "accepted": item.accepted,
            "reasons": list(item.reasons),
        }
    )
    return summary


def _decision_summary(item: Decision) -> dict[str, Any]:
    return redact_payload(item.model_dump(mode="json"))


def _intent_summary(intent: ResourceIntent) -> dict[str, Any]:
    return {
        "intent_id": intent.intent_id,
        "source": intent.source.value,
        "kind": intent.kind.value,
        "title": intent.title,
        "year": intent.year,
        "season": intent.season,
        "episode": intent.episode,
        "resolution": intent.resolution,
        "quality": intent.quality,
        "language": intent.language,
        "state": intent.state.value,
    }


def _ranked_release_summary(item: RankedRelease) -> dict[str, Any]:
    return {
        "release_id": item.release.release_id,
        "site": item.release.site,
        "title": item.release.title,
        "source_url": safe_url_identity(item.release.source_url),
        "download_url": safe_url_identity(item.release.download_url),
        "size_gb": round(item.release.size_bytes / (1024**3), 2),
        "seeders": item.release.seeders,
        "leechers": item.release.leechers,
        "discount": item.release.discount.value,
        "score": item.score,
        "confidence": item.confidence,
        "accepted": item.accepted,
        "confirmation_required": item.confirmation_required,
        "reasons": list(item.reasons),
        "risks": list(item.risks),
    }


def _managed_torrent_summary(
    torrent: ManagedTorrent,
    policy: CategoryPolicyConfig | None = None,
) -> dict[str, Any]:
    summary = {
        "hash": torrent.hash,
        "name": torrent.name,
        "category": torrent.category,
        "tags": sorted(torrent.tags),
        "state": torrent.state,
        "size_gb": round(torrent.size_bytes / (1024**3), 2),
        "uploaded_gb": round(torrent.uploaded_bytes / (1024**3), 2),
        "downloaded_gb": round(torrent.downloaded_bytes / (1024**3), 2),
        "added_at": torrent.added_at.isoformat(),
        "last_activity_at": torrent.last_activity_at.isoformat()
        if torrent.last_activity_at is not None
        else None,
    }
    if policy is not None:
        summary["policy_mode"] = policy.mode
        summary["budget_pool"] = policy.budget_pool
    return summary


def _managed_torrents_for_report(config: SeedAgentConfig) -> list[ManagedTorrent]:
    downloader = _maybe_build_downloader(config)
    if downloader is None:
        return []
    torrents = _load_policy_torrents(downloader, config)
    return StateStore(_state_path(config)).apply_torrent_runtime(torrents)


def _policy_lookup(config: SeedAgentConfig) -> dict[str, CategoryPolicyConfig]:
    return {policy.name: policy for policy in config.downloader.category_policies}


def _default_category_policy(config: SeedAgentConfig) -> CategoryPolicyConfig:
    return _policy_lookup(config)[config.downloader.default_category]


def _load_policy_torrents(
    downloader: QbittorrentClient | _NullDownloader,
    config: SeedAgentConfig,
    *,
    policies: list[CategoryPolicyConfig] | None = None,
) -> list[ManagedTorrent]:
    selected_policies = policies if policies is not None else config.downloader.category_policies
    torrents: list[ManagedTorrent] = []
    seen_hashes: set[str] = set()
    for policy in selected_policies:
        for torrent in _run(downloader.list_torrents(policy.name, None)):
            if torrent.hash in seen_hashes:
                continue
            seen_hashes.add(torrent.hash)
            torrents.append(torrent)
    return torrents


def _pool_usage_summary(
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
) -> dict[str, dict[str, float | bool]]:
    usage = usage_by_pool(
        config.downloader.category_policies,
        config.downloader.budget_pools,
        torrents,
    )
    return {
        name: {
            "size_tib": round(item.size_bytes / 1024**4, 2),
            "max_size_tib": round(item.max_size_bytes / 1024**4, 2),
            "over_budget": item.over_budget,
        }
        for name, item in usage.items()
    }


def _default_category_paused(
    config: SeedAgentConfig,
    downloader: QbittorrentClient | _NullDownloader | None = None,
) -> bool:
    if downloader is None:
        downloader = _maybe_build_downloader(config)
    if downloader is None:
        return False
    torrents = _load_policy_torrents(downloader, config)
    default_policy = _default_category_policy(config)
    usage = usage_by_pool(
        config.downloader.category_policies,
        config.downloader.budget_pools,
        torrents,
    )
    pool_usage = usage[default_policy.budget_pool]
    return pool_usage.over_budget and default_policy.over_budget_behavior == "add_paused"


def _maybe_build_downloader(config: SeedAgentConfig) -> QbittorrentClient | None:
    secret_ref = config.downloader.secret_ref
    if not secret_ref:
        return None
    secret_path = _resolve_path(secret_ref, config.config_dir)
    if secret_path is None or not secret_path.is_file():
        return None
    secret = load_downloader_secret(secret_path)
    base_url = secret.get("base_url")
    username = secret.get("username")
    password = secret.get("password")
    if not base_url or not username or not password:
        return None
    return QbittorrentClient(base_url=base_url, username=username, password=password)


def build_downloader(config: SeedAgentConfig) -> QbittorrentClient:
    secret_ref = config.downloader.secret_ref
    if not secret_ref:
        raise typer.BadParameter("missing downloader secret")
    secret_path = _resolve_path(secret_ref, config.config_dir)
    if secret_path is None or not secret_path.is_file():
        raise typer.BadParameter("missing downloader secret")
    downloader = _maybe_build_downloader(config)
    if downloader is None:
        raise typer.BadParameter("missing downloader secret")
    return downloader


def _build_search_providers(config: SeedAgentConfig) -> list[RssSearchProvider]:
    providers: list[RssSearchProvider] = []
    for site in config.enabled_sites:
        providers.append(
            RssSearchProvider(
                url=site.rss_url,
                site=site.name,
                site_type=site.type,
                cookie=_read_cookie_ref(site.cookie_ref, config.config_dir),
                api_key=_read_secret_ref(site.api_key_ref, config.config_dir),
                max_results=config.search.max_results_per_site,
            )
        )
    return providers


def _site_access_mode(site: Any, config_dir: Path | None) -> str:
    if _read_secret_ref(getattr(site, "api_key_ref", None), config_dir):
        return "api_key"
    if _read_cookie_ref(getattr(site, "cookie_ref", None), config_dir):
        return "logged_in"
    return "anonymous"


def _site_discovery_mode(site: Any) -> str:
    if getattr(site, "type", None) == "mteam":
        return str(getattr(site, "discovery_mode", "rss"))
    return "rss"


def _read_cookie_ref(cookie_ref: str | None, config_dir: Path | None) -> str | None:
    raw = _read_secret_ref(cookie_ref, config_dir)
    if raw is None:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(loaded, dict):
        for key in ("cookie", "Cookie", "header"):
            value = loaded.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return raw


def _read_secret_ref(secret_ref: str | None, config_dir: Path | None) -> str | None:
    if not secret_ref:
        return None
    path = _resolve_path(secret_ref, config_dir)
    if path is None or not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    return raw or None


def _write_audit_decisions(config: SeedAgentConfig, decisions: list[Decision]) -> None:
    if not decisions:
        return
    audit_path = _audit_path(config)
    logger = AuditLogger(audit_path)
    for decision in decisions:
        logger.write(decision)


def _persist_enqueue_state(
    store: StateStore,
    scored_by_id: dict[str, ScoreBreakdown],
    decisions: list[Decision],
) -> None:
    for decision in decisions:
        if decision.action != "qb.enqueue":
            continue
        scored_item = scored_by_id.get(decision.target_id)
        if scored_item is None:
            continue
        torrent_hash = decision.new_state.get("torrent_hash")
        store.upsert_candidate(
            scored_item.candidate_id,
            scored_item.candidate.title,
            scored_item.candidate.site,
            LifecycleState.ENQUEUED,
            score=scored_item.score,
            torrent_hash=str(torrent_hash) if torrent_hash is not None else None,
        )


def _persist_prune_state(store: StateStore, decisions: list[Decision]) -> None:
    for decision in decisions:
        if decision.action == "qb.cleanup.pause":
            store.mark_torrent_paused(decision.target_id)
            store.update_by_torrent_hash(decision.target_id, LifecycleState.PAUSED)
        elif decision.action == "qb.cleanup.delete":
            store.clear_torrent_runtime(decision.target_id)
            store.update_by_torrent_hash(decision.target_id, LifecycleState.DELETED)


def _raise_if_batch_failed(error: MutationBatchError | None) -> None:
    if error is None:
        return
    raise typer.Exit(1)


def _audit_path(config: SeedAgentConfig) -> Path:
    return _runtime_root(config) / "audit.jsonl"


def _state_path(config: SeedAgentConfig) -> Path:
    return _runtime_root(config) / "state.db"


def _runtime_root(config: SeedAgentConfig) -> Path:
    return _workspace_root(config) / ".seed-agent"


def _workspace_root(config: SeedAgentConfig) -> Path:
    if config.config_dir is None:
        return Path.cwd()
    if config.config_dir.name == "config":
        return config.config_dir.parent
    return config.config_dir


class _NullDownloader:
    async def add_url(
        self, url: str, category: str, tags: list[str], *, paused: bool = False
    ) -> str | None:
        return None

    async def list_torrents(
        self, category: str | None = None, tags: set[str] | None = None
    ) -> list[ManagedTorrent]:
        return []

    async def pause(self, hash: str) -> None:
        return None

    async def delete(self, hash: str, delete_files: bool) -> None:
        return None


def _resolve_path(path_value: str, config_dir: Path | None) -> Path | None:
    path = Path(path_value)
    if not path.is_absolute() and config_dir is not None:
        base_dir = config_dir.parent if config_dir.name == "config" else config_dir
        path = base_dir / path
    try:
        return path.resolve()
    except OSError:
        return None


_build_downloader = build_downloader
