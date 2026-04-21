from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from seed_agent.config import CleanupConfig
from seed_agent.models import ManagedTorrent

GIB = 1024**3

CleanupAction = Literal["protect", "keep", "pause", "delete"]


class CleanupDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: CleanupAction
    reason: str
    managed: bool = False
    protected: bool = False


@dataclass(frozen=True)
class _MatchedRule:
    action: CleanupAction
    reason: str


def classify_cleanup(
    torrent: ManagedTorrent,
    cleanup: CleanupConfig,
    managed_category: str,
    managed_tags: set[str],
) -> CleanupDecision:
    if not _is_managed(torrent, managed_category, managed_tags):
        return CleanupDecision(
            action="protect",
            reason=_reason("unmanaged torrent: category/tags do not prove seed-agent control"),
            managed=False,
            protected=True,
        )

    metadata = torrent.metadata or {}
    for rule in _protection_rules(torrent, cleanup, metadata):
        return CleanupDecision(
            action="protect",
            reason=_reason(rule.reason),
            managed=True,
            protected=True,
        )

    if torrent.last_activity_at is not None:
        age = _utcnow() - torrent.last_activity_at
        if age < timedelta(days=cleanup.cold_after_days):
            return CleanupDecision(
                action="keep",
                reason=_reason(
                    f"recent activity {age.days}d {age.seconds // 3600}h < cold threshold "
                    f"{cleanup.cold_after_days}d"
                ),
                managed=True,
            )

    if _is_paused_or_stopped(torrent.state):
        paused_at = _paused_at(metadata)
        if paused_at is not None:
            paused_age = _utcnow() - paused_at
            if paused_age >= timedelta(hours=cleanup.pause_before_delete_hours):
                return CleanupDecision(
                    action="delete",
                    reason=_reason(
                        f"paused for {paused_age.days}d {paused_age.seconds // 3600}h "
                        f">= delete delay {cleanup.pause_before_delete_hours}h"
                    ),
                    managed=True,
                )
            return CleanupDecision(
                action="keep",
                reason=_reason(
                    f"paused for {paused_age.days}d {paused_age.seconds // 3600}h "
                    f"< delete delay {cleanup.pause_before_delete_hours}h"
                ),
                managed=True,
            )
        return CleanupDecision(
            action="keep",
            reason=_reason("paused/stopped torrent missing paused_at timestamp"),
            managed=True,
        )

    upload_delta_gb = _upload_delta_gb(torrent, metadata)
    if upload_delta_gb is not None and upload_delta_gb >= cleanup.min_upload_delta_gb:
        return CleanupDecision(
            action="keep",
            reason=_reason(
                f"upload delta {upload_delta_gb:.2f} GiB >= min "
                f"{cleanup.min_upload_delta_gb:.2f} GiB"
            ),
            managed=True,
        )

    return CleanupDecision(
        action="pause",
        reason=_reason("cold managed torrent should be paused before deletion"),
        managed=True,
    )


def _is_managed(
    torrent: ManagedTorrent,
    managed_category: str,
    managed_tags: set[str],
) -> bool:
    category_matches = torrent.category == managed_category
    tag_matches = bool(managed_tags.intersection(torrent.tags))
    return category_matches or tag_matches


def _protection_rules(
    torrent: ManagedTorrent,
    cleanup: CleanupConfig,
    metadata: dict[str, object],
) -> list[_MatchedRule]:
    rules: list[_MatchedRule] = []
    if cleanup.protect_hr and bool(metadata.get("hr")):
        rules.append(_MatchedRule("protect", "hr torrent protected by cleanup policy"))
    if cleanup.protect_manual and bool(metadata.get("manual")):
        rules.append(_MatchedRule("protect", "manual torrent protected by cleanup policy"))
    if cleanup.protect_media_library and bool(metadata.get("media_library")):
        rules.append(
            _MatchedRule("protect", "media library torrent protected by cleanup policy")
        )
    return rules


def _upload_delta_gb(torrent: ManagedTorrent, metadata: dict[str, object]) -> float | None:
    for key in ("upload_delta_gb", "recent_upload_gb"):
        raw_value = metadata.get(key)
        if isinstance(raw_value, (int, float)):
            return float(raw_value)

    delta_bytes = torrent.uploaded_bytes - torrent.downloaded_bytes
    if delta_bytes <= 0:
        return None
    return delta_bytes / GIB


def _paused_at(metadata: dict[str, object]) -> datetime | None:
    value = metadata.get("paused_at")
    if isinstance(value, datetime):
        return value
    return None


def _is_paused_or_stopped(state: str) -> bool:
    normalized = state.strip().lower()
    return normalized.startswith("paused") or normalized.startswith("stopped")


def _reason(message: str) -> str:
    return message


def _utcnow() -> datetime:
    return datetime.now(UTC)
