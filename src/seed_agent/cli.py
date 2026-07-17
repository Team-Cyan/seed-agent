from __future__ import annotations

import asyncio
import atexit
import base64
import binascii
import errno
import json
import os
import re
import signal
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlparse

import httpx
import typer
import yaml

from seed_agent import __version__
from seed_agent.actions.intent import (
    add_intent,
    enqueue_intent,
    ingest_inbox,
    rank_intent,
    reject_intent,
    review_intents,
    run_intent_once,
    search_intent,
)
from seed_agent.actions.pt import (
    SiteDiscoveryConfigError,
    apply_site_history_feedback,
    discover_candidates,
    get_last_discovery_warnings,
    resolve_deferred_download_urls,
    score_candidates,
)
from seed_agent.actions.pt import daily_report as build_daily_report
from seed_agent.actions.pt import (
    strategy_report as build_strategy_report,
)
from seed_agent.actions.qb import MutationBatchError, enqueue_candidates, prune_cold_torrents
from seed_agent.audit import AuditLogger, redact_payload
from seed_agent.config import (
    CategoryPolicyConfig,
    SeedAgentConfig,
    load_config,
    load_config_mapping,
    load_downloader_secret,
    write_config_mapping,
)
from seed_agent.downloaders.base import Downloader, DownloaderStatus, DownloaderStatusProvider
from seed_agent.downloaders.qbittorrent import QbittorrentClient
from seed_agent.downloaders.transmission import TransmissionClient
from seed_agent.maintenance import (
    archive_audit_jsonl,
    backup_sqlite_database,
    enforce_retention,
    restore_sqlite_database,
    storage_health,
    verify_sqlite_database,
)
from seed_agent.models import (
    Decision,
    IntentKind,
    IntentSource,
    LifecycleState,
    ManagedTorrent,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
    ScoreBreakdown,
    TorrentCandidate,
    safe_url_identity,
)
from seed_agent.policies.category_policy import PoolUsage, usage_by_pool
from seed_agent.policies.quality import candidate_value_score, torrent_eviction_evidence
from seed_agent.search.base import SearchProvider
from seed_agent.search.mteam import (
    MTeamSearchProvider,
    resolve_mteam_release_download_url,
)
from seed_agent.search.rss import RssSearchProvider
from seed_agent.search.torznab import TorznabSearchProvider
from seed_agent.sites.mteam import (
    DEFERRED_DOWNLOAD_URL_PREFIX,
    MTeamApiClient,
    MTeamApiDiscoveryOptions,
    MTeamApiResponseError,
)
from seed_agent.sites.mteam import (
    fetch_api_candidates as fetch_mteam_api_candidates,
)
from seed_agent.sources.base import SourceIntentEvent
from seed_agent.sources.douban import fetch_douban_wanted_user, read_douban_wanted
from seed_agent.sources.imdb import fetch_imdb_watchlist, read_imdb_watchlist_csv
from seed_agent.sources.letterboxd import read_letterboxd_watchlist_csv
from seed_agent.sources.telegram import poll_telegram_updates
from seed_agent.state import STATE_PRIORITY, StateStore

ReleaseDownloadResolver = Callable[[ReleaseCandidate], Awaitable[ReleaseCandidate | None]]

app = typer.Typer(help="Docker-first PT automation for NAS and homelab operations.")
DEFAULT_CONFIG = Path("config/example.yaml")
SCHEDULE_BACKOFF_FILE = "schedule-backoff.json"
MTEAM_RATE_LIMIT_MARKERS = ("請求過於頻繁", "请求过于频繁")
MTEAM_RATE_LIMIT_BACKOFF_HOURS = 24
MTEAM_NETWORK_BACKOFF_MINUTES = 30
MTEAM_NETWORK_ERROR_TYPES = {
    "ConnectError",
    "ConnectTimeout",
    "NetworkError",
    "PoolTimeout",
    "ReadError",
    "ReadTimeout",
    "TimeoutException",
    "WriteError",
    "WriteTimeout",
}
CONFIG_RULE_SECTIONS = (
    "pt_filters",
    "pt_scoring",
    "seed_cleanup",
    "download_client",
    "want_decision",
    "release_preferences",
    "release_profiles",
    "want_sources",
    "local_state",
    "scheduler",
    "metrics",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the seed-agent version and exit.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Seed Agent CLI."""
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def discover(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _discover_candidates(loaded)
    payload = {
        "command": "discover",
        "config": str(config),
        "discovered": len(candidates),
        "candidates": [_candidate_summary(candidate) for candidate in candidates],
    }
    _attach_discovery_warnings(payload)
    _print_json(payload)


@app.command()
def web(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
) -> None:
    from seed_agent.web.app import serve

    typer.echo(f"Serving seed-agent settings UI at http://{host}:{port}")
    try:
        serve(config, host, port)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        alternate_port = port + 1
        typer.echo(
            (
                f"Port {port} is already in use on {host}. "
                f"Retry with --port {alternate_port}, for example: "
                f"seed-agent web --config {config} --host {host} --port {alternate_port}"
            ),
            err=True,
        )
        raise typer.Exit(1) from exc


@app.command(name="site-probe")
def site_probe(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _discover_candidates(loaded)

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
        "tracker_sites": summary_by_site,
    }
    _attach_discovery_warnings(payload)
    _print_json(payload)


@app.command()
def score(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _discover_candidates(loaded)
    candidates = _apply_site_history_feedback_for_config(candidates, loaded)
    scored = score_candidates(candidates, loaded.pt_filters, loaded.pt_scoring)
    payload = {
        "command": "score",
        "config": str(config),
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "rejected": sum(1 for item in scored if not item.accepted),
        "scores": [_score_summary(item) for item in scored],
    }
    _attach_discovery_warnings(payload)
    _print_json(payload)


@app.command()
def enqueue(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    min_free_window_minutes: Annotated[
        int | None, typer.Option("--min-free-window-minutes")
    ] = None,
    require_known_free_window: Annotated[
        bool, typer.Option("--require-known-free-window/--allow-unknown-free-window")
    ] = False,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    candidates = _discover_candidates(loaded)
    candidates = _apply_site_history_feedback_from_store(candidates, store)
    scored = score_candidates(candidates, loaded.pt_filters, loaded.pt_scoring)
    scored = _apply_free_window_safety(
        scored,
        min_free_window_minutes=min_free_window_minutes,
        require_known_free_window=require_known_free_window if execute else False,
    )
    if execute:
        scored = _run(
            resolve_deferred_download_urls(
                scored,
                loaded,
                min_free_window_minutes=min_free_window_minutes,
                require_known_free_window=require_known_free_window,
            )
        )
    default_policy = _default_category_policy(loaded)
    (
        downloader,
        live_torrents,
        downloader_status,
        paused,
        pool_usage,
        missing_reconciled,
    ) = _enqueue_runtime_context(loaded, store=store, execute=execute)
    skipped_existing = 0
    scored, skipped_live_existing = _link_existing_live_torrent_candidates(
        store, scored, live_torrents
    )
    skipped_existing += skipped_live_existing
    batch_error = None
    enqueue_batches = _enqueue_candidate_batches(
        scored,
        loaded,
        live_torrents,
        pool_usage,
        downloader_status,
    )
    paused = any(batch_paused for _, batch_paused, _ in enqueue_batches)
    pause_reasons = _batch_pause_reasons(enqueue_batches)
    try:
        decisions = _run(
            _enqueue_candidate_batches_action(
                enqueue_batches,
                downloader,
                default_policy,
                execute,
                pool_usage=pool_usage,
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
        "skipped_existing": skipped_existing,
        "enqueued": sum(1 for item in decisions if item.action == "qb.enqueue"),
        "scores": [_score_summary(item) for item in scored],
        "decisions": [_decision_summary(item) for item in decisions],
        "runtime_activity": _runtime_activity_summary(live_torrents),
        "missing_from_qb_reconciled": missing_reconciled,
    }
    if downloader_status is not None:
        payload["downloader_status"] = _downloader_status_summary(
            loaded,
            downloader_status,
            live_torrents,
        )
    if pool_usage is not None:
        payload["default_pool_usage"] = _pool_usage_item_summary(pool_usage)
        payload["enqueue_paused_by_pool_policy"] = False
        payload["enqueue_blocked_by_runtime_gate"] = paused
    if pause_reasons:
        payload["enqueue_blocked_reasons"] = pause_reasons
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _attach_discovery_warnings(payload)
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
    inbox_path = _resolve_path(loaded.want_decision.inbox_ref, loaded.config_dir)
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
        "inbox_ref": loaded.want_decision.inbox_ref,
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
        intent, ranked, decision = rank_intent(
            intent_id,
            store,
            loaded.want_decision,
            loaded.release_preferences,
        )
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
    release_id: Annotated[str | None, typer.Option("--release-id")] = None,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    default_policy = _default_category_policy(loaded)

    def policy_resolver(intent: ResourceIntent) -> CategoryPolicyConfig:
        return _intent_category_policy(loaded, intent)

    (
        downloader,
        live_torrents,
        downloader_status,
        paused,
        pool_usage,
        missing_reconciled,
    ) = _enqueue_runtime_context(loaded, store=store, execute=execute)
    batch_error = None
    pause_reasons = _enqueue_pause_reasons(
        loaded,
        live_torrents,
        pool_usage,
        downloader_status,
    )
    enqueue_context_resolver = _build_intent_enqueue_context_resolver(
        loaded,
        live_torrents,
        downloader_status,
    )
    try:
        release_resolver = _build_release_download_resolver(loaded)
        intent, ranked, decisions = _run(
            enqueue_intent(
                intent_id,
                store,
                downloader,
                default_policy,
                execute,
                paused=paused,
                pool_usage=pool_usage,
                pause_reasons=pause_reasons,
                release_resolver=release_resolver,
                policy_resolver=policy_resolver,
                enqueue_context_resolver=enqueue_context_resolver,
                release_id=release_id,
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except MutationBatchError as exc:
        intent = None
        ranked = None
        decisions = exc.decisions
        batch_error = exc
    effective_paused, effective_pause_reasons = _intent_enqueue_pause_state(
        decisions,
        fallback_paused=paused,
        fallback_reasons=pause_reasons,
    )
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "intent-enqueue",
        "config": str(config),
        "execute": execute,
        "intent": _intent_summary(intent) if intent is not None else None,
        "selected": _ranked_release_summary(ranked) if ranked is not None else None,
        "enqueued": sum(1 for item in decisions if item.action == "qb.enqueue"),
        "decisions": [_decision_summary(item) for item in decisions],
        "runtime_activity": _runtime_activity_summary(live_torrents),
        "missing_from_qb_reconciled": missing_reconciled,
    }
    if downloader_status is not None:
        payload["downloader_status"] = _downloader_status_summary(
            loaded,
            downloader_status,
            live_torrents,
        )
    if pool_usage is not None:
        payload["default_pool_usage"] = _pool_usage_item_summary(pool_usage)
        payload["enqueue_paused_by_pool_policy"] = False
        payload["enqueue_blocked_by_runtime_gate"] = effective_paused
    if effective_pause_reasons:
        payload["enqueue_blocked_reasons"] = effective_pause_reasons
    if batch_error is not None:
        payload["error"] = str(batch_error)
    _print_json(payload)
    _raise_if_batch_failed(batch_error)


@app.command(name="intent-run-once")
def intent_run_once(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    payload = _intent_run_once_payload(config, execute=execute)
    _print_json(payload)
    if "error" in payload:
        raise typer.Exit(code=1)


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
    torrents, missing_reconciled = _apply_live_torrent_state(store, torrents)
    candidate_reconciliation = _persist_live_torrent_candidates(store, torrents)
    payload = {
        "command": "review",
        "config": str(config),
        "managed_count": len(torrents),
        "missing_from_qb_reconciled": missing_reconciled,
        "candidate_reconciliation": candidate_reconciliation,
        "pool_usage": _pool_usage_summary(loaded, torrents),
        "runtime_activity": _runtime_activity_summary(torrents),
        "managed_torrents": [
            _managed_torrent_summary(
                torrent,
                policy_lookup.get(torrent.category or ""),
                store=store,
            )
            for torrent in torrents
        ],
    }
    _print_json(payload)


@app.command()
def prune(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    payload = _prune_payload(config, execute=execute)
    _print_json(payload)
    if "error" in payload:
        raise typer.Exit(code=1)


@app.command(name="daily-report")
def daily_report_command(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    candidates = _discover_candidates(loaded)
    candidates = _apply_site_history_feedback_from_store(candidates, store)
    scored = score_candidates(candidates, loaded.pt_filters, loaded.pt_scoring)
    managed_torrents, missing_reconciled = _managed_torrents_for_report_with_reconciliation(
        loaded, store=store
    )
    policy_lookup = _policy_lookup(loaded)
    payload = {
        "command": "daily-report",
        "config": str(config),
        "report": build_daily_report(scored, managed_torrents),
        "pool_usage": _pool_usage_summary(loaded, managed_torrents),
        "runtime_activity": _runtime_activity_summary(managed_torrents),
        "managed_count": len(managed_torrents),
        "missing_from_qb_reconciled": missing_reconciled,
        "managed_torrents": [
            _managed_torrent_summary(
                torrent,
                policy_lookup.get(torrent.category or ""),
                store=store,
            )
            for torrent in managed_torrents
        ],
    }
    _attach_discovery_warnings(payload)
    _print_json(payload)


@app.command(name="strategy-report")
def strategy_report_command(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    candidates = _discover_candidates(loaded)
    site_history = store.site_history_scores()
    candidates = apply_site_history_feedback(candidates, site_history)
    scored = score_candidates(candidates, loaded.pt_filters, loaded.pt_scoring)
    downloader = _maybe_build_downloader(loaded)
    managed_torrents = _load_policy_torrents(downloader, loaded) if downloader is not None else []
    policy_lookup = _policy_lookup(loaded)
    managed_summaries = [
        _managed_torrent_summary(
            torrent,
            policy_lookup.get(torrent.category or ""),
            store=store,
        )
        for torrent in managed_torrents
    ]
    payload = {
        "command": "strategy-report",
        "config": str(config),
        "report": build_strategy_report(
            scored,
            managed_torrents,
            managed_summaries=managed_summaries,
            site_history=site_history,
        ),
        "managed_torrents": managed_summaries,
    }
    _attach_discovery_warnings(payload)
    _print_json(payload)


@app.command(name="run-once")
def run_once(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    min_free_window_minutes: Annotated[
        int | None, typer.Option("--min-free-window-minutes")
    ] = None,
    require_known_free_window: Annotated[
        bool, typer.Option("--require-known-free-window/--allow-unknown-free-window")
    ] = False,
    prune: Annotated[bool, typer.Option("--prune/--no-prune")] = False,
) -> None:
    payload = _run_once_payload(
        config,
        execute=execute,
        min_free_window_minutes=min_free_window_minutes,
        require_known_free_window=require_known_free_window if execute else False,
        prune=prune,
    )
    _print_json(payload)
    if "error" in payload:
        raise typer.Exit(code=1)


@app.command()
def healthcheck(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    heartbeat_file: Annotated[Path | None, typer.Option("--heartbeat-file")] = None,
    max_staleness_minutes: Annotated[int, typer.Option("--max-staleness-minutes")] = 90,
) -> None:
    if max_staleness_minutes < 1:
        raise typer.BadParameter("max_staleness_minutes must be >= 1")
    load_config(config)
    payload: dict[str, Any] = {
        "command": "healthcheck",
        "config": str(config),
        "status": "ok",
    }
    if heartbeat_file is not None:
        payload["heartbeat"] = _heartbeat_status(
            heartbeat_file,
            max_staleness_minutes=max_staleness_minutes,
        )
    _print_json(payload)


@app.command(name="runtime-status")
def runtime_status(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    heartbeat_file: Annotated[Path | None, typer.Option("--heartbeat-file")] = None,
    max_staleness_minutes: Annotated[int, typer.Option("--max-staleness-minutes")] = 90,
) -> None:
    if max_staleness_minutes < 1:
        raise typer.BadParameter("max_staleness_minutes must be >= 1")
    payload = _runtime_status_payload(
        config,
        heartbeat_file=heartbeat_file,
        max_staleness_minutes=max_staleness_minutes,
    )
    _print_json(payload)


@app.command(name="config-status")
def config_status(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    _print_json(_config_status_payload(config))


@app.command(name="schedule-trigger")
def schedule_trigger(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    lease = store.get_scheduler_lease()
    lease_expires_at = _parse_schedule_backoff_datetime(
        lease.get("expires_at") if lease is not None else None
    )
    if lease is None or lease_expires_at is None or lease_expires_at <= datetime.now(UTC):
        _print_json(
            {
                "command": "schedule-trigger",
                "config": str(config),
                "error": "no active scheduler lease",
                "scheduler_lease": lease,
            }
        )
        raise typer.Exit(code=1)
    trigger = store.request_scheduler_trigger(source="cli")
    if not trigger["queued"]:
        _print_json(
            {
                "command": "schedule-trigger",
                "config": str(config),
                "error": trigger["reason"],
                "trigger": trigger,
                "scheduler_lease": lease,
            }
        )
        raise typer.Exit(code=1)
    _print_json(
        {
            "command": "schedule-trigger",
            "config": str(config),
            "status": "queued",
            "trigger": trigger,
            "scheduler_lease": lease,
        }
    )


@app.command(name="scheduler-backoff-clear")
def scheduler_backoff_clear(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    _print_json(_clear_schedule_backoff(config, source="cli"))


@app.command(name="runtime-doctor")
def runtime_doctor(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    heartbeat_file: Annotated[Path | None, typer.Option("--heartbeat-file")] = None,
    max_staleness_minutes: Annotated[int, typer.Option("--max-staleness-minutes")] = 90,
) -> None:
    status = _runtime_status_payload(
        config,
        heartbeat_file=heartbeat_file,
        max_staleness_minutes=max_staleness_minutes,
    )
    _print_json(
        {
            "command": "runtime-doctor",
            "config": str(config),
            "status": status.get("status"),
            "checks": _runtime_doctor_checks(status),
            "storage": storage_health(_runtime_root(load_config(config))),
        }
    )


@app.command(name="state-backup")
def state_backup(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    loaded = load_config(config)
    runtime_root = _runtime_root(loaded)
    destination = output or (
        runtime_root / "backups" / f"state-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    )
    verification = backup_sqlite_database(_state_path(loaded), destination)
    removed = enforce_retention(
        destination.parent,
        "state-*.db",
        loaded.local_state.backup_retention_count,
    )
    _print_json(
        {
            "command": "state-backup",
            "config": str(config),
            "backup": str(destination),
            "verification": verification,
            "retention_removed": removed,
        }
    )


@app.command(name="state-backup-verify")
def state_backup_verify(backup: Annotated[Path, typer.Option("--backup")]) -> None:
    payload = verify_sqlite_database(backup)
    _print_json({"command": "state-backup-verify", **payload})
    if not payload["valid"]:
        raise typer.Exit(code=1)


@app.command(name="state-restore")
def state_restore(
    backup: Annotated[Path, typer.Option("--backup")],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    payload = restore_sqlite_database(_state_path(loaded), backup, execute=execute)
    _print_json({"command": "state-restore", "config": str(config), **payload})
    if payload["status"] not in {"dry_run", "restored"}:
        raise typer.Exit(code=1)


@app.command(name="audit-archive")
def audit_archive(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    loaded = load_config(config)
    runtime_root = _runtime_root(loaded)
    audit_path = _audit_path(loaded)
    size_bytes = audit_path.stat().st_size if audit_path.exists() else 0
    threshold = loaded.local_state.audit_archive_max_mb * 1024**2
    if not force and size_bytes < threshold:
        payload: dict[str, Any] = {
            "execute": execute,
            "status": "below_threshold",
            "audit_path": str(audit_path),
            "size_bytes": size_bytes,
            "threshold_bytes": threshold,
        }
    else:
        payload = archive_audit_jsonl(
            audit_path,
            runtime_root / "audit-archives",
            execute=execute,
        )
    removed = (
        enforce_retention(
            runtime_root / "audit-archives",
            "audit-*.jsonl.gz",
            loaded.local_state.audit_archive_retention_count,
        )
        if execute
        else []
    )
    _print_json(
        {
            "command": "audit-archive",
            "config": str(config),
            **payload,
            "retention_removed": removed,
        }
    )


@app.command(name="scheduler-report")
def scheduler_report(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    runs = store.list_scheduler_runs(limit=limit)
    selected_run_id = run_id or (str(runs[0]["run_id"]) if runs else None)
    payload = {
        "command": "scheduler-report",
        "config": str(config),
        "state_path": str(_state_path(loaded)),
        "backoff": _schedule_backoff_status(config),
        "runs": runs,
        "events": store.list_scheduler_run_events(run_id=selected_run_id, limit=100)
        if selected_run_id
        else [],
        "want_search_runs": store.list_want_search_runs(limit=limit),
    }
    _print_json(payload)


@app.command(name="tracker-api-report")
def tracker_api_report(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    site: Annotated[str | None, typer.Option("--site")] = None,
    endpoint: Annotated[str | None, typer.Option("--endpoint")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    events = store.list_tracker_api_events(site=site, endpoint=endpoint, limit=limit)
    _print_json(
        {
            "command": "tracker-api-report",
            "config": str(config),
            "state_path": str(_state_path(loaded)),
            "backoffs": store.list_tracker_backoffs(),
            "events": events,
            "summary": _tracker_api_event_summary(events),
        }
    )


@app.command(name="tracker-source-backfill")
def tracker_source_backfill(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
    max_api_requests: Annotated[int, typer.Option("--max-api-requests", min=1)] = 20,
) -> None:
    loaded = load_config(config)
    payload = _tracker_source_backfill_payload(
        loaded,
        execute=execute,
        limit=limit,
        category=category,
        max_api_requests=max_api_requests,
    )
    _print_json(payload)
    if "error" in payload:
        raise typer.Exit(code=1)


@app.command(name="config-export")
def config_export(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    loaded = load_config(config)
    payload = {
        "command": "config-export",
        "config": str(config),
        "rules": _config_rules_payload(loaded),
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            yaml.safe_dump(payload["rules"], sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        payload["output"] = str(output)
    _print_json(payload)


@app.command(name="config-import")
def config_import(
    rules: Annotated[Path, typer.Option("--rules")],
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    current = load_config_mapping(config)
    current_rules = _config_rules_payload(load_config(config))
    incoming_raw = _load_yaml_mapping(rules)
    incoming = (
        incoming_raw.get("rules") if isinstance(incoming_raw.get("rules"), dict) else incoming_raw
    )
    updates = {
        key: incoming[key]
        for key in CONFIG_RULE_SECTIONS
        if key in incoming and current_rules.get(key) != incoming[key]
    }
    merged = {**current, **updates}
    SeedAgentConfig(**merged)
    if execute and updates:
        write_config_mapping(config, merged)
    _print_json(
        {
            "command": "config-import",
            "config": str(config),
            "rules": str(rules),
            "execute": execute,
            "changed_sections": sorted(updates),
            "status": "applied" if execute else "dry_run",
        }
    )


@app.command(name="release-profiles")
def release_profiles(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    _print_json(
        {
            "command": "release-profiles",
            "config": str(config),
            "current": _current_release_profile(loaded),
            "profiles": {
                name: _resolved_release_profile(loaded, profile.model_dump(mode="json"))
                for name, profile in loaded.release_profiles.items()
            },
        }
    )


@app.command(name="reseed-report")
def reseed_report(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    candidates = _reseed_candidates(store, loaded)
    _print_json(
        {
            "command": "reseed-report",
            "config": str(config),
            "state_path": str(_state_path(loaded)),
            "eligible_count": len(candidates),
            "candidates": candidates[: max(limit, 1)],
        }
    )


@app.command(name="headroom-report")
def headroom_report(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    candidates = _discover_candidates(loaded)
    candidates = _apply_site_history_feedback_from_store(candidates, store)
    scored = score_candidates(candidates, loaded.pt_filters, loaded.pt_scoring)
    downloader = _maybe_build_downloader(loaded)
    live_torrents = _load_policy_torrents(downloader, loaded) if downloader is not None else []
    downloader_status = _downloader_status(downloader)
    default_pool_usage = _pool_usage_for_policy(
        loaded,
        live_torrents,
        _default_category_policy(loaded),
    )
    accepted = [item for item in scored if item.accepted]
    accepted_size_bytes = sum(item.candidate.size_bytes for item in accepted)
    headroom_bytes = default_pool_usage.max_size_bytes - default_pool_usage.size_bytes
    disk_headroom = _disk_headroom_state(loaded, downloader_status, live_torrents)
    pool_over_after_accepts = accepted_size_bytes > headroom_bytes
    disk_over_after_accepts = (
        disk_headroom is not None and accepted_size_bytes > disk_headroom["available_for_new_bytes"]
    )
    _print_json(
        {
            "command": "headroom-report",
            "config": str(config),
            "discovered": len(candidates),
            "accepted": len(accepted),
            "accepted_size_gb": round(accepted_size_bytes / 1024**3, 2),
            "default_pool_usage": _pool_usage_item_summary(default_pool_usage),
            "runtime_activity": _runtime_activity_summary(live_torrents),
            "headroom_v2": {
                "headroom_gb": round(headroom_bytes / 1024**3, 2),
                "over_budget_after_accepts": pool_over_after_accepts,
                "over_disk_after_accepts": disk_over_after_accepts,
                "recommended_enqueue_mode": "reject"
                if pool_over_after_accepts or disk_over_after_accepts
                else "normal",
            },
            **(
                {
                    "downloader_status": _downloader_status_summary(
                        loaded,
                        downloader_status,
                        live_torrents,
                    )
                }
                if downloader_status is not None
                else {}
            ),
        }
    )


@app.command(name="contribution-report")
def contribution_report(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    torrents, missing_reconciled = _managed_torrents_for_report_with_reconciliation(
        loaded,
        store=store,
    )
    items = sorted(
        (_torrent_contribution_item(torrent) for torrent in torrents),
        key=lambda item: (
            float(item.get("recent_upload_gb") or 0),
            float(item.get("uploaded_gb") or 0),
        ),
    )
    _print_json(
        {
            "command": "contribution-report",
            "config": str(config),
            "state_path": str(_state_path(loaded)),
            "managed_count": len(torrents),
            "missing_from_qb_reconciled": missing_reconciled,
            "summary": _contribution_summary(items),
            "lowest_contribution": items[: max(limit, 1)],
        }
    )


@app.command(name="quality-replay-report")
def quality_replay_report(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path(loaded))
    torrents, missing_reconciled = _managed_torrents_for_report_with_reconciliation(
        loaded,
        store=store,
    )
    current = sorted(
        torrents,
        key=lambda torrent: float(torrent_eviction_evidence(torrent)["eviction_pressure_score"]),
        reverse=True,
    )
    legacy = sorted(
        torrents,
        key=lambda torrent: (
            float(torrent.metadata.get("recent_upload_gb", 0) or 0),
            torrent.uploaded_bytes,
            -torrent.size_bytes,
        ),
    )
    legacy_rank = {torrent.hash: index + 1 for index, torrent in enumerate(legacy)}
    rows = []
    for current_index, torrent in enumerate(current, start=1):
        evidence = torrent_eviction_evidence(torrent)
        rows.append(
            {
                "hash": torrent.hash,
                "name": torrent.name,
                "category": torrent.category,
                "current_rank": current_index,
                "legacy_rank": legacy_rank[torrent.hash],
                "rank_delta": legacy_rank[torrent.hash] - current_index,
                "evidence": evidence,
                "deletion_provenance": _torrent_deletion_provenance(store, torrent.hash),
            }
        )
    _print_json(
        {
            "command": "quality-replay-report",
            "config": str(config),
            "managed_count": len(torrents),
            "missing_from_qb_reconciled": missing_reconciled,
            "max_capacity_deletes_per_run": loaded.seed_cleanup.max_capacity_deletes_per_run,
            "insufficient_evidence_count": sum(
                not bool(row["evidence"]["evidence_sufficient"]) for row in rows
            ),
            "items": rows[:limit],
        }
    )


def _torrent_deletion_provenance(store: StateStore, torrent_hash: str) -> str:
    runtime = store.get_torrent_runtime(torrent_hash)
    if runtime and runtime.get("missing_from_qb_at"):
        return "external_or_manual"
    rows = store.list_by_torrent_hash(torrent_hash)
    if any(row.get("state") == LifecycleState.DELETED.value for row in rows):
        return "agent_recorded"
    return "active"


class _SchedulerLeaseHeartbeat:
    def __init__(
        self,
        store: StateStore,
        owner_id: str,
        *,
        ttl_seconds: int,
    ) -> None:
        self._store = store
        self._owner_id = owner_id
        self._ttl_seconds = max(int(ttl_seconds), 1)
        self._ttl_lock = threading.Lock()
        self._renew_lock = threading.Lock()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._error: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="seed-agent-scheduler-lease",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def update_ttl(self, ttl_seconds: int) -> None:
        with self._ttl_lock:
            self._ttl_seconds = max(int(ttl_seconds), 1)

    def renew(self, *, ttl_seconds: int | None = None) -> dict[str, Any]:
        if ttl_seconds is not None:
            self.update_ttl(ttl_seconds)
        with self._renew_lock:
            with self._ttl_lock:
                current_ttl = self._ttl_seconds
            try:
                lease = self._store.acquire_scheduler_lease(
                    self._owner_id,
                    ttl_seconds=current_ttl,
                )
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
                self._lost.set()
                raise
            if not lease.get("acquired"):
                self._error = (
                    "scheduler lease ownership changed to "
                    f"{lease.get('owner_id') or 'another owner'}"
                )
                self._lost.set()
            return lease

    def ensure_owned(self) -> None:
        if self._lost.is_set():
            raise RuntimeError(self._error or "scheduler lease was lost")

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while True:
            with self._ttl_lock:
                ttl_seconds = self._ttl_seconds
            renew_after_seconds = max(min(ttl_seconds / 3, 30), 1)
            if self._stop.wait(renew_after_seconds):
                return
            try:
                self.renew()
            except Exception:
                return
            if self._lost.is_set():
                return


@app.command(name="schedule-run")
def schedule_run(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    interval_minutes: Annotated[int | None, typer.Option("--interval-minutes")] = None,
    min_free_window_minutes: Annotated[
        int | None, typer.Option("--min-free-window-minutes")
    ] = None,
    require_known_free_window: Annotated[
        bool | None, typer.Option("--require-known-free-window/--allow-unknown-free-window")
    ] = None,
    prune: Annotated[bool | None, typer.Option("--prune/--no-prune")] = None,
    tracker_backfill: Annotated[
        bool | None, typer.Option("--tracker-backfill/--no-tracker-backfill")
    ] = None,
    tracker_backfill_category: Annotated[
        str | None, typer.Option("--tracker-backfill-category")
    ] = None,
    intent: Annotated[bool | None, typer.Option("--intent/--no-intent")] = None,
    intent_execute: Annotated[
        bool | None,
        typer.Option("--intent-execute/--intent-dry-run"),
    ] = None,
    heartbeat_file: Annotated[Path | None, typer.Option("--heartbeat-file")] = None,
    max_cycles: Annotated[int | None, typer.Option("--max-cycles")] = None,
) -> None:
    scheduler_option_overrides = {
        "interval_minutes": interval_minutes,
        "min_free_window_minutes": min_free_window_minutes,
        "require_known_free_window": require_known_free_window,
        "prune_enabled": prune,
        "tracker_backfill_enabled": tracker_backfill,
        "tracker_backfill_category": tracker_backfill_category,
        "intent_enabled": intent,
        "intent_execute": intent_execute,
    }
    scheduler_cli_overrides = sorted(
        name for name, value in scheduler_option_overrides.items() if value is not None
    )
    if max_cycles is not None and max_cycles < 1:
        raise typer.BadParameter("max_cycles must be >= 1")

    initial_config = load_config(config)
    initial_scheduler = initial_config.scheduler.with_overrides(scheduler_option_overrides)
    lease_store = StateStore(_state_path(initial_config))
    lease_owner_id = f"schedule-run:{os.getpid()}:{uuid.uuid4().hex}"
    lease = lease_store.acquire_scheduler_lease(
        lease_owner_id,
        ttl_seconds=initial_scheduler.lease_ttl_minutes * 60,
    )
    if not lease["acquired"]:
        _print_json(
            {
                "command": "schedule-run",
                "config": str(config),
                "error": "scheduler lease is already held",
                "scheduler_lease": lease,
            }
        )
        raise typer.Exit(code=1)
    lease_heartbeat = _SchedulerLeaseHeartbeat(
        lease_store,
        lease_owner_id,
        ttl_seconds=initial_scheduler.lease_ttl_minutes * 60,
    )
    lease_heartbeat.start()
    lease_released = False
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def release_scheduler_lease() -> None:
        nonlocal lease_released
        if lease_released:
            return
        lease_heartbeat.stop()
        lease_store.release_scheduler_lease(lease_owner_id)
        lease_released = True

    def handle_scheduler_sigterm(signum: int, frame: object) -> None:
        del frame
        release_scheduler_lease()
        raise SystemExit(128 + signum)

    atexit.register(release_scheduler_lease)
    signal.signal(signal.SIGTERM, handle_scheduler_sigterm)

    cycle = 0
    manual_trigger: dict[str, Any] | None = None
    while True:
        cycle_started_monotonic = time.monotonic()
        if manual_trigger is None:
            manual_trigger = lease_store.begin_scheduler_cycle()
        cycle += 1
        run_id = _new_schedule_run_id()
        loaded_for_run = load_config(config)
        scheduler = loaded_for_run.scheduler.with_overrides(scheduler_option_overrides)
        lease = lease_heartbeat.renew(
            ttl_seconds=scheduler.lease_ttl_minutes * 60,
        )
        if not lease["acquired"]:
            _print_json(
                {
                    "command": "schedule-run",
                    "config": str(config),
                    "error": "scheduler lease was lost",
                    "scheduler_lease": lease,
                }
            )
            release_scheduler_lease()
            atexit.unregister(release_scheduler_lease)
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
            raise typer.Exit(code=1)
        lease_heartbeat.ensure_owned()
        interval_minutes = scheduler.interval_minutes
        min_free_window_minutes = _schedule_free_window_safety_minutes(
            interval_minutes=interval_minutes,
            configured_minutes=scheduler.min_free_window_minutes,
        )
        require_known_free_window = scheduler.require_known_free_window
        prune = scheduler.prune_enabled
        tracker_backfill = scheduler.tracker_backfill_enabled
        tracker_backfill_category = scheduler.tracker_backfill_category
        intent = scheduler.intent_enabled
        intent_execute = scheduler.intent_execute
        store_for_run = StateStore(_state_path(loaded_for_run))
        backoff = _schedule_backoff_status(config)
        store_for_run.start_scheduler_run(
            run_id=run_id,
            command="schedule-run",
            config=str(config),
            execute=execute,
            interval_minutes=interval_minutes,
            prune_enabled=prune,
            intent_enabled=intent,
            intent_execute=intent_execute,
            backoff_active=bool(backoff.get("active")),
            backoff_until=str(backoff.get("until")) if backoff.get("until") else None,
            summary={"cycle": cycle, "manual_trigger": manual_trigger},
        )
        _record_schedule_phase(
            store_for_run,
            run_id=run_id,
            phase="backoff_check",
            event="active" if backoff.get("active") else "inactive",
            payload={"schedule_backoff": backoff},
        )
        if heartbeat_file is not None:
            _write_heartbeat(
                heartbeat_file,
                cycle=cycle,
                interval_minutes=interval_minutes,
                payload={
                    "command": "schedule-run",
                    "run_id": run_id,
                    "config": str(config),
                    "execute": execute,
                    "phase": "running",
                    "error": None,
                    "schedule_backoff": backoff if backoff.get("active") else None,
                    "skipped_by_backoff": bool(backoff.get("active")),
                },
            )
        if backoff.get("active"):
            _record_schedule_phase(
                store_for_run,
                run_id=run_id,
                phase="backoff_check",
                event="skip",
                message="schedule backoff active; tracker API work skipped",
                payload={"schedule_backoff": backoff},
            )
            payload = _schedule_backoff_skip_payload(
                config,
                execute=execute,
                intent_enabled=intent,
                intent_execute=intent_execute,
                backoff=backoff,
                run_id=run_id,
            )
            if prune:
                lease_heartbeat.ensure_owned()
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="prune",
                    event="start",
                    payload={"schedule_backoff_active": True},
                )
                prune_payload = _prune_payload(
                    config,
                    execute=execute,
                    free_window_min_remaining_minutes=min_free_window_minutes,
                    completed_low_upload_requires_reclamation=True,
                    fail_closed_unknown_incomplete=True,
                )
                payload["prune"] = prune_payload
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="prune",
                    event="end",
                    payload=_prune_payload_summary(prune_payload),
                )
                if "error" in prune_payload:
                    payload["error"] = f"prune: {prune_payload['error']}"
        else:
            tracker_backfill_payload: dict[str, Any] | None = None
            payload: dict[str, Any] = {}
            if tracker_backfill:
                lease_heartbeat.ensure_owned()
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="tracker_source_backfill",
                    event="start",
                    payload={
                        "category": tracker_backfill_category,
                        "limit": None,
                        "max_api_requests": None,
                    },
                )
                tracker_backfill_payload = _tracker_source_backfill_payload(
                    loaded_for_run,
                    execute=execute,
                    limit=None,
                    category=tracker_backfill_category,
                    max_api_requests=None,
                )
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="tracker_source_backfill",
                    event="end",
                    payload=_tracker_source_backfill_payload_summary(tracker_backfill_payload),
                )
                payload["tracker_source_backfill"] = tracker_backfill_payload
                if _tracker_source_backfill_has_rate_limit(tracker_backfill_payload):
                    payload["schedule_backoff"] = _record_schedule_rate_limit_backoff(
                        config,
                        endpoint="torrent/search",
                        reason="mteam request too frequent",
                        run_id=run_id,
                    )
                    payload["skipped_by_backoff"] = True
                    store_for_run.record_tracker_api_event(
                        site="mteam",
                        endpoint="torrent/search",
                        event="rate_limited",
                        run_id=run_id,
                        rate_limited=True,
                        message="mteam request too frequent",
                    )
                    _record_schedule_phase(
                        store_for_run,
                        run_id=run_id,
                        phase="tracker_source_backfill",
                        event="warning",
                        message="mteam rate limited",
                        payload={"schedule_backoff": payload["schedule_backoff"]},
                    )
                elif _tracker_source_backfill_has_network_unavailable(tracker_backfill_payload):
                    payload["schedule_backoff"] = _record_schedule_network_backoff(
                        config,
                        endpoint="torrent/search",
                        reason="mteam api unavailable",
                        run_id=run_id,
                    )
                    payload["skipped_by_backoff"] = True
                    store_for_run.record_tracker_api_event(
                        site="mteam",
                        endpoint="torrent/search",
                        event="unavailable",
                        run_id=run_id,
                        rate_limited=False,
                        message="mteam api unavailable",
                    )
                    _record_schedule_phase(
                        store_for_run,
                        run_id=run_id,
                        phase="tracker_source_backfill",
                        event="warning",
                        message="mteam api unavailable",
                        payload={"schedule_backoff": payload["schedule_backoff"]},
                    )

            prune_payload: dict[str, Any] | None = None
            if prune and "error" not in payload:
                lease_heartbeat.ensure_owned()
                unresolved_risk_hashes = (
                    _tracker_source_backfill_unresolved_risk_hashes(tracker_backfill_payload)
                    if tracker_backfill_payload is not None
                    else set()
                )
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="prune",
                    event="start",
                )
                prune_payload = _prune_payload(
                    config,
                    execute=execute,
                    free_window_min_remaining_minutes=min_free_window_minutes,
                    completed_low_upload_requires_reclamation=True,
                    **(
                        {"fail_closed_unknown_incomplete": True}
                        if payload.get("schedule_backoff")
                        else {}
                    ),
                    **(
                        {"unknown_free_risk_hashes": unresolved_risk_hashes}
                        if unresolved_risk_hashes
                        else {}
                    ),
                )
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="prune",
                    event="end",
                    payload=_prune_payload_summary(prune_payload),
                )
                if "error" in prune_payload:
                    payload.update(
                        {
                            "command": "schedule-run",
                            "run_id": run_id,
                            "config": str(config),
                            "execute": execute,
                            "error": f"prune: {prune_payload['error']}",
                            "prune": prune_payload,
                        }
                    )
                else:
                    payload.setdefault("prune", prune_payload)

            if "error" not in payload and "schedule_backoff" not in payload:
                lease_heartbeat.ensure_owned()
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="pt_discovery",
                    event="start",
                )
                payload = _run_once_payload(
                    config,
                    execute=execute,
                    min_free_window_minutes=min_free_window_minutes,
                    require_known_free_window=require_known_free_window if execute else False,
                    prune=False,
                    capacity_prune=prune,
                )
                if tracker_backfill_payload is not None:
                    payload["tracker_source_backfill"] = tracker_backfill_payload
                _record_schedule_phase(
                    store_for_run,
                    run_id=run_id,
                    phase="pt_enqueue",
                    event="end",
                    payload={
                        "discovered": payload.get("discovered"),
                        "scored": payload.get("scored"),
                        "accepted": payload.get("accepted"),
                        "enqueued": payload.get("enqueued"),
                        "discovery_warnings": payload.get("discovery_warnings"),
                    },
                )
                if prune_payload is not None:
                    payload["prune"] = prune_payload
                if _payload_has_mteam_rate_limit(payload):
                    endpoint = _mteam_rate_limit_endpoint(payload)
                    payload["schedule_backoff"] = _record_schedule_rate_limit_backoff(
                        config,
                        endpoint=endpoint,
                        reason="mteam request too frequent",
                        run_id=run_id,
                    )
                    payload["skipped_by_backoff"] = True
                    store_for_run.record_tracker_api_event(
                        site="mteam",
                        endpoint=endpoint,
                        event="rate_limited",
                        run_id=run_id,
                        rate_limited=True,
                        message="mteam request too frequent",
                    )
                    _record_schedule_phase(
                        store_for_run,
                        run_id=run_id,
                        phase="pt_discovery",
                        event="warning",
                        message="mteam rate limited",
                        payload={"schedule_backoff": payload["schedule_backoff"]},
                    )
                elif _payload_has_mteam_network_unavailable(payload):
                    endpoint = _mteam_network_unavailable_endpoint(payload)
                    payload["schedule_backoff"] = _record_schedule_network_backoff(
                        config,
                        endpoint=endpoint,
                        reason="mteam api unavailable",
                        run_id=run_id,
                    )
                    payload["skipped_by_backoff"] = True
                    store_for_run.record_tracker_api_event(
                        site="mteam",
                        endpoint=endpoint,
                        event="unavailable",
                        run_id=run_id,
                        rate_limited=False,
                        message="mteam api unavailable",
                    )
                    _record_schedule_phase(
                        store_for_run,
                        run_id=run_id,
                        phase="pt_discovery",
                        event="warning",
                        message="mteam api unavailable",
                        payload={"schedule_backoff": payload["schedule_backoff"]},
                    )

        payload["command"] = "schedule-run"
        payload["run_id"] = run_id
        payload["cycle"] = cycle
        payload["interval_minutes"] = interval_minutes
        payload["capacity_guard_interval_seconds"] = (
            scheduler.capacity_guard_interval_seconds
        )
        payload["scheduled_at"] = datetime.now(UTC).isoformat()
        payload["min_free_window_minutes"] = min_free_window_minutes
        payload["require_known_free_window"] = require_known_free_window if execute else False
        payload["prune_enabled"] = prune
        payload["tracker_backfill_enabled"] = tracker_backfill
        payload["tracker_backfill_category"] = tracker_backfill_category
        payload["tracker_backfill_unbounded"] = True
        payload["intent_enabled"] = intent
        payload["intent_execute"] = intent_execute
        payload["scheduler_config_source"] = (
            "yaml+cli_overrides" if scheduler_cli_overrides else "yaml"
        )
        payload["scheduler_cli_overrides"] = scheduler_cli_overrides
        payload["scheduler_lease"] = lease
        payload["manual_trigger"] = manual_trigger
        if payload.get("schedule_backoff", {}).get("active"):
            payload["intent_search_enabled"] = False
            if intent and "intent" not in payload:
                payload["intent"] = _intent_backoff_skip_payload(
                    execute=intent_execute,
                    backoff=payload["schedule_backoff"],
                    run_id=run_id,
                )
        elif intent and "error" not in payload:
            lease_heartbeat.ensure_owned()
            intent_search = _scheduled_intent_search_due(
                mode=scheduler.intent_search_mode,
                hour=scheduler.intent_search_hour,
                last_search_at=_latest_scheduled_intent_search_at(store_for_run),
            )
            _record_schedule_phase(
                store_for_run,
                run_id=run_id,
                phase="intent_search" if intent_search else "intent_source_sync",
                event="start",
                payload={"search_enabled": intent_search},
            )
            intent_payload = _intent_run_once_payload(
                config,
                execute=intent_execute,
                search_ingested=intent_search,
                run_id=run_id,
            )
            _record_schedule_phase(
                store_for_run,
                run_id=run_id,
                phase="intent_search" if intent_search else "intent_source_sync",
                event="end",
                payload=_intent_payload_summary(intent_payload),
            )
            payload["intent"] = intent_payload
            payload["intent_search_enabled"] = intent_search
            if "error" in intent_payload:
                payload["error"] = f"intent: {intent_payload['error']}"
        if heartbeat_file is not None:
            _write_heartbeat(
                heartbeat_file,
                cycle=cycle,
                interval_minutes=interval_minutes,
                payload=payload,
            )
            payload["heartbeat_file"] = str(heartbeat_file)
        summary = _schedule_log_summary(payload)
        lease_heartbeat.ensure_owned()
        store_for_run.finish_scheduler_run(
            run_id=run_id,
            status=_schedule_run_status(summary),
            summary=summary,
        )
        _print_json(summary)

        if "error" in payload and max_cycles is not None:
            release_scheduler_lease()
            atexit.unregister(release_scheduler_lease)
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
            raise typer.Exit(code=1)
        if max_cycles is not None and cycle >= max_cycles:
            release_scheduler_lease()
            atexit.unregister(release_scheduler_lease)
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
            return
        lease_store.mark_scheduler_waiting()
        manual_trigger = _wait_for_next_schedule_cycle(
            config,
            execute=execute and prune,
            interval_seconds=_remaining_schedule_interval_seconds(
                interval_minutes=interval_minutes,
                cycle_started_monotonic=cycle_started_monotonic,
            ),
            guard_interval_seconds=scheduler.capacity_guard_interval_seconds,
            lease_heartbeat=lease_heartbeat,
            trigger_store=lease_store,
        )


def _remaining_schedule_interval_seconds(
    *,
    interval_minutes: int,
    cycle_started_monotonic: float,
    now_monotonic: float | None = None,
) -> int:
    current = time.monotonic() if now_monotonic is None else now_monotonic
    elapsed_seconds = max(current - cycle_started_monotonic, 0.0)
    return max(int(interval_minutes * 60 - elapsed_seconds), 0)


def _wait_for_next_schedule_cycle(
    config_path: Path,
    *,
    execute: bool,
    interval_seconds: int,
    guard_interval_seconds: int,
    lease_heartbeat: _SchedulerLeaseHeartbeat,
    trigger_store: StateStore | None = None,
) -> dict[str, Any] | None:
    remaining_seconds = max(int(interval_seconds), 0)
    guard_interval_seconds = max(int(guard_interval_seconds), 10)
    seconds_until_guard = guard_interval_seconds
    while remaining_seconds > 0:
        if trigger_store is not None:
            trigger = trigger_store.consume_scheduler_trigger()
            if trigger is not None:
                return trigger
        sleep_seconds = min(
            1 if trigger_store is not None else seconds_until_guard,
            remaining_seconds,
        )
        time.sleep(sleep_seconds)
        remaining_seconds -= sleep_seconds
        seconds_until_guard -= sleep_seconds
        if remaining_seconds <= 0:
            return None
        if seconds_until_guard > 0:
            continue
        seconds_until_guard = guard_interval_seconds
        lease_heartbeat.ensure_owned()
        try:
            payload = _capacity_guard_payload(config_path, execute=execute)
        except Exception as exc:
            payload = {
                "command": "capacity-guard",
                "execute": execute,
                "triggered": False,
                "error": _runtime_error_summary(exc),
            }
        _print_json(_capacity_guard_payload_summary(payload))
    return None


def _capacity_guard_payload(config_path: Path, *, execute: bool) -> dict[str, Any]:
    loaded = load_config(config_path)
    downloader = build_downloader(loaded) if execute else _maybe_build_downloader(loaded)
    if downloader is None:
        return {
            "command": "capacity-guard",
            "config": str(config_path),
            "execute": execute,
            "triggered": False,
            "error": "downloader unavailable for capacity guard",
        }

    torrents = _load_policy_torrents(downloader, loaded)
    mutable_policies = [
        policy
        for policy in loaded.download_client.category_policies
        if policy.mode == "mutable" and policy.delete_enabled
    ]
    mutable_categories = {policy.name for policy in mutable_policies}
    usage = usage_by_pool(
        loaded.download_client.category_policies,
        loaded.download_client.budget_pools,
        torrents,
    )
    enforceable_pools = {policy.budget_pool for policy in mutable_policies}
    over_budget_pools = sorted(
        name for name, item in usage.items() if name in enforceable_pools and item.over_budget
    )
    broken_incomplete_hashes = sorted(
        torrent.hash
        for torrent in torrents
        if torrent.category in mutable_categories and _is_broken_incomplete_torrent(torrent)
    )
    if not over_budget_pools and not broken_incomplete_hashes:
        return {
            "command": "capacity-guard",
            "config": str(config_path),
            "execute": execute,
            "triggered": False,
            "hard_cap_satisfied": True,
            "pool_usage": {
                name: _pool_usage_item_summary(item) for name, item in usage.items()
            },
        }

    payload = _prune_payload(
        config_path,
        execute=execute,
        completed_low_upload_requires_reclamation=True,
        fail_closed_unknown_incomplete=True,
    )
    payload["command"] = "capacity-guard"
    payload["triggered"] = True
    payload["trigger_over_budget_pools"] = over_budget_pools
    payload["trigger_broken_incomplete_hashes"] = broken_incomplete_hashes
    return payload


def _is_broken_incomplete_torrent(torrent: ManagedTorrent) -> bool:
    if torrent.state.strip().lower() not in {"error", "missingfiles", "unknown"}:
        return False
    amount_left = torrent.metadata.get("amount_left_bytes")
    if isinstance(amount_left, int | float):
        return amount_left > 0
    return torrent.downloaded_bytes < torrent.size_bytes


def _capacity_guard_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": "capacity-guard",
        "execute": payload.get("execute"),
        "triggered": payload.get("triggered"),
        "trigger_over_budget_pools": payload.get("trigger_over_budget_pools", []),
        "trigger_broken_incomplete_count": len(
            payload.get("trigger_broken_incomplete_hashes") or []
        ),
        "hard_cap_satisfied": payload.get("hard_cap_satisfied"),
        "hard_cap_violations_by_pool": payload.get("hard_cap_violations_by_pool", {}),
        "verified_committed_reclaim_by_pool": payload.get(
            "verified_committed_reclaim_by_pool", {}
        ),
        "pool_usage": payload.get("pool_usage"),
        "error": payload.get("error"),
    }


def _scheduled_intent_search_due(
    now: datetime | None = None,
    *,
    mode: str = "daily",
    hour: int = 0,
    last_search_at: datetime | None = None,
) -> bool:
    if mode == "every_cycle":
        return True
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    scheduled_at = current.replace(hour=hour, minute=0, second=0, microsecond=0)
    if current < scheduled_at:
        return False
    if last_search_at is None:
        return True
    previous = last_search_at
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=UTC)
    return previous.astimezone(current.tzinfo) < scheduled_at


def _latest_scheduled_intent_search_at(store: StateStore) -> datetime | None:
    for row in store.list_scheduler_runs(limit=100):
        if not row.get("finished_at"):
            continue
        try:
            summary = json.loads(str(row.get("summary_json") or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(summary, dict) or summary.get("intent_search_enabled") is not True:
            continue
        try:
            searched_at = datetime.fromisoformat(str(row["finished_at"]).replace("Z", "+00:00"))
        except KeyError, ValueError:
            continue
        return searched_at
    return None


def _new_schedule_run_id(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    return f"sched-{current.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _record_schedule_phase(
    store: StateStore,
    *,
    run_id: str,
    phase: str,
    event: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    event_payload: dict[str, Any] = {
        "run_id": run_id,
        "phase": phase,
        "event": event,
    }
    if message is not None:
        event_payload["message"] = message
    if payload is not None:
        event_payload["payload"] = payload
    store.record_scheduler_event(
        run_id=run_id,
        phase=phase,
        event=event,
        message=message,
        payload=payload,
    )
    _print_json(event_payload)


def _schedule_run_status(summary: dict[str, Any]) -> str:
    if summary.get("error"):
        return "error"
    if summary.get("skipped_by_backoff") and summary.get("schedule_backoff"):
        return "skipped_backoff"
    if _payload_has_mteam_rate_limit(summary):
        return "rate_limited"
    if _tracker_source_backfill_has_unresolved(summary.get("tracker_source_backfill")):
        return "warning"
    return "success"


def _schedule_backoff_path(config_path: Path) -> Path:
    return _runtime_root(load_config(config_path)) / SCHEDULE_BACKOFF_FILE


def _schedule_backoff_status(
    config_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    tracker_status = _tracker_backoff_status(config_path, now=now)
    if tracker_status.get("active"):
        return tracker_status
    path = _schedule_backoff_path(config_path)
    status: dict[str, Any] = {"active": False, "path": str(path)}
    if not path.exists():
        return status
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return status
    if not isinstance(raw, dict):
        return status
    until = _parse_schedule_backoff_datetime(raw.get("until"))
    if until is None:
        return status
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    remaining_minutes = (until - current).total_seconds() / 60
    status.update(
        {
            "active": remaining_minutes > 0,
            "created_at": raw.get("created_at"),
            "until": until.isoformat(),
            "reason": raw.get("reason"),
            "remaining_minutes": round(max(remaining_minutes, 0.0), 2),
        }
    )
    return status


def _clear_schedule_backoff(
    config_path: Path,
    *,
    source: str,
) -> dict[str, Any]:
    loaded = load_config(config_path)
    store = StateStore(_state_path(loaded))
    before = _schedule_backoff_status(config_path)
    path = _schedule_backoff_path(config_path)
    file_removed = path.exists()
    path.unlink(missing_ok=True)
    cleared = store.clear_tracker_backoffs(site="mteam")
    store.record_tracker_api_event(
        site="mteam",
        endpoint=str(before.get("endpoint") or "*"),
        event="backoff_cleared",
        rate_limited=False,
        message=f"cleared by {source}",
    )
    return {
        "command": "scheduler-backoff-clear",
        "config": str(config_path),
        "status": "cleared",
        "source": source,
        "file_removed": file_removed,
        "tracker_backoffs_cleared": cleared,
        "previous_backoff": before,
        "schedule_backoff": _schedule_backoff_status(config_path),
    }


def _record_schedule_rate_limit_backoff(
    config_path: Path,
    *,
    endpoint: str = "torrent/search",
    reason: str,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    until = _next_local_midnight_at_or_after(
        current + timedelta(hours=MTEAM_RATE_LIMIT_BACKOFF_HOURS)
    )
    path = _schedule_backoff_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "active": True,
                "created_at": current.isoformat(),
                "until": until.isoformat(),
                "reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    store = StateStore(_state_path(load_config(config_path)))
    store.set_tracker_backoff(
        site="mteam",
        endpoint=endpoint,
        until=until.isoformat(),
        reason=reason,
        source="schedule",
        run_id=run_id,
        created_at=current,
    )
    return _schedule_backoff_status(config_path, now=current)


def _record_schedule_network_backoff(
    config_path: Path,
    *,
    endpoint: str,
    reason: str,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    until = current + timedelta(minutes=MTEAM_NETWORK_BACKOFF_MINUTES)
    store = StateStore(_state_path(load_config(config_path)))
    store.set_tracker_backoff(
        site="mteam",
        endpoint=endpoint,
        until=until.isoformat(),
        reason=reason,
        source="schedule_network",
        run_id=run_id,
        created_at=current,
    )
    return _schedule_backoff_status(config_path, now=current)


def _tracker_backoff_status(
    config_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    store = StateStore(_state_path(load_config(config_path)))
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    active_rows: list[dict[str, Any]] = []
    for row in store.list_tracker_backoffs():
        if str(row.get("site")) != "mteam" or not bool(row.get("active")):
            continue
        until = _parse_schedule_backoff_datetime(row.get("until"))
        if until is None:
            continue
        remaining_minutes = (until - current).total_seconds() / 60
        if remaining_minutes <= 0:
            continue
        item = dict(row)
        item["until"] = until.isoformat()
        item["remaining_minutes"] = round(remaining_minutes, 2)
        active_rows.append(item)
    if not active_rows:
        return {"active": False, "path": str(_schedule_backoff_path(config_path))}
    primary = max(active_rows, key=lambda row: str(row.get("until") or ""))
    return {
        "active": True,
        "path": str(_schedule_backoff_path(config_path)),
        "site": primary.get("site"),
        "endpoint": primary.get("endpoint"),
        "created_at": primary.get("created_at"),
        "until": primary.get("until"),
        "reason": primary.get("reason"),
        "remaining_minutes": primary.get("remaining_minutes"),
        "tracker_backoffs": active_rows,
    }


def _next_local_midnight_at_or_after(value: datetime) -> datetime:
    local = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    local = local.astimezone()
    candidate = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if candidate < local:
        candidate += timedelta(days=1)
    return candidate


def _parse_schedule_backoff_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _payload_has_mteam_rate_limit(payload: dict[str, Any]) -> bool:
    messages: list[str] = []
    for warning in payload.get("discovery_warnings") or []:
        if isinstance(warning, dict):
            if warning.get("rate_limited") is True:
                return True
            messages.append(str(warning.get("message") or warning.get("error") or ""))
        else:
            messages.append(str(warning))
    if payload.get("error"):
        messages.append(str(payload["error"]))
    return any(marker in message for message in messages for marker in MTEAM_RATE_LIMIT_MARKERS)


def _payload_has_mteam_network_unavailable(payload: dict[str, Any]) -> bool:
    for warning in payload.get("discovery_warnings") or []:
        if not isinstance(warning, dict):
            continue
        if str(warning.get("site") or "").lower() not in {"mteam", "mt"}:
            continue
        if warning.get("rate_limited") is True:
            continue
        if warning.get("unavailable") is True:
            return True
        error_type = str(warning.get("error_type") or "")
        message = str(warning.get("message") or "")
        if error_type in MTEAM_NETWORK_ERROR_TYPES or _is_mteam_network_message(message):
            return True
    return False


def _mteam_network_unavailable_endpoint(payload: dict[str, Any]) -> str:
    for warning in payload.get("discovery_warnings") or []:
        if not isinstance(warning, dict):
            continue
        if str(warning.get("site") or "").lower() not in {"mteam", "mt"}:
            continue
        endpoint = str(warning.get("endpoint") or "").strip()
        if endpoint:
            return endpoint
    return "torrent/search"


def _mteam_rate_limit_endpoint(payload: dict[str, Any]) -> str:
    for warning in payload.get("discovery_warnings") or []:
        if isinstance(warning, dict) and warning.get("rate_limited") is True:
            endpoint = str(warning.get("endpoint") or "").strip()
            if endpoint:
                return endpoint
    return "torrent/search"


def _schedule_backoff_skip_payload(
    config_path: Path,
    *,
    execute: bool,
    intent_enabled: bool,
    intent_execute: bool,
    backoff: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command": "schedule-run",
        "run_id": run_id,
        "config": str(config_path),
        "execute": execute,
        "discovered": 0,
        "scored": 0,
        "accepted": 0,
        "enqueued": 0,
        "scores": [],
        "decisions": [],
        "schedule_backoff": backoff,
        "skipped_by_backoff": True,
    }
    if intent_enabled:
        payload["intent"] = _intent_backoff_skip_payload(
            execute=intent_execute,
            backoff=backoff,
            run_id=run_id,
        )
        payload["intent_search_enabled"] = False
    return payload


def _intent_backoff_skip_payload(
    *,
    execute: bool,
    backoff: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "command": "intent-run-once",
        "run_id": run_id,
        "execute": execute,
        "search_enabled": False,
        "ingested": 0,
        "searched": 0,
        "ranked": 0,
        "enqueue_candidates": 0,
        "decisions": [],
        "schedule_backoff": backoff,
        "skipped_by_backoff": True,
    }


def _prune_payload(
    config_path: Path,
    *,
    execute: bool,
    free_window_min_remaining_minutes: int | None = None,
    force_space_reclamation: bool = False,
    completed_low_upload_requires_reclamation: bool = False,
    reclaim_targets_by_pool: dict[str, int] | None = None,
    unknown_free_risk_hashes: set[str] | None = None,
    fail_closed_unknown_incomplete: bool = False,
) -> dict[str, Any]:
    loaded = load_config(config_path)
    store = StateStore(_state_path(loaded))
    mutable_policies = [
        policy
        for policy in loaded.download_client.category_policies
        if policy.mode == "mutable" and policy.delete_enabled
    ]
    if execute:
        downloader = build_downloader(loaded)
    else:
        downloader = _maybe_build_downloader(loaded)
        if downloader is None:
            downloader = _NullDownloader()
    all_torrents = _load_policy_torrents(downloader, loaded)
    if isinstance(downloader, _NullDownloader):
        missing_reconciled = 0
        candidate_reconciliation = {
            "created_qb_records": 0,
            "linked_existing_candidates": 0,
            "marked_present": 0,
        }
    else:
        all_torrents, missing_reconciled = _apply_live_torrent_state(store, all_torrents)
        candidate_reconciliation = _persist_live_torrent_candidates(store, all_torrents)
    unknown_free_risk_hashes = set(unknown_free_risk_hashes or set())
    if fail_closed_unknown_incomplete:
        unknown_free_risk_hashes.update(_incomplete_unknown_free_hashes(all_torrents))
    if unknown_free_risk_hashes:
        all_torrents = [
            _mark_unknown_free_status_high_risk(torrent)
            if torrent.hash in unknown_free_risk_hashes
            else torrent
            for torrent in all_torrents
        ]
    mutable_policy_names = {policy.name for policy in mutable_policies}
    torrents = [torrent for torrent in all_torrents if torrent.category in mutable_policy_names]
    batch_error = None
    decisions: list[Decision] = []
    pool_usage_by_name = usage_by_pool(
        loaded.download_client.category_policies,
        loaded.download_client.budget_pools,
        all_torrents,
    )
    effective_reclaim_targets = {
        name: max(item.size_bytes - item.max_size_bytes, 0)
        for name, item in pool_usage_by_name.items()
    }
    for name, target in (reclaim_targets_by_pool or {}).items():
        effective_reclaim_targets[name] = max(
            effective_reclaim_targets.get(name, 0), int(target), 0
        )
    reclaimed_by_pool = {name: 0 for name in effective_reclaim_targets}
    remaining_capacity_deletes = loaded.seed_cleanup.max_capacity_deletes_per_run
    torrents_by_category: dict[str, list[ManagedTorrent]] = {}
    for torrent in torrents:
        if torrent.category is None:
            continue
        torrents_by_category.setdefault(torrent.category, []).append(torrent)
    for policy in mutable_policies:
        category_torrents = torrents_by_category.get(policy.name, [])
        pool_usage = pool_usage_by_name.get(policy.budget_pool)
        reclaim_target = effective_reclaim_targets.get(policy.budget_pool, 0)
        remaining_reclaim_target = max(
            reclaim_target - reclaimed_by_pool.get(policy.budget_pool, 0), 0
        )
        try:
            policy_decisions = _run(
                prune_cold_torrents(
                    category_torrents,
                    downloader,
                    loaded.seed_cleanup,
                    policy,
                    execute,
                    pool_usage=pool_usage,
                    free_window_min_remaining_minutes=free_window_min_remaining_minutes,
                    force_space_reclamation=force_space_reclamation,
                    completed_low_upload_requires_reclamation=(
                        completed_low_upload_requires_reclamation
                    ),
                    reclaim_target_bytes=remaining_reclaim_target,
                    capacity_delete_limit=remaining_capacity_deletes,
                )
            )
            decisions.extend(policy_decisions)
            remaining_capacity_deletes = max(
                remaining_capacity_deletes - _capacity_delete_count(policy_decisions),
                0,
            )
            reclaimed_by_pool[policy.budget_pool] = reclaimed_by_pool.get(
                policy.budget_pool, 0
            ) + _reclaimed_capacity_bytes(policy_decisions)
        except MutationBatchError as exc:
            decisions.extend(exc.decisions)
            batch_error = exc
            break
    _write_audit_decisions(loaded, decisions)
    if execute:
        _persist_prune_state(store, decisions)
    final_torrents = all_torrents
    if execute and batch_error is None:
        final_torrents = _load_policy_torrents(downloader, loaded)
        final_torrents, _ = _apply_live_torrent_state(store, final_torrents)
    final_usage_by_name = usage_by_pool(
        loaded.download_client.category_policies,
        loaded.download_client.budget_pools,
        final_torrents,
    )
    enforceable_pools = {
        policy.budget_pool
        for policy in mutable_policies
        if policy.mode == "mutable" and policy.delete_enabled
    }
    hard_cap_violations = {
        name: item.size_bytes - item.max_size_bytes
        for name, item in final_usage_by_name.items()
        if name in enforceable_pools and item.over_budget
    }
    verified_reclaimed_by_pool = {
        name: max(
            pool_usage_by_name[name].size_bytes - final_usage_by_name[name].size_bytes,
            0,
        )
        for name in final_usage_by_name
        if name in pool_usage_by_name
    }
    preview = _prune_preview(decisions, torrents, store)
    payload = {
        "command": "prune",
        "config": str(config_path),
        "execute": execute,
        "force_space_reclamation": force_space_reclamation,
        "completed_low_upload_requires_reclamation": (completed_low_upload_requires_reclamation),
        "reclaim_targets_by_pool": effective_reclaim_targets,
        "reclaimed_capacity_by_pool": reclaimed_by_pool,
        "verified_committed_reclaim_by_pool": verified_reclaimed_by_pool,
        "verified_downloaded_reclaim_by_pool": _reclaimed_downloaded_bytes_by_pool(
            decisions
        ),
        "hard_cap_satisfied": not hard_cap_violations,
        "hard_cap_violations_by_pool": hard_cap_violations,
        "unknown_free_risk_count": len(unknown_free_risk_hashes),
        "capacity_deletes_remaining": remaining_capacity_deletes,
        "managed_count": len(torrents),
        "missing_from_qb_reconciled": missing_reconciled,
        "candidate_reconciliation": candidate_reconciliation,
        "pool_usage_before": _pool_usage_summary(loaded, all_torrents),
        "pool_usage": {
            name: _pool_usage_item_summary(item)
            for name, item in final_usage_by_name.items()
        },
        "decisions": [_decision_summary(item) for item in decisions],
        "preview": preview,
        "cleanup_evidence": _cleanup_decision_evidence(preview),
    }
    if batch_error is not None:
        payload["error"] = str(batch_error)
    elif execute and hard_cap_violations:
        details = ", ".join(
            f"{name} over by {round(value / 1024**3, 3)} GiB"
            for name, value in sorted(hard_cap_violations.items())
        )
        payload["error"] = f"hard pool capacity invariant not satisfied: {details}"
    return payload


def _reclaimed_capacity_bytes(decisions: list[Decision]) -> int:
    reclaimed = 0
    for decision in decisions:
        if decision.action != "qb.cleanup.delete":
            continue
        if not bool(decision.new_state.get("space_reclamation_required")):
            continue
        size_bytes = decision.old_state.get("size_bytes", 0)
        if isinstance(size_bytes, int | float):
            reclaimed += max(int(size_bytes), 0)
    return reclaimed


def _reclaimed_downloaded_bytes_by_pool(decisions: list[Decision]) -> dict[str, int]:
    reclaimed: dict[str, int] = {}
    for decision in decisions:
        if decision.action != "qb.cleanup.delete":
            continue
        pool = str(decision.new_state.get("budget_pool") or "")
        if not pool:
            continue
        downloaded = decision.old_state.get("downloaded_bytes", 0)
        if isinstance(downloaded, int | float):
            reclaimed[pool] = reclaimed.get(pool, 0) + max(int(downloaded), 0)
    return reclaimed


def _capacity_delete_count(decisions: list[Decision]) -> int:
    return sum(
        1
        for decision in decisions
        if decision.action == "qb.cleanup.delete"
        and bool(decision.new_state.get("capacity_reclamation"))
    )


def _incomplete_unknown_free_hashes(torrents: list[ManagedTorrent]) -> set[str]:
    hashes: set[str] = set()
    for torrent in torrents:
        amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
        if amount_left <= 0:
            continue
        discount = str(torrent.metadata.get("discount") or "").strip().lower()
        if discount in {"free", "2xfree", "2x_free", "normal", "50%", "half", "2x50%"}:
            continue
        if torrent.metadata.get("free_window_expires_at"):
            continue
        hashes.add(torrent.hash)
    return hashes


def _mark_unknown_free_status_high_risk(torrent: ManagedTorrent) -> ManagedTorrent:
    metadata = dict(torrent.metadata)
    metadata["unknown_free_status_high_risk"] = True
    return torrent.model_copy(update={"metadata": metadata})


def _run_once_payload(
    config_path: Path,
    *,
    execute: bool,
    min_free_window_minutes: int | None,
    require_known_free_window: bool,
    prune: bool,
    prune_free_window_min_remaining_minutes: int | None = None,
    capacity_prune: bool = False,
) -> dict[str, Any]:
    loaded = load_config(config_path)
    store = StateStore(_state_path(loaded))
    default_policy = _default_category_policy(loaded)

    candidates = _discover_candidates(loaded)
    for candidate in candidates:
        store.upsert_candidate(
            candidate.stable_id,
            candidate.title,
            candidate.site,
            LifecycleState.DISCOVERED,
            score=None,
            torrent_hash=None,
            **_candidate_snapshot_kwargs(candidate),
        )

    candidates = _apply_site_history_feedback_from_store(candidates, store)
    scored = score_candidates(candidates, loaded.pt_filters, loaded.pt_scoring)
    scored = _apply_free_window_safety(
        scored,
        min_free_window_minutes=min_free_window_minutes,
        require_known_free_window=require_known_free_window,
    )
    if execute:
        scored = _run(
            resolve_deferred_download_urls(
                scored,
                loaded,
                min_free_window_minutes=min_free_window_minutes,
                require_known_free_window=require_known_free_window,
            )
        )
    scored_by_id = {item.candidate_id: item for item in scored}
    for item in scored:
        store.upsert_candidate(
            item.candidate_id,
            item.candidate.title,
            item.candidate.site,
            LifecycleState.SCORED,
            score=item.score,
            torrent_hash=None,
            **_candidate_snapshot_kwargs(item.candidate, score_reasons=list(item.reasons)),
        )
    scored, skipped_existing = _filter_existing_enqueue_candidates(store, scored)
    stale_candidates_pruned = store.prune_stale_candidates(
        retention_days=loaded.local_state.candidate_retention_days
    )

    (
        downloader,
        live_torrents,
        downloader_status,
        paused,
        pool_usage,
        missing_reconciled,
    ) = _enqueue_runtime_context(loaded, store=store, execute=execute)
    scored, skipped_live_existing = _link_existing_live_torrent_candidates(
        store, scored, live_torrents
    )
    skipped_existing += skipped_live_existing
    batch_error = None
    enqueue_batches = _enqueue_candidate_batches(
        scored,
        loaded,
        live_torrents,
        pool_usage,
        downloader_status,
    )
    paused = any(batch_paused for _, batch_paused, _ in enqueue_batches)
    pause_reasons = _batch_pause_reasons(enqueue_batches)
    capacity_prune_payload: dict[str, Any] | None = None
    capacity_prune_error: str | None = None
    accepted_waiting = any(item.accepted for item in scored)
    if capacity_prune and accepted_waiting and paused:
        reclaim_target = _capacity_reclaim_target_bytes(
            scored,
            loaded,
            live_torrents,
            pool_usage,
            downloader_status,
        )
        capacity_prune_payload = _prune_payload(
            config_path,
            execute=execute,
            force_space_reclamation=True,
            completed_low_upload_requires_reclamation=True,
            reclaim_targets_by_pool={default_policy.budget_pool: reclaim_target},
        )
        if "error" in capacity_prune_payload:
            capacity_prune_error = f"capacity_prune: {capacity_prune_payload['error']}"
        else:
            (
                downloader,
                live_torrents,
                downloader_status,
                paused,
                pool_usage,
                refreshed_missing_reconciled,
            ) = _enqueue_runtime_context(loaded, store=store, execute=execute)
            missing_reconciled += refreshed_missing_reconciled
            scored, refreshed_skipped_existing = _link_existing_live_torrent_candidates(
                store, scored, live_torrents
            )
            skipped_existing += refreshed_skipped_existing
            enqueue_batches = _enqueue_candidate_batches(
                scored,
                loaded,
                live_torrents,
                pool_usage,
                downloader_status,
            )
            paused = any(batch_paused for _, batch_paused, _ in enqueue_batches)
            pause_reasons = _batch_pause_reasons(enqueue_batches)
    if capacity_prune_error is not None:
        decisions = []
    else:
        try:
            decisions = _run(
                _enqueue_candidate_batches_action(
                    enqueue_batches,
                    downloader,
                    default_policy,
                    execute,
                    pool_usage=pool_usage,
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
        "config": str(config_path),
        "execute": execute,
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "skipped_existing": skipped_existing,
        "enqueued": sum(1 for item in decisions if item.action == "qb.enqueue"),
        "scores": [_score_summary(item) for item in scored],
        "decisions": [_decision_summary(item) for item in decisions],
        "runtime_activity": _runtime_activity_summary(live_torrents),
        "missing_from_qb_reconciled": missing_reconciled,
        "stale_candidates_pruned": stale_candidates_pruned,
    }
    if pool_usage is not None:
        payload["default_pool_usage"] = _pool_usage_item_summary(pool_usage)
        payload["enqueue_paused_by_pool_policy"] = False
        payload["enqueue_blocked_by_runtime_gate"] = paused
    if downloader_status is not None:
        payload["downloader_status"] = _downloader_status_summary(
            loaded,
            downloader_status,
            live_torrents,
        )
    if pause_reasons:
        payload["enqueue_blocked_reasons"] = pause_reasons
    if min_free_window_minutes is not None:
        payload["min_free_window_minutes"] = min_free_window_minutes
    if require_known_free_window:
        payload["require_known_free_window"] = True
    if batch_error is not None:
        payload["error"] = str(batch_error)
    if capacity_prune_payload is not None:
        payload["capacity_prune"] = capacity_prune_payload
    if capacity_prune_error is not None:
        payload["error"] = capacity_prune_error
    if prune:
        prune_payload = _prune_payload(
            config_path,
            execute=execute,
            free_window_min_remaining_minutes=prune_free_window_min_remaining_minutes,
        )
        payload["prune"] = prune_payload
        if "error" in prune_payload:
            payload["error"] = f"prune: {prune_payload['error']}"
    _attach_discovery_warnings(payload)
    return payload


def _intent_run_once_payload(
    config_path: Path,
    *,
    execute: bool,
    search_ingested: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    loaded = load_config(config_path)
    store = StateStore(_state_path(loaded))
    providers = _build_search_providers(loaded)
    inbox_path = _resolve_path(loaded.want_decision.inbox_ref, loaded.config_dir)
    default_policy = _default_category_policy(loaded)

    def policy_resolver(intent: ResourceIntent) -> CategoryPolicyConfig:
        return _intent_category_policy(loaded, intent)

    (
        downloader,
        live_torrents,
        downloader_status,
        paused,
        pool_usage,
        missing_reconciled,
    ) = _enqueue_runtime_context(loaded, store=store, execute=execute)
    batch_error = None
    pause_reasons = _enqueue_pause_reasons(
        loaded,
        live_torrents,
        pool_usage,
        downloader_status,
    )
    enqueue_context_resolver = _build_intent_enqueue_context_resolver(
        loaded,
        live_torrents,
        downloader_status,
    )
    source_warnings: list[dict[str, str]] = []
    try:
        source_events = _read_configured_source_events(loaded)
    except Exception as exc:
        source_events = []
        source_warnings.append(
            {
                "source": "configured_sources",
                "error_type": type(exc).__name__,
                "message": _runtime_error_summary(exc),
            }
        )
    try:
        release_resolver = _build_release_download_resolver(loaded)
        result = _run(
            run_intent_once(
                inbox_path=inbox_path,
                store=store,
                providers=providers,
                intent_config=loaded.want_decision,
                search_config=loaded.release_preferences,
                downloader=downloader,
                policy=default_policy,
                execute=execute,
                paused=paused,
                pool_usage=pool_usage,
                pause_reasons=pause_reasons,
                source_events=source_events,
                release_resolver=release_resolver,
                policy_resolver=policy_resolver,
                enqueue_context_resolver=enqueue_context_resolver,
                search_ingested=search_ingested,
            )
        )
        decisions = result.decisions
    except MutationBatchError as exc:
        result = None
        decisions = exc.decisions
        batch_error = exc
    effective_paused, effective_pause_reasons = _intent_enqueue_pause_state(
        decisions,
        fallback_paused=paused,
        fallback_reasons=pause_reasons,
    )
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "intent-run-once",
        "config": str(config_path),
        "run_id": run_id,
        "execute": execute,
        "search_enabled": search_ingested,
        "ingested": len(result.ingested) if result is not None else 0,
        "searched": len(result.searched) if result is not None else 0,
        "ranked": len(result.ranked) if result is not None else 0,
        "enqueue_candidates": len(result.enqueue_selected) if result is not None else 0,
        "decisions": [_decision_summary(item) for item in decisions],
        "runtime_activity": _runtime_activity_summary(live_torrents),
        "missing_from_qb_reconciled": missing_reconciled,
    }
    if pool_usage is not None:
        payload["default_pool_usage"] = _pool_usage_item_summary(pool_usage)
        payload["enqueue_paused_by_pool_policy"] = False
        payload["enqueue_blocked_by_runtime_gate"] = effective_paused
    if downloader_status is not None:
        payload["downloader_status"] = _downloader_status_summary(
            loaded,
            downloader_status,
            live_torrents,
        )
    if effective_pause_reasons:
        payload["enqueue_blocked_reasons"] = effective_pause_reasons
    if result is not None:
        _record_intent_search_runs(
            store,
            intents=result.searched,
            run_id=run_id,
            source="intent-run-once",
            search_enabled=search_ingested,
        )
        payload["intents"] = [_intent_summary(intent) for intent in result.searched]
        payload["selected"] = [_ranked_release_summary(item) for item in result.enqueue_selected]
    search_diagnostics = _search_provider_diagnostics(providers)
    if search_diagnostics:
        payload["search_diagnostics"] = search_diagnostics
    if source_warnings:
        payload["source_warnings"] = source_warnings
    if batch_error is not None:
        payload["error"] = str(batch_error)
    return payload


def _record_intent_search_runs(
    store: StateStore,
    *,
    intents: list[ResourceIntent],
    run_id: str | None,
    source: str,
    search_enabled: bool,
    backoff: dict[str, Any] | None = None,
    message: str | None = None,
) -> None:
    for intent in intents:
        ranked = _stored_ranked_releases(store, intent.intent_id)
        best = ranked[0] if ranked else None
        row = store.get_intent(intent.intent_id) or {}
        status = "searched" if search_enabled else "skipped"
        if backoff and backoff.get("active"):
            status = "skipped_backoff"
        store.record_want_search_run(
            intent_id=intent.intent_id,
            run_id=run_id,
            source=source,
            status=status,
            search_enabled=search_enabled,
            results_count=len(ranked),
            best_score=best.score if best is not None else None,
            selected_release_id=str(row.get("selected_release_id"))
            if row.get("selected_release_id") is not None
            else None,
            backoff_active=bool(backoff.get("active")) if backoff else False,
            backoff_until=str(backoff.get("until")) if backoff and backoff.get("until") else None,
            message=message,
            payload={"state": row.get("state"), "title": intent.title},
        )


def _search_provider_diagnostics(providers: list[SearchProvider]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for provider in providers:
        rows = getattr(provider, "search_diagnostics", None)
        if not isinstance(rows, list):
            continue
        diagnostics.extend(row for row in rows if isinstance(row, dict))
    return diagnostics


def _stored_ranked_releases(store: StateStore, intent_id: str) -> list[RankedRelease]:
    ranked: list[RankedRelease] = []
    for row in store.list_release_candidates(intent_id):
        try:
            loaded = json.loads(str(row.get("release_json") or "{}"))
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict) and "release" in loaded:
            try:
                ranked.append(RankedRelease.model_validate(loaded))
            except ValueError:
                continue
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _filter_existing_enqueue_candidates(
    store: StateStore,
    scored: list[ScoreBreakdown],
) -> tuple[list[ScoreBreakdown], int]:
    filtered: list[ScoreBreakdown] = []
    skipped = 0
    for item in scored:
        if item.accepted and _candidate_already_active(store, item.candidate_id):
            skipped += 1
            continue
        filtered.append(item)
    return filtered, skipped


def _candidate_already_active(store: StateStore, candidate_id: str) -> bool:
    row = store.get_candidate(candidate_id)
    if row is None:
        return False
    state = str(row["state"])
    return STATE_PRIORITY.get(state, -1) >= STATE_PRIORITY[LifecycleState.ENQUEUED.value]


def _link_existing_live_torrent_candidates(
    store: StateStore,
    scored: list[ScoreBreakdown],
    torrents: list[ManagedTorrent],
) -> tuple[list[ScoreBreakdown], int]:
    live_by_identity: dict[tuple[str, int], ManagedTorrent] = {}
    for torrent in torrents:
        if not torrent.hash:
            continue
        identity = _live_torrent_identity(torrent)
        if identity is not None:
            live_by_identity[identity] = torrent
    if not live_by_identity:
        return scored, 0

    filtered: list[ScoreBreakdown] = []
    skipped = 0
    for item in scored:
        torrent = live_by_identity.get(_candidate_live_identity(item.candidate))
        if item.accepted and torrent is not None:
            store.upsert_candidate(
                item.candidate_id,
                item.candidate.title,
                item.candidate.site,
                _lifecycle_state_from_torrent(torrent),
                score=item.score,
                torrent_hash=torrent.hash,
                free_window_expires_at=_candidate_free_window_expires_at(item.candidate),
                **_candidate_snapshot_kwargs(
                    item.candidate,
                    score_reasons=list(item.reasons),
                ),
            )
            skipped += 1
            continue
        filtered.append(item)
    return filtered, skipped


def _candidate_live_identity(candidate: TorrentCandidate) -> tuple[str, int]:
    return (_normalize_torrent_title(candidate.title), int(candidate.size_bytes))


def _live_torrent_identity(torrent: ManagedTorrent) -> tuple[str, int] | None:
    if torrent.size_bytes <= 0:
        return None
    return (_normalize_torrent_title(torrent.name), int(torrent.size_bytes))


def _normalize_torrent_title(title: str) -> str:
    return " ".join(title.strip().casefold().split())


def _apply_free_window_safety(
    scored: list[ScoreBreakdown],
    *,
    min_free_window_minutes: int | None,
    require_known_free_window: bool,
) -> list[ScoreBreakdown]:
    if min_free_window_minutes is not None and min_free_window_minutes < 0:
        raise typer.BadParameter("min_free_window_minutes must be >= 0")
    if not require_known_free_window and min_free_window_minutes is None:
        return scored

    adjusted: list[ScoreBreakdown] = []
    for item in scored:
        candidate = item.candidate
        if not item.accepted:
            adjusted.append(item)
            continue

        left_time = candidate.left_time_minutes
        if require_known_free_window and left_time is None:
            if candidate.metadata.get("left_time_source") == "mteam_api_unlimited":
                adjusted.append(item)
                continue
            adjusted.append(
                item.model_copy(
                    update={
                        "score": 0,
                        "accepted": False,
                        "reasons": [*item.reasons, "left_time required for execute safety"],
                    }
                )
            )
            continue
        if min_free_window_minutes is not None and left_time is not None:
            if left_time < min_free_window_minutes:
                adjusted.append(
                    item.model_copy(
                        update={
                            "score": 0,
                            "accepted": False,
                            "reasons": [
                                *item.reasons,
                                (
                                    f"left_time {left_time} < execute safety "
                                    f"{min_free_window_minutes}"
                                ),
                            ],
                        }
                    )
                )
                continue
        adjusted.append(item)
    return adjusted


def _write_heartbeat(
    heartbeat_file: Path,
    *,
    cycle: int,
    interval_minutes: int,
    payload: dict[str, Any],
) -> None:
    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "updated_at": datetime.now(UTC).isoformat(),
        "version": __version__,
        "cycle": cycle,
        "interval_minutes": interval_minutes,
        "command": payload.get("command"),
        "run_id": payload.get("run_id"),
        "config": payload.get("config"),
        "execute": payload.get("execute"),
        "phase": payload.get("phase"),
        "accepted": payload.get("accepted"),
        "enqueued": payload.get("enqueued"),
        "intent": _intent_payload_summary(payload.get("intent")),
        "intent_search_enabled": payload.get("intent_search_enabled"),
        "schedule_backoff": payload.get("schedule_backoff"),
        "skipped_by_backoff": payload.get("skipped_by_backoff"),
        "error": payload.get("error"),
    }
    heartbeat_file.write_text(
        json.dumps(heartbeat, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _schedule_free_window_safety_minutes(
    *,
    interval_minutes: int,
    configured_minutes: int | None,
) -> int:
    """Keep enough freeleech time to survive one delayed scheduler cycle."""
    return max(configured_minutes or 0, interval_minutes * 2)


def _heartbeat_status(
    heartbeat_file: Path,
    *,
    max_staleness_minutes: int,
) -> dict[str, Any]:
    if not heartbeat_file.exists():
        raise typer.Exit(
            code=_print_error_payload(
                {
                    "command": "healthcheck",
                    "status": "error",
                    "error": f"heartbeat file not found: {heartbeat_file}",
                }
            )
        )
    try:
        heartbeat = json.loads(heartbeat_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.Exit(
            code=_print_error_payload(
                {
                    "command": "healthcheck",
                    "status": "error",
                    "error": f"invalid heartbeat json: {exc.msg}",
                    "heartbeat_file": str(heartbeat_file),
                }
            )
        ) from exc

    updated_at_raw = heartbeat.get("updated_at")
    if not isinstance(updated_at_raw, str):
        raise typer.Exit(
            code=_print_error_payload(
                {
                    "command": "healthcheck",
                    "status": "error",
                    "error": "heartbeat missing updated_at",
                    "heartbeat_file": str(heartbeat_file),
                }
            )
        )
    try:
        updated_at = datetime.fromisoformat(updated_at_raw)
    except ValueError as exc:
        raise typer.Exit(
            code=_print_error_payload(
                {
                    "command": "healthcheck",
                    "status": "error",
                    "error": "heartbeat updated_at is not valid ISO datetime",
                    "heartbeat_file": str(heartbeat_file),
                }
            )
        ) from exc

    age_minutes = max((datetime.now(UTC) - updated_at).total_seconds() / 60, 0.0)
    status = {
        "heartbeat_file": str(heartbeat_file),
        "updated_at": updated_at.isoformat(),
        "age_minutes": round(age_minutes, 2),
        "max_staleness_minutes": max_staleness_minutes,
        "cycle": heartbeat.get("cycle"),
        "interval_minutes": heartbeat.get("interval_minutes"),
        "last_error": heartbeat.get("error"),
    }
    if age_minutes > max_staleness_minutes:
        raise typer.Exit(
            code=_print_error_payload(
                {
                    "command": "healthcheck",
                    "status": "error",
                    "error": (
                        f"heartbeat stale: {round(age_minutes, 2)} minutes old "
                        f"(max {max_staleness_minutes})"
                    ),
                    "heartbeat": status,
                }
            )
        )
    return status


def _runtime_status_payload(
    config_path: Path,
    *,
    heartbeat_file: Path | None,
    max_staleness_minutes: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command": "runtime-status",
        "version": __version__,
        "config": str(config_path),
        "config_exists": config_path.exists(),
    }
    try:
        loaded = load_config(config_path)
    except Exception as exc:
        payload.update(
            {
                "status": "config_error",
                "error": str(exc),
            }
        )
    else:
        runtime_root = _runtime_root(loaded)
        credential_path = (
            _resolve_path(loaded.download_client.secret_ref, loaded.config_dir)
            if loaded.download_client.secret_ref
            else None
        )
        payload.update(
            {
                "status": "ok",
                "config_dir": str(loaded.config_dir) if loaded.config_dir else None,
                "workspace_root": str(_workspace_root(loaded)),
                "state_path": str(_state_path(loaded)),
                "state_exists": _state_path(loaded).exists(),
                "audit_path": str(_audit_path(loaded)),
                "audit_exists": _audit_path(loaded).exists(),
                "runtime_root": str(runtime_root),
                "tracker_sites": [
                    {
                        "name": site.name,
                        "type": site.type,
                        "enabled": site.enabled,
                        "discovery_mode": site.discovery_mode,
                        "access_mode": _site_access_mode(site, loaded.config_dir),
                    }
                    for site in loaded.tracker_sites
                ],
                "download_client": {
                    "type": loaded.download_client.type,
                    "target": loaded.download_client.target,
                    "default_category": loaded.download_client.default_category,
                    "credential_ref_set": loaded.download_client.secret_ref is not None,
                    "credential_file_present": bool(credential_path and credential_path.exists()),
                    "budget_pools": [
                        {"name": pool.name, "max_size_tib": pool.max_size_tib}
                        for pool in loaded.download_client.budget_pools
                    ],
                    "category_policies": [
                        {
                            "name": policy.name,
                            "mode": policy.mode,
                            "budget_pool": policy.budget_pool,
                            "delete_enabled": policy.delete_enabled,
                        }
                        for policy in loaded.download_client.category_policies
                    ],
                },
                "pt_filters": {
                    "min_leechers": loaded.pt_filters.min_leechers,
                    "min_seeders": loaded.pt_filters.min_seeders,
                    "max_size_gb": loaded.pt_filters.max_size_gb,
                    "max_active_downloads": loaded.pt_filters.max_active_downloads,
                    "max_total_amount_left_gb": loaded.pt_filters.max_total_amount_left_gb,
                },
                "seed_cleanup": {
                    "cold_after_days": loaded.seed_cleanup.cold_after_days,
                    "delete_after_no_upload_hours": (
                        loaded.seed_cleanup.delete_after_no_upload_hours
                    ),
                },
                "scheduler": loaded.scheduler.model_dump(mode="json"),
            }
        )
    if heartbeat_file is not None:
        payload["heartbeat_file"] = str(heartbeat_file)
        if heartbeat_file.exists():
            try:
                payload["heartbeat"] = _heartbeat_status(
                    heartbeat_file,
                    max_staleness_minutes=max_staleness_minutes,
                )
            except typer.Exit:
                try:
                    payload["heartbeat_raw"] = json.loads(
                        heartbeat_file.read_text(encoding="utf-8")
                    )
                except Exception:
                    payload["heartbeat_raw"] = None
                payload["heartbeat_status"] = "error"
        else:
            payload["heartbeat_status"] = "missing"
    return payload


def _config_status_payload(config_path: Path) -> dict[str, Any]:
    loaded = load_config(config_path)
    state_path = _state_path(loaded)
    store = StateStore(state_path)
    return {
        "command": "config-status",
        "config": str(config_path),
        "status": "ok",
        "workspace_root": str(_workspace_root(loaded)),
        "state_path": str(state_path),
        "state_exists": state_path.exists(),
        "tracker_sites": [
            {
                "name": site.name,
                "type": site.type,
                "enabled": site.enabled,
                "discovery_mode": site.discovery_mode,
                "api_key_ref": site.api_key_ref,
                "has_api_key": bool(
                    site.api_key_ref and _resolve_path(site.api_key_ref, loaded.config_dir).exists()
                ),
            }
            for site in loaded.tracker_sites
        ],
        "schedule_backoff": _schedule_backoff_status(config_path),
        "tracker_backoffs": store.list_tracker_backoffs(),
        "pt_filters": loaded.pt_filters.model_dump(mode="json"),
        "pt_scoring": loaded.pt_scoring.model_dump(mode="json"),
        "seed_cleanup": loaded.seed_cleanup.model_dump(mode="json"),
        "download_client": {
            "type": loaded.download_client.type,
            "target": loaded.download_client.target,
            "default_category": loaded.download_client.default_category,
            "budget_pools": [
                pool.model_dump(mode="json") for pool in loaded.download_client.budget_pools
            ],
            "category_policies": [
                policy.model_dump(mode="json")
                for policy in loaded.download_client.category_policies
            ],
        },
    }


def _config_rules_payload(config: SeedAgentConfig) -> dict[str, Any]:
    dumped = config.model_dump(mode="json")
    return {key: dumped[key] for key in CONFIG_RULE_SECTIONS if key in dumped}


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise typer.BadParameter(f"expected YAML mapping: {path}")
    return dict(loaded)


def _current_release_profile(config: SeedAgentConfig) -> dict[str, Any]:
    return {
        "default_resolution": config.want_decision.default_resolution,
        "series_search_mode": config.want_decision.series_search_mode,
        "quality_tag_scores": config.release_preferences.quality_tag_scores,
        "site_priority": config.release_preferences.site_priority,
        "source_ids": [source.id for source in config.want_sources.want_lists if source.enabled],
    }


def _resolved_release_profile(
    config: SeedAgentConfig,
    profile: dict[str, Any],
) -> dict[str, Any]:
    current = _current_release_profile(config)
    return {
        "default_resolution": profile.get("default_resolution") or current["default_resolution"],
        "series_search_mode": profile.get("series_search_mode") or current["series_search_mode"],
        "quality_tag_scores": {
            **dict(current["quality_tag_scores"]),
            **dict(profile.get("quality_tag_scores") or {}),
        },
        "site_priority": {
            **dict(current["site_priority"]),
            **dict(profile.get("site_priority") or {}),
        },
        "source_ids": profile.get("source_ids") or current["source_ids"],
    }


def _reseed_candidates(
    store: StateStore,
    config: SeedAgentConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in (LifecycleState.DELETED, LifecycleState.PAUSED, LifecycleState.COLD):
        rows.extend(store.list_by_state(state))
    candidates: list[dict[str, Any]] = []
    for row in rows:
        score = row.get("score")
        if not isinstance(score, int) or score < config.pt_scoring.min_score_to_enqueue:
            continue
        torrent_hash = row.get("torrent_hash")
        runtime = store.get_torrent_runtime(str(torrent_hash)) if torrent_hash is not None else None
        reason = _reseed_reason(row, runtime)
        candidates.append(
            {
                "candidate_id": row["stable_id"],
                "site": row["site"],
                "title": row["title"],
                "state": row["state"],
                "score": score,
                "torrent_hash": torrent_hash,
                "reason": reason,
                "missing_from_downloader": bool(runtime and runtime.get("missing_from_qb_at")),
                "no_upload_since_at": runtime.get("no_upload_since_at") if runtime else None,
                "updated_at": row["updated_at"],
            }
        )
    return sorted(
        candidates,
        key=lambda item: (-int(item["score"]), str(item["updated_at"])),
    )


def _reseed_reason(
    row: dict[str, Any],
    runtime: dict[str, Any] | None,
) -> str:
    if runtime and runtime.get("missing_from_qb_at"):
        return "missing_from_downloader"
    if runtime and runtime.get("no_upload_since_at"):
        return "stalled_no_upload"
    return f"state_{row['state']}"


def _runtime_doctor_checks(status: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _doctor_check(
            "config",
            status.get("status") == "ok",
            str(status.get("error") or "config loaded"),
        )
    )
    checks.append(
        _doctor_check(
            "state_db",
            bool(status.get("state_exists")),
            str(status.get("state_path") or "state db path unavailable"),
        )
    )
    if "heartbeat" in status:
        heartbeat = status.get("heartbeat")
        checks.append(
            _doctor_check(
                "heartbeat",
                isinstance(heartbeat, dict) and heartbeat.get("status") == "ok",
                str(heartbeat.get("status") if isinstance(heartbeat, dict) else "missing"),
            )
        )
    elif status.get("heartbeat_status"):
        checks.append(
            _doctor_check(
                "heartbeat",
                False,
                str(status.get("heartbeat_status")),
            )
        )
    download_client = status.get("download_client")
    if isinstance(download_client, dict):
        needs_secret = download_client.get("target") not in {None, "local"}
        checks.append(
            _doctor_check(
                "downloader_credentials",
                (not needs_secret) or bool(download_client.get("credential_file_present")),
                "credential file present"
                if download_client.get("credential_file_present")
                else "credential file missing",
            )
        )
    return checks


def _doctor_check(name: str, ok: bool, message: str) -> dict[str, Any]:
    return {"name": name, "status": "ok" if ok else "warning", "message": message}


def _tracker_api_event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_site: dict[str, int] = {}
    by_endpoint: dict[str, int] = {}
    rate_limited = 0
    for event in events:
        site = str(event.get("site") or "unknown")
        endpoint = str(event.get("endpoint") or "unknown")
        by_site[site] = by_site.get(site, 0) + 1
        by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
        if bool(event.get("rate_limited")):
            rate_limited += 1
    return {
        "total": len(events),
        "rate_limited": rate_limited,
        "by_site": by_site,
        "by_endpoint": by_endpoint,
    }


def _tracker_source_backfill_payload(
    config: SeedAgentConfig,
    *,
    execute: bool,
    limit: int | None,
    category: str | None,
    max_api_requests: int | None,
) -> dict[str, Any]:
    store = StateStore(_state_path(config))
    downloader = _maybe_build_downloader(config)
    if downloader is None:
        return {
            "command": "tracker-source-backfill",
            "execute": execute,
            "error": "qB secret missing or unreadable",
        }
    all_torrents = _load_policy_torrents(downloader, config)
    all_torrents, missing_reconciled = _apply_live_torrent_state(store, all_torrents)
    candidate_reconciliation = _persist_live_torrent_candidates(store, all_torrents)
    torrents = (
        [torrent for torrent in all_torrents if torrent.category == category]
        if category is not None
        else all_torrents
    )
    candidates = _qb_only_backfill_targets(store, torrents)
    if limit is not None:
        candidates = candidates[:limit]
    request_budget: dict[str, int | None] = {
        "remaining": max_api_requests,
        "used": 0,
    }
    results = _run(
        _backfill_tracker_sources(
            config,
            store,
            candidates,
            execute=execute,
            request_budget=request_budget,
        )
    )
    return {
        "command": "tracker-source-backfill",
        "execute": execute,
        "state_path": str(_state_path(config)),
        "live_torrent_count": len(torrents),
        "category": category,
        "missing_from_qb_reconciled": missing_reconciled,
        "candidate_reconciliation": candidate_reconciliation,
        "qbonly_candidates": len(candidates),
        "api_requests_used": request_budget["used"],
        "api_requests_remaining": request_budget["remaining"],
        "max_api_requests": max_api_requests,
        "summary": _tracker_source_backfill_summary(results),
        "results": results,
    }


def _qb_only_backfill_targets(
    store: StateStore,
    torrents: list[ManagedTorrent],
) -> list[ManagedTorrent]:
    targets: list[ManagedTorrent] = []
    for torrent in torrents:
        if not torrent.hash:
            continue
        rows = store.list_by_torrent_hash(torrent.hash)
        if not rows:
            continue
        amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
        has_tracker_evidence = any(row.get("site") != "qb" for row in rows)
        if amount_left <= 0 and has_tracker_evidence:
            continue
        targets.append(torrent)
    targets.sort(key=lambda torrent: _qb_only_backfill_priority(store, torrent))
    return targets


def _qb_only_backfill_priority(
    store: StateStore,
    torrent: ManagedTorrent,
) -> tuple[int, datetime, int, datetime, str]:
    risk = _qb_only_unknown_free_risk(torrent)
    amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
    return (
        -risk,
        _tracker_evidence_updated_at(store, torrent.hash),
        -amount_left,
        torrent.added_at,
        torrent.name,
    )


def _tracker_evidence_updated_at(store: StateStore, torrent_hash: str) -> datetime:
    rows = [
        row
        for row in store.list_by_torrent_hash(torrent_hash)
        if row.get("site") != "qb" and row.get("updated_at")
    ]
    parsed: list[datetime | None] = []
    for row in rows:
        try:
            value = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
        except ValueError:
            value = None
        parsed.append(value)
    known = [value for value in parsed if value is not None]
    return max(known, default=datetime.min.replace(tzinfo=UTC))


def _qb_only_unknown_free_risk(torrent: ManagedTorrent) -> int:
    state = torrent.state.strip().lower()
    amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
    if amount_left > 0:
        return 3
    if "err" in state and not state.endswith("up"):
        return 2
    if state in {"stoppeddl", "pauseddl", "missingfiles"}:
        return 2
    if state in {"downloading", "stalleddl", "metadl", "checkingdl"}:
        return 1
    return 0


async def _backfill_tracker_sources(
    config: SeedAgentConfig,
    store: StateStore,
    torrents: list[ManagedTorrent],
    *,
    execute: bool,
    request_budget: dict[str, int | None],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for torrent in torrents:
        if _tracker_request_budget_exhausted(request_budget):
            results.append(
                _tracker_source_result(
                    torrent,
                    "skipped",
                    reason="api request budget exhausted",
                )
            )
            continue
        site_name = _infer_tracker_site(torrent)
        if site_name is None:
            results.append(_tracker_source_result(torrent, "skipped", reason="site unknown"))
            continue
        site = _configured_site_for_inferred_tracker(config, site_name)
        if site is None:
            results.append(
                _tracker_source_result(
                    torrent,
                    "skipped",
                    site=site_name,
                    reason="site not configured",
                )
            )
            continue
        site_name = site.name
        if site.type != "mteam":
            results.append(
                _tracker_source_result(
                    torrent,
                    "skipped",
                    site=site_name,
                    reason=f"unsupported tracker type {site.type}",
                )
            )
            continue
        api_key = _read_secret_ref(site.api_key_ref, config.config_dir)
        if not api_key:
            results.append(
                _tracker_source_result(
                    torrent,
                    "skipped",
                    site=site_name,
                    reason="missing mteam api key",
                )
            )
            continue
        match_result = await _find_mteam_match_for_torrent(
            site_name=site.name,
            site_mode=site.api_discovery.mode if site.api_discovery is not None else None,
            api_key=api_key,
            api_key_header=site.auth_header or "x-api-key",
            torrent=torrent,
            request_budget=request_budget,
        )
        result = _tracker_source_result(
            torrent,
            str(match_result["status"]),
            site=site_name,
            reason=match_result.get("reason"),
            match=match_result.get("match"),
        )
        if execute and match_result["status"] == "matched":
            candidate = match_result["candidate"]
            assert isinstance(candidate, TorrentCandidate)
            store.upsert_candidate(
                candidate.stable_id,
                candidate.title,
                candidate.site,
                _lifecycle_state_from_torrent(torrent),
                score=None,
                torrent_hash=torrent.hash,
                free_window_expires_at=_candidate_free_window_expires_at(candidate),
                **_candidate_snapshot_kwargs(
                    candidate,
                    score_reasons=["tracker source backfill matched live qB torrent"],
                ),
            )
            result["updated"] = True
        else:
            result["updated"] = False
        results.append(result)
    return results


def _tracker_source_result(
    torrent: ManagedTorrent,
    status: str,
    *,
    site: str | None = None,
    reason: object = None,
    match: object = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "hash": torrent.hash,
        "name": torrent.name,
        "category": torrent.category,
        "size_gb": round(torrent.size_bytes / 1024**3, 2),
        "incomplete": int(torrent.metadata.get("amount_left_bytes", 0) or 0) > 0,
        "status": status,
    }
    if site is not None:
        result["site"] = site
    if reason:
        result["reason"] = str(reason)
    if match is not None:
        result["match"] = match
    return result


def _tracker_source_backfill_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
        if result.get("updated"):
            summary["updated"] = summary.get("updated", 0) + 1
    return summary


def _tracker_source_backfill_has_rate_limit(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary")
    if isinstance(summary, dict) and int(summary.get("rate_limited") or 0) > 0:
        return True
    for result in payload.get("results") or []:
        if isinstance(result, dict) and result.get("status") == "rate_limited":
            return True
        reason = str(result.get("reason") if isinstance(result, dict) else "")
        if any(marker in reason for marker in MTEAM_RATE_LIMIT_MARKERS):
            return True
    return False


def _tracker_source_backfill_has_network_unavailable(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary")
    if isinstance(summary, dict) and int(summary.get("unavailable") or 0) > 0:
        return True
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        if result.get("status") == "unavailable":
            return True
        reason = str(result.get("reason") or "")
        if _is_mteam_network_message(reason):
            return True
    return False


def _tracker_source_backfill_unresolved_risk_hashes(payload: dict[str, Any]) -> set[str]:
    hashes: set[str] = set()
    for result in payload.get("results") or []:
        if not isinstance(result, dict) or not bool(result.get("incomplete")):
            continue
        status = str(result.get("status") or "")
        if status in {"not_found", "ambiguous", "error"}:
            torrent_hash = str(result.get("hash") or "")
            if torrent_hash:
                hashes.add(torrent_hash)
    return hashes


def _tracker_source_backfill_has_unresolved(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return False
    return any(int(summary.get(status) or 0) > 0 for status in ("not_found", "ambiguous", "error"))


def _is_mteam_network_message(message: str) -> bool:
    return any(error_type in message for error_type in MTEAM_NETWORK_ERROR_TYPES)


def _infer_tracker_site(torrent: ManagedTorrent) -> str | None:
    for tag in torrent.tags:
        if tag.startswith("site:") and len(tag) > len("site:"):
            return tag.split(":", 1)[1].strip() or None
    tracker = str(torrent.metadata.get("tracker") or "")
    if "m-team" in tracker or "mteam" in tracker:
        return "mt"
    return None


def _configured_site_for_inferred_tracker(config: SeedAgentConfig, site_name: str) -> Any | None:
    direct = next((item for item in config.enabled_sites if item.name == site_name), None)
    if direct is not None:
        return direct
    if site_name in {"mteam", "mt"}:
        return next((item for item in config.enabled_sites if item.type == "mteam"), None)
    return None


def _tracker_request_budget_exhausted(budget: dict[str, int | None]) -> bool:
    remaining = budget["remaining"]
    return remaining is not None and remaining <= 0


def _consume_tracker_request_budget(budget: dict[str, int | None]) -> None:
    remaining = budget["remaining"]
    if remaining is not None:
        budget["remaining"] = remaining - 1
    budget["used"] = int(budget["used"] or 0) + 1


async def _find_mteam_match_for_torrent(
    *,
    site_name: str,
    site_mode: str | None,
    api_key: str,
    api_key_header: str,
    torrent: ManagedTorrent,
    request_budget: dict[str, int | None],
) -> dict[str, Any]:
    direct_match = await _find_mteam_match_by_tracker_id(
        site_name=site_name,
        api_key=api_key,
        api_key_header=api_key_header,
        torrent=torrent,
        request_budget=request_budget,
    )
    if direct_match is not None:
        return direct_match

    matches: list[TorrentCandidate] = []
    searched_keywords: list[str] = []
    for keyword in _mteam_backfill_keywords(torrent.name):
        for mode in _mteam_backfill_modes(site_mode):
            if _tracker_request_budget_exhausted(request_budget):
                return {
                    "status": "skipped",
                    "reason": "api request budget exhausted",
                    "searched": searched_keywords,
                }
            _consume_tracker_request_budget(request_budget)
            searched_keywords.append(f"{mode or 'all'}:{keyword}")
            try:
                candidates = await fetch_mteam_api_candidates(
                    site=site_name,
                    api_key=api_key,
                    api_key_header=api_key_header,
                    options=MTeamApiDiscoveryOptions(
                        mode=mode,
                        keyword=keyword,
                        only_free=False,
                        discount=None,
                        sort_field="created_date",
                        sort_order="desc",
                        page_size=20,
                        max_pages=1,
                        max_seeders=None,
                    ),
                )
            except MTeamApiResponseError as exc:
                if exc.rate_limited:
                    request_budget["remaining"] = 0
                    return {
                        "status": "rate_limited",
                        "reason": exc.message,
                        "searched": searched_keywords,
                    }
                if exc.unavailable or exc.retriable:
                    request_budget["remaining"] = 0
                    return {
                        "status": "unavailable",
                        "reason": exc.message,
                        "searched": searched_keywords,
                    }
                return {
                    "status": "error",
                    "reason": str(exc),
                    "searched": searched_keywords,
                }
            except httpx.TimeoutException as exc:
                request_budget["remaining"] = 0
                return {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "searched": searched_keywords,
                }
            except httpx.NetworkError as exc:
                request_budget["remaining"] = 0
                return {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "searched": searched_keywords,
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "reason": str(exc),
                    "searched": searched_keywords,
                }
            matches.extend(_matching_mteam_candidates(torrent, candidates))
        unique = _unique_candidates(matches)
        if len(unique) == 1:
            candidate = unique[0]
            return {
                "status": "matched",
                "candidate": candidate,
                "match": _candidate_match_summary(candidate),
            }
        if len(unique) > 1:
            return {
                "status": "ambiguous",
                "reason": "multiple title/size matches",
                "matches": [_candidate_match_summary(item) for item in unique[:5]],
            }
    return {
        "status": "not_found",
        "reason": "no unique title/size match",
        "searched": searched_keywords,
    }


async def _find_mteam_match_by_tracker_id(
    *,
    site_name: str,
    api_key: str,
    api_key_header: str,
    torrent: ManagedTorrent,
    request_budget: dict[str, int | None],
) -> dict[str, Any] | None:
    torrent_id = _mteam_torrent_id_from_tracker(torrent)
    if torrent_id is None:
        return None
    if _tracker_request_budget_exhausted(request_budget):
        return {
            "status": "skipped",
            "reason": "api request budget exhausted",
            "searched": [f"detail:{torrent_id}"],
        }
    _consume_tracker_request_budget(request_budget)
    client = MTeamApiClient(api_key=api_key, api_key_header=api_key_header)
    try:
        detail = await client.fetch_torrent_detail(torrent_id)
    except MTeamApiResponseError as exc:
        if exc.rate_limited:
            request_budget["remaining"] = 0
            return {
                "status": "rate_limited",
                "reason": exc.message,
                "searched": [f"detail:{torrent_id}"],
            }
        if exc.unavailable or exc.retriable:
            request_budget["remaining"] = 0
            return {
                "status": "unavailable",
                "reason": exc.message,
                "searched": [f"detail:{torrent_id}"],
            }
        return {
            "status": "error",
            "reason": str(exc),
            "searched": [f"detail:{torrent_id}"],
        }
    except httpx.TimeoutException as exc:
        request_budget["remaining"] = 0
        return {
            "status": "unavailable",
            "reason": type(exc).__name__,
            "searched": [f"detail:{torrent_id}"],
        }
    except httpx.NetworkError as exc:
        request_budget["remaining"] = 0
        return {
            "status": "unavailable",
            "reason": type(exc).__name__,
            "searched": [f"detail:{torrent_id}"],
        }
    except Exception as exc:
        return {
            "status": "error",
            "reason": str(exc),
            "searched": [f"detail:{torrent_id}"],
        }
    if detail is None:
        return None
    candidate = await client._candidate_from_search_row(site_name, detail)
    if candidate is None:
        return {
            "status": "error",
            "reason": "mteam detail response missing torrent identity",
            "searched": [f"detail:{torrent_id}"],
        }
    return {
        "status": "matched",
        "candidate": candidate.model_copy(
            update={
                "download_url": f"{DEFERRED_DOWNLOAD_URL_PREFIX}{torrent_id}",
                "metadata": {
                    **candidate.metadata,
                    "mteam_torrent_id": torrent_id,
                    "backfill_match_source": "tracker_tid",
                },
            }
        ),
        "match": _candidate_match_summary(candidate),
        "searched": [f"detail:{torrent_id}"],
    }


def _mteam_torrent_id_from_tracker(torrent: ManagedTorrent) -> str | None:
    tracker = str(torrent.metadata.get("tracker") or "").strip()
    if not tracker:
        return None
    parsed = urlparse(tracker)
    direct = _mteam_torrent_id_from_query(parsed.query)
    if direct is not None:
        return direct
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    credential = params.get("credential")
    if not credential:
        return None
    decoded = _decode_mteam_tracker_credential(credential)
    if decoded is None:
        return None
    return _mteam_torrent_id_from_query(decoded)


def _mteam_torrent_id_from_query(query: str) -> str | None:
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key.lower() in {"tid", "id", "torrent_id", "torrentid"} and value.isdigit():
            return value
    return None


def _decode_mteam_tracker_credential(value: str) -> str | None:
    clean = value.strip()
    if not clean:
        return None
    padded = clean + ("=" * (-len(clean) % 4))
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(padded).decode("utf-8", errors="ignore")
        except binascii.Error, ValueError, TypeError:
            continue
    return None


def _mteam_backfill_keywords(name: str) -> list[str]:
    stripped = _strip_torrent_name_suffix(name)
    keywords = [stripped]
    code_match = re.search(r"\b([A-Z]{2,8}-\d{2,6})\b", stripped, flags=re.IGNORECASE)
    if code_match:
        keywords.insert(0, code_match.group(1).upper())
    compact = " ".join(part for part in re.split(r"[\W_]+", stripped) if part)
    if compact and compact not in keywords:
        keywords.append(compact)
    deduped: list[str] = []
    for keyword in keywords:
        clean = keyword.strip()
        if clean and clean not in deduped:
            deduped.append(clean)
    return deduped[:3]


def _mteam_backfill_modes(site_mode: str | None) -> list[str | None]:
    modes: list[str | None] = []
    if site_mode:
        modes.append(site_mode)
    modes.append(None)
    deduped: list[str | None] = []
    for mode in modes:
        if mode not in deduped:
            deduped.append(mode)
    return deduped


def _matching_mteam_candidates(
    torrent: ManagedTorrent,
    candidates: list[TorrentCandidate],
) -> list[TorrentCandidate]:
    torrent_title = _backfill_title_key(torrent.name)
    return [
        candidate
        for candidate in candidates
        if _backfill_title_key(candidate.title) == torrent_title
        and _size_close_enough(candidate.size_bytes, torrent.size_bytes)
    ]


def _unique_candidates(candidates: list[TorrentCandidate]) -> list[TorrentCandidate]:
    unique: dict[str, TorrentCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.stable_id, candidate)
    return list(unique.values())


def _candidate_match_summary(candidate: TorrentCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.stable_id,
        "title": candidate.title,
        "discount": candidate.discount.value,
        "left_time_minutes": candidate.left_time_minutes,
        "size_gb": round(candidate.size_bytes / 1024**3, 2),
        "seeders": candidate.seeders,
        "leechers": candidate.leechers,
        "mteam_torrent_id": candidate.metadata.get("mteam_torrent_id"),
    }


def _strip_torrent_name_suffix(name: str) -> str:
    stripped = name.strip()
    for suffix in (".!qB", ".mkv", ".mp4", ".ts", ".m2ts", ".iso"):
        if stripped.casefold().endswith(suffix.casefold()):
            return stripped[: -len(suffix)].strip()
    return stripped


def _backfill_title_key(name: str) -> str:
    stripped = _strip_torrent_name_suffix(name)
    return " ".join(part for part in re.split(r"[\W_]+", stripped.casefold()) if part)


def _size_close_enough(left: int, right: int) -> bool:
    if left == right:
        return True
    tolerance = max(64 * 1024 * 1024, int(max(left, right) * 0.01))
    return abs(left - right) <= tolerance


def _torrent_contribution_item(torrent: ManagedTorrent) -> dict[str, Any]:
    downloaded = torrent.downloaded_bytes or torrent.size_bytes
    ratio = torrent.uploaded_bytes / downloaded if downloaded else None
    recent_upload = torrent.metadata.get("recent_upload_gb")
    return {
        "name": torrent.name,
        "hash": torrent.hash,
        "category": torrent.category,
        "state": torrent.state,
        "size_gb": round(torrent.size_bytes / 1024**3, 2),
        "uploaded_gb": round(torrent.uploaded_bytes / 1024**3, 2),
        "downloaded_gb": round(downloaded / 1024**3, 2) if downloaded else 0,
        "ratio": round(ratio, 4) if ratio is not None else None,
        "recent_upload_gb": round(float(recent_upload), 3) if recent_upload is not None else None,
        "progress": torrent.metadata.get("progress"),
        "upspeed": torrent.metadata.get("upspeed"),
        "eta_seconds": torrent.metadata.get("eta_seconds"),
        "no_upload_since_at": _metadata_datetime_string(torrent.metadata.get("no_upload_since_at")),
        "tags": list(torrent.tags),
    }


def _contribution_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_size = sum(float(item.get("size_gb") or 0) for item in items)
    total_uploaded = sum(float(item.get("uploaded_gb") or 0) for item in items)
    zero_upload_large = [
        item
        for item in items
        if float(item.get("uploaded_gb") or 0) <= 0 and float(item.get("size_gb") or 0) >= 100
    ]
    low_recent = [
        item
        for item in items
        if item.get("recent_upload_gb") is not None
        and float(item.get("recent_upload_gb") or 0) <= 0
    ]
    return {
        "total_size_gb": round(total_size, 2),
        "total_uploaded_gb": round(total_uploaded, 2),
        "overall_ratio": round(total_uploaded / total_size, 4) if total_size else None,
        "zero_upload_large_count": len(zero_upload_large),
        "low_recent_upload_count": len(low_recent),
    }


def _metadata_datetime_string(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _run(value: Any) -> Any:
    return asyncio.run(value)


def _apply_site_history_feedback_for_config(
    candidates: list[TorrentCandidate],
    config: SeedAgentConfig,
) -> list[TorrentCandidate]:
    state_path = _state_path(config)
    if not state_path.exists():
        return candidates
    return _apply_site_history_feedback_from_store(candidates, StateStore(state_path))


def _apply_site_history_feedback_from_store(
    candidates: list[TorrentCandidate],
    store: StateStore,
) -> list[TorrentCandidate]:
    return apply_site_history_feedback(candidates, store.site_history_scores())


def _discover_candidates(config: SeedAgentConfig) -> list[TorrentCandidate]:
    try:
        return _run(discover_candidates(config))
    except SiteDiscoveryConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _attach_discovery_warnings(payload: dict[str, Any]) -> None:
    warnings = get_last_discovery_warnings()
    if warnings:
        payload["discovery_warnings"] = warnings


def _runtime_error_summary(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    if not text:
        return type(exc).__name__
    return text[:500]


def _print_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True))


def _print_error_payload(payload: dict[str, Any]) -> int:
    _print_json(payload)
    return 1


def _schedule_log_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary_keys = [
        "command",
        "run_id",
        "config",
        "execute",
        "cycle",
        "interval_minutes",
        "capacity_guard_interval_seconds",
        "scheduled_at",
        "min_free_window_minutes",
        "require_known_free_window",
        "prune_enabled",
        "tracker_backfill_enabled",
        "tracker_backfill_category",
        "tracker_backfill_unbounded",
        "intent_enabled",
        "intent_execute",
        "scheduler_config_source",
        "scheduler_cli_overrides",
        "manual_trigger",
        "intent_search_enabled",
        "schedule_backoff",
        "skipped_by_backoff",
        "heartbeat_file",
        "discovered",
        "scored",
        "accepted",
        "enqueued",
        "enqueue_paused_by_pool_policy",
        "enqueue_blocked_by_runtime_gate",
        "enqueue_blocked_reasons",
        "default_pool_usage",
        "runtime_activity",
        "discovery_warnings",
        "error",
    ]
    summary = {key: payload[key] for key in summary_keys if key in payload}
    summary["scores_count"] = len(payload.get("scores") or [])
    summary["decisions_count"] = len(payload.get("decisions") or [])
    for key in ("prune", "capacity_prune"):
        prune_payload = payload.get(key)
        prune_summary = _prune_payload_summary(prune_payload)
        if prune_summary is not None:
            summary[key] = prune_summary
    tracker_backfill_summary = _tracker_source_backfill_payload_summary(
        payload.get("tracker_source_backfill")
    )
    if tracker_backfill_summary is not None:
        summary["tracker_source_backfill"] = tracker_backfill_summary
    intent_summary = _intent_payload_summary(payload.get("intent"))
    if intent_summary is not None:
        summary["intent"] = intent_summary
    return summary


def _prune_payload_summary(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "command": payload.get("command"),
        "execute": payload.get("execute"),
        "force_space_reclamation": payload.get("force_space_reclamation"),
        "completed_low_upload_requires_reclamation": payload.get(
            "completed_low_upload_requires_reclamation"
        ),
        "reclaim_targets_by_pool": payload.get("reclaim_targets_by_pool"),
        "reclaimed_capacity_by_pool": payload.get("reclaimed_capacity_by_pool"),
        "verified_committed_reclaim_by_pool": payload.get(
            "verified_committed_reclaim_by_pool"
        ),
        "verified_downloaded_reclaim_by_pool": payload.get(
            "verified_downloaded_reclaim_by_pool"
        ),
        "hard_cap_satisfied": payload.get("hard_cap_satisfied"),
        "hard_cap_violations_by_pool": payload.get("hard_cap_violations_by_pool"),
        "unknown_free_risk_count": payload.get("unknown_free_risk_count"),
        "delete_count": (payload.get("cleanup_evidence") or {}).get("delete_count"),
        "managed_count": payload.get("managed_count"),
        "decisions_count": len(payload.get("decisions") or []),
        "preview_count": len(payload.get("preview") or []),
        "pool_usage_before": payload.get("pool_usage_before"),
        "pool_usage": payload.get("pool_usage"),
        "error": payload.get("error"),
    }


def _tracker_source_backfill_payload_summary(
    payload: object,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "command": payload.get("command"),
        "execute": payload.get("execute"),
        "category": payload.get("category"),
        "live_torrent_count": payload.get("live_torrent_count"),
        "qbonly_candidates": payload.get("qbonly_candidates"),
        "api_requests_used": payload.get("api_requests_used"),
        "api_requests_remaining": payload.get("api_requests_remaining"),
        "max_api_requests": payload.get("max_api_requests"),
        "summary": payload.get("summary"),
        "error": payload.get("error"),
    }


def _intent_payload_summary(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    summary = {
        "command": payload.get("command"),
        "run_id": payload.get("run_id"),
        "execute": payload.get("execute"),
        "search_enabled": payload.get("search_enabled"),
        "ingested": payload.get("ingested"),
        "searched": payload.get("searched"),
        "ranked": payload.get("ranked"),
        "enqueue_candidates": payload.get("enqueue_candidates"),
        "decisions_count": len(payload.get("decisions") or []),
    }
    if payload.get("source_warnings"):
        summary["source_warnings"] = payload.get("source_warnings")
    if payload.get("skipped_by_backoff"):
        summary["skipped_by_backoff"] = payload.get("skipped_by_backoff")
    if payload.get("schedule_backoff"):
        summary["schedule_backoff"] = payload.get("schedule_backoff")
    return summary


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


def _candidate_snapshot_kwargs(
    candidate: TorrentCandidate,
    *,
    score_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "size_bytes": candidate.size_bytes,
        "seeders": candidate.seeders,
        "leechers": candidate.leechers,
        "discount": candidate.discount.value,
        "left_time_minutes": candidate.left_time_minutes,
        "score_reasons": score_reasons,
    }


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
    *,
    store: StateStore | None = None,
) -> dict[str, Any]:
    upspeed = int(torrent.metadata.get("upspeed_bps", 0) or 0)
    dlspeed = int(torrent.metadata.get("dlspeed_bps", 0) or 0)
    uploaded_session = int(torrent.metadata.get("uploaded_session_bytes", 0) or 0)
    amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
    ratio = (
        torrent.uploaded_bytes / torrent.downloaded_bytes if torrent.downloaded_bytes > 0 else None
    )
    no_upload_since_at = torrent.metadata.get("no_upload_since_at")
    summary = {
        "hash": torrent.hash,
        "name": torrent.name,
        "category": torrent.category,
        "tags": sorted(torrent.tags),
        "state": torrent.state,
        "size_gb": round(torrent.size_bytes / (1024**3), 2),
        "uploaded_gb": round(torrent.uploaded_bytes / (1024**3), 2),
        "downloaded_gb": round(torrent.downloaded_bytes / (1024**3), 2),
        "ratio": round(ratio, 4) if ratio is not None else None,
        "added_at": torrent.added_at.isoformat(),
        "completed_at": torrent.completed_at.isoformat()
        if torrent.completed_at is not None
        else None,
        "last_activity_at": torrent.last_activity_at.isoformat()
        if torrent.last_activity_at is not None
        else None,
        "upspeed_mib_s": round(upspeed / 1024**2, 3),
        "dlspeed_mib_s": round(dlspeed / 1024**2, 3),
        "uploaded_session_gb": round(uploaded_session / 1024**3, 3),
        "amount_left_gb": round(amount_left / 1024**3, 3),
        "active_uploading": upspeed > 0,
        "active_downloading": dlspeed > 0,
    }
    if isinstance(no_upload_since_at, datetime):
        summary["no_upload_since_at"] = no_upload_since_at.isoformat()
    elif no_upload_since_at is not None:
        summary["no_upload_since_at"] = str(no_upload_since_at)
    if policy is not None:
        summary["policy_mode"] = policy.mode
        summary["budget_pool"] = policy.budget_pool
    if store is not None:
        evidence = _candidate_evidence_summary(store, torrent.hash)
        if evidence is not None:
            summary["candidate_evidence"] = evidence
    return summary


def _managed_torrents_for_report(
    config: SeedAgentConfig,
    *,
    store: StateStore | None = None,
) -> list[ManagedTorrent]:
    torrents, _ = _managed_torrents_for_report_with_reconciliation(config, store=store)
    return torrents


def _managed_torrents_for_report_with_reconciliation(
    config: SeedAgentConfig,
    *,
    store: StateStore | None = None,
) -> tuple[list[ManagedTorrent], int]:
    downloader = _maybe_build_downloader(config)
    if downloader is None:
        return [], 0
    torrents = _load_policy_torrents(downloader, config)
    return _apply_live_torrent_state(store or StateStore(_state_path(config)), torrents)


def _apply_live_torrent_state(
    store: StateStore,
    torrents: list[ManagedTorrent],
) -> tuple[list[ManagedTorrent], int]:
    enriched = store.apply_torrent_runtime(torrents)
    live_hashes = {torrent.hash for torrent in enriched if torrent.hash}
    missing_count = store.reconcile_missing_torrents(live_hashes)
    return enriched, missing_count


def _candidate_evidence_summary(store: StateStore, torrent_hash: str) -> dict[str, Any] | None:
    rows = store.list_by_torrent_hash(torrent_hash)
    if not rows:
        return None
    non_qb_rows = [row for row in rows if row.get("site") != "qb"]
    row = (non_qb_rows or rows)[-1]
    return {
        "candidate_id": row["stable_id"],
        "candidate_state": row["state"],
        "site": row["site"],
        "title": row["title"],
        "score": row["score"],
        "size_gb": round(row["size_bytes"] / 1024**3, 2)
        if row.get("size_bytes") is not None
        else None,
        "seeders": row.get("seeders"),
        "leechers": row.get("leechers"),
        "discount": row.get("discount"),
        "left_time_minutes": row.get("left_time_minutes"),
        "free_window_expires_at": row.get("free_window_expires_at"),
        "score_reasons": row.get("score_reasons") or [],
        "first_seen_at": row.get("first_seen_at"),
        "updated_at": row.get("updated_at"),
    }


def _policy_lookup(config: SeedAgentConfig) -> dict[str, CategoryPolicyConfig]:
    return {policy.name: policy for policy in config.download_client.category_policies}


def _default_category_policy(config: SeedAgentConfig) -> CategoryPolicyConfig:
    return _policy_lookup(config)[config.download_client.default_category]


def _intent_category_policy(
    config: SeedAgentConfig,
    intent: ResourceIntent,
) -> CategoryPolicyConfig:
    policies = _policy_lookup(config)
    media_type = (
        str(intent.metadata.get("media_type") or intent.metadata.get("kind") or "").strip().lower()
    )
    if media_type == "anime":
        mapped_category = config.download_client.media_category_map.get("anime")
        if mapped_category and mapped_category in policies:
            return policies[mapped_category]
        return policies.get("tv") or _default_category_policy(config)
    if intent.kind == IntentKind.MOVIE or media_type == "movie":
        mapped_category = config.download_client.media_category_map.get("movie")
        if mapped_category and mapped_category in policies:
            return policies[mapped_category]
        return policies.get("movie") or _default_category_policy(config)
    if intent.kind in {IntentKind.SHOW, IntentKind.EPISODE} or media_type in {
        "tv",
        "show",
        "series",
    }:
        mapped_category = config.download_client.media_category_map.get("tv")
        if mapped_category and mapped_category in policies:
            return policies[mapped_category]
        return policies.get("tv") or _default_category_policy(config)
    return _default_category_policy(config)


def _load_policy_torrents(
    downloader: Downloader | _NullDownloader,
    config: SeedAgentConfig,
    *,
    policies: list[CategoryPolicyConfig] | None = None,
) -> list[ManagedTorrent]:
    selected_policies = (
        policies if policies is not None else config.download_client.category_policies
    )
    policy_names = {policy.name for policy in selected_policies}
    torrents: list[ManagedTorrent] = []
    seen_hashes: set[str] = set()
    category_filter = next(iter(policy_names)) if len(policy_names) == 1 else None
    if isinstance(downloader, TransmissionClient):
        listed = downloader.list_torrents(
            category_filter,
            None,
            known_policy_categories=policy_names,
        )
    else:
        listed = downloader.list_torrents(category_filter, None)
    for torrent in _run(listed):
        if torrent.category not in policy_names:
            continue
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
        config.download_client.category_policies,
        config.download_client.budget_pools,
        torrents,
    )
    return {name: _pool_usage_item_summary(item) for name, item in usage.items()}


def _default_category_budget_state(
    config: SeedAgentConfig,
    downloader: Downloader | _NullDownloader | None = None,
) -> tuple[bool, PoolUsage | None]:
    if downloader is None:
        downloader = _maybe_build_downloader(config)
    if downloader is None:
        return False, None
    torrents = _load_policy_torrents(downloader, config)
    return _default_category_budget_state_from_torrents(config, torrents)


def _default_category_budget_state_from_torrents(
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
) -> tuple[bool, PoolUsage | None]:
    if not torrents and not config.download_client.category_policies:
        return False, None
    default_policy = _default_category_policy(config)
    usage = usage_by_pool(
        config.download_client.category_policies,
        config.download_client.budget_pools,
        torrents,
    )
    pool_usage = usage[default_policy.budget_pool]
    paused = pool_usage.over_budget and config.pt_filters.max_total_amount_left_gb is None
    return paused, pool_usage


def _downloader_status(
    downloader: Downloader | _NullDownloader | None,
) -> DownloaderStatus | None:
    if not isinstance(downloader, DownloaderStatusProvider):
        return None
    return _run(downloader.get_status())


def _enqueue_runtime_context(
    config: SeedAgentConfig,
    *,
    store: StateStore,
    execute: bool,
) -> tuple[
    Downloader | _NullDownloader,
    list[ManagedTorrent],
    DownloaderStatus | None,
    bool,
    PoolUsage | None,
    int,
]:
    live_downloader = build_downloader(config) if execute else _maybe_build_downloader(config)
    if live_downloader is None:
        return _NullDownloader(), [], None, False, None, 0
    live_torrents = _load_policy_torrents(live_downloader, config)
    downloader_status = _downloader_status(live_downloader)
    live_torrents, missing_reconciled = _apply_live_torrent_state(store, live_torrents)
    _persist_live_torrent_candidates(store, live_torrents)
    paused, pool_usage = _default_category_budget_state_from_torrents(config, live_torrents)
    paused = paused or bool(
        _enqueue_pause_reasons(config, live_torrents, pool_usage, downloader_status)
    )
    return live_downloader, live_torrents, downloader_status, paused, pool_usage, missing_reconciled


def _build_intent_enqueue_context_resolver(
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
    downloader_status: DownloaderStatus | None,
) -> Callable[
    [ResourceIntent, CategoryPolicyConfig, ScoreBreakdown],
    tuple[bool, PoolUsage | None, list[str]],
]:
    pool_usage_by_name = usage_by_pool(
        config.download_client.category_policies,
        config.download_client.budget_pools,
        torrents,
    )
    reserved_pool_bytes: dict[str, int] = {}
    reserved_download_bytes = 0
    reserved_active_downloads = 0
    existing_download_bytes = sum(_download_liability_bytes(item) for item in torrents)
    existing_active_downloads = int(_runtime_activity_summary(torrents)["active_download_count"])
    disk_state = _disk_headroom_state(config, downloader_status, torrents)
    max_active_downloads = config.pt_filters.max_active_downloads
    max_download_bytes = (
        int(config.pt_filters.max_total_amount_left_gb * 1024**3)
        if config.pt_filters.max_total_amount_left_gb is not None
        else None
    )

    def resolve(
        intent: ResourceIntent,
        policy: CategoryPolicyConfig,
        score: ScoreBreakdown,
    ) -> tuple[bool, PoolUsage | None, list[str]]:
        nonlocal reserved_active_downloads, reserved_download_bytes
        del intent
        candidate_bytes = max(int(score.candidate.size_bytes), 0)
        base_pool_usage = pool_usage_by_name.get(policy.budget_pool)
        reserved_for_pool = reserved_pool_bytes.get(policy.budget_pool, 0)
        pool_usage = (
            PoolUsage(
                pool_name=base_pool_usage.pool_name,
                size_bytes=base_pool_usage.size_bytes + reserved_for_pool,
                max_size_bytes=base_pool_usage.max_size_bytes,
            )
            if base_pool_usage is not None
            else None
        )
        reasons: list[str] = []
        if (
            pool_usage is not None
            and pool_usage.size_bytes + candidate_bytes > pool_usage.max_size_bytes
        ):
            reasons.append(
                f"budget pool {pool_usage.pool_name} projected usage "
                f"{round((pool_usage.size_bytes + candidate_bytes) / 1024**4, 4)} TiB "
                f"> max {round(pool_usage.max_size_bytes / 1024**4, 4)} TiB"
            )
        projected_active_downloads = existing_active_downloads + reserved_active_downloads
        if max_active_downloads is not None and projected_active_downloads >= max_active_downloads:
            reasons.append(
                f"active downloads {projected_active_downloads} >= max {max_active_downloads}"
            )
        projected_download_bytes = (
            existing_download_bytes + reserved_download_bytes + candidate_bytes
        )
        if max_download_bytes is not None and projected_download_bytes > max_download_bytes:
            reasons.append(
                f"projected remaining download "
                f"{round(projected_download_bytes / 1024**3, 4)} GiB > max "
                f"{config.pt_filters.max_total_amount_left_gb} GiB"
            )
        if disk_state is not None and reserved_download_bytes + candidate_bytes > int(
            disk_state["available_for_new_bytes"]
        ):
            reasons.append(_disk_headroom_batch_reason(disk_state))

        if not reasons:
            reserved_pool_bytes[policy.budget_pool] = reserved_for_pool + candidate_bytes
            reserved_download_bytes += candidate_bytes
            reserved_active_downloads += 1
        return bool(reasons), pool_usage, reasons

    return resolve


async def _enqueue_candidate_batches_action(
    batches: list[tuple[list[ScoreBreakdown], bool, list[str]]],
    downloader: Downloader | _NullDownloader,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    pool_usage: PoolUsage | None,
) -> list[Decision]:
    decisions: list[Decision] = []
    for batch, paused, pause_reasons in batches:
        if not batch:
            continue
        try:
            batch_decisions = await enqueue_candidates(
                batch,
                downloader,
                policy,
                execute,
                paused=paused,
                pool_usage=pool_usage,
                pause_reasons=pause_reasons,
            )
        except MutationBatchError as exc:
            raise MutationBatchError(
                str(exc),
                [*decisions, *exc.decisions],
            ) from exc
        decisions.extend(batch_decisions)
    return decisions


def _enqueue_candidate_batches(
    scored: list[ScoreBreakdown],
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
    pool_usage: PoolUsage | None,
    downloader_status: DownloaderStatus | None,
) -> list[tuple[list[ScoreBreakdown], bool, list[str]]]:
    accepted = sorted(
        (item for item in scored if item.accepted),
        key=candidate_value_score,
        reverse=True,
    )
    if not accepted:
        return [(list(scored), False, [])]

    hard_reasons = _enqueue_pause_reasons(
        config,
        torrents,
        pool_usage,
        downloader_status,
        include_amount=False,
    )
    if hard_reasons:
        return [(accepted, True, hard_reasons)]

    max_left_gb = config.pt_filters.max_total_amount_left_gb
    max_left_bytes = int(max_left_gb * 1024**3) if max_left_gb is not None else None
    disk_state = _disk_headroom_state(config, downloader_status, torrents)
    disk_max_new_bytes = (
        int(disk_state["available_for_new_bytes"]) if disk_state is not None else None
    )
    planned_left_bytes = sum(_download_liability_bytes(torrent) for torrent in torrents)
    planned_new_bytes = 0
    runtime = _runtime_activity_summary(torrents)
    planned_active_downloads = int(runtime["active_download_count"])
    max_active_downloads = config.pt_filters.max_active_downloads
    planned_pool_new_bytes = 0
    active: list[ScoreBreakdown] = []
    paused_for_amount: list[ScoreBreakdown] = []
    paused_for_disk: list[ScoreBreakdown] = []
    paused_for_active: list[ScoreBreakdown] = []
    paused_for_pool: list[ScoreBreakdown] = []
    for item in accepted:
        candidate_left = max(int(item.candidate.size_bytes), 0)
        if max_active_downloads is not None and planned_active_downloads >= max_active_downloads:
            paused_for_active.append(item)
        elif (
            pool_usage is not None
            and pool_usage.size_bytes + planned_pool_new_bytes + candidate_left
            > pool_usage.max_size_bytes
        ):
            paused_for_pool.append(item)
        elif max_left_bytes is not None and planned_left_bytes + candidate_left > max_left_bytes:
            paused_for_amount.append(item)
        elif (
            disk_max_new_bytes is not None
            and planned_new_bytes + candidate_left > disk_max_new_bytes
        ):
            paused_for_disk.append(item)
        else:
            active.append(item)
            planned_active_downloads += 1

            planned_pool_new_bytes += candidate_left
            planned_left_bytes += candidate_left
            planned_new_bytes += candidate_left

    batches: list[tuple[list[ScoreBreakdown], bool, list[str]]] = []
    if active:
        batches.append((active, False, []))
    if paused_for_active:
        batches.append(
            (
                paused_for_active,
                True,
                [
                    f"active download slots reserved for higher-score candidates "
                    f"({planned_active_downloads} / max {max_active_downloads})"
                ],
            )
        )
    if paused_for_pool and pool_usage is not None:
        batches.append(
            (
                paused_for_pool,
                True,
                [
                    f"budget pool {pool_usage.pool_name} capacity reserved for "
                    f"higher-score candidates "
                    f"({round((pool_usage.size_bytes + planned_pool_new_bytes) / 1024**4, 4)} "
                    f"/ max {round(pool_usage.max_size_bytes / 1024**4, 4)} TiB)"
                ],
            )
        )
    if paused_for_amount:
        batches.append(
            (
                paused_for_amount,
                True,
                [
                    f"remaining download budget reserved for higher-score candidates "
                    f"({round(planned_left_bytes / 1024**3, 4)} GiB / max {max_left_gb})"
                ],
            )
        )
    if paused_for_disk and disk_state is not None:
        batches.append(
            (
                paused_for_disk,
                True,
                [_disk_headroom_batch_reason(disk_state)],
            )
        )
    return batches


def _batch_pause_reasons(
    batches: list[tuple[list[ScoreBreakdown], bool, list[str]]],
) -> list[str]:
    reasons: list[str] = []
    for _, paused, batch_reasons in batches:
        if not paused:
            continue
        for reason in batch_reasons:
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def _intent_enqueue_pause_state(
    decisions: list[Decision],
    *,
    fallback_paused: bool,
    fallback_reasons: list[str],
) -> tuple[bool, list[str]]:
    enqueue_states = [
        decision.new_state
        for decision in decisions
        if decision.action in {"qb.enqueue", "qb.enqueue.failed", "qb.enqueue.rejected"}
        and isinstance(decision.new_state, dict)
    ]
    if not enqueue_states:
        return fallback_paused, list(fallback_reasons)
    paused = any(
        bool(state.get("paused")) or bool(state.get("rejected"))
        for state in enqueue_states
    )
    reasons: list[str] = []
    for state in enqueue_states:
        raw_reasons = state.get("pause_reasons")
        if not isinstance(raw_reasons, list):
            continue
        for reason in raw_reasons:
            text = str(reason)
            if text and text not in reasons:
                reasons.append(text)
    return paused, reasons


def _enqueue_pause_reasons(
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
    pool_usage: PoolUsage | None,
    downloader_status: DownloaderStatus | None = None,
    *,
    include_amount: bool = True,
) -> list[str]:
    reasons: list[str] = []
    if pool_usage is not None and pool_usage.over_budget:
        reasons.append(
            f"budget pool {pool_usage.pool_name} over budget "
            f"({round(pool_usage.size_bytes / 1024**4, 2)} / "
            f"{round(pool_usage.max_size_bytes / 1024**4, 2)} TiB)"
        )
    runtime = _runtime_activity_summary(torrents)
    max_active_downloads = config.pt_filters.max_active_downloads
    if (
        max_active_downloads is not None
        and runtime["active_download_count"] >= max_active_downloads
    ):
        reasons.append(
            f"active downloads {runtime['active_download_count']} >= max {max_active_downloads}"
        )
    disk_state = _disk_headroom_state(config, downloader_status, torrents)
    if disk_state is not None and bool(disk_state["over_existing_liability"]):
        reasons.append(_disk_headroom_existing_reason(disk_state))
    max_total_amount_left_gb = config.pt_filters.max_total_amount_left_gb
    if not include_amount:
        return reasons
    total_amount_left_bytes = sum(_download_liability_bytes(torrent) for torrent in torrents)
    total_amount_left_gb = total_amount_left_bytes / 1024**3
    if max_total_amount_left_gb is not None and total_amount_left_gb > max_total_amount_left_gb:
        reasons.append(
            f"remaining download {round(total_amount_left_gb, 4)} GiB > max "
            f"{max_total_amount_left_gb}"
        )
    return reasons


def _capacity_reclaim_target_bytes(
    scored: list[ScoreBreakdown],
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
    pool_usage: PoolUsage | None,
    downloader_status: DownloaderStatus | None,
) -> int:
    accepted_bytes = sum(max(int(item.candidate.size_bytes), 0) for item in scored if item.accepted)
    targets: list[int] = []
    if pool_usage is not None:
        targets.append(max(pool_usage.size_bytes + accepted_bytes - pool_usage.max_size_bytes, 0))

    existing_liability = sum(_download_liability_bytes(torrent) for torrent in torrents)
    max_total_amount_left_gb = config.pt_filters.max_total_amount_left_gb
    if max_total_amount_left_gb is not None:
        max_total_amount_left_bytes = int(max_total_amount_left_gb * 1024**3)
        targets.append(
            max(
                existing_liability + accepted_bytes - max_total_amount_left_bytes,
                0,
            )
        )

    disk_state = _disk_headroom_state(config, downloader_status, torrents)
    if disk_state is not None:
        targets.append(
            max(
                existing_liability + accepted_bytes - int(disk_state["usable_free_bytes"]),
                0,
            )
        )
    return max(targets, default=0)


def _disk_headroom_state(
    config: SeedAgentConfig,
    downloader_status: DownloaderStatus | None,
    torrents: list[ManagedTorrent],
) -> dict[str, int | bool] | None:
    if downloader_status is None or downloader_status.free_space_bytes is None:
        return None
    free_space_bytes = max(int(downloader_status.free_space_bytes), 0)
    reserve_bytes = int((config.pt_filters.min_free_disk_gb or 0) * 1024**3)
    existing_liability_bytes = sum(_download_liability_bytes(torrent) for torrent in torrents)
    usable_free_bytes = max(free_space_bytes - reserve_bytes, 0)
    available_for_new_bytes = max(usable_free_bytes - existing_liability_bytes, 0)
    return {
        "free_space_bytes": free_space_bytes,
        "reserve_bytes": reserve_bytes,
        "existing_liability_bytes": existing_liability_bytes,
        "usable_free_bytes": usable_free_bytes,
        "available_for_new_bytes": available_for_new_bytes,
        "over_existing_liability": existing_liability_bytes > usable_free_bytes,
    }


def _downloader_status_summary(
    config: SeedAgentConfig,
    downloader_status: DownloaderStatus,
    torrents: list[ManagedTorrent],
) -> dict[str, float | bool | None]:
    state = _disk_headroom_state(config, downloader_status, torrents)
    if state is None:
        return {
            "free_space_gb": None,
            "min_free_disk_gb": config.pt_filters.min_free_disk_gb,
        }
    return {
        "free_space_gb": round(int(state["free_space_bytes"]) / 1024**3, 2),
        "min_free_disk_gb": config.pt_filters.min_free_disk_gb,
        "existing_download_liability_gb": round(
            int(state["existing_liability_bytes"]) / 1024**3,
            2,
        ),
        "available_for_new_downloads_gb": round(
            int(state["available_for_new_bytes"]) / 1024**3,
            2,
        ),
        "over_existing_liability": bool(state["over_existing_liability"]),
    }


def _disk_headroom_existing_reason(state: dict[str, int | bool]) -> str:
    return (
        f"free disk {round(int(state['usable_free_bytes']) / 1024**3, 4)} GiB below "
        f"existing remaining download "
        f"{round(int(state['existing_liability_bytes']) / 1024**3, 4)} GiB"
    )


def _disk_headroom_batch_reason(state: dict[str, int | bool]) -> str:
    return (
        f"free disk reserved for higher-score candidates "
        f"({round(int(state['available_for_new_bytes']) / 1024**3, 4)} GiB available)"
    )


def _download_liability_bytes(torrent: ManagedTorrent) -> int:
    amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
    if amount_left <= 0:
        return 0
    state = torrent.state.strip().lower()
    if (
        state.startswith("paused") or state.startswith("stopped")
    ) and torrent.downloaded_bytes <= 0:
        return 0
    return amount_left


def _pool_usage_for_policy(
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
    policy: CategoryPolicyConfig,
) -> PoolUsage | None:
    usage = usage_by_pool(
        config.download_client.category_policies,
        config.download_client.budget_pools,
        torrents,
    )
    return usage.get(policy.budget_pool)


def _pool_usage_item_summary(pool_usage: PoolUsage) -> dict[str, float | bool]:
    return {
        "size_tib": round(pool_usage.size_bytes / 1024**4, 2),
        "max_size_tib": round(pool_usage.max_size_bytes / 1024**4, 2),
        "over_budget": pool_usage.over_budget,
    }


def _persist_live_torrent_candidates(
    store: StateStore,
    torrents: list[ManagedTorrent],
) -> dict[str, int]:
    unlinked_by_identity = _unlinked_candidate_identity_map(store)
    unlinked_by_mteam_id = _unlinked_mteam_candidate_id_map(store)
    created_qb_records = 0
    linked_existing_candidates = 0
    marked_present = 0
    for torrent in torrents:
        existing_rows = store.list_by_torrent_hash(torrent.hash)
        non_qb_rows = [row for row in existing_rows if row.get("site") != "qb"]
        if non_qb_rows:
            store.mark_present_by_torrent_hash(
                torrent.hash,
                _lifecycle_state_from_torrent(torrent),
            )
            marked_present += 1
            continue
        tracker_id = _mteam_torrent_id_from_tracker(torrent)
        linked_row = unlinked_by_mteam_id.get(tracker_id) if tracker_id is not None else None
        if linked_row is None:
            linked_row = unlinked_by_identity.get(_live_torrent_identity(torrent))
        if linked_row is not None:
            store.upsert_candidate(
                stable_id=str(linked_row["stable_id"]),
                title=str(linked_row["title"]),
                site=str(linked_row["site"]),
                state=_lifecycle_state_from_torrent(torrent),
                score=linked_row.get("score"),
                torrent_hash=torrent.hash,
                size_bytes=torrent.size_bytes,
            )
            linked_existing_candidates += 1
            continue
        if existing_rows:
            store.mark_present_by_torrent_hash(
                torrent.hash,
                _lifecycle_state_from_torrent(torrent),
            )
            marked_present += 1
            continue
        store.upsert_candidate(
            stable_id=f"qb:{torrent.hash}",
            title=torrent.name,
            site="qb",
            state=_lifecycle_state_from_torrent(torrent),
            score=None,
            torrent_hash=torrent.hash,
            size_bytes=torrent.size_bytes,
        )
        created_qb_records += 1
    return {
        "created_qb_records": created_qb_records,
        "linked_existing_candidates": linked_existing_candidates,
        "marked_present": marked_present,
    }


def _unlinked_candidate_identity_map(store: StateStore) -> dict[tuple[str, int], dict[str, Any]]:
    candidates: dict[tuple[str, int], dict[str, Any]] = {}
    for row in store.list_unlinked_candidates():
        size_bytes = row.get("size_bytes")
        if size_bytes is None:
            continue
        try:
            identity = (_normalize_torrent_title(str(row["title"])), int(size_bytes))
        except TypeError, ValueError:
            continue
        candidates.setdefault(identity, row)
    return candidates


def _unlinked_mteam_candidate_id_map(store: StateStore) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    marker = "/detail/"
    for row in store.list_unlinked_candidates():
        stable_id = str(row.get("stable_id") or "")
        if row.get("site") == "qb" or marker not in stable_id:
            continue
        torrent_id = stable_id.rsplit(marker, 1)[-1].strip()
        if torrent_id.isdigit():
            candidates.setdefault(torrent_id, row)
    return candidates


def _lifecycle_state_from_torrent(torrent: ManagedTorrent) -> LifecycleState:
    state = torrent.state.strip().lower()
    if state.startswith("paused") or state.startswith("stopped"):
        return LifecycleState.PAUSED
    if state in {"downloading", "stalleddl", "metadl", "checkingdl"}:
        return LifecycleState.DOWNLOADING
    return LifecycleState.SEEDING


def _prune_preview(
    decisions: list[Decision],
    torrents: list[ManagedTorrent],
    store: StateStore,
) -> list[dict[str, Any]]:
    torrents_by_hash = {torrent.hash: torrent for torrent in torrents}
    preview: list[dict[str, Any]] = []
    for decision in decisions:
        torrent = torrents_by_hash.get(decision.target_id)
        rows = store.list_by_torrent_hash(decision.target_id)
        candidate_state = rows[-1]["state"] if rows else None
        candidate_id = rows[-1]["stable_id"] if rows else None
        item: dict[str, Any] = {
            "hash": decision.target_id,
            "candidate_id": candidate_id,
            "candidate_state": candidate_state,
            "action": decision.action,
            "execute": decision.execute,
            "reason": decision.reason,
            "delete_files_on_delete": True,
        }
        if torrent is not None:
            evidence_summary = _managed_torrent_summary(torrent, store=store)
            item.update(
                {
                    "name": torrent.name,
                    "category": torrent.category,
                    "state": torrent.state,
                    "size_gb": round(torrent.size_bytes / 1024**3, 2),
                    "uploaded_gb": round(torrent.uploaded_bytes / 1024**3, 2),
                    "downloaded_gb": round(torrent.downloaded_bytes / 1024**3, 2),
                    "ratio": evidence_summary.get("ratio"),
                    "completed_at": evidence_summary.get("completed_at"),
                    "amount_left_gb": evidence_summary.get("amount_left_gb"),
                    "upspeed_mib_s": evidence_summary.get("upspeed_mib_s"),
                    "dlspeed_mib_s": evidence_summary.get("dlspeed_mib_s"),
                    "uploaded_session_gb": evidence_summary.get("uploaded_session_gb"),
                    "no_upload_since_at": evidence_summary.get("no_upload_since_at"),
                    "free_window_expires_at": torrent.metadata.get("free_window_expires_at"),
                    "recent_upload_gb": torrent.metadata.get("recent_upload_gb"),
                }
            )
            if "candidate_evidence" in evidence_summary:
                item["candidate_evidence"] = evidence_summary["candidate_evidence"]
        preview.append(item)
    return preview


def _cleanup_decision_evidence(preview: list[dict[str, Any]]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    low_upload_large: list[dict[str, Any]] = []
    deletion_candidates: list[dict[str, Any]] = []
    for item in preview:
        action = str(item.get("action") or "unknown")
        by_action[action] = by_action.get(action, 0) + 1
        sample = _cleanup_evidence_sample(item)
        if action.endswith(".delete"):
            deletion_candidates.append(sample)
        uploaded = float(item.get("uploaded_gb") or 0)
        recent = item.get("recent_upload_gb")
        recent_value = float(recent or 0) if recent is not None else None
        size = float(item.get("size_gb") or 0)
        if size >= 100 and uploaded <= 0 and (recent_value is None or recent_value <= 0):
            low_upload_large.append(sample)
    return {
        "total": len(preview),
        "by_action": by_action,
        "delete_count": len(deletion_candidates),
        "low_upload_large_count": len(low_upload_large),
        "delete_samples": deletion_candidates[:10],
        "low_upload_large_samples": low_upload_large[:10],
    }


def _cleanup_evidence_sample(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "hash": item.get("hash"),
        "candidate_id": item.get("candidate_id"),
        "name": item.get("name"),
        "action": item.get("action"),
        "reason": item.get("reason"),
        "size_gb": item.get("size_gb"),
        "uploaded_gb": item.get("uploaded_gb"),
        "recent_upload_gb": item.get("recent_upload_gb"),
        "ratio": item.get("ratio"),
        "no_upload_since_at": item.get("no_upload_since_at"),
    }


def _runtime_activity_summary(torrents: list[ManagedTorrent]) -> dict[str, float | int]:
    total_upspeed = 0
    total_dlspeed = 0
    total_amount_left = 0
    total_download_liability = 0
    active_upload_count = 0
    active_download_count = 0
    paused_count = 0
    stalled_upload_count = 0
    stalled_download_count = 0

    for torrent in torrents:
        state = torrent.state.lower()
        upspeed = int(torrent.metadata.get("upspeed_bps", 0) or 0)
        dlspeed = int(torrent.metadata.get("dlspeed_bps", 0) or 0)
        amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
        total_upspeed += upspeed
        total_dlspeed += dlspeed
        total_amount_left += amount_left
        total_download_liability += _download_liability_bytes(torrent)
        if upspeed > 0:
            active_upload_count += 1
        if dlspeed > 0 or state in {"stalleddl", "metadl"}:
            active_download_count += 1
        if state.startswith("paused"):
            paused_count += 1
        if state == "stalledup":
            stalled_upload_count += 1
        if state in {"stalleddl", "metadl"}:
            stalled_download_count += 1

    return {
        "managed_count": len(torrents),
        "active_upload_count": active_upload_count,
        "active_download_count": active_download_count,
        "paused_count": paused_count,
        "stalled_upload_count": stalled_upload_count,
        "stalled_download_count": stalled_download_count,
        "total_upspeed_mib_s": round(total_upspeed / 1024**2, 3),
        "total_dlspeed_mib_s": round(total_dlspeed / 1024**2, 3),
        "total_amount_left_gb": round(total_amount_left / 1024**3, 3),
        "total_download_liability_gb": round(total_download_liability / 1024**3, 3),
    }


def _maybe_build_downloader(config: SeedAgentConfig) -> Downloader | None:
    secret_ref = config.download_client.secret_ref
    if not secret_ref:
        return None
    secret_path = _resolve_path(secret_ref, config.config_dir)
    if secret_path is None or not secret_path.is_file():
        return None
    secret = load_downloader_secret(secret_path)
    base_url = secret.get("base_url")
    if not base_url:
        return None
    if config.download_client.type == "transmission":
        return TransmissionClient(
            base_url=base_url,
            username=secret.get("username"),
            password=secret.get("password"),
        )
    username = secret.get("username")
    password = secret.get("password")
    if not username or not password:
        return None
    return QbittorrentClient(base_url=base_url, username=username, password=password)


def build_downloader(config: SeedAgentConfig) -> Downloader:
    secret_ref = config.download_client.secret_ref
    if not secret_ref:
        raise typer.BadParameter("missing downloader secret")
    secret_path = _resolve_path(secret_ref, config.config_dir)
    if secret_path is None or not secret_path.is_file():
        raise typer.BadParameter("missing downloader secret")
    downloader = _maybe_build_downloader(config)
    if downloader is None:
        raise typer.BadParameter("missing downloader secret")
    return downloader


def _build_search_providers(config: SeedAgentConfig) -> list[SearchProvider]:
    providers: list[SearchProvider] = []
    for site in config.enabled_sites:
        api_key = _read_secret_ref(site.api_key_ref, config.config_dir)
        cookie = _read_cookie_ref(site.cookie_ref, config.config_dir)
        if site.type == "torznab":
            providers.append(
                TorznabSearchProvider(
                    url=site.rss_url,
                    site=site.name,
                    api_key=api_key,
                    max_results=config.release_preferences.max_results_per_site,
                )
            )
            continue
        if site.type == "mteam" and site.discovery_mode == "api" and api_key:
            providers.append(
                MTeamSearchProvider(
                    site=site.name,
                    api_key=api_key,
                    api_key_header=site.auth_header,
                    cookie=cookie,
                    search_config=config.release_preferences,
                    default_resolution=config.want_decision.default_resolution,
                    series_search_mode=config.want_decision.series_search_mode,
                )
            )
            continue
        providers.append(
            RssSearchProvider(
                url=site.rss_url,
                site=site.name,
                site_type=site.type,
                cookie=cookie,
                api_key=api_key,
                max_results=config.release_preferences.max_results_per_site,
            )
        )
    return providers


def _read_configured_source_events(config: SeedAgentConfig) -> list[SourceIntentEvent]:
    events: list[SourceIntentEvent] = []
    if config.want_sources.telegram.enabled:
        events.extend(_read_configured_telegram_events(config))
    for source in config.want_sources.want_lists:
        if not source.enabled:
            continue
        if source.provider == "douban":
            if source.export_ref:
                export_path = _resolve_path(source.export_ref, config.config_dir)
                if export_path is not None:
                    events.extend(
                        read_douban_wanted(
                            export_path,
                            source_config_id=source.id,
                            label=source.label,
                        )
                    )
            if source.user_name:
                events.extend(
                    fetch_douban_wanted_user(
                        source.user_name,
                        max_pages=source.max_pages,
                        source_config_id=source.id,
                        label=source.label,
                    )
                )
            continue
        if source.provider == "imdb":
            if source.export_ref:
                export_path = _resolve_path(source.export_ref, config.config_dir)
                if export_path is not None:
                    events.extend(
                        read_imdb_watchlist_csv(
                            export_path,
                            source_config_id=source.id,
                            label=source.label,
                        )
                    )
            if source.watchlist_url:
                events.extend(
                    fetch_imdb_watchlist(
                        source.watchlist_url,
                        source_config_id=source.id,
                        label=source.label,
                    )
                )
            continue
        if source.provider == "letterboxd":
            if source.export_ref:
                export_path = _resolve_path(source.export_ref, config.config_dir)
                if export_path is not None:
                    events.extend(
                        read_letterboxd_watchlist_csv(
                            export_path,
                            source_config_id=source.id,
                            label=source.label,
                        )
                    )
    douban = config.want_sources.douban_wanted
    if not douban.enabled:
        return events
    if douban.export_ref:
        export_path = _resolve_path(douban.export_ref, config.config_dir)
        if export_path is not None:
            events.extend(read_douban_wanted(export_path))
    if douban.user_name:
        events.extend(fetch_douban_wanted_user(douban.user_name, max_pages=douban.max_pages))
    return events


def _read_configured_telegram_events(config: SeedAgentConfig) -> list[SourceIntentEvent]:
    secret_ref = config.want_sources.telegram.secret_ref
    if not secret_ref:
        return []
    secret_path = _resolve_path(secret_ref, config.config_dir)
    if secret_path is None or not secret_path.is_file():
        return []
    secret = load_downloader_secret(secret_path)
    bot_token = secret.get("bot_token") or secret.get("token")
    if not bot_token:
        return []
    return poll_telegram_updates(
        bot_token=bot_token,
        offset=_optional_int(secret.get("offset")),
        timeout_seconds=_optional_int(secret.get("timeout_seconds")) or 0,
        allowed_chat_ids=_csv_set(secret.get("allowed_chat_ids")),
    )


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except TypeError, ValueError:
        return None


def _csv_set(value: object) -> set[str] | None:
    if value is None:
        return None
    parts = {part.strip() for part in str(value).split(",") if part.strip()}
    return parts or None


def _build_release_download_resolver(config: SeedAgentConfig) -> ReleaseDownloadResolver | None:
    mteam_auth: dict[str, tuple[str, str]] = {}
    for site in config.enabled_sites:
        if site.type != "mteam":
            continue
        api_key = _read_secret_ref(site.api_key_ref, config.config_dir)
        if api_key:
            mteam_auth[site.name] = (api_key, site.auth_header or "x-api-key")
    if not mteam_auth:
        return None

    async def resolver(release: ReleaseCandidate) -> ReleaseCandidate | None:
        if release.site not in mteam_auth:
            return release
        if release.metadata.get("download_url_source") != "mteam_api_deferred":
            return release
        api_key, api_key_header = mteam_auth[release.site]
        return await resolve_mteam_release_download_url(
            release,
            api_key=api_key,
            api_key_header=api_key_header,
        )

    return resolver


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
            free_window_expires_at=_candidate_free_window_expires_at(scored_item.candidate),
            **_candidate_snapshot_kwargs(
                scored_item.candidate,
                score_reasons=list(scored_item.reasons),
            ),
        )


def _candidate_free_window_expires_at(candidate: TorrentCandidate) -> str | None:
    if candidate.left_time_minutes is None:
        if candidate.metadata.get("left_time_source") == "mteam_api_unlimited":
            return "9999-12-31T23:59:59+00:00"
        return None
    return (datetime.now(UTC) + timedelta(minutes=candidate.left_time_minutes)).isoformat()


def _persist_prune_state(store: StateStore, decisions: list[Decision]) -> None:
    for decision in decisions:
        if decision.action == "qb.cleanup.delete":
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
