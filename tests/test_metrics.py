from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seed_agent.metrics import render_prometheus_metrics
from seed_agent.state import StateStore


def test_prometheus_metrics_are_local_bounded_and_secret_free(tmp_path: Path) -> None:
    state_path = tmp_path / ".seed-agent" / "state.db"
    heartbeat_path = tmp_path / "state" / "schedule-heartbeat.json"
    heartbeat_path.parent.mkdir(parents=True)
    heartbeat_path.write_text(
        json.dumps({"updated_at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat()}),
        encoding="utf-8",
    )
    store = StateStore(state_path)
    store.start_scheduler_run(
        run_id="sched-metrics",
        command="schedule-run",
        config="/secret/config.yaml",
        execute=True,
        interval_minutes=30,
        prune_enabled=True,
        intent_enabled=True,
        intent_execute=False,
        backoff_active=False,
        backoff_until=None,
    )
    store.record_scheduler_event(
        run_id="sched-metrics",
        phase="prune",
        event="start",
        created_at=datetime.now(UTC) - timedelta(seconds=2),
    )
    store.record_scheduler_event(
        run_id="sched-metrics",
        phase="prune",
        event="end",
        created_at=datetime.now(UTC),
    )
    store.finish_scheduler_run(
        run_id="sched-metrics",
        status="success",
        summary={
            "enqueued": 2,
            "prune": {
                "delete_count": 1,
                "reclaim_targets_by_pool": {"secret-pool-name": 100},
                "reclaimed_capacity_by_pool": {"secret-pool-name": 80},
            },
        },
    )
    store.record_tracker_api_event(
        site="private-tracker-name",
        endpoint="torrent/search",
        event="rate_limited",
        rate_limited=True,
        message="secret-token",
    )

    output = render_prometheus_metrics(state_path, heartbeat_path)

    assert 'seed_agent_scheduler_runs_total{status="success"} 1.000000' in output
    assert "seed_agent_last_cycle_cleanup_delete_count 1.000000" in output
    assert "seed_agent_last_cycle_reclaim_target_bytes 100.000000" in output
    assert 'seed_agent_last_cycle_phase_duration_seconds{phase="prune"}' in output
    assert "seed_agent_heartbeat_age_seconds" in output
    assert "private-tracker-name" not in output
    assert "secret-pool-name" not in output
    assert "secret-token" not in output
    assert "torrent_hash" not in output
