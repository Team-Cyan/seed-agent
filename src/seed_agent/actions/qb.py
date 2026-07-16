from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence

from seed_agent.config import CategoryPolicyConfig, CleanupConfig
from seed_agent.downloaders.base import Downloader
from seed_agent.models import Decision, ManagedTorrent, ScoreBreakdown, TorrentCandidate
from seed_agent.policies.category_policy import PoolUsage
from seed_agent.policies.cleanup import CleanupDecision, classify_cleanup
from seed_agent.policies.eviction import rank_eviction_candidates

ROLLBACK_INSTRUCTION = "Delete torrent from qBittorrent if enqueue was accidental"


class MutationBatchError(RuntimeError):
    def __init__(self, message: str, decisions: list[Decision]) -> None:
        super().__init__(message)
        self.decisions = decisions


async def enqueue_candidates(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    downloader: Downloader,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    paused: bool = False,
    pool_usage: PoolUsage | None = None,
    pause_reasons: Sequence[str] | None = None,
) -> list[Decision]:
    decisions: list[Decision] = []
    tags_list = list(policy.tags)
    pause_reasons_list = list(pause_reasons or [])

    for item in scored:
        if not item.accepted:
            continue

        candidate = item.candidate
        reason = _build_reason(item, paused=paused, pause_reasons=pause_reasons_list)
        new_state: dict[str, object] = {
            "candidate_id": item.candidate_id,
            "candidate_title": candidate.title,
            "download_url": candidate.download_url,
            "category": policy.name,
            "category_mode": policy.mode,
            "budget_pool": policy.budget_pool,
            "delete_enabled": policy.delete_enabled,
            "tags": tags_list,
            "paused": paused,
            "score": item.score,
            "reasons": list(item.reasons),
        }
        if pause_reasons_list:
            new_state["pause_reasons"] = pause_reasons_list
        new_state.update(_pool_usage_state(pool_usage))

        if paused:
            new_state.update({"paused": False, "rejected": True})
            decisions.append(
                Decision(
                    action="qb.enqueue.rejected",
                    target_id=item.candidate_id,
                    execute=execute,
                    reason=(
                        "enqueue rejected by hard runtime gate: "
                        + "; ".join(pause_reasons_list or ["runtime capacity unavailable"])
                    ),
                    new_state=new_state,
                    rollback=None,
                )
            )
            continue

        torrent_hash = None
        if execute:
            try:
                torrent_hash = await downloader.add_url(
                    candidate.download_url,
                    policy.name,
                    tags_list,
                    paused=paused,
                )
                if torrent_hash is None:
                    torrent_hash = await _resolve_added_torrent_hash(
                        downloader,
                        candidate,
                        policy.name,
                        set(tags_list),
                    )
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


async def _resolve_added_torrent_hash(
    downloader: Downloader,
    candidate: TorrentCandidate,
    category: str,
    tags: set[str],
) -> str | None:
    try:
        torrents = await downloader.list_torrents(category=category, tags=tags or None)
    except Exception:
        return None
    identity = _candidate_identity(candidate)
    matches = [
        torrent.hash
        for torrent in torrents
        if torrent.hash and _torrent_identity(torrent) == identity
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _candidate_identity(candidate: TorrentCandidate) -> tuple[str, int]:
    return (_normalize_torrent_title(candidate.title), int(candidate.size_bytes))


def _torrent_identity(torrent: ManagedTorrent) -> tuple[str, int]:
    return (_normalize_torrent_title(torrent.name), int(torrent.size_bytes))


def _normalize_torrent_title(title: str) -> str:
    return " ".join(title.strip().casefold().split())


def _build_reason(
    item: ScoreBreakdown,
    *,
    paused: bool = False,
    pause_reasons: Sequence[str] | None = None,
) -> str:
    pause_reasons = list(pause_reasons or [])
    if item.reasons:
        reason = f"accepted for enqueue: score={item.score}; reasons={'; '.join(item.reasons)}"
    else:
        reason = f"accepted for enqueue: score={item.score}"
    if paused:
        if pause_reasons:
            return f"{reason}; paused_by_policy={'; '.join(pause_reasons)}"
        return f"{reason}; paused_by_policy=true"
    return reason


async def prune_cold_torrents(
    torrents: Sequence[ManagedTorrent] | Iterable[ManagedTorrent],
    downloader: Downloader,
    cleanup: CleanupConfig,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    pool_usage: PoolUsage | None = None,
    free_window_min_remaining_minutes: int | None = None,
    force_space_reclamation: bool = False,
    completed_low_upload_requires_reclamation: bool = False,
    reclaim_target_bytes: int | None = None,
    capacity_delete_limit: int | None = None,
) -> list[Decision]:
    if policy.mode != "mutable" or not policy.delete_enabled:
        return [
            Decision(
                action="qb.cleanup.protect",
                target_id=torrent.hash,
                execute=execute,
                reason=(f"cleanup protect: category {policy.name} is add_only or delete-disabled"),
                old_state=torrent.model_dump(mode="json"),
                new_state={
                    "torrent_hash": torrent.hash,
                    "cleanup_action": "protect",
                    "managed": False,
                    "protected": True,
                    **_policy_state(policy),
                    **_pool_usage_state(pool_usage),
                },
            )
            for torrent in torrents
        ]

    decisions: list[Decision] = []
    tags = set(policy.tags)
    space_reclamation_required = force_space_reclamation or bool(
        pool_usage and pool_usage.over_budget
    )
    if reclaim_target_bytes is None:
        if pool_usage is not None and pool_usage.over_budget:
            reclaim_target_bytes = pool_usage.size_bytes - pool_usage.max_size_bytes
        elif force_space_reclamation:
            reclaim_target_bytes = 1
        else:
            reclaim_target_bytes = 0
    reclaim_target_bytes = max(int(reclaim_target_bytes), 0)
    reclaimed_bytes = 0
    capacity_delete_count = 0
    effective_capacity_delete_limit = (
        len(torrents)
        if pool_usage is not None and pool_usage.over_budget
        else cleanup.max_capacity_deletes_per_run
        if capacity_delete_limit is None
        else max(int(capacity_delete_limit), 0)
    )

    for torrent in rank_eviction_candidates(list(torrents)):
        if free_window_min_remaining_minutes is not None:
            metadata = dict(torrent.metadata)
            metadata["free_window_min_remaining_minutes"] = free_window_min_remaining_minutes
            torrent = torrent.model_copy(update={"metadata": metadata})
        reclamation_needed = space_reclamation_required and reclaimed_bytes < reclaim_target_bytes
        classification = classify_cleanup(
            torrent,
            cleanup,
            policy.name,
            tags,
            space_reclamation_required=reclamation_needed,
            completed_low_upload_requires_reclamation=(completed_low_upload_requires_reclamation),
        )
        if (
            classification.action == "delete"
            and classification.capacity_reclamation
            and capacity_delete_count >= effective_capacity_delete_limit
        ):
            classification = CleanupDecision(
                action="keep",
                reason=(
                    "capacity deletion limit reached: "
                    f"{effective_capacity_delete_limit} remaining for this run"
                ),
                managed=True,
            )

        if execute and classification.action == "delete":
            current_supported, current = await _current_torrent(downloader, torrent.hash)
            if current_supported and current is None:
                classification = CleanupDecision(
                    action="keep",
                    reason="torrent disappeared before cleanup mutation",
                    managed=True,
                )
            elif current is not None and current.category != policy.name:
                classification = CleanupDecision(
                    action="protect",
                    reason=(
                        "torrent category changed before cleanup mutation: "
                        f"{current.category or 'unassigned'}"
                    ),
                    managed=False,
                    protected=True,
                )
            elif current is not None:
                current = current.model_copy(
                    update={
                        "metadata": {
                            **torrent.metadata,
                            **current.metadata,
                        }
                    }
                )
                torrent = current
                classification = classify_cleanup(
                    torrent,
                    cleanup,
                    policy.name,
                    tags,
                    space_reclamation_required=reclamation_needed,
                    completed_low_upload_requires_reclamation=(
                        completed_low_upload_requires_reclamation
                    ),
                )

        decision = _decision_for_cleanup(
            torrent,
            classification,
            policy,
            execute,
            pool_usage=pool_usage,
            space_reclamation_required=reclamation_needed,
            force_space_reclamation=force_space_reclamation,
            completed_low_upload_requires_reclamation=(completed_low_upload_requires_reclamation),
            reclaim_target_bytes=reclaim_target_bytes,
            reclaimed_bytes=reclaimed_bytes,
        )

        if not execute:
            decisions.append(decision)
            if classification.action == "delete" and reclamation_needed:
                reclaimed_bytes += max(int(torrent.size_bytes), 0)
            if classification.action == "delete" and classification.capacity_reclamation:
                capacity_delete_count += 1
            continue
        try:
            if classification.action == "delete":
                await downloader.delete(torrent.hash, delete_files=True)
                if not await _delete_is_absent(downloader, torrent.hash):
                    raise RuntimeError("delete verification failed: torrent still present")
        except Exception as exc:
            decisions.append(
                _failed_cleanup_decision(
                    torrent,
                    classification,
                    policy,
                    execute,
                    exc,
                    pool_usage=pool_usage,
                    space_reclamation_required=reclamation_needed,
                    force_space_reclamation=force_space_reclamation,
                    completed_low_upload_requires_reclamation=(
                        completed_low_upload_requires_reclamation
                    ),
                    reclaim_target_bytes=reclaim_target_bytes,
                    reclaimed_bytes=reclaimed_bytes,
                )
            )
            raise MutationBatchError("qBittorrent cleanup batch failed", decisions) from exc
        decisions.append(decision)
        if classification.action == "delete" and reclamation_needed:
            reclaimed_bytes += max(int(torrent.size_bytes), 0)
        if classification.action == "delete" and classification.capacity_reclamation:
            capacity_delete_count += 1

    return decisions


async def _current_torrent(
    downloader: Downloader,
    torrent_hash: str,
) -> tuple[bool, ManagedTorrent | None]:
    list_torrents = getattr(downloader, "list_torrents", None)
    if not callable(list_torrents):
        return False, None
    torrents = await list_torrents(None, None)
    return True, next((item for item in torrents if item.hash == torrent_hash), None)


async def _delete_is_absent(downloader: Downloader, torrent_hash: str) -> bool:
    list_torrents = getattr(downloader, "list_torrents", None)
    if not callable(list_torrents):
        return True
    for attempt in range(3):
        torrents = await list_torrents(None, None)
        if all(item.hash != torrent_hash for item in torrents):
            return True
        if attempt < 2:
            await asyncio.sleep(0.25)
    return False


def _decision_for_cleanup(
    torrent: ManagedTorrent,
    classification: CleanupDecision,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    pool_usage: PoolUsage | None = None,
    space_reclamation_required: bool = False,
    force_space_reclamation: bool = False,
    completed_low_upload_requires_reclamation: bool = False,
    reclaim_target_bytes: int = 0,
    reclaimed_bytes: int = 0,
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
            "capacity_reclamation": classification.capacity_reclamation,
            "space_reclamation_required": space_reclamation_required,
            "force_space_reclamation": force_space_reclamation,
            "completed_low_upload_requires_reclamation": (
                completed_low_upload_requires_reclamation
            ),
            "reclaim_target_bytes": reclaim_target_bytes,
            "reclaimed_bytes_before_action": reclaimed_bytes,
            **_policy_state(policy),
            **_pool_usage_state(pool_usage),
        },
    )


def _failed_cleanup_decision(
    torrent: ManagedTorrent,
    classification: CleanupDecision,
    policy: CategoryPolicyConfig,
    execute: bool,
    exc: Exception,
    *,
    pool_usage: PoolUsage | None = None,
    space_reclamation_required: bool = False,
    force_space_reclamation: bool = False,
    completed_low_upload_requires_reclamation: bool = False,
    reclaim_target_bytes: int = 0,
    reclaimed_bytes: int = 0,
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
            "capacity_reclamation": classification.capacity_reclamation,
            "error": error,
            "space_reclamation_required": space_reclamation_required,
            "force_space_reclamation": force_space_reclamation,
            "completed_low_upload_requires_reclamation": (
                completed_low_upload_requires_reclamation
            ),
            "reclaim_target_bytes": reclaim_target_bytes,
            "reclaimed_bytes_before_action": reclaimed_bytes,
            **_policy_state(policy),
            **_pool_usage_state(pool_usage),
        },
    )


def _policy_state(policy: CategoryPolicyConfig) -> dict[str, object]:
    return {
        "category": policy.name,
        "category_mode": policy.mode,
        "budget_pool": policy.budget_pool,
        "delete_enabled": policy.delete_enabled,
    }


def _pool_usage_state(pool_usage: PoolUsage | None) -> dict[str, object]:
    if pool_usage is None:
        return {}
    return {
        "budget_pool_limit_tib": round(pool_usage.max_size_bytes / 1024**4, 2),
        "estimated_pool_usage_tib": round(pool_usage.size_bytes / 1024**4, 2),
        "over_budget_before_action": pool_usage.over_budget,
    }


def _error_summary(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"
