"""Fenced worker lifecycle and bounded, read-only media-role observations.

The caller holds worker_lease for the lifecycle's entire lifetime. A heartbeat
shows process liveness only; phase deadlines are independent business-work bounds.
No health query initializes stores, acquires application locks, scans roots or
calls providers. SQLite may create its native WAL coordination sidecars for a
read-only connection; live WAL must remain visible. Container restart
policy/exhaustion is outside this observation.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

from seed_agent import __version__
from seed_agent.config_views import load_view
from seed_agent.media_import.runtime import media_state_path
from seed_agent.media_import.store import MediaStore, validate_schema
from seed_agent.runtime_identity import runtime_identity_observation, verify_runtime_identity

WORKER_ROLE = "media-worker"
MAX_STATUS_BYTES = 32_768
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _seconds(value, *, maximum=86_400):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError("duration must be positive, finite and bounded")
    return float(value)


def _decode(value):
    if not isinstance(value, str) or len(value.encode()) > MAX_STATUS_BYTES:
        raise ValueError("invalid runtime observation")
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("invalid runtime observation")
    return result


def _counter(completed, total):
    for value in (completed, total):
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
            raise ValueError("progress counters must be bounded nonnegative integers")
    if completed is not None and total is not None and completed > total:
        raise ValueError("progress exceeds total")
    return {"completed": completed, "total": total}


class MediaWorkerLifecycle:
    """One worker instance; all writes fence its token and original restore epoch.

    Start only under the process worker lease. Call apply after each successful
    config reload. Declare a finite phase before synchronous work; progress never
    renews the deadline. Stop/failure do not imply domain work completed.
    """

    def __init__(self, store, view, *, heartbeat_seconds=10.0, clock=time.time):
        if view.role != "media":
            raise ValueError("worker lifecycle requires a media config view")
        if store.read_only:
            raise ValueError("worker lifecycle requires a writable media store")
        self.store, self.view, self.clock = store, view, clock
        self.heartbeat_seconds = _seconds(heartbeat_seconds, maximum=30)
        self.instance_id, self.epoch = uuid.uuid4().hex, store.epoch()
        self._stop = threading.Event()
        self._thread = None
        self._mutex = threading.RLock()
        self._background_failed = False
        self._started = False
        self._last_heartbeat_success = time.monotonic()

    def _write(self, changes, *, start=False, applied=None):
        with self._mutex, self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            epoch = conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()
            if not epoch or epoch[0] != self.epoch:
                raise ValueError("worker restore epoch changed; restart required")
            row = conn.execute(
                "SELECT payload_json FROM media_runtime_status WHERE role=?", (WORKER_ROLE,)
            ).fetchone()
            current = _decode(row[0]) if row else {}
            if not start and (
                current.get("instance_id") != self.instance_id
                or current.get("state_epoch") != self.epoch
                or current.get("status") in {"stopped", "failed"}
            ):
                raise ValueError("worker lifecycle superseded or terminal")
            current = changes if start else {**current, **changes}
            conn.execute(
                "INSERT INTO media_runtime_status VALUES(?,?) "
                "ON CONFLICT(role) DO UPDATE SET payload_json=excluded.payload_json",
                (WORKER_ROLE, json.dumps(current, sort_keys=True)),
            )
            if applied is not None:
                observation = {
                    **applied,
                    "state_epoch": self.epoch,
                    "media_schema_version": self.store.schema_version,
                }
                conn.execute(
                    "INSERT INTO media_runtime_status VALUES('media',?) "
                    "ON CONFLICT(role) DO UPDATE SET payload_json=excluded.payload_json",
                    (json.dumps(observation, sort_keys=True),),
                )
            return current

    def start(self):
        if self._started:
            raise ValueError("worker lifecycle already started")
        now = self.clock()
        self._write(
            {
                **self.view.observation(),
                "role": "media",
                "instance_id": self.instance_id,
                "state_epoch": self.epoch,
                "media_schema_version": self.store.schema_version,
                "status": "starting",
                "started_at": now,
                "heartbeat_at": now,
                "last_progress_at": now,
                "phase": "starting",
                "phase_started_at": now,
                "phase_deadline_at": now + 60,
                "progress": _counter(None, None),
                "error_type": None,
            },
            start=True,
            applied=self.view.observation(),
        )
        self._started = True
        self._thread = threading.Thread(target=self._beat, name="media-liveness", daemon=True)
        self._thread.start()
        return self

    def _beat(self):
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self.heartbeat()
                self._last_heartbeat_success = time.monotonic()
            except Exception as exc:
                transient = isinstance(exc, TimeoutError) or (
                    isinstance(exc, sqlite3.OperationalError)
                    and any(word in str(exc).lower() for word in ("locked", "busy"))
                )
                # A normal bounded writer transaction can outlast one beat. Retry
                # only within the liveness horizon; deadlines never move with it.
                if transient and time.monotonic() - self._last_heartbeat_success < 60:
                    continue
                self._background_failed = True
                try:
                    self._write(
                        {
                            "status": "failed",
                            "finished_at": self.clock(),
                            "error_type": type(exc).__name__,
                        }
                    )
                except OSError, ValueError, sqlite3.Error:
                    # Locked/unavailable state cannot be repaired by a heartbeat.
                    # The old observation expires; never overwrite a new epoch.
                    pass
                return

    def _ensure_background(self):
        if self._background_failed:
            raise RuntimeError("media lifecycle heartbeat failed; restart required")

    def heartbeat(self):
        self._ensure_background()
        return self._write({"heartbeat_at": self.clock()})

    def apply(self, view):
        self._ensure_background()
        if view.role != "media" or view.source_id != self.view.source_id:
            raise ValueError("worker configuration source changed; restart required")
        observation = view.observation()
        self._write({**observation, "heartbeat_at": self.clock()}, applied=observation)
        self.view = view
        return observation

    def phase(self, name, *, deadline_seconds, completed=None, total=None):
        self._ensure_background()
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("phase must be a bounded diagnostic identifier")
        duration, now = _seconds(deadline_seconds), self.clock()
        return self._write(
            {
                "status": "idle" if name == "idle" else "running",
                "phase": name,
                "phase_started_at": now,
                "phase_deadline_at": now + duration,
                "last_progress_at": now,
                "heartbeat_at": now,
                "progress": _counter(completed, total),
            }
        )

    def progress(self, *, completed, total=None):
        self._ensure_background()
        return self._write(
            {"progress": _counter(completed, total), "last_progress_at": self.clock()}
        )

    def _finish(self, status, error_type=None, *, sqlite_error=None):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        now = self.clock()
        changes = {
            "status": status,
            "finished_at": now,
            "heartbeat_at": now,
            "error_type": error_type,
        }
        if isinstance(sqlite_error, sqlite3.Error):
            changes.update(
                sqlite_errorcode=getattr(sqlite_error, "sqlite_errorcode", None),
                sqlite_errorname=getattr(sqlite_error, "sqlite_errorname", None),
            )
        return self._write(changes)

    def stopped(self):
        return self._finish("stopped")

    def failed(self, exc):
        name = type(exc).__name__
        name = name if _NAME.fullmatch(name) else "Exception"
        observation = {"error_type": name}
        if isinstance(exc, sqlite3.Error):
            code = getattr(exc, "sqlite_errorcode", None)
            error_name = getattr(exc, "sqlite_errorname", None)
            if type(code) is int:
                observation["sqlite_errorcode"] = code
            if isinstance(error_name, str) and re.fullmatch(r"SQLITE_[A-Z0-9_]{1,64}", error_name):
                observation["sqlite_errorname"] = error_name
        # Database status can fail too or be replaced by the next process startup.
        # Retain safe extended codes in container logs without exception text.
        logging.getLogger(__name__).error("media_worker_failure %s", json.dumps(observation))
        return self._finish("failed", name, sqlite_error=exc)

    def __enter__(self):
        return self.start()

    def __exit__(self, kind, exc, traceback):
        try:
            self.failed(exc) if exc is not None else self.stopped()
        except OSError, ValueError, sqlite3.Error:
            # A restored/new worker owns the row. Never overwrite its timeline;
            # preserve an existing domain exception when status cannot be written.
            if exc is None:
                raise
        return False


def _age(value, now):
    if type(value) not in (float, int) or not math.isfinite(value) or value > now + 5:
        raise ValueError("invalid runtime timestamp")
    return max(0.0, now - value)


def _read_state(path):
    verify_runtime_identity()
    # Avoid MediaStore._connect: its access-lock creation/chmod is a writer.
    # SQLite-native WAL/SHM coordination may occur; do not use immutable=1, which
    # hides uncheckpointed live observations.
    if path.is_symlink() or not path.is_file():
        raise ValueError("media state missing or unsafe")
    with closing(
        sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=0.1)
    ) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=100")
        deadline = time.monotonic() + 0.25
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        conn.execute("BEGIN")
        validate_schema(conn)
        row = conn.execute("SELECT epoch,schema_version FROM media_control WHERE id=1").fetchone()
        if not row or row[1] != MediaStore.schema_version:
            raise ValueError("media schema/epoch invalid")
        rows = conn.execute(
            "SELECT role,payload_json FROM media_runtime_status "
            "WHERE role IN ('media','media-worker')"
        ).fetchall()
        status = {role: _decode(payload) for role, payload in rows}
        # Bounded output, not a list of arbitrary command payloads/secret values.
        queue = dict(
            conn.execute("SELECT status,COUNT(*) FROM media_commands GROUP BY status LIMIT 16")
        )
        oldest = conn.execute(
            "SELECT MIN(created) FROM media_commands WHERE status='queued'"
        ).fetchone()[0]
    return row[0], status, {"counts": queue, "oldest_queued_at": oldest}


def media_role_status(config_path: Path, *, max_staleness_seconds=60.0, now=None):
    """Return bounded diagnostics. `healthy` is the healthcheck exit decision.

    Fail closed for absent/invalid config/state, stale/wrong instance observations,
    config drift, restore, terminal workers, and expired declared work deadlines.
    This does not prove provider success, hardlink compatibility or client playback.
    """
    maximum = _seconds(max_staleness_seconds)
    now = time.time() if now is None else now
    result = {
        "role": "media",
        "healthy": False,
        "checks": {},
        "configured": None,
        "applied": None,
        "worker": None,
        "queue": None,
        "restart_budget": "unavailable",
    }
    try:
        view = load_view(Path(config_path), "media", require_identity=True)
        result["configured"] = view.observation()
        result["checks"]["configuration"] = True
    except Exception as exc:
        result["checks"]["configuration"] = False
        result["error"] = {"code": "invalid_configuration", "type": type(exc).__name__}
        return result
    try:
        epoch, observations, queue = _read_state(media_state_path(view))
        result["process_identity"] = runtime_identity_observation()
        result["state_epoch"] = epoch
        result["media_schema_version"] = MediaStore.schema_version
        result["checks"]["state"] = True
        applied, worker = observations.get("media"), observations.get(WORKER_ROLE)
        result.update(applied=applied, worker=worker, queue=queue)
        queue["oldest_queued_age_seconds"] = (
            _age(queue["oldest_queued_at"], now) if queue["oldest_queued_at"] is not None else None
        )
        checks = result["checks"]
        checks["worker_observed"] = bool(worker)
        checks["applied_observed"] = bool(applied)
        for name, observation in (("applied", applied), ("worker", worker)):
            checks[name + "_configuration"] = bool(observation) and all(
                observation.get(key) == value
                for key, value in {
                    "config_source_id": view.source_id,
                    "full_revision": view.full_revision,
                    "effective_revision": view.effective_revision,
                    "applied_revision": view.effective_revision,
                    "state_epoch": epoch,
                    "media_schema_version": MediaStore.schema_version,
                    "schema_version": result["configured"]["schema_version"],
                    "application_version": __version__,
                    "image_digest": result["configured"]["image_digest"],
                }.items()
            )
        if worker:
            result["heartbeat_age_seconds"] = _age(worker.get("heartbeat_at"), now)
            result["progress_age_seconds"] = _age(worker.get("last_progress_at"), now)
            deadline = worker.get("phase_deadline_at")
            checks["worker_running"] = worker.get("status") in {"starting", "running", "idle"}
            checks["liveness"] = result["heartbeat_age_seconds"] <= maximum
            checks["phase_deadline"] = (
                type(deadline) in (float, int)
                and math.isfinite(deadline)
                and now <= deadline <= now + 86_400 + 5
            )
        result["healthy"] = all(checks.values())
    except Exception as exc:
        result["checks"]["state"] = False
        result["error"] = {"code": "invalid_media_state", "type": type(exc).__name__}
    return result
