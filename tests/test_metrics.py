from __future__ import annotations

import json
import sqlite3
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
                "verified_committed_reclaim_by_pool": {"secret-pool-name": 75},
                "hard_cap_violations_by_pool": {},
                "hard_cap_satisfied": True,
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
    assert "seed_agent_last_cycle_verified_committed_reclaim_bytes 75.000000" in output
    assert "seed_agent_last_cycle_hard_cap_violation_bytes 0.000000" in output
    assert "seed_agent_last_cycle_hard_cap_satisfied 1.000000" in output
    assert 'seed_agent_last_cycle_phase_duration_seconds{phase="prune"}' in output
    assert "seed_agent_heartbeat_age_seconds" in output
    assert "private-tracker-name" not in output
    assert "secret-pool-name" not in output
    assert "secret-token" not in output
    assert "torrent_hash" not in output


def test_prometheus_totals_are_cumulative_and_expired_backoff_is_inactive(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / ".seed-agent" / "state.db"
    heartbeat_path = tmp_path / "missing-heartbeat.json"
    store = StateStore(state_path)
    store.set_tracker_backoff(
        site="mt",
        endpoint="torrent/search",
        until=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        reason="expired",
    )
    with sqlite3.connect(state_path) as conn:
        conn.execute(
            """
            WITH RECURSIVE seq(value) AS (
              SELECT 1
              UNION ALL
              SELECT value + 1 FROM seq WHERE value < 1001
            )
            INSERT INTO scheduler_runs (
              run_id, started_at, status, command, execute, prune_enabled,
              intent_enabled, intent_execute, backoff_active, warning_count,
              summary_json
            )
            SELECT
              printf('run-%04d', value), '2026-01-01T00:00:00+00:00',
              'success', 'schedule-run', 0, 0, 0, 0, 0, 0, '{}'
            FROM seq
            """
        )
        conn.execute(
            """
            WITH RECURSIVE seq(value) AS (
              SELECT 1
              UNION ALL
              SELECT value + 1 FROM seq WHERE value < 10001
            )
            INSERT INTO tracker_api_events (
              site, endpoint, event, created_at, rate_limited
            )
            SELECT
              'mt', 'torrent/search', 'ok',
              '2026-01-01T00:00:00+00:00', 0
            FROM seq
            """
        )

    output = render_prometheus_metrics(state_path, heartbeat_path)

    assert 'seed_agent_scheduler_runs_total{status="success"} 1001.000000' in output
    assert 'seed_agent_tracker_api_events_total{event="ok"} 10001.000000' in output
    assert "seed_agent_tracker_backoff_active 0.000000" in output
