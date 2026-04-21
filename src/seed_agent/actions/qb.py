from __future__ import annotations

from collections.abc import Iterable, Sequence

from seed_agent.config import CleanupConfig
from seed_agent.downloaders.base import Downloader
from seed_agent.models import Decision, ManagedTorrent, ScoreBreakdown
from seed_agent.policies.cleanup import CleanupDecision, classify_cleanup

ROLLBACK_INSTRUCTION = "Delete torrent from qBittorrent if enqueue was accidental"


class MutationBatchError(RuntimeError):
    def __init__(self, message: str, decisions: list[Decision]) -> None:
        super().__init__(message)
        self.decisions = decisions


async def enqueue_candidates(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    downloader: Downloader,
    category: str,
    tags: Sequence[str],
    execute: bool,
) -> list[Decision]:
    decisions: list[Decision] = []
    tags_list = list(tags)

    for item in scored:
        if not item.accepted:
            continue

        candidate = item.candidate
        reason = _build_reason(item)
        new_state: dict[str, object] = {
            "candidate_id": item.candidate_id,
            "candidate_title": candidate.title,
            "download_url": candidate.download_url,
            "category": category,
            "tags": tags_list,
            "score": item.score,
            "reasons": list(item.reasons),
        }

        torrent_hash = None
        if execute:
            try:
                torrent_hash = await downloader.add_url(candidate.download_url, category, tags_list)
            except Exception as exc:
                decisions.append(
                    Decision(
                        action="qb.enqueue.failed",
                        target_id=item.candidate_id,
                        execute=execute,
                        reason=f"enqueue failed: {_error_summary(exc)}",
                        new_state={
                            **new_state,
                            "error": _error_summary(exc),
                        },
                        rollback=ROLLBACK_INSTRUCTION,
                    )
                )
                raise MutationBatchError("qBittorrent enqueue batch failed", decisions) from exc
            if torrent_hash is not None:
                new_state["torrent_hash"] = torrent_hash

        decisions.append(
            Decision(
                action="qb.enqueue",
                target_id=item.candidate_id,
                execute=execute,
                reason=reason,
                new_state=new_state,
                rollback=ROLLBACK_INSTRUCTION,
            )
        )

    return decisions


def _build_reason(item: ScoreBreakdown) -> str:
    if item.reasons:
        return f"accepted for enqueue: score={item.score}; reasons={'; '.join(item.reasons)}"
    return f"accepted for enqueue: score={item.score}"


async def prune_cold_torrents(
    torrents: Sequence[ManagedTorrent] | Iterable[ManagedTorrent],
    downloader: Downloader,
    cleanup: CleanupConfig,
    managed_category: str,
    managed_tags: Sequence[str] | set[str],
    execute: bool,
) -> list[Decision]:
    decisions: list[Decision] = []
    tags = set(managed_tags)

    for torrent in torrents:
        classification = classify_cleanup(torrent, cleanup, managed_category, tags)
        decision = _decision_for_cleanup(torrent, classification, execute)

        if not execute:
            decisions.append(decision)
            continue
        try:
            if classification.action == "pause":
                await downloader.pause(torrent.hash)
            elif classification.action == "delete":
                await downloader.delete(torrent.hash, delete_files=True)
        except Exception as exc:
            decisions.append(_failed_cleanup_decision(torrent, classification, execute, exc))
            raise MutationBatchError("qBittorrent cleanup batch failed", decisions) from exc
        decisions.append(decision)

    return decisions


def _decision_for_cleanup(
    torrent: ManagedTorrent,
    classification: CleanupDecision,
    execute: bool,
) -> Decision:
    action = f"qb.cleanup.{classification.action}"
    reason = f"cleanup {classification.action}: {classification.reason}"
    return Decision(
        action=action,
        target_id=torrent.hash,
        execute=execute,
        reason=reason,
        old_state=torrent.model_dump(mode="json"),
        new_state={
            "torrent_hash": torrent.hash,
            "cleanup_action": classification.action,
            "managed": classification.managed,
            "protected": classification.protected,
        },
    )


def _failed_cleanup_decision(
    torrent: ManagedTorrent,
    classification: CleanupDecision,
    execute: bool,
    exc: Exception,
) -> Decision:
    error = _error_summary(exc)
    return Decision(
        action=f"qb.cleanup.{classification.action}.failed",
        target_id=torrent.hash,
        execute=execute,
        reason=f"cleanup {classification.action} failed: {error}",
        old_state=torrent.model_dump(mode="json"),
        new_state={
            "torrent_hash": torrent.hash,
            "cleanup_action": classification.action,
            "managed": classification.managed,
            "protected": classification.protected,
            "error": error,
        },
    )


def _error_summary(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"
