from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from seed_agent.audit import redact_payload
from seed_agent.models import (
    IntentState,
    LifecycleState,
    ManagedTorrent,
    RankedRelease,
    ResourceIntent,
)

STATE_PRIORITY = {
    LifecycleState.DISCOVERED.value: 0,
    LifecycleState.SCORED.value: 1,
    LifecycleState.ENQUEUED.value: 2,
    LifecycleState.DOWNLOADING.value: 3,
    LifecycleState.SEEDING.value: 4,
    LifecycleState.COLD.value: 5,
    LifecycleState.PAUSED.value: 6,
    LifecycleState.DELETED.value: 7,
}
INTENT_STATE_PRIORITY = {
    IntentState.RECEIVED.value: 0,
    IntentState.NORMALIZED.value: 1,
    IntentState.SEARCHED.value: 2,
    IntentState.CONFIRMATION_REQUIRED.value: 3,
    IntentState.REJECTED.value: 4,
    IntentState.FAILED.value: 4,
    IntentState.ENQUEUED.value: 5,
    IntentState.VIEWED.value: 6,
}
GIB = 1024**3
_UNSET = object()
SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30_000
SITE_HISTORY_MIN_SAMPLES = 3
_RELEASE_CANDIDATE_UPSERT_SQL = """
    INSERT INTO release_candidates (
        release_id,
        intent_id,
        site,
        title,
        score,
        confidence,
        accepted,
        confirmation_required,
        release_json,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(intent_id, release_id) DO UPDATE SET
        site = excluded.site,
        title = excluded.title,
        score = excluded.score,
        confidence = excluded.confidence,
        accepted = excluded.accepted,
        confirmation_required = excluded.confirmation_required,
        release_json = excluded.release_json
"""
_WANT_SEARCH_RUN_INSERT_SQL = """
    INSERT INTO want_search_runs (
      intent_id,
      run_id,
      source,
      searched_at,
      status,
      search_enabled,
      results_count,
      best_score,
      selected_release_id,
      backoff_active,
      backoff_until,
      message,
      payload_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class StateStore:
    def __init__(
        self,
        path: Path,
        *,
        initialize: bool = True,
        read_only: bool = False,
    ) -> None:
        if read_only and initialize:
            raise ValueError("read-only state stores cannot initialize the database")
        self.path = path
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _ensure_private_file(self.path)
        if initialize:
            self._initialize()

    def acquire_scheduler_lease(
        self,
        owner_id: str,
        *,
        lease_name: str = "schedule-run",
        ttl_seconds: int = 7200,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or _utc_now_datetime()
        expires_at = current_time + timedelta(seconds=max(ttl_seconds, 1))
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM scheduler_leases WHERE lease_name = ?",
                (lease_name,),
            ).fetchone()
            if row is not None:
                current = dict(row)
                current_expiry = _parse_datetime(current.get("expires_at"))
                if (
                    current.get("owner_id") != owner_id
                    and current_expiry is not None
                    and current_expiry > current_time
                ):
                    return {"acquired": False, **current}
            acquired_at = (
                str(row["acquired_at"])
                if row is not None and row["owner_id"] == owner_id
                else current_time.isoformat()
            )
            conn.execute(
                """
                INSERT INTO scheduler_leases (
                  lease_name, owner_id, acquired_at, renewed_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(lease_name) DO UPDATE SET
                  owner_id = excluded.owner_id,
                  acquired_at = excluded.acquired_at,
                  renewed_at = excluded.renewed_at,
                  expires_at = excluded.expires_at
                """,
                (
                    lease_name,
                    owner_id,
                    acquired_at,
                    current_time.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return {
            "acquired": True,
            "lease_name": lease_name,
            "owner_id": owner_id,
            "acquired_at": acquired_at,
            "renewed_at": current_time.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    def release_scheduler_lease(
        self,
        owner_id: str,
        *,
        lease_name: str = "schedule-run",
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM scheduler_leases WHERE lease_name = ? AND owner_id = ?",
                (lease_name, owner_id),
            )
        return cursor.rowcount > 0

    def get_scheduler_lease(self, lease_name: str = "schedule-run") -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_leases WHERE lease_name = ?",
                (lease_name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def request_scheduler_trigger(
        self,
        *,
        source: str,
        trigger_name: str = "schedule-run",
        requested_at: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = requested_at or _utc_now_datetime()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            control = conn.execute(
                "SELECT * FROM scheduler_controls WHERE control_name = ?",
                (trigger_name,),
            ).fetchone()
            if control is None or str(control["phase"]) != "waiting":
                return {
                    "queued": False,
                    "trigger_name": trigger_name,
                    "requested_at": current_time.isoformat(),
                    "source": source,
                    "reason": "scheduler cycle is already running",
                    "scheduler_phase": dict(control) if control is not None else None,
                }
            conn.execute(
                """
                INSERT INTO scheduler_triggers (trigger_name, requested_at, source)
                VALUES (?, ?, ?)
                ON CONFLICT(trigger_name) DO UPDATE SET
                  requested_at = excluded.requested_at,
                  source = excluded.source
                """,
                (trigger_name, current_time.isoformat(), source),
            )
        return {
            "queued": True,
            "trigger_name": trigger_name,
            "requested_at": current_time.isoformat(),
            "source": source,
        }

    def get_scheduler_trigger(
        self,
        trigger_name: str = "schedule-run",
    ) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_triggers WHERE trigger_name = ?",
                (trigger_name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_scheduler_control(
        self,
        control_name: str = "schedule-run",
    ) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_controls WHERE control_name = ?",
                (control_name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def begin_scheduler_cycle(
        self,
        control_name: str = "schedule-run",
        *,
        started_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        current_time = started_at or _utc_now_datetime()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM scheduler_triggers WHERE trigger_name = ?",
                (control_name,),
            ).fetchone()
            conn.execute(
                "DELETE FROM scheduler_triggers WHERE trigger_name = ?",
                (control_name,),
            )
            conn.execute(
                """
                INSERT INTO scheduler_controls (control_name, phase, updated_at)
                VALUES (?, 'running', ?)
                ON CONFLICT(control_name) DO UPDATE SET
                  phase = excluded.phase,
                  updated_at = excluded.updated_at
                """,
                (control_name, current_time.isoformat()),
            )
        return dict(row) if row is not None else None

    def mark_scheduler_waiting(
        self,
        control_name: str = "schedule-run",
        *,
        updated_at: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = updated_at or _utc_now_datetime()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_controls (control_name, phase, updated_at)
                VALUES (?, 'waiting', ?)
                ON CONFLICT(control_name) DO UPDATE SET
                  phase = excluded.phase,
                  updated_at = excluded.updated_at
                """,
                (control_name, current_time.isoformat()),
            )
        return {
            "control_name": control_name,
            "phase": "waiting",
            "updated_at": current_time.isoformat(),
        }

    def consume_scheduler_trigger(
        self,
        trigger_name: str = "schedule-run",
    ) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM scheduler_triggers WHERE trigger_name = ?",
                (trigger_name,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM scheduler_triggers WHERE trigger_name = ?",
                (trigger_name,),
            )
            conn.execute(
                """
                INSERT INTO scheduler_controls (control_name, phase, updated_at)
                VALUES (?, 'running', ?)
                ON CONFLICT(control_name) DO UPDATE SET
                  phase = excluded.phase,
                  updated_at = excluded.updated_at
                """,
                (trigger_name, _utc_now_datetime().isoformat()),
            )
        return dict(row)

    def start_scheduler_run(
        self,
        *,
        run_id: str,
        command: str,
        config: str | None,
        execute: bool,
        interval_minutes: int | None,
        prune_enabled: bool,
        intent_enabled: bool,
        intent_execute: bool,
        backoff_active: bool,
        backoff_until: str | None,
        summary: dict[str, Any] | None = None,
        started_at: datetime | None = None,
    ) -> None:
        started = (started_at or _utc_now_datetime()).isoformat()
        summary_json = _json_dumps(summary or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_runs (
                  run_id,
                  started_at,
                  finished_at,
                  status,
                  command,
                  config,
                  execute,
                  interval_minutes,
                  prune_enabled,
                  intent_enabled,
                  intent_execute,
                  backoff_active,
                  backoff_until,
                  warning_count,
                  summary_json
                )
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  started_at = excluded.started_at,
                  finished_at = NULL,
                  status = excluded.status,
                  command = excluded.command,
                  config = excluded.config,
                  execute = excluded.execute,
                  interval_minutes = excluded.interval_minutes,
                  prune_enabled = excluded.prune_enabled,
                  intent_enabled = excluded.intent_enabled,
                  intent_execute = excluded.intent_execute,
                  backoff_active = excluded.backoff_active,
                  backoff_until = excluded.backoff_until,
                  error = NULL,
                  summary_json = excluded.summary_json
                """,
                (
                    run_id,
                    started,
                    "running",
                    command,
                    config,
                    int(execute),
                    interval_minutes,
                    int(prune_enabled),
                    int(intent_enabled),
                    int(intent_execute),
                    int(backoff_active),
                    backoff_until,
                    summary_json,
                ),
            )

    def finish_scheduler_run(
        self,
        *,
        run_id: str,
        status: str,
        summary: dict[str, Any],
        finished_at: datetime | None = None,
    ) -> None:
        finished = (finished_at or _utc_now_datetime()).isoformat()
        intent_payload = summary.get("intent") if isinstance(summary.get("intent"), dict) else {}
        backoff = (
            summary.get("schedule_backoff")
            if isinstance(summary.get("schedule_backoff"), dict)
            else {}
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE scheduler_runs
                SET
                  finished_at = ?,
                  status = ?,
                  backoff_active = ?,
                  backoff_until = ?,
                  discovered = ?,
                  scored = ?,
                  accepted = ?,
                  enqueued = ?,
                  intent_ingested = ?,
                  intent_searched = ?,
                  intent_ranked = ?,
                  intent_enqueue_candidates = ?,
                  warning_count = ?,
                  error = ?,
                  summary_json = ?
                WHERE run_id = ?
                """,
                (
                    finished,
                    status,
                    int(bool(backoff.get("active"))),
                    backoff.get("until"),
                    _optional_int(summary.get("discovered")),
                    _optional_int(summary.get("scored")),
                    _optional_int(summary.get("accepted")),
                    _optional_int(summary.get("enqueued")),
                    _optional_int(intent_payload.get("ingested")),
                    _optional_int(intent_payload.get("searched")),
                    _optional_int(intent_payload.get("ranked")),
                    _optional_int(intent_payload.get("enqueue_candidates")),
                    len(summary.get("discovery_warnings") or []),
                    summary.get("error"),
                    _json_dumps(summary),
                    run_id,
                ),
            )

    def record_scheduler_event(
        self,
        *,
        run_id: str,
        phase: str,
        event: str,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_run_events (
                  run_id,
                  phase,
                  event,
                  created_at,
                  message,
                  payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    phase,
                    event,
                    (created_at or _utc_now_datetime()).isoformat(),
                    message,
                    _json_dumps(payload) if payload is not None else None,
                ),
            )

    def list_scheduler_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scheduler_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (max(limit, 1),),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_completed_scheduler_run(
        self,
        *,
        summary_flag: str,
    ) -> dict[str, Any] | None:
        if re.fullmatch(r"[A-Za-z0-9_]+", summary_flag) is None:
            raise ValueError("summary_flag must contain only letters, digits, or underscores")
        json_path = f"$.{summary_flag}"
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM scheduler_runs
                WHERE finished_at IS NOT NULL
                  AND json_valid(summary_json) = 1
                  AND json_type(summary_json, ?) = 'true'
                  AND json_extract(summary_json, ?) = 1
                ORDER BY finished_at DESC, started_at DESC
                LIMIT 1
                """,
                (json_path, json_path),
            ).fetchone()
        return dict(row) if row is not None else None

    def scheduler_run_status_counts(self) -> dict[str, int]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM scheduler_runs GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def list_scheduler_run_events(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM scheduler_run_events"
        params: list[Any] = []
        if run_id is not None:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(limit, 1))
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def set_tracker_backoff(
        self,
        *,
        site: str,
        endpoint: str,
        until: str,
        reason: str,
        active: bool = True,
        source: str | None = None,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tracker_backoffs (
                  site,
                  endpoint,
                  active,
                  created_at,
                  until,
                  reason,
                  source,
                  run_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site, endpoint) DO UPDATE SET
                  active = excluded.active,
                  created_at = excluded.created_at,
                  until = excluded.until,
                  reason = excluded.reason,
                  source = excluded.source,
                  run_id = excluded.run_id
                """,
                (
                    site,
                    endpoint,
                    int(active),
                    (created_at or _utc_now_datetime()).isoformat(),
                    until,
                    reason,
                    source,
                    run_id,
                ),
            )

    def get_tracker_backoff(self, site: str, endpoint: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM tracker_backoffs
                WHERE site = ? AND endpoint = ?
                """,
                (site, endpoint),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_tracker_backoffs(self) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM tracker_backoffs
                ORDER BY created_at DESC, site ASC, endpoint ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def has_active_tracker_backoff(self, *, now: datetime | None = None) -> bool:
        current_time = _as_utc(now or _utc_now_datetime())
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT until
                FROM tracker_backoffs
                WHERE active = 1
                """
            ).fetchall()
        return any(
            until is not None and _as_utc(until) > current_time
            for row in rows
            if (until := _parse_datetime(row["until"])) is not None
        )

    def clear_tracker_backoffs(self, *, site: str | None = None) -> int:
        query = "UPDATE tracker_backoffs SET active = 0 WHERE active = 1"
        params: tuple[object, ...] = ()
        if site is not None:
            query += " AND site = ?"
            params = (site,)
        with self._connect() as conn:
            cursor = conn.execute(query, params)
        return cursor.rowcount

    def record_tracker_api_event(
        self,
        *,
        site: str,
        endpoint: str,
        event: str,
        run_id: str | None = None,
        status_code: int | None = None,
        api_code: str | None = None,
        rate_limited: bool = False,
        message: str | None = None,
        request: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tracker_api_events (
                  site,
                  endpoint,
                  event,
                  created_at,
                  run_id,
                  status_code,
                  api_code,
                  rate_limited,
                  message,
                  request_json,
                  response_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    site,
                    endpoint,
                    event,
                    (created_at or _utc_now_datetime()).isoformat(),
                    run_id,
                    status_code,
                    api_code,
                    int(rate_limited),
                    message,
                    _json_dumps(request) if request is not None else None,
                    _json_dumps(response) if response is not None else None,
                ),
            )

    def list_tracker_api_events(
        self,
        *,
        site: str | None = None,
        endpoint: str | None = None,
        event: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM tracker_api_events"
        params: list[Any] = []
        filters = []
        if site is not None:
            filters.append("site = ?")
            params.append(site)
        if endpoint is not None:
            filters.append("endpoint = ?")
            params.append(endpoint)
        if event is not None:
            filters.append("event = ?")
            params.append(event)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(limit, 1))
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def tracker_api_event_counts(self) -> dict[str, int]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                "SELECT event, COUNT(*) AS count FROM tracker_api_events GROUP BY event"
            ).fetchall()
        return {str(row["event"]): int(row["count"]) for row in rows}

    def get_source_cursor(self, source: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cursor FROM source_cursors WHERE source = ?",
                (source,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def set_source_cursor(self, source: str, cursor: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_cursors (source, cursor, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                  cursor = excluded.cursor,
                  updated_at = excluded.updated_at
                """,
                (source, cursor, _utc_now_datetime().isoformat()),
            )

    def record_want_search_run(
        self,
        *,
        intent_id: str,
        source: str,
        status: str,
        search_enabled: bool,
        results_count: int,
        run_id: str | None = None,
        best_score: int | None = None,
        selected_release_id: str | None = None,
        backoff_active: bool = False,
        backoff_until: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        searched_at: datetime | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                _WANT_SEARCH_RUN_INSERT_SQL,
                (
                    intent_id,
                    run_id,
                    source,
                    (searched_at or _utc_now_datetime()).isoformat(),
                    status,
                    int(search_enabled),
                    results_count,
                    best_score,
                    selected_release_id,
                    int(backoff_active),
                    backoff_until,
                    message,
                    _json_dumps(payload) if payload is not None else None,
                ),
            )

    def list_want_search_runs(
        self,
        *,
        intent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM want_search_runs"
        params: list[Any] = []
        if intent_id is not None:
            query += " WHERE intent_id = ?"
            params.append(intent_id)
        query += " ORDER BY searched_at DESC, id DESC LIMIT ?"
        params.append(max(limit, 1))
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def site_history_scores(
        self,
        *,
        window_days: int = 30,
        min_samples: int = SITE_HISTORY_MIN_SAMPLES,
    ) -> dict[str, dict[str, Any]]:
        cutoff = (_utc_now_datetime() - timedelta(days=max(window_days, 1))).isoformat()
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    c.site,
                    c.stable_id,
                    c.state,
                    c.torrent_hash,
                    c.updated_at AS candidate_updated_at,
                    tr.uploaded_bytes,
                    tr.downloaded_bytes,
                    tr.missing_from_qb_at,
                    tr.no_upload_since_at,
                    tr.paused_at,
                    tr.seen_at,
                    tr.updated_at AS runtime_updated_at
                FROM candidates c
                JOIN torrent_runtime tr ON tr.torrent_hash = c.torrent_hash
                WHERE c.torrent_hash IS NOT NULL
                  AND (
                    c.updated_at >= ?
                    OR tr.updated_at >= ?
                    OR tr.seen_at >= ?
                  )
                ORDER BY c.site ASC, c.updated_at DESC, c.stable_id ASC
                """,
                (cutoff, cutoff, cutoff),
            ).fetchall()
            rate_limited_rows = conn.execute(
                """
                SELECT site, COUNT(*) AS count
                FROM tracker_api_events
                WHERE rate_limited = 1 AND created_at >= ?
                GROUP BY site
                """,
                (cutoff,),
            ).fetchall()
            backoff_rows = conn.execute(
                """
                SELECT site, until
                FROM tracker_backoffs
                WHERE active = 1
                """
            ).fetchall()

        rate_limited_counts = {
            str(row["site"]): int(row["count"]) for row in rate_limited_rows
        }
        active_backoff_counts: dict[str, int] = {}
        current_time = _utc_now_datetime()
        for row in backoff_rows:
            until = _parse_datetime(row["until"])
            if until is None or _as_utc(until) <= current_time:
                continue
            site = str(row["site"])
            active_backoff_counts[site] = active_backoff_counts.get(site, 0) + 1
        grouped: dict[str, dict[str, Any]] = {}
        seen_hashes: set[tuple[str, str]] = set()
        for row in rows:
            site = str(row["site"])
            torrent_hash = str(row["torrent_hash"])
            identity = (site, torrent_hash)
            if identity in seen_hashes:
                continue
            seen_hashes.add(identity)
            uploaded = _int_value(row["uploaded_bytes"])
            downloaded = _int_value(row["downloaded_bytes"])
            upload_ratio = uploaded / downloaded if downloaded > 0 else None
            entry = grouped.setdefault(
                site,
                {
                    "site": site,
                    "window_days": max(window_days, 1),
                    "min_samples": max(min_samples, 1),
                    "samples": 0,
                    "productive_count": 0,
                    "no_upload_count": 0,
                    "missing_count": 0,
                    "paused_count": 0,
                    "total_uploaded_gb": 0.0,
                    "upload_ratios": [],
                },
            )
            entry["samples"] += 1
            entry["total_uploaded_gb"] += uploaded / GIB
            if upload_ratio is not None:
                entry["upload_ratios"].append(upload_ratio)
            if uploaded >= GIB or (upload_ratio is not None and upload_ratio >= 0.25):
                entry["productive_count"] += 1
            if row["no_upload_since_at"] is not None:
                entry["no_upload_count"] += 1
            if (
                row["missing_from_qb_at"] is not None
                or row["state"] == LifecycleState.DELETED.value
            ):
                entry["missing_count"] += 1
            if row["paused_at"] is not None or row["state"] == LifecycleState.PAUSED.value:
                entry["paused_count"] += 1

        for site, rate_limited_count in rate_limited_counts.items():
            grouped.setdefault(site, _empty_site_history_entry(site, window_days, min_samples))
            grouped[site]["rate_limited_events"] = rate_limited_count
        for site, active_backoffs in active_backoff_counts.items():
            grouped.setdefault(site, _empty_site_history_entry(site, window_days, min_samples))
            grouped[site]["active_backoffs"] = active_backoffs

        summaries: dict[str, dict[str, Any]] = {}
        for site, entry in grouped.items():
            entry.setdefault("rate_limited_events", rate_limited_counts.get(site, 0))
            entry.setdefault("active_backoffs", active_backoff_counts.get(site, 0))
            summaries[site] = _site_history_summary(entry)
        return summaries

    def upsert_candidate(
        self,
        stable_id: str,
        title: str,
        site: str,
        state: LifecycleState,
        score: int | None,
        torrent_hash: str | None,
        *,
        free_window_expires_at: str | None | object = _UNSET,
        size_bytes: int | None | object = _UNSET,
        seeders: int | None | object = _UNSET,
        leechers: int | None | object = _UNSET,
        discount: str | None | object = _UNSET,
        left_time_minutes: int | None | object = _UNSET,
        score_reasons: list[str] | None | object = _UNSET,
    ) -> None:
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _candidate_row(
                conn.execute(
                    "SELECT * FROM candidates WHERE stable_id = ?",
                    (stable_id,),
                ).fetchone()
            )
            first_seen_at = current["first_seen_at"] if current is not None else now
            free_window_value = _preserved_value(
                current,
                "free_window_expires_at",
                free_window_expires_at,
            )
            size_value = _preserved_value(current, "size_bytes", size_bytes)
            seeders_value = _preserved_value(current, "seeders", seeders)
            leechers_value = _preserved_value(current, "leechers", leechers)
            discount_value = _preserved_value(current, "discount", discount)
            left_time_value = _preserved_value(current, "left_time_minutes", left_time_minutes)
            score_reasons_value = _preserved_value(current, "score_reasons", score_reasons)
            score_reasons_json = (
                _json_dumps(score_reasons_value) if score_reasons_value is not None else None
            )
            state_value, score_value, torrent_hash_value = _monotonic_values(
                current,
                state,
                score,
                torrent_hash,
            )
            conn.execute(
                """
                INSERT INTO candidates (
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stable_id) DO UPDATE SET
                    site = excluded.site,
                    title = excluded.title,
                    state = excluded.state,
                    score = excluded.score,
                    torrent_hash = excluded.torrent_hash,
                    free_window_expires_at = excluded.free_window_expires_at,
                    size_bytes = excluded.size_bytes,
                    seeders = excluded.seeders,
                    leechers = excluded.leechers,
                    discount = excluded.discount,
                    left_time_minutes = excluded.left_time_minutes,
                    score_reasons = excluded.score_reasons,
                    updated_at = excluded.updated_at
                """,
                (
                    stable_id,
                    site,
                    title,
                    state_value,
                    score_value,
                    torrent_hash_value,
                    free_window_value,
                    size_value,
                    seeders_value,
                    leechers_value,
                    discount_value,
                    left_time_value,
                    score_reasons_json,
                    first_seen_at,
                    now,
                ),
            )

    def record_candidate_enqueue_snapshot(
        self,
        *,
        stable_id: str,
        torrent_hash: str | None,
        seeders: int,
        leechers: int,
        size_bytes: int,
        published_at: str | None,
        candidate_age_minutes: int | None,
        score: int,
        score_reasons: list[str],
    ) -> None:
        now = _utc_now()
        ratio = seeders / max(leechers, 1)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO candidate_enqueue_snapshots (
                    stable_id,
                    torrent_hash,
                    seeders,
                    leechers,
                    seed_leecher_ratio,
                    size_bytes,
                    published_at,
                    candidate_age_minutes,
                    score,
                    score_reasons,
                    enqueued_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stable_id) DO UPDATE SET
                    torrent_hash = COALESCE(
                        candidate_enqueue_snapshots.torrent_hash,
                        excluded.torrent_hash
                    )
                """,
                (
                    stable_id,
                    torrent_hash,
                    seeders,
                    leechers,
                    ratio,
                    size_bytes,
                    published_at,
                    candidate_age_minutes,
                    score,
                    _json_dumps(score_reasons),
                    now,
                ),
            )

    def get_candidate_enqueue_snapshot(self, stable_id: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT * FROM candidate_enqueue_snapshots WHERE stable_id = ?",
                (stable_id,),
            ).fetchone()
        return _enqueue_snapshot_row(row)

    def get_candidate_enqueue_snapshot_by_hash(
        self, torrent_hash: str
    ) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM candidate_enqueue_snapshots
                WHERE torrent_hash = ?
                ORDER BY enqueued_at DESC
                LIMIT 1
                """,
                (torrent_hash,),
            ).fetchone()
        return _enqueue_snapshot_row(row)

    def get_candidate(self, stable_id: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE stable_id = ?
                """,
                (stable_id,),
            ).fetchone()
        return _candidate_row(row)

    def list_by_state(self, state: LifecycleState) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE state = ?
                ORDER BY updated_at ASC, stable_id ASC
                """,
                (state.value,),
            ).fetchall()
        return [_candidate_row(row) for row in rows]

    def list_by_torrent_hash(self, torrent_hash: str) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE torrent_hash = ?
                ORDER BY updated_at ASC, stable_id ASC
                """,
                (torrent_hash,),
            ).fetchall()
        return [_candidate_row(row) for row in rows]

    def list_unlinked_candidates(self) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE torrent_hash IS NULL
                ORDER BY updated_at DESC, stable_id ASC
                """
            ).fetchall()
        return [_candidate_row(row) for row in rows]

    def update_by_torrent_hash(self, torrent_hash: str, state: LifecycleState) -> int:
        rows = self.list_by_torrent_hash(torrent_hash)
        for row in rows:
            self.upsert_candidate(
                stable_id=str(row["stable_id"]),
                title=str(row["title"]),
                site=str(row["site"]),
                state=state,
                score=row["score"],
                torrent_hash=str(row["torrent_hash"]) if row["torrent_hash"] is not None else None,
            )
        return len(rows)

    def mark_present_by_torrent_hash(self, torrent_hash: str, state: LifecycleState) -> int:
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            cursor = conn.execute(
                """
                UPDATE candidates
                SET state = ?, updated_at = ?
                WHERE torrent_hash = ?
                  AND state = ?
                """,
                (state.value, now, torrent_hash, LifecycleState.DELETED.value),
            )
            return int(cursor.rowcount)

    def prune_stale_candidates(
        self,
        *,
        retention_days: int,
        states: tuple[LifecycleState, ...] = (
            LifecycleState.DISCOVERED,
            LifecycleState.SCORED,
        ),
    ) -> int:
        if retention_days <= 0:
            return 0
        cutoff = (_utc_now_datetime() - timedelta(days=retention_days)).isoformat()
        state_values = tuple(state.value for state in states)
        placeholders = ", ".join("?" for _ in state_values)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                DELETE FROM candidates
                WHERE torrent_hash IS NULL
                  AND state IN ({placeholders})
                  AND updated_at < ?
                """,
                (*state_values, cutoff),
            )
            return int(cursor.rowcount)

    def mark_torrent_paused(self, torrent_hash: str, paused_at: datetime | None = None) -> None:
        self._upsert_torrent_runtime(
            torrent_hash,
            paused_at=(paused_at or _utc_now_datetime()).isoformat(),
            replace_paused_at=True,
        )

    def clear_torrent_runtime(self, torrent_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM torrent_runtime
                WHERE torrent_hash = ?
                """,
                (torrent_hash,),
            )

    def get_torrent_runtime(self, torrent_hash: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                FROM torrent_runtime
                WHERE torrent_hash = ?
                """,
                (torrent_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def apply_torrent_runtime(self, torrents: list[ManagedTorrent]) -> list[ManagedTorrent]:
        torrent_hashes = [torrent.hash for torrent in torrents if torrent.hash]
        runtime_by_hash = self._torrent_runtime_by_hash(torrent_hashes)
        candidate_rows_by_hash = self._candidate_rows_by_torrent_hash(torrent_hashes)
        seen_at = _utc_now()
        updates: list[tuple[object, ...]] = []
        enriched: list[ManagedTorrent] = []
        for torrent in torrents:
            runtime = runtime_by_hash.get(torrent.hash)
            metadata = dict(torrent.metadata)
            candidate_rows = candidate_rows_by_hash.get(torrent.hash, [])
            candidate_free_expiry = next(
                (
                    row.get("free_window_expires_at")
                    for row in candidate_rows
                    if row.get("free_window_expires_at")
                ),
                None,
            )
            candidate_discount = next(
                (
                    row.get("discount")
                    for row in candidate_rows
                    if row.get("discount")
                ),
                None,
            )
            if candidate_free_expiry:
                metadata["free_window_expires_at"] = candidate_free_expiry
                metadata["free_window_source"] = "candidate_state"
            if candidate_discount:
                metadata["discount"] = candidate_discount
                metadata["discount_source"] = "candidate_state"
            recent_upload_gb = _recent_upload_gb(runtime, torrent.uploaded_bytes)
            if recent_upload_gb is not None:
                metadata["recent_upload_gb"] = recent_upload_gb
                metadata["upload_delta_gb"] = recent_upload_gb
            no_upload_since_at = _no_upload_since_at(
                runtime,
                torrent_added_at=torrent.added_at,
                uploaded_bytes=torrent.uploaded_bytes,
                recent_upload_gb=recent_upload_gb,
            )
            if no_upload_since_at is not None:
                metadata["no_upload_since_at"] = no_upload_since_at
            paused_at = _parse_datetime(runtime.get("paused_at")) if runtime is not None else None
            if paused_at is None:
                paused_at = _parse_datetime(metadata.get("paused_at"))
            if _is_paused_state(torrent.state):
                if paused_at is None:
                    paused_at = _utc_now_datetime()
                metadata["paused_at"] = paused_at
            else:
                paused_at = None
            updates.append(
                (
                    torrent.hash,
                    paused_at.isoformat() if paused_at is not None else None,
                    torrent.uploaded_bytes,
                    torrent.downloaded_bytes,
                    int(metadata.get("upspeed_bps", 0) or 0),
                    int(metadata.get("dlspeed_bps", 0) or 0),
                    None,
                    None,
                    (
                        no_upload_since_at.isoformat()
                        if no_upload_since_at is not None
                        else None
                    ),
                    seen_at,
                    seen_at,
                )
            )
            enriched.append(torrent.model_copy(update={"metadata": metadata}))
        self._bulk_upsert_torrent_runtime(updates)
        return enriched

    def reconcile_missing_torrents(
        self,
        live_hashes: set[str],
        *,
        reason: str = "missing from qB live torrent list",
        min_age_minutes: int = 15,
    ) -> int:
        now = _utc_now()
        cutoff = (
            _utc_now_datetime() - timedelta(minutes=max(min_age_minutes, 0))
        ).isoformat()
        with self._connect() as conn:
            if live_hashes:
                placeholders = ", ".join("?" for _ in live_hashes)
                missing_rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.torrent_hash
                    FROM candidates c
                    WHERE c.torrent_hash IS NOT NULL
                      AND c.state IN (?, ?, ?, ?, ?)
                      AND c.updated_at < ?
                      AND c.torrent_hash NOT IN ({placeholders})
                    """,
                    (
                        LifecycleState.ENQUEUED.value,
                        LifecycleState.DOWNLOADING.value,
                        LifecycleState.SEEDING.value,
                        LifecycleState.COLD.value,
                        LifecycleState.PAUSED.value,
                        cutoff,
                        *tuple(live_hashes),
                    ),
                ).fetchall()
            else:
                missing_rows = conn.execute(
                    """
                    SELECT DISTINCT c.torrent_hash
                    FROM candidates c
                    WHERE c.torrent_hash IS NOT NULL
                      AND c.state IN (?, ?, ?, ?, ?)
                      AND c.updated_at < ?
                    """,
                    (
                        LifecycleState.ENQUEUED.value,
                        LifecycleState.DOWNLOADING.value,
                        LifecycleState.SEEDING.value,
                        LifecycleState.COLD.value,
                        LifecycleState.PAUSED.value,
                        cutoff,
                    ),
                ).fetchall()
            missing_hashes = [str(row[0]) for row in missing_rows if row[0]]
            if not missing_hashes:
                return 0
            placeholders = ", ".join("?" for _ in missing_hashes)
            conn.execute(
                f"""
                UPDATE candidates
                SET state = ?, updated_at = ?
                WHERE torrent_hash IN ({placeholders})
                  AND state IN (?, ?, ?, ?, ?)
                """,
                (
                    LifecycleState.DELETED.value,
                    now,
                    *missing_hashes,
                    LifecycleState.ENQUEUED.value,
                    LifecycleState.DOWNLOADING.value,
                    LifecycleState.SEEDING.value,
                    LifecycleState.COLD.value,
                    LifecycleState.PAUSED.value,
                ),
            )
            conn.executemany(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    missing_from_qb_at = excluded.missing_from_qb_at,
                    missing_from_qb_reason = excluded.missing_from_qb_reason,
                    updated_at = excluded.updated_at
                """,
                [(torrent_hash, now, reason, now) for torrent_hash in missing_hashes],
            )
            return len(missing_hashes)

    def _torrent_runtime_by_hash(self, torrent_hashes: list[str]) -> dict[str, dict[str, Any]]:
        if not torrent_hashes:
            return {}
        placeholders = ", ".join("?" for _ in torrent_hashes)
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                FROM torrent_runtime
                WHERE torrent_hash IN ({placeholders})
                """,
                tuple(torrent_hashes),
            ).fetchall()
        return {str(row["torrent_hash"]): dict(row) for row in rows}

    def _candidate_rows_by_torrent_hash(
        self, torrent_hashes: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not torrent_hashes:
            return {}
        placeholders = ", ".join("?" for _ in torrent_hashes)
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE torrent_hash IN ({placeholders})
                ORDER BY updated_at ASC, stable_id ASC
                """,
                tuple(torrent_hashes),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["torrent_hash"]), []).append(_candidate_row(row))
        return grouped

    def _bulk_upsert_torrent_runtime(self, rows: list[tuple[object, ...]]) -> None:
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    paused_at = excluded.paused_at,
                    uploaded_bytes = excluded.uploaded_bytes,
                    downloaded_bytes = excluded.downloaded_bytes,
                    upspeed_bps = excluded.upspeed_bps,
                    dlspeed_bps = excluded.dlspeed_bps,
                    missing_from_qb_at = excluded.missing_from_qb_at,
                    missing_from_qb_reason = excluded.missing_from_qb_reason,
                    no_upload_since_at = excluded.no_upload_since_at,
                    seen_at = excluded.seen_at,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def _upsert_torrent_runtime(
        self,
        torrent_hash: str,
        *,
        paused_at: str | None | object = _UNSET,
        replace_paused_at: bool = False,
        uploaded_bytes: int | None = None,
        downloaded_bytes: int | None = None,
        upspeed_bps: int | None = None,
        dlspeed_bps: int | None = None,
        missing_from_qb_at: str | None | object = _UNSET,
        missing_from_qb_reason: str | None | object = _UNSET,
        no_upload_since_at: str | None = None,
        seen_at: str | None = None,
    ) -> None:
        current = self.get_torrent_runtime(torrent_hash) or {}
        now = _utc_now()
        paused_value = current.get("paused_at")
        if replace_paused_at or paused_at is not _UNSET:
            paused_value = paused_at

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    paused_at = excluded.paused_at,
                    uploaded_bytes = excluded.uploaded_bytes,
                    downloaded_bytes = excluded.downloaded_bytes,
                    upspeed_bps = excluded.upspeed_bps,
                    dlspeed_bps = excluded.dlspeed_bps,
                    missing_from_qb_at = excluded.missing_from_qb_at,
                    missing_from_qb_reason = excluded.missing_from_qb_reason,
                    no_upload_since_at = excluded.no_upload_since_at,
                    seen_at = excluded.seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    torrent_hash,
                    paused_value,
                    uploaded_bytes if uploaded_bytes is not None else current.get("uploaded_bytes"),
                    downloaded_bytes
                    if downloaded_bytes is not None
                    else current.get("downloaded_bytes"),
                    upspeed_bps if upspeed_bps is not None else current.get("upspeed_bps"),
                    dlspeed_bps if dlspeed_bps is not None else current.get("dlspeed_bps"),
                    missing_from_qb_at
                    if missing_from_qb_at is not _UNSET
                    else current.get("missing_from_qb_at"),
                    missing_from_qb_reason
                    if missing_from_qb_reason is not _UNSET
                    else current.get("missing_from_qb_reason"),
                    no_upload_since_at,
                    seen_at if seen_at is not None else current.get("seen_at"),
                    now,
                ),
            )

    def upsert_intent(
        self,
        intent: ResourceIntent,
        selected_release_id: str | None = None,
    ) -> None:
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current_row = conn.execute(
                "SELECT * FROM intents WHERE intent_id = ?",
                (intent.intent_id,),
            ).fetchone()
            current = dict(current_row) if current_row is not None else None
            created_at = current["created_at"] if current is not None else now
            selected_value = selected_release_id
            if selected_value is None and current is not None:
                selected_value = current["selected_release_id"]
            effective_intent = _monotonic_intent(current, intent)
            conn.execute(
                """
                INSERT INTO intents (
                    intent_id,
                    source,
                    raw_text,
                    title,
                    kind,
                    state,
                    normalized_json,
                    selected_release_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(intent_id) DO UPDATE SET
                    source = excluded.source,
                    raw_text = excluded.raw_text,
                    title = excluded.title,
                    kind = excluded.kind,
                    state = excluded.state,
                    normalized_json = excluded.normalized_json,
                    selected_release_id = excluded.selected_release_id,
                    updated_at = excluded.updated_at
                """,
                (
                    effective_intent.intent_id,
                    effective_intent.source.value,
                    effective_intent.raw_text,
                    effective_intent.title,
                    effective_intent.kind.value,
                    effective_intent.state.value,
                    _json_dumps(effective_intent.model_dump(mode="json")),
                    selected_value,
                    created_at,
                    now,
                ),
            )

    def get_intent(self, intent_id: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT
                    intent_id,
                    source,
                    raw_text,
                    title,
                    kind,
                    state,
                    normalized_json,
                    selected_release_id,
                    created_at,
                    updated_at
                FROM intents
                WHERE intent_id = ?
                """,
                (intent_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_intents_by_state(self, state: IntentState) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    intent_id,
                    source,
                    raw_text,
                    title,
                    kind,
                    state,
                    normalized_json,
                    selected_release_id,
                    created_at,
                    updated_at
                FROM intents
                WHERE state = ?
                ORDER BY updated_at ASC, intent_id ASC
                """,
                (state.value,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_intent_state(
        self,
        intent_id: str,
        state: IntentState,
        selected_release_id: str | None = None,
    ) -> bool:
        current = self.get_intent(intent_id)
        if current is None:
            return False
        normalized = json.loads(str(current["normalized_json"]))
        normalized["state"] = state.value
        intent = ResourceIntent.model_validate(normalized)
        self.upsert_intent(intent, selected_release_id=selected_release_id)
        return True

    def mark_intent_viewed(self, intent_id: str) -> str:
        """Mark an intent as viewed unless an enqueue is currently in flight."""
        now = _utc_now()
        current_time = _utc_now_datetime()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, normalized_json FROM intents WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if row is None:
                return "missing"
            if str(row["state"]) == IntentState.VIEWED.value:
                return "already_viewed"
            claim = conn.execute(
                "SELECT expires_at FROM intent_enqueue_claims WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if claim is not None:
                expires_at = _parse_datetime(claim["expires_at"])
                if expires_at is not None and expires_at > current_time:
                    return "enqueue_in_progress"
            normalized = json.loads(str(row["normalized_json"]))
            normalized["state"] = IntentState.VIEWED.value
            ResourceIntent.model_validate(normalized)
            conn.execute(
                """
                UPDATE intents
                SET state = ?, normalized_json = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (IntentState.VIEWED.value, _json_dumps(normalized), now, intent_id),
            )
        return "viewed"

    def acquire_intent_enqueue_claim(
        self,
        intent_id: str,
        release_id: str,
        owner_id: str,
        *,
        ttl_seconds: int = 600,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or _utc_now_datetime()
        expires_at = current_time + timedelta(seconds=max(ttl_seconds, 1))
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            intent = conn.execute(
                "SELECT state, selected_release_id FROM intents WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if intent is None:
                return {"acquired": False, "status": "missing"}
            if str(intent["state"]) == IntentState.VIEWED.value:
                return {"acquired": False, "status": "already_viewed"}
            if str(intent["state"]) == IntentState.ENQUEUED.value:
                return {
                    "acquired": False,
                    "status": "already_enqueued",
                    "selected_release_id": intent["selected_release_id"],
                }
            claim = conn.execute(
                "SELECT * FROM intent_enqueue_claims WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if claim is not None:
                claim_expiry = _parse_datetime(claim["expires_at"])
                if (
                    str(claim["owner_id"]) != owner_id
                    and claim_expiry is not None
                    and claim_expiry > current_time
                ):
                    return {"acquired": False, "status": "in_progress", **dict(claim)}
            conn.execute(
                """
                INSERT INTO intent_enqueue_claims (
                  intent_id, release_id, owner_id, acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(intent_id) DO UPDATE SET
                  release_id = excluded.release_id,
                  owner_id = excluded.owner_id,
                  acquired_at = excluded.acquired_at,
                  expires_at = excluded.expires_at
                """,
                (
                    intent_id,
                    release_id,
                    owner_id,
                    current_time.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return {
            "acquired": True,
            "status": "acquired",
            "intent_id": intent_id,
            "release_id": release_id,
            "owner_id": owner_id,
            "expires_at": expires_at.isoformat(),
        }

    def complete_intent_enqueue_claim(
        self,
        intent_id: str,
        release_id: str,
        owner_id: str,
    ) -> bool:
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                """
                SELECT owner_id, release_id
                FROM intent_enqueue_claims
                WHERE intent_id = ?
                """,
                (intent_id,),
            ).fetchone()
            if (
                claim is None
                or str(claim["owner_id"]) != owner_id
                or str(claim["release_id"]) != release_id
            ):
                return False
            row = conn.execute(
                "SELECT state, normalized_json FROM intents WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if row is None:
                return False
            if str(row["state"]) == IntentState.VIEWED.value:
                conn.execute(
                    """
                    UPDATE intents
                    SET selected_release_id = ?, updated_at = ?
                    WHERE intent_id = ?
                    """,
                    (release_id, now, intent_id),
                )
                conn.execute(
                    "DELETE FROM intent_enqueue_claims WHERE intent_id = ? AND owner_id = ?",
                    (intent_id, owner_id),
                )
                return True
            normalized = json.loads(str(row["normalized_json"]))
            normalized["state"] = IntentState.ENQUEUED.value
            ResourceIntent.model_validate(normalized)
            conn.execute(
                """
                UPDATE intents
                SET state = ?, normalized_json = ?, selected_release_id = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    IntentState.ENQUEUED.value,
                    _json_dumps(normalized),
                    release_id,
                    now,
                    intent_id,
                ),
            )
            conn.execute(
                "DELETE FROM intent_enqueue_claims WHERE intent_id = ? AND owner_id = ?",
                (intent_id, owner_id),
            )
        return True

    def release_intent_enqueue_claim(self, intent_id: str, owner_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM intent_enqueue_claims WHERE intent_id = ? AND owner_id = ?",
                (intent_id, owner_id),
            )
        return cursor.rowcount > 0

    def find_intent_id_by_alias(self, alias: str) -> str | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT intent_id FROM intent_aliases WHERE alias = ?",
                (alias,),
            ).fetchone()
        return None if row is None else str(row["intent_id"])

    def upsert_intent_alias(self, alias: str, intent_id: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_aliases (alias, intent_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    intent_id = excluded.intent_id,
                    updated_at = excluded.updated_at
                """,
                (alias, intent_id, now, now),
            )

    def list_intent_aliases(self, intent_id: str) -> list[str]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT alias
                FROM intent_aliases
                WHERE intent_id = ?
                ORDER BY alias ASC
                """,
                (intent_id,),
            ).fetchall()
        return [str(row["alias"]) for row in rows]

    def upsert_intent_source_evidence(
        self,
        *,
        intent_id: str,
        source: str,
        raw_text: str,
        source_event_id: str | None,
        requested_at: str | None,
        metadata: dict[str, Any],
    ) -> None:
        source_config_id = _optional_text(metadata.get("source_config_id"))
        source_label = _optional_text(metadata.get("source_label"))
        evidence_id = _evidence_id(source, source_config_id, source_event_id, raw_text)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_source_evidence (
                    evidence_id,
                    intent_id,
                    source,
                    source_event_id,
                    source_config_id,
                    source_label,
                    requested_at,
                    raw_text,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    intent_id = excluded.intent_id,
                    source = excluded.source,
                    source_event_id = excluded.source_event_id,
                    source_config_id = excluded.source_config_id,
                    source_label = excluded.source_label,
                    requested_at = excluded.requested_at,
                    raw_text = excluded.raw_text,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    evidence_id,
                    intent_id,
                    source,
                    source_event_id,
                    source_config_id,
                    source_label,
                    requested_at,
                    raw_text,
                    _json_dumps(metadata),
                    now,
                    now,
                ),
            )

    def list_intent_source_evidence(self, intent_id: str) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    evidence_id,
                    intent_id,
                    source,
                    source_event_id,
                    source_config_id,
                    source_label,
                    requested_at,
                    raw_text,
                    metadata_json,
                    created_at,
                    updated_at
                FROM intent_source_evidence
                WHERE intent_id = ?
                ORDER BY
                    COALESCE(requested_at, created_at) ASC,
                    created_at ASC,
                    evidence_id ASC
                """,
                (intent_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                loaded = json.loads(str(item.pop("metadata_json")))
            except json.JSONDecodeError:
                loaded = {}
            item["metadata"] = loaded if isinstance(loaded, dict) else {}
            items.append(item)
        return items

    def merge_intents(self, canonical_intent_id: str, duplicate_intent_id: str) -> bool:
        if canonical_intent_id == duplicate_intent_id:
            return True
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            canonical_row = conn.execute(
                "SELECT * FROM intents WHERE intent_id = ?",
                (canonical_intent_id,),
            ).fetchone()
            duplicate_row = conn.execute(
                "SELECT * FROM intents WHERE intent_id = ?",
                (duplicate_intent_id,),
            ).fetchone()
            if canonical_row is None or duplicate_row is None:
                return False
            canonical = dict(canonical_row)
            duplicate = dict(duplicate_row)
            conn.execute(
                """
                DELETE FROM intent_enqueue_claims
                WHERE julianday(expires_at) <= julianday(?)
                """,
                (now,),
            )
            active_claim = conn.execute(
                """
                SELECT intent_id
                FROM intent_enqueue_claims
                WHERE intent_id IN (?, ?)
                LIMIT 1
                """,
                (canonical_intent_id, duplicate_intent_id),
            ).fetchone()
            if active_claim is not None:
                return False
            canonical_payload = json.loads(str(canonical["normalized_json"]))
            duplicate_payload = json.loads(str(duplicate["normalized_json"]))
            canonical_payload["metadata"] = _merge_intent_metadata(
                dict(canonical_payload.get("metadata") or {}),
                dict(duplicate_payload.get("metadata") or {}),
            )
            canonical_state = str(canonical_payload.get("state") or canonical["state"])
            duplicate_state = str(duplicate_payload.get("state") or duplicate["state"])
            canonical_rank = INTENT_STATE_PRIORITY.get(canonical_state, -1)
            duplicate_rank = INTENT_STATE_PRIORITY.get(duplicate_state, -1)
            state_winner = canonical
            if duplicate_rank > canonical_rank:
                canonical_payload["state"] = duplicate_state
                state_winner = duplicate
            merged_intent = ResourceIntent.model_validate(canonical_payload)
            if merged_intent.state in {
                IntentState.ENQUEUED,
                IntentState.REJECTED,
                IntentState.FAILED,
                IntentState.VIEWED,
            }:
                selected_release_id = state_winner["selected_release_id"]
            else:
                selected_release_id = (
                    canonical["selected_release_id"] or duplicate["selected_release_id"]
                )
            duplicate_rows = conn.execute(
                """
                SELECT release_id, site, title, score, confidence, accepted,
                       confirmation_required, release_json, created_at
                FROM release_candidates
                WHERE intent_id = ?
                """,
                (duplicate_intent_id,),
            ).fetchall()
            for row in duplicate_rows:
                data = dict(row)
                try:
                    release_payload = json.loads(str(data["release_json"]))
                except json.JSONDecodeError:
                    release_payload = {}
                if isinstance(release_payload, dict):
                    release_payload["intent_id"] = canonical_intent_id
                conn.execute(
                    """
                    INSERT INTO release_candidates (
                        intent_id,
                        release_id,
                        site,
                        title,
                        score,
                        confidence,
                        accepted,
                        confirmation_required,
                        release_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(intent_id, release_id) DO UPDATE SET
                        site = excluded.site,
                        title = excluded.title,
                        score = excluded.score,
                        confidence = excluded.confidence,
                        accepted = excluded.accepted,
                        confirmation_required = excluded.confirmation_required,
                        release_json = excluded.release_json
                    """,
                    (
                        canonical_intent_id,
                        data["release_id"],
                        data["site"],
                        data["title"],
                        data["score"],
                        data["confidence"],
                        data["accepted"],
                        data["confirmation_required"],
                        _json_dumps(release_payload),
                        data["created_at"],
                    ),
                )
            conn.execute(
                "UPDATE intent_aliases SET intent_id = ?, updated_at = ? WHERE intent_id = ?",
                (canonical_intent_id, now, duplicate_intent_id),
            )
            conn.execute(
                """
                UPDATE intent_source_evidence
                SET intent_id = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (canonical_intent_id, now, duplicate_intent_id),
            )
            conn.execute(
                """
                UPDATE want_search_runs
                SET intent_id = ?
                WHERE intent_id = ?
                """,
                (canonical_intent_id, duplicate_intent_id),
            )
            conn.execute(
                "DELETE FROM release_candidates WHERE intent_id = ?",
                (duplicate_intent_id,),
            )
            conn.execute(
                """
                UPDATE intents
                SET source = ?,
                    raw_text = ?,
                    title = ?,
                    kind = ?,
                    state = ?,
                    normalized_json = ?,
                    selected_release_id = ?,
                    updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    merged_intent.source.value,
                    merged_intent.raw_text,
                    merged_intent.title,
                    merged_intent.kind.value,
                    merged_intent.state.value,
                    _json_dumps(merged_intent.model_dump(mode="json")),
                    selected_release_id,
                    now,
                    canonical_intent_id,
                ),
            )
            conn.execute("DELETE FROM intents WHERE intent_id = ?", (duplicate_intent_id,))
        return True

    def save_ranked_releases(
        self,
        releases: list[RankedRelease],
        *,
        replace_intent_id: str | None = None,
    ) -> None:
        now = _utc_now()
        rows = [_ranked_release_row(ranked, now) for ranked in releases]
        with self._connect() as conn:
            if replace_intent_id is not None:
                if any(ranked.intent_id != replace_intent_id for ranked in releases):
                    raise ValueError("replacement releases must belong to one intent")
                conn.execute(
                    "DELETE FROM release_candidates WHERE intent_id = ?",
                    (replace_intent_id,),
                )
            conn.executemany(_RELEASE_CANDIDATE_UPSERT_SQL, rows)

    def save_want_search_batch(
        self,
        results: list[tuple[ResourceIntent, list[RankedRelease]]],
        *,
        source: str,
        run_id: str | None = None,
        searched_at: datetime | None = None,
        history_payloads: dict[str, dict[str, Any]] | None = None,
    ) -> int:
        """Atomically replace candidates, intent states, and history for a search batch."""
        if not results:
            return 0
        intent_ids = [intent.intent_id for intent, _ in results]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("want search batch contains duplicate intents")
        for intent, ranked in results:
            if any(item.intent_id != intent.intent_id for item in ranked):
                raise ValueError("ranked releases must belong to their batch intent")

        now = _utc_now()
        search_time = (searched_at or _utc_now_datetime()).isoformat()
        candidate_rows = {
            intent.intent_id: [_ranked_release_row(item, now) for item in ranked]
            for intent, ranked in results
        }
        committed = 0
        history_rows: list[tuple[object, ...]] = []
        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for intent, ranked in results:
                current_row = conn.execute(
                    "SELECT * FROM intents WHERE intent_id = ?",
                    (intent.intent_id,),
                ).fetchone()
                if current_row is None:
                    raise ValueError(f"unknown intent: {intent.intent_id}")
                current = dict(current_row)
                current_intent = ResourceIntent.model_validate(
                    json.loads(str(current["normalized_json"]))
                )
                if (
                    current_intent.state
                    in {
                        IntentState.ENQUEUED,
                        IntentState.REJECTED,
                        IntentState.FAILED,
                        IntentState.VIEWED,
                    }
                    or current.get("selected_release_id") is not None
                ):
                    continue
                next_state = _want_search_state(ranked)
                effective_intent = _monotonic_intent(
                    current,
                    current_intent.model_copy(update={"state": next_state}),
                )
                conn.execute(
                    "DELETE FROM release_candidates WHERE intent_id = ?",
                    (intent.intent_id,),
                )
                conn.executemany(
                    _RELEASE_CANDIDATE_UPSERT_SQL,
                    candidate_rows[intent.intent_id],
                )
                conn.execute(
                    """
                    UPDATE intents
                    SET state = ?, normalized_json = ?, updated_at = ?
                    WHERE intent_id = ?
                    """,
                    (
                        effective_intent.state.value,
                        _json_dumps(effective_intent.model_dump(mode="json")),
                        now,
                        intent.intent_id,
                    ),
                )
                best_score = max((item.score for item in ranked), default=None)
                history_payload = {
                    "state": effective_intent.state.value,
                    "title": effective_intent.title,
                }
                diagnostics = (history_payloads or {}).get(intent.intent_id)
                if diagnostics:
                    history_payload.update(
                        redact_payload(
                            {
                                key: diagnostics[key]
                                for key in ("provider_diagnostics", "search_summary")
                                if key in diagnostics
                            }
                        )
                    )
                history_rows.append(
                    (
                        intent.intent_id,
                        run_id,
                        source,
                        search_time,
                        "searched",
                        1,
                        len(ranked),
                        best_score,
                        None,
                        0,
                        None,
                        None,
                        _json_dumps(history_payload),
                    )
                )
                committed += 1
            conn.executemany(_WANT_SEARCH_RUN_INSERT_SQL, history_rows)
        return committed

    def list_release_candidates(self, intent_id: str) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    release_id,
                    intent_id,
                    site,
                    title,
                    score,
                    confidence,
                    accepted,
                    confirmation_required,
                    release_json,
                    created_at
                FROM release_candidates
                WHERE intent_id = ?
                ORDER BY score DESC, confidence DESC, release_id ASC
                """,
                (intent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _initialize(self) -> None:
        with self._connect() as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                  stable_id TEXT PRIMARY KEY,
                  site TEXT NOT NULL,
                  title TEXT NOT NULL,
                  state TEXT NOT NULL,
                  score INTEGER,
                  torrent_hash TEXT,
                  free_window_expires_at TEXT,
                  size_bytes INTEGER,
                  seeders INTEGER,
                  leechers INTEGER,
                  discount TEXT,
                  left_time_minutes INTEGER,
                  score_reasons TEXT,
                  first_seen_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_state ON candidates(state);
                CREATE INDEX IF NOT EXISTS idx_candidates_hash ON candidates(torrent_hash);
                CREATE TABLE IF NOT EXISTS candidate_enqueue_snapshots (
                  stable_id TEXT PRIMARY KEY,
                  torrent_hash TEXT,
                  seeders INTEGER NOT NULL,
                  leechers INTEGER NOT NULL,
                  seed_leecher_ratio REAL NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  published_at TEXT,
                  candidate_age_minutes INTEGER,
                  score INTEGER NOT NULL,
                  score_reasons TEXT NOT NULL,
                  enqueued_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidate_enqueue_snapshots_hash
                  ON candidate_enqueue_snapshots(torrent_hash);
                CREATE TABLE IF NOT EXISTS intents (
                  intent_id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  raw_text TEXT NOT NULL,
                  title TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  state TEXT NOT NULL,
                  normalized_json TEXT NOT NULL,
                  selected_release_id TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intent_enqueue_claims (
                  intent_id TEXT PRIMARY KEY,
                  release_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  acquired_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS release_candidates (
                  intent_id TEXT NOT NULL,
                  release_id TEXT NOT NULL,
                  site TEXT NOT NULL,
                  title TEXT NOT NULL,
                  score INTEGER,
                  confidence REAL,
                  accepted INTEGER NOT NULL,
                  confirmation_required INTEGER NOT NULL,
                  release_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (intent_id, release_id)
                );
                CREATE TABLE IF NOT EXISTS intent_aliases (
                  alias TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_aliases_intent
                  ON intent_aliases(intent_id);
                CREATE TABLE IF NOT EXISTS intent_source_evidence (
                  evidence_id TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL,
                  source TEXT NOT NULL,
                  source_event_id TEXT,
                  source_config_id TEXT,
                  source_label TEXT,
                  requested_at TEXT,
                  raw_text TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_source_evidence_intent
                  ON intent_source_evidence(intent_id);
                CREATE TABLE IF NOT EXISTS torrent_runtime (
                  torrent_hash TEXT PRIMARY KEY,
                  paused_at TEXT,
                  uploaded_bytes INTEGER,
                  downloaded_bytes INTEGER,
                  upspeed_bps INTEGER,
                  dlspeed_bps INTEGER,
                  missing_from_qb_at TEXT,
                  missing_from_qb_reason TEXT,
                  no_upload_since_at TEXT,
                  seen_at TEXT,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intents_state ON intents(state);
                CREATE INDEX IF NOT EXISTS idx_release_candidates_intent
                  ON release_candidates(intent_id);
                CREATE TABLE IF NOT EXISTS scheduler_runs (
                  run_id TEXT PRIMARY KEY,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  status TEXT NOT NULL,
                  command TEXT NOT NULL,
                  config TEXT,
                  execute INTEGER NOT NULL,
                  interval_minutes INTEGER,
                  prune_enabled INTEGER NOT NULL,
                  intent_enabled INTEGER NOT NULL,
                  intent_execute INTEGER NOT NULL,
                  backoff_active INTEGER NOT NULL,
                  backoff_until TEXT,
                  discovered INTEGER,
                  scored INTEGER,
                  accepted INTEGER,
                  enqueued INTEGER,
                  intent_ingested INTEGER,
                  intent_searched INTEGER,
                  intent_ranked INTEGER,
                  intent_enqueue_candidates INTEGER,
                  warning_count INTEGER NOT NULL DEFAULT 0,
                  error TEXT,
                  summary_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scheduler_runs_status
                  ON scheduler_runs(status);
                CREATE INDEX IF NOT EXISTS idx_scheduler_runs_finished_at
                  ON scheduler_runs(finished_at DESC, started_at DESC)
                  WHERE finished_at IS NOT NULL;
                CREATE TABLE IF NOT EXISTS scheduler_leases (
                  lease_name TEXT PRIMARY KEY,
                  owner_id TEXT NOT NULL,
                  acquired_at TEXT NOT NULL,
                  renewed_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduler_triggers (
                  trigger_name TEXT PRIMARY KEY,
                  requested_at TEXT NOT NULL,
                  source TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduler_controls (
                  control_name TEXT PRIMARY KEY,
                  phase TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduler_run_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  event TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  message TEXT,
                  payload_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_scheduler_run_events_run_id
                  ON scheduler_run_events(run_id);
                CREATE TABLE IF NOT EXISTS tracker_backoffs (
                  site TEXT NOT NULL,
                  endpoint TEXT NOT NULL,
                  active INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  until TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  source TEXT,
                  run_id TEXT,
                  PRIMARY KEY (site, endpoint)
                );
                CREATE TABLE IF NOT EXISTS tracker_api_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  site TEXT NOT NULL,
                  endpoint TEXT NOT NULL,
                  event TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  run_id TEXT,
                  status_code INTEGER,
                  api_code TEXT,
                  rate_limited INTEGER NOT NULL,
                  message TEXT,
                  request_json TEXT,
                  response_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tracker_api_events_site_endpoint
                  ON tracker_api_events(site, endpoint);
                CREATE INDEX IF NOT EXISTS idx_tracker_api_events_event
                  ON tracker_api_events(event);
                CREATE TABLE IF NOT EXISTS source_cursors (
                  source TEXT PRIMARY KEY,
                  cursor TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS want_search_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  intent_id TEXT NOT NULL,
                  run_id TEXT,
                  source TEXT NOT NULL,
                  searched_at TEXT NOT NULL,
                  status TEXT NOT NULL,
                  search_enabled INTEGER NOT NULL,
                  results_count INTEGER NOT NULL,
                  best_score INTEGER,
                  selected_release_id TEXT,
                  backoff_active INTEGER NOT NULL,
                  backoff_until TEXT,
                  message TEXT,
                  payload_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_want_search_runs_intent
                  ON want_search_runs(intent_id);
                """
            )
            self._migrate_candidates(conn)
            self._migrate_release_candidates(conn)
            self._migrate_confirmed_intents(conn)
            self._migrate_torrent_runtime(conn)

    @contextmanager
    def _connect(self, *, row_factory: Any | None = None) -> Iterator[sqlite3.Connection]:
        if not self.read_only:
            _ensure_private_file(self.path)
            _ensure_sqlite_sidecars_private(self.path)
        lock_path = _sqlite_access_lock_path(self.path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = _open_private_file(lock_path)
        with os.fdopen(lock_fd, "a+b") as access_lock:
            fcntl.flock(access_lock.fileno(), fcntl.LOCK_SH)
            target: str | Path = self.path
            if self.read_only:
                target = f"file:{self.path.resolve()}?mode=ro&cache=private"
            conn = sqlite3.connect(
                target,
                timeout=SQLITE_TIMEOUT_SECONDS,
                uri=self.read_only,
            )
            try:
                conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
                if self.read_only:
                    conn.execute("PRAGMA query_only=ON")
                else:
                    _ensure_sqlite_sidecars_private(self.path)
                if row_factory is not None:
                    conn.row_factory = row_factory
                yield conn
                if not self.read_only:
                    conn.commit()
            except Exception:
                if not self.read_only:
                    conn.rollback()
                raise
            finally:
                conn.close()
                fcntl.flock(access_lock.fileno(), fcntl.LOCK_UN)

    def _migrate_release_candidates(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'release_candidates'
            """
        ).fetchone()
        sql = row[0] if row is not None else ""
        if "PRIMARY KEY (intent_id, release_id)" in sql:
            return
        conn.executescript(
            """
            ALTER TABLE release_candidates RENAME TO release_candidates_old;
            CREATE TABLE release_candidates (
              intent_id TEXT NOT NULL,
              release_id TEXT NOT NULL,
              site TEXT NOT NULL,
              title TEXT NOT NULL,
              score INTEGER,
              confidence REAL,
              accepted INTEGER NOT NULL,
              confirmation_required INTEGER NOT NULL,
              release_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (intent_id, release_id)
            );
            INSERT INTO release_candidates (
              intent_id,
              release_id,
              site,
              title,
              score,
              confidence,
              accepted,
              confirmation_required,
              release_json,
              created_at
            )
            SELECT
              intent_id,
              release_id,
              site,
              title,
              score,
              confidence,
              accepted,
              confirmation_required,
              release_json,
              created_at
            FROM release_candidates_old;
            DROP TABLE release_candidates_old;
            CREATE INDEX IF NOT EXISTS idx_release_candidates_intent
              ON release_candidates(intent_id);
            """
        )

    def _migrate_confirmed_intents(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT intent_id, normalized_json
            FROM intents
            WHERE state = ?
            """,
            ("confirmed",),
        ).fetchall()
        if not rows:
            return
        now = _utc_now()
        for intent_id, normalized_json in rows:
            try:
                normalized = json.loads(str(normalized_json))
            except json.JSONDecodeError:
                normalized = {}
            if isinstance(normalized, dict):
                normalized["state"] = IntentState.CONFIRMATION_REQUIRED.value
            conn.execute(
                """
                UPDATE intents
                SET state = ?, normalized_json = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    IntentState.CONFIRMATION_REQUIRED.value,
                    _json_dumps(normalized),
                    now,
                    intent_id,
                ),
            )

    def _migrate_candidates(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()}
        additions = {
            "free_window_expires_at": "TEXT",
            "size_bytes": "INTEGER",
            "seeders": "INTEGER",
            "leechers": "INTEGER",
            "discount": "TEXT",
            "left_time_minutes": "INTEGER",
            "score_reasons": "TEXT",
        }
        for column, column_type in additions.items():
            if column in columns:
                continue
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {column} {column_type}")

    def _migrate_torrent_runtime(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(torrent_runtime)").fetchall()}
        additions = {
            "uploaded_bytes": "INTEGER",
            "downloaded_bytes": "INTEGER",
            "upspeed_bps": "INTEGER",
            "dlspeed_bps": "INTEGER",
            "missing_from_qb_at": "TEXT",
            "missing_from_qb_reason": "TEXT",
            "no_upload_since_at": "TEXT",
            "seen_at": "TEXT",
        }
        for column, column_type in additions.items():
            if column in columns:
                continue
            conn.execute(f"ALTER TABLE torrent_runtime ADD COLUMN {column} {column_type}")


def _empty_site_history_entry(
    site: str,
    window_days: int,
    min_samples: int,
) -> dict[str, Any]:
    return {
        "site": site,
        "window_days": max(window_days, 1),
        "min_samples": max(min_samples, 1),
        "samples": 0,
        "productive_count": 0,
        "no_upload_count": 0,
        "missing_count": 0,
        "paused_count": 0,
        "total_uploaded_gb": 0.0,
        "upload_ratios": [],
        "rate_limited_events": 0,
        "active_backoffs": 0,
    }


def _site_history_summary(entry: dict[str, Any]) -> dict[str, Any]:
    samples = int(entry["samples"])
    min_samples = int(entry["min_samples"])
    productive = int(entry["productive_count"])
    no_upload = int(entry["no_upload_count"])
    missing = int(entry["missing_count"])
    paused = int(entry["paused_count"])
    rate_limited_events = int(entry.get("rate_limited_events") or 0)
    active_backoffs = int(entry.get("active_backoffs") or 0)
    upload_ratios = [float(value) for value in entry.get("upload_ratios", [])]
    throttle_penalty = min(
        0.10,
        (rate_limited_events * 0.02) + (active_backoffs * 0.05),
    )
    applied = samples >= min_samples
    if applied:
        score = _clamp_float(
            0.5
            + ((productive / samples) * 0.35)
            - ((no_upload / samples) * 0.20)
            - ((missing / samples) * 0.20)
            - ((paused / samples) * 0.10)
            - throttle_penalty
        )
        confidence = "sufficient"
    else:
        score = 0.5
        confidence = "low_sample"
    return {
        "site": entry["site"],
        "window_days": entry["window_days"],
        "samples": samples,
        "min_samples": min_samples,
        "applied": applied,
        "confidence": confidence,
        "score": round(score, 2),
        "productive_count": productive,
        "no_upload_count": no_upload,
        "missing_count": missing,
        "paused_count": paused,
        "total_uploaded_gb": round(float(entry["total_uploaded_gb"]), 2),
        "avg_upload_ratio": round(sum(upload_ratios) / len(upload_ratios), 2)
        if upload_ratios
        else None,
        "rate_limited_events": rate_limited_events,
        "active_backoffs": active_backoffs,
        "throttle_penalty": round(throttle_penalty, 2),
    }


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clamp_float(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _utc_now() -> str:
    return _utc_now_datetime().isoformat()


def _utc_now_datetime() -> datetime:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence_id(
    source: str,
    source_config_id: str | None,
    source_event_id: str | None,
    raw_text: str,
) -> str:
    identity = source_event_id or raw_text
    return f"{source}:{source_config_id or ''}:{identity}"


def _merge_intent_metadata(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
) -> dict[str, Any]:
    merged = {**canonical, **duplicate}
    external_ids = {
        **_dict_value(canonical.get("external_ids")),
        **_dict_value(duplicate.get("external_ids")),
    }
    if external_ids:
        merged["external_ids"] = external_ids
    return merged


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _preserved_value(
    current: dict[str, Any] | None,
    key: str,
    value: Any,
) -> Any:
    if value is _UNSET:
        return current.get(key) if current is not None else None
    return value


def _candidate_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["score_reasons"] = _json_loads_list(data.get("score_reasons"))
    return data


def _enqueue_snapshot_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["score_reasons"] = _json_loads_list(data.get("score_reasons")) or []
    return data


def _json_loads_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return None
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, list):
        return None
    return [str(item) for item in loaded]


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    from datetime import UTC

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_paused_state(state: str) -> bool:
    normalized = state.strip().lower()
    return normalized.startswith("paused") or normalized.startswith("stopped")


def _recent_upload_gb(runtime: dict[str, Any] | None, uploaded_bytes: int) -> float | None:
    if runtime is None:
        return None
    previous = runtime.get("uploaded_bytes")
    if not isinstance(previous, int):
        return None
    if uploaded_bytes < previous:
        return 0.0
    return (uploaded_bytes - previous) / GIB


def _no_upload_since_at(
    runtime: dict[str, Any] | None,
    *,
    torrent_added_at: datetime,
    uploaded_bytes: int,
    recent_upload_gb: float | None,
) -> datetime | None:
    if uploaded_bytes <= 0:
        existing = (
            _parse_datetime(runtime.get("no_upload_since_at"))
            if runtime is not None
            else None
        )
        if existing is not None:
            return min(existing, torrent_added_at)
        return torrent_added_at
    if runtime is None or recent_upload_gb is None:
        return None
    if recent_upload_gb > 0:
        return None
    existing = _parse_datetime(runtime.get("no_upload_since_at"))
    if existing is not None:
        return existing
    seen_at = _parse_datetime(runtime.get("seen_at"))
    return seen_at or _utc_now_datetime()


def _monotonic_values(
    current: dict[str, Any] | None,
    incoming_state: LifecycleState,
    incoming_score: int | None,
    incoming_torrent_hash: str | None,
) -> tuple[str, int | None, str | None]:
    if current is None:
        return incoming_state.value, incoming_score, incoming_torrent_hash

    current_state_value = str(current["state"])
    current_rank = STATE_PRIORITY.get(current_state_value, -1)
    incoming_rank = STATE_PRIORITY.get(incoming_state.value, -1)

    if current_rank > incoming_rank:
        return (
            current_state_value,
            current["score"],
            current["torrent_hash"],
        )

    return (
        incoming_state.value,
        incoming_score if incoming_score is not None else current["score"],
        incoming_torrent_hash if incoming_torrent_hash is not None else current["torrent_hash"],
    )


def _monotonic_intent(
    current: dict[str, Any] | None,
    incoming: ResourceIntent,
) -> ResourceIntent:
    if current is None:
        return incoming
    current_payload = json.loads(str(current["normalized_json"]))
    current_intent = ResourceIntent.model_validate(current_payload)
    current_rank = INTENT_STATE_PRIORITY.get(current_intent.state.value, -1)
    incoming_rank = INTENT_STATE_PRIORITY.get(incoming.state.value, -1)
    if current_rank <= incoming_rank:
        return incoming
    return incoming.model_copy(
        update={
            "state": current_intent.state,
            "metadata": _merge_intent_metadata(
                current_intent.metadata,
                incoming.metadata,
            ),
        }
    )


def _ranked_release_row(ranked: RankedRelease, created_at: str) -> tuple[object, ...]:
    return (
        ranked.release.release_id,
        ranked.intent_id,
        ranked.release.site,
        ranked.release.title,
        ranked.score,
        ranked.confidence,
        int(ranked.accepted),
        int(ranked.confirmation_required),
        _json_dumps(ranked.model_dump(mode="json")),
        created_at,
    )


def _want_search_state(ranked: list[RankedRelease]) -> IntentState:
    if not ranked or ranked[0].confirmation_required:
        return IntentState.CONFIRMATION_REQUIRED
    return IntentState.SEARCHED


def _sqlite_access_lock_path(path: Path) -> Path:
    return Path(f"{path}.access.lock")


def _open_private_file(path: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except Exception:
        os.close(fd)
        raise
    return fd


def _ensure_private_file(path: Path) -> None:
    fd = _open_private_file(path)
    os.close(fd)


def _ensure_sqlite_sidecars_private(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        _ensure_existing_private_file(Path(f"{path}{suffix}"))


def _ensure_existing_private_file(path: Path) -> None:
    flags = os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return
    try:
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
