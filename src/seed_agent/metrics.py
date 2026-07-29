from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seed_agent.state import StateStore


def render_prometheus_metrics(state_path: Path, heartbeat_path: Path) -> str:
    samples: list[str] = []
    if state_path.exists():
        store = StateStore(state_path)
        runs = store.list_scheduler_runs(limit=1)
        status_counts: dict[str, int] = {}
        for raw_status, count in store.scheduler_run_status_counts().items():
            status = _bounded_status(raw_status)
            status_counts[status] = status_counts.get(status, 0) + count
        for status in sorted(status_counts):
            _sample(
                samples,
                "seed_agent_scheduler_runs_total",
                status_counts[status],
                {"status": status},
            )
        _sample(
            samples,
            "seed_agent_tracker_backoff_active",
            int(store.has_active_tracker_backoff()),
        )
        api_counts: dict[str, int] = {}
        for raw_event, count in store.tracker_api_event_counts().items():
            event = _bounded_api_event(raw_event)
            api_counts[event] = api_counts.get(event, 0) + count
        for event in sorted(api_counts):
            _sample(
                samples,
                "seed_agent_tracker_api_events_total",
                api_counts[event],
                {"event": event},
            )
        if runs:
            _latest_run_samples(samples, runs[0], store)
    _heartbeat_samples(samples, heartbeat_path)
    return "\n".join(samples) + "\n"


def _latest_run_samples(
    samples: list[str],
    row: dict[str, Any],
    store: StateStore,
) -> None:
    summary = _json_mapping(row.get("summary_json"))
    _sample(samples, "seed_agent_last_cycle_enqueued", _number(summary.get("enqueued")))
    prune = summary.get("prune") if isinstance(summary.get("prune"), dict) else {}
    _sample(
        samples,
        "seed_agent_last_cycle_cleanup_delete_count",
        _number(prune.get("delete_count")),
    )
    _sample(
        samples,
        "seed_agent_last_cycle_reclaim_target_bytes",
        _mapping_sum(prune.get("reclaim_targets_by_pool")),
    )
    _sample(
        samples,
        "seed_agent_last_cycle_reclaimed_bytes",
        _mapping_sum(prune.get("reclaimed_capacity_by_pool")),
    )
    _sample(
        samples,
        "seed_agent_last_cycle_verified_committed_reclaim_bytes",
        _mapping_sum(prune.get("verified_committed_reclaim_by_pool")),
    )
    _sample(
        samples,
        "seed_agent_last_cycle_hard_cap_violation_bytes",
        _mapping_sum(prune.get("hard_cap_violations_by_pool")),
    )
    if prune.get("hard_cap_satisfied") is not None:
        _sample(
            samples,
            "seed_agent_last_cycle_hard_cap_satisfied",
            int(bool(prune.get("hard_cap_satisfied"))),
        )
    usage = summary.get("default_pool_usage")
    if isinstance(usage, dict):
        _sample(
            samples,
            "seed_agent_last_cycle_pool_projected_bytes",
            _number(usage.get("size_tib")) * 1024**4,
        )
    run_id = row.get("run_id")
    if not isinstance(run_id, str):
        return
    events = sorted(
        store.list_scheduler_run_events(run_id=run_id, limit=100),
        key=lambda item: str(item.get("created_at") or ""),
    )
    starts: dict[str, datetime] = {}
    for event in events:
        phase = _bounded_phase(event.get("phase"))
        created_at = _datetime(event.get("created_at"))
        if created_at is None:
            continue
        if event.get("event") == "start":
            starts[phase] = created_at
        elif event.get("event") == "end" and phase in starts:
            _sample(
                samples,
                "seed_agent_last_cycle_phase_duration_seconds",
                max((created_at - starts[phase]).total_seconds(), 0.0),
                {"phase": phase},
            )


def _heartbeat_samples(samples: list[str], path: Path) -> None:
    if not path.is_file():
        _sample(samples, "seed_agent_heartbeat_present", 0)
        return
    _sample(samples, "seed_agent_heartbeat_present", 1)
    try:
        heartbeat = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(heartbeat, dict):
        return
    updated_at = _datetime(heartbeat.get("updated_at"))
    if updated_at is not None:
        _sample(
            samples,
            "seed_agent_heartbeat_age_seconds",
            max((datetime.now(UTC) - updated_at).total_seconds(), 0.0),
        )


def _sample(
    samples: list[str],
    name: str,
    value: int | float,
    labels: dict[str, str] | None = None,
) -> None:
    label_text = ""
    if labels:
        encoded = ",".join(
            f'{key}="{_escape_label(value)}"' for key, value in sorted(labels.items())
        )
        label_text = "{" + encoded + "}"
    samples.append(f"{name}{label_text} {float(value):.6f}")


def _bounded_status(value: object) -> str:
    status = str(value or "unknown")
    allowed = {"running", "success", "warning", "error", "skipped_backoff"}
    return status if status in allowed else "other"


def _bounded_api_event(value: object) -> str:
    event = str(value or "unknown")
    return event if event in {"ok", "rate_limited", "unavailable", "error"} else "other"


def _bounded_phase(value: object) -> str:
    phase = str(value or "unknown")
    allowed = {
        "backoff_check",
        "tracker_source_backfill",
        "prune",
        "pt_discovery",
        "pt_enqueue",
        "intent_source_sync",
        "intent_search",
    }
    return phase if phase in allowed else "other"


def _mapping_sum(value: object) -> float:
    if not isinstance(value, dict):
        return 0.0
    return sum(_number(item) for item in value.values())


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _json_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
