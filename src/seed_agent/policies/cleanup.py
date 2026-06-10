from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from seed_agent.config import CleanupConfig
from seed_agent.models import ManagedTorrent

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
    *,
    space_reclamation_required: bool = False,
) -> CleanupDecision:
    if not _is_managed(torrent, managed_category, managed_tags):
        return CleanupDecision(
            action="protect",
            reason=_reason("unmanaged torrent: category/tags do not prove seed-agent control"),
            managed=False,
            protected=True,
        )

    metadata = torrent.metadata or {}
    for rule in _protection_rules(cleanup, metadata):
        return CleanupDecision(
            action="protect",
            reason=_reason(rule.reason),
            managed=True,
            protected=True,
        )

    if _is_currently_uploading(metadata):
        return CleanupDecision(
            action="keep",
            reason=_reason("currently uploading; retain managed torrent"),
            managed=True,
        )

    if _is_completed_seed(torrent):
        low_upload_decision = _completed_low_upload_decision(torrent, cleanup, metadata)
        if low_upload_decision is not None:
            return low_upload_decision
        return CleanupDecision(
            action="keep",
            reason=_reason("completed seed retained for upload"),
            managed=True,
        )

    free_window_decision = _free_window_decision(torrent, cleanup, metadata)
    if free_window_decision is not None:
        return free_window_decision

    no_upload_decision = _no_upload_observation_decision(
        torrent,
        cleanup,
        metadata,
        space_reclamation_required=space_reclamation_required,
    )
    if no_upload_decision is not None:
        return no_upload_decision

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
            if not space_reclamation_required:
                return CleanupDecision(
                    action="keep",
                    reason=_reason("paused but space reclamation not required"),
                    managed=True,
                )
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

    recent_upload_gb = _recent_upload_gb(metadata)
    if recent_upload_gb is not None and recent_upload_gb >= cleanup.min_upload_delta_gb:
        return CleanupDecision(
            action="keep",
            reason=_reason(
                f"recent upload {recent_upload_gb:.2f} GiB >= min "
                f"{cleanup.min_upload_delta_gb:.2f} GiB; retain cold managed torrent"
            ),
            managed=True,
        )

    return CleanupDecision(
        action="pause" if space_reclamation_required else "keep",
        reason=_reason(
            "cold managed torrent should be paused before deletion"
            if space_reclamation_required
            else "cold managed torrent retained; space reclamation not required"
        ),
        managed=True,
    )


def _no_upload_observation_decision(
    torrent: ManagedTorrent,
    cleanup: CleanupConfig,
    metadata: dict[str, object],
    *,
    space_reclamation_required: bool,
) -> CleanupDecision | None:
    if torrent.uploaded_bytes <= 0:
        return _zero_total_upload_decision(
            cleanup,
            metadata,
            space_reclamation_required=space_reclamation_required,
        )
    if not _is_completed_seed(torrent):
        return None
    if _is_paused_or_stopped(torrent.state):
        return None
    recent_upload_gb = _recent_upload_gb(metadata)
    if recent_upload_gb is None:
        return None
    if recent_upload_gb >= cleanup.min_upload_delta_gb:
        return CleanupDecision(
            action="keep",
            reason=_reason(
                f"recent upload {recent_upload_gb:.2f} GiB >= min "
                f"{cleanup.min_upload_delta_gb:.2f} GiB; retain managed seed"
            ),
            managed=True,
        )

    no_upload_since_at = _no_upload_since_at(metadata)
    if no_upload_since_at is None:
        return CleanupDecision(
            action="keep",
            reason=_reason("no-upload observation window just started"),
            managed=True,
        )
    no_upload_age = _utcnow() - no_upload_since_at
    delete_delay = timedelta(hours=cleanup.delete_after_no_upload_hours)
    if no_upload_age >= delete_delay:
        if not space_reclamation_required:
            return CleanupDecision(
                action="keep",
                reason=_reason(
                    f"no upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h "
                    "but space reclamation not required"
                ),
                managed=True,
            )
        return CleanupDecision(
            action="delete",
            reason=_reason(
                f"no upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h "
                f">= delete delay {cleanup.delete_after_no_upload_hours}h"
            ),
            managed=True,
        )
    return CleanupDecision(
        action="keep",
        reason=_reason(
            f"no upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h "
            f"< delete delay {cleanup.delete_after_no_upload_hours}h"
        ),
        managed=True,
    )


def _zero_total_upload_decision(
    cleanup: CleanupConfig,
    metadata: dict[str, object],
    *,
    space_reclamation_required: bool,
) -> CleanupDecision | None:
    no_upload_since_at = _no_upload_since_at(metadata)
    if no_upload_since_at is None:
        return CleanupDecision(
            action="keep",
            reason=_reason("zero total upload observation window just started"),
            managed=True,
        )
    no_upload_age = _utcnow() - no_upload_since_at
    delete_delay = timedelta(hours=cleanup.delete_after_no_upload_hours)
    if no_upload_age >= delete_delay:
        if not space_reclamation_required:
            return CleanupDecision(
                action="keep",
                reason=_reason(
                    f"zero total upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h "
                    "but space reclamation not required"
                ),
                managed=True,
            )
        return CleanupDecision(
            action="delete",
            reason=_reason(
                f"zero total upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h "
                f">= delete delay {cleanup.delete_after_no_upload_hours}h"
            ),
            managed=True,
        )
    return CleanupDecision(
        action="keep",
        reason=_reason(
            f"zero total upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h "
            f"< delete delay {cleanup.delete_after_no_upload_hours}h"
        ),
        managed=True,
    )


def _completed_low_upload_decision(
    torrent: ManagedTorrent,
    cleanup: CleanupConfig,
    metadata: dict[str, object],
) -> CleanupDecision | None:
    threshold_hours = cleanup.delete_completed_low_upload_after_hours
    if threshold_hours is None:
        return None

    no_upload_since_at = _no_upload_since_at(metadata)
    if no_upload_since_at is None:
        return CleanupDecision(
            action="keep",
            reason=_reason("completed low-upload observation window just started"),
            managed=True,
        )

    no_upload_age = _utcnow() - no_upload_since_at
    delete_delay = timedelta(hours=threshold_hours)
    if no_upload_age < delete_delay:
        return CleanupDecision(
            action="keep",
            reason=_reason(
                "completed low-upload observation "
                f"{no_upload_age.days}d {no_upload_age.seconds // 3600}h "
                f"< delete delay {threshold_hours}h"
            ),
            managed=True,
        )

    downloaded_bytes = max(torrent.downloaded_bytes, 1)
    uploaded_gb = torrent.uploaded_bytes / 1024**3
    ratio = torrent.uploaded_bytes / downloaded_bytes
    low_total_upload = (
        torrent.uploaded_bytes <= 0
        or (
            cleanup.completed_low_upload_min_gb > 0
            and uploaded_gb < cleanup.completed_low_upload_min_gb
        )
        or (
            cleanup.completed_low_upload_min_ratio > 0
            and ratio < cleanup.completed_low_upload_min_ratio
        )
    )
    if not low_total_upload:
        return None

    return CleanupDecision(
        action="delete",
        reason=_reason(
            "completed low-upload seed "
            f"{uploaded_gb:.2f} GiB uploaded, ratio {ratio:.4f}, "
            f"no upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h"
        ),
        managed=True,
    )


def _free_window_decision(
    torrent: ManagedTorrent,
    cleanup: CleanupConfig,
    metadata: dict[str, object],
) -> CleanupDecision | None:
    expires_at = _free_window_expires_at(metadata)
    if expires_at is None:
        return None
    min_remaining = _free_window_min_remaining_minutes(metadata)
    if min_remaining is None:
        return None
    remaining = expires_at - _utcnow()
    if remaining > timedelta(minutes=min_remaining):
        return None
    if _is_paused_or_stopped(torrent.state):
        return _paused_or_stopped_decision(metadata, cleanup)
    return CleanupDecision(
        action="pause",
        reason=_reason(
            "free window expires before next check; pause managed torrent before paid period"
        ),
        managed=True,
    )


def _paused_or_stopped_decision(
    metadata: dict[str, object],
    cleanup: CleanupConfig,
) -> CleanupDecision:
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


def _is_managed(
    torrent: ManagedTorrent,
    managed_category: str,
    managed_tags: set[str],
) -> bool:
    del managed_tags
    return torrent.category == managed_category


def _protection_rules(
    cleanup: CleanupConfig,
    metadata: dict[str, object],
) -> list[_MatchedRule]:
    rules: list[_MatchedRule] = []
    if cleanup.protect_hr and bool(metadata.get("hr")):
        rules.append(_MatchedRule("protect", "hr torrent protected by cleanup policy"))
    if cleanup.protect_manual and bool(metadata.get("manual")):
        rules.append(_MatchedRule("protect", "manual torrent protected by cleanup policy"))
    if cleanup.protect_media_library and bool(metadata.get("media_library")):
        rules.append(_MatchedRule("protect", "media library torrent protected by cleanup policy"))
    return rules


def _recent_upload_gb(metadata: dict[str, object]) -> float | None:
    # Cleanup uses explicit recent-upload metadata only. `recent_upload_gb` is the
    # preferred field; `upload_delta_gb` is kept as a legacy alias for the same
    # semantic value when present.
    for key in ("recent_upload_gb", "upload_delta_gb"):
        raw_value = metadata.get(key)
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
    return None


def _is_currently_uploading(metadata: dict[str, object]) -> bool:
    value = metadata.get("upspeed_bps")
    if value is None:
        return False
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _paused_at(metadata: dict[str, object]) -> datetime | None:
    value = metadata.get("paused_at")
    if isinstance(value, datetime):
        return value
    return None


def _no_upload_since_at(metadata: dict[str, object]) -> datetime | None:
    value = metadata.get("no_upload_since_at")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_completed_seed(torrent: ManagedTorrent) -> bool:
    amount_left = int(torrent.metadata.get("amount_left_bytes", 0) or 0)
    return amount_left <= 0 and torrent.downloaded_bytes > 0


def _free_window_expires_at(metadata: dict[str, object]) -> datetime | None:
    value = metadata.get("free_window_expires_at")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _free_window_min_remaining_minutes(metadata: dict[str, object]) -> int | None:
    value = metadata.get("free_window_min_remaining_minutes")
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return None


def _is_paused_or_stopped(state: str) -> bool:
    normalized = state.strip().lower()
    return normalized.startswith("paused") or normalized.startswith("stopped")


def _reason(message: str) -> str:
    return message


def _utcnow() -> datetime:
    return datetime.now(UTC)
