from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from seed_agent.actions.pt import daily_report as build_daily_report
from seed_agent.actions.pt import discover_candidates, score_candidates
from seed_agent.actions.qb import enqueue_candidates, prune_cold_torrents
from seed_agent.audit import AuditLogger, redact_payload
from seed_agent.config import SeedAgentConfig, load_config, load_downloader_secret
from seed_agent.downloaders.qbittorrent import QbittorrentClient
from seed_agent.models import (
    Decision,
    LifecycleState,
    ManagedTorrent,
    ScoreBreakdown,
    TorrentCandidate,
    safe_url_identity,
)
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
    decisions = _run(
        enqueue_candidates(
            scored,
            downloader,
            loaded.downloader.category,
            loaded.downloader.tags,
            execute,
        )
    )
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "enqueue",
        "config": str(config),
        "execute": execute,
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "enqueued": len(decisions),
        "scores": [_score_summary(item) for item in scored],
        "decisions": [_decision_summary(item) for item in decisions],
    }
    _print_json(payload)


@app.command()
def review(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
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

    torrent_tags = set(loaded.downloader.tags)
    torrents = _run(downloader.list_torrents(loaded.downloader.category, torrent_tags))
    payload = {
        "command": "review",
        "config": str(config),
        "managed_count": len(torrents),
        "managed_torrents": [_managed_torrent_summary(torrent) for torrent in torrents],
    }
    _print_json(payload)


@app.command()
def prune(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    if execute:
        downloader = build_downloader(loaded)
        torrents = _run(
            downloader.list_torrents(loaded.downloader.category, set(loaded.downloader.tags))
        )
    else:
        torrents = []
        downloader = _NullDownloader()
    decisions = _run(
        prune_cold_torrents(
            torrents,
            downloader,
            loaded.cleanup,
            loaded.downloader.category,
            loaded.downloader.tags,
            execute,
        )
    )
    _write_audit_decisions(loaded, decisions)
    payload = {
        "command": "prune",
        "config": str(config),
        "execute": execute,
        "managed_count": len(torrents),
        "decisions": [_decision_summary(item) for item in decisions],
    }
    _print_json(payload)


@app.command(name="daily-report")
def daily_report_command(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
) -> None:
    loaded = load_config(config)
    candidates = _run(discover_candidates(loaded))
    scored = score_candidates(candidates, loaded.discovery, loaded.scoring)
    managed_torrents = _managed_torrents_for_report(loaded)
    payload = {
        "command": "daily-report",
        "config": str(config),
        "report": build_daily_report(scored, managed_torrents),
        "managed_count": len(managed_torrents),
        "managed_torrents": [_managed_torrent_summary(torrent) for torrent in managed_torrents],
    }
    _print_json(payload)


@app.command(name="run-once")
def run_once(
    config: Annotated[Path, typer.Option("--config")] = DEFAULT_CONFIG,
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    loaded = load_config(config)
    store = StateStore(_state_path())

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
    decisions = _run(
        enqueue_candidates(
            scored,
            downloader,
            loaded.downloader.category,
            loaded.downloader.tags,
            execute,
        )
    )
    _write_audit_decisions(loaded, decisions)

    if execute:
        for decision in decisions:
            torrent_hash = decision.new_state.get("torrent_hash")
            if not torrent_hash:
                continue
            scored_item = scored_by_id.get(decision.target_id)
            if scored_item is None:
                continue
            store.upsert_candidate(
                scored_item.candidate_id,
                scored_item.candidate.title,
                scored_item.candidate.site,
                LifecycleState.ENQUEUED,
                score=scored_item.score,
                torrent_hash=str(torrent_hash),
            )

    payload = {
        "command": "run-once",
        "config": str(config),
        "execute": execute,
        "discovered": len(candidates),
        "scored": len(scored),
        "accepted": sum(1 for item in scored if item.accepted),
        "enqueued": len(decisions),
        "scores": [_score_summary(item) for item in scored],
        "decisions": [_decision_summary(item) for item in decisions],
    }
    _print_json(payload)


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


def _managed_torrent_summary(torrent: ManagedTorrent) -> dict[str, Any]:
    return {
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


def _managed_torrents_for_report(config: SeedAgentConfig) -> list[ManagedTorrent]:
    downloader = _maybe_build_downloader(config)
    if downloader is None:
        return []
    return _run(downloader.list_torrents(config.downloader.category, set(config.downloader.tags)))


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


def _write_audit_decisions(config: SeedAgentConfig, decisions: list[Decision]) -> None:
    if not decisions:
        return
    audit_path = _audit_path()
    logger = AuditLogger(audit_path)
    for decision in decisions:
        logger.write(decision)


def _audit_path() -> Path:
    return Path.cwd() / ".seed-agent" / "audit.jsonl"


def _state_path() -> Path:
    return Path.cwd() / ".seed-agent" / "state.db"


class _NullDownloader:
    async def add_url(self, url: str, category: str, tags: list[str]) -> str | None:
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
        path = config_dir / path
    try:
        return path.resolve()
    except OSError:
        return None


_build_downloader = build_downloader
