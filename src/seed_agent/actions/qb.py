from __future__ import annotations

from collections.abc import Iterable, Sequence

from seed_agent.config import CategoryPolicyConfig, CleanupConfig
from seed_agent.downloaders.base import Downloader
from seed_agent.models import Decision, ManagedTorrent, ScoreBreakdown
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
) -> list[Decision]:
    decisions: list[Decision] = []
    tags_list = list(policy.tags)

    for item in scored:
        if not item.accepted:
            continue

        candidate = item.candidate
        reason = _build_reason(item)
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
        new_state.update(_pool_usage_state(pool_usage))

        torrent_hash = None
        if execute:
            try:
                torrent_hash = await downloader.add_url(
                    candidate.download_url,
                    policy.name,
                    tags_list,
                    paused=paused,
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


def _build_reason(item: ScoreBreakdown) -> str:
    if item.reasons:
        return f"accepted for enqueue: score={item.score}; reasons={'; '.join(item.reasons)}"
    return f"accepted for enqueue: score={item.score}"


async def prune_cold_torrents(
    torrents: Sequence[ManagedTorrent] | Iterable[ManagedTorrent],
    downloader: Downloader,
    cleanup: CleanupConfig,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    pool_usage: PoolUsage | None = None,
) -> list[Decision]:
    if policy.mode != "mutable" or not policy.delete_enabled:
        return [
            Decision(
                action="qb.cleanup.protect",
                target_id=torrent.hash,
                execute=execute,
                reason=(
                    f"cleanup protect: category {policy.name} is add_only or delete-disabled"
                ),
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

    for torrent in rank_eviction_candidates(list(torrents)):
        classification = classify_cleanup(torrent, cleanup, policy.name, tags)
        decision = _decision_for_cleanup(
            torrent,
            classification,
            policy,
            execute,
            pool_usage=pool_usage,
        )

        if not execute:
            decisions.append(decision)
            continue
        try:
            if classification.action == "pause":
                await downloader.pause(torrent.hash)
            elif classification.action == "delete":
                await downloader.delete(torrent.hash, delete_files=True)
        except Exception as exc:
            decisions.append(
                _failed_cleanup_decision(
                    torrent,
                    classification,
                    policy,
                    execute,
                    exc,
                    pool_usage=pool_usage,
                )
            )
            raise MutationBatchError("qBittorrent cleanup batch failed", decisions) from exc
        decisions.append(decision)

    return decisions


def _decision_for_cleanup(
    torrent: ManagedTorrent,
    classification: CleanupDecision,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    pool_usage: PoolUsage | None = None,
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
