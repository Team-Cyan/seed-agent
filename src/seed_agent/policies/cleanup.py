from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from seed_agent.config import CleanupConfig
from seed_agent.models import ManagedTorrent

CleanupAction = Literal["protect", "keep", "delete"]


class CleanupDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: CleanupAction
    reason: str
    managed: bool = False
    protected: bool = False
    capacity_reclamation: bool = False


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
    completed_low_upload_requires_reclamation: bool = False,
) -> CleanupDecision:
    if not _is_managed(torrent, managed_category, managed_tags):
        return CleanupDecision(
            action="protect",
            reason=_reason("unmanaged torrent: category/tags do not prove seed-agent control"),
            managed=False,
            protected=True,
        )

    metadata = torrent.metadata or {}
    # Billing safety outranks retention protection for incomplete downloads.
    # Completed H&R, manual, and media-library torrents remain protected below.
    free_window_decision = _free_window_decision(torrent, cleanup, metadata)
    if free_window_decision is not None:
        return free_window_decision

    if _is_broken_incomplete(torrent, metadata):
        return CleanupDecision(
            action="delete",
            reason=_reason("broken incomplete managed torrent deleted"),
            managed=True,
        )

    # A mutable pool's configured maximum is a hard invariant. Explicit
    # retention markers and current upload activity remain soft policy signals
    # inside a mutable category and cannot leave its pool above the byte limit.
    if space_reclamation_required:
        return CleanupDecision(
            action="delete",
            reason=_reason("managed torrent deleted to satisfy hard pool capacity"),
            managed=True,
            capacity_reclamation=True,
        )

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
        low_upload_decision = _completed_low_upload_decision(
            torrent,
            cleanup,
            metadata,
            space_reclamation_required=space_reclamation_required,
            requires_reclamation=completed_low_upload_requires_reclamation,
        )
        if low_upload_decision is not None:
            return low_upload_decision
        return CleanupDecision(
            action="keep",
            reason=_reason("completed seed retained for upload"),
            managed=True,
        )

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

    if space_reclamation_required:
        return CleanupDecision(
            action="delete",
            reason=_reason("cold managed torrent deleted for required space reclamation"),
            managed=True,
            capacity_reclamation=True,
        )
    return CleanupDecision(
        action="keep",
        reason=_reason("cold managed torrent retained; space reclamation not required"),
        managed=True,
    )


def _is_broken_incomplete(torrent: ManagedTorrent, metadata: dict[str, object]) -> bool:
    if torrent.state.strip().lower() not in {"error", "missingfiles", "unknown"}:
        return False
    amount_left = metadata.get("amount_left_bytes")
    if isinstance(amount_left, int | float):
        return amount_left > 0
    return torrent.downloaded_bytes < torrent.size_bytes


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
            capacity_reclamation=True,
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
            capacity_reclamation=True,
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
    *,
    space_reclamation_required: bool,
    requires_reclamation: bool,
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

    if requires_reclamation and not space_reclamation_required:
        return CleanupDecision(
            action="keep",
            reason=_reason(
                "completed low-upload seed retained; space reclamation not required"
            ),
            managed=True,
        )

    return CleanupDecision(
        action="delete",
        reason=_reason(
            "completed low-upload seed "
            f"{uploaded_gb:.2f} GiB uploaded, ratio {ratio:.4f}, "
            f"no upload for {no_upload_age.days}d {no_upload_age.seconds // 3600}h"
        ),
        managed=True,
        capacity_reclamation=requires_reclamation,
    )


def _free_window_decision(
    torrent: ManagedTorrent,
    cleanup: CleanupConfig,
    metadata: dict[str, object],
) -> CleanupDecision | None:
    if not _is_completed_seed(torrent) and bool(metadata.get("unknown_free_status_high_risk")):
        return CleanupDecision(
            action="delete",
            reason=_reason(
                "incomplete torrent free status remained unknown after bounded tracker lookup"
            ),
            managed=True,
        )
    if not _is_completed_seed(torrent) and _is_confirmed_non_free(metadata):
        return CleanupDecision(
            action="delete",
            reason=_reason(
                "incomplete torrent is confirmed non-free; delete files before paid download"
            ),
            managed=True,
        )
    expires_at = _free_window_expires_at(metadata)
    if expires_at is None:
        return None
    min_remaining = _free_window_min_remaining_minutes(metadata)
    if min_remaining is None:
        return None
    remaining = expires_at - _utcnow()
    if remaining > timedelta(minutes=min_remaining):
        return None
    if not _is_completed_seed(torrent):
        return CleanupDecision(
            action="delete",
            reason=_reason(
                "incomplete free window expires before next check; delete files before paid period"
            ),
            managed=True,
        )
    return None


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


def _is_confirmed_non_free(metadata: dict[str, object]) -> bool:
    value = metadata.get("discount")
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower().replace(" ", "")
    if not normalized:
        return False
    return normalized not in {"free", "2xfree", "2x_free"}


def _reason(message: str) -> str:
    return message


def _utcnow() -> datetime:
    return datetime.now(UTC)
