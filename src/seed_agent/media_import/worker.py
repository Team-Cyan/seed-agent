"""Independent media clock and single process lease; seed never calls this loop."""

import json
import sqlite3
import time
import uuid
from pathlib import Path

from seed_agent.config_views import MediaConfigGuard, load_view
from seed_agent.media_import.commands import baseline, command_store
from seed_agent.media_import.runtime import build_engine, run_engine
from seed_agent.media_import.store import bounded_lock
from seed_agent.media_import.subtitles.jobs import SubtitleJobs


def worker_lease(path):
    _, store = command_store(path)
    return bounded_lock(Path(str(store.path) + ".worker.lock"), exclusive=True, timeout=0)


def recover_commands(path):
    _, store = command_store(path)
    with store._connect() as conn:
        # A dead process may have published before losing its acknowledgement.
        # Preserve receipts; never automatically replay such a manual command.
        conn.execute(
            "UPDATE media_commands SET status='interrupted',claim_token=NULL,"
            "result_json=? WHERE status='running'",
            (json.dumps({"error": "worker restarted; inspect receipts before retry"}),),
        )


def claim(path):
    view, store = command_store(path)
    with store._connect(row_factory=sqlite3.Row) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM media_commands WHERE status='queued' ORDER BY created LIMIT 1"
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        token = uuid.uuid4().hex
        conn.execute(
            "UPDATE media_commands SET status='running',claimed=?,claim_token=? WHERE id=?",
            (time.time(), token, result["id"]),
        )
        result["claim_token"] = token
    return result


def execute_command(path, command, *, lifecycle=None):
    engine, _ = build_engine(path)
    view = engine.config_view
    if (
        command["epoch"] != engine.store_epoch
        or command["config_source"] != view.source_id
        or command["config_revision"] != view.effective_revision
    ):
        raise ValueError("stale command configuration/restore epoch; submit again")
    modes = json.loads(command["modes_json"])
    engine.config_guard = MediaConfigGuard(view, modes=modes)
    # Planning and recovery must obey pinned modes as well as final publication gates.
    for kind, mode in modes.items():
        setattr(engine.config, kind + "_policy", mode)
    payload = json.loads(command["payload_json"])
    action = command["action"]
    if payload.get("_baseline") != baseline(engine.store, action, payload):
        raise ValueError("media command source/plan baseline changed; submit again")
    if action in {"scan", "subtitles"}:
        return run_engine(
            engine,
            path,
            profile=payload.get("profile"),
            force=action == "scan",
            scan=action == "scan",
            refresh=action == "subtitles",
            lifecycle=lifecycle,
        )
    if action == "review":
        return engine.review(
            payload["source_id"],
            payload["mapping"],
            fingerprint=payload["fingerprint"],
            ready=payload.get("ready", False),
            repair=payload.get("repair", False),
        )
    if action == "subtitle-select":
        return SubtitleJobs(engine).select(payload["job_id"], payload["candidate_id"])
    if action == "series-preview":
        return engine.series_preview(payload["source_id"], payload["mapping"])
    if action == "series-review":
        return engine.series_apply(int(payload["preview_id"]))
    raise ValueError("unsupported command")


def process_one(path, *, lifecycle=None):
    command = claim(path)
    if command is None:
        return None
    _, store = command_store(path)
    try:
        result = (
            execute_command(path, command, lifecycle=lifecycle)
            if lifecycle
            else execute_command(path, command)
        )
        state = "complete"
    except Exception as exc:
        result, state = (
            {
                "error_type": type(exc).__name__,
                "error": "media command failed; inspect domain status",
            },
            "failed",
        )
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > 128_000:
        encoded = json.dumps(
            {"status": state, "detail": "result exceeds limit; consult paginated media state"}
        )
    with store._connect() as conn:
        conn.execute(
            "UPDATE media_commands SET status=?,result_json=? WHERE id=? "
            "AND claim_token=? AND epoch=(SELECT epoch FROM media_control WHERE id=1)",
            (state, encoded, command["id"], command["claim_token"]),
        )
    return {"command_id": command["id"], "status": state, "result": result}


def serve(path, *, max_cycles=None, poll_seconds=2, stop=None):
    cycles = 0
    next_scan = 0
    from seed_agent.media_import.role_health import MediaWorkerLifecycle

    with worker_lease(path):
        view, store = command_store(path)
        with MediaWorkerLifecycle(store, view) as lifecycle:
            lifecycle.phase("recovery", deadline_seconds=60)
            recover_commands(path)
            while not stop or not stop.is_set():
                view = load_view(path, "media", require_identity=True)
                lifecycle.apply(view)
                if view.config.media_import.enabled:
                    engine, _ = build_engine(path)
                    # Deadlines describe business progress independently from the
                    # background heartbeat; a live but stuck provider is unhealthy.
                    deadline = min(
                        86400,
                        max(
                            600,
                            engine.config.inventory_timeout_seconds * (len(engine.profiles()) + 1)
                            + engine.config.work_batch_size * 240
                            + 600,
                        ),
                    )
                    lifecycle.phase("command", deadline_seconds=deadline)
                    process_one(path, lifecycle=lifecycle)
                    lifecycle.progress(completed=1, total=1)
                    if time.monotonic() >= next_scan:
                        lifecycle.phase("scan-enrichment", deadline_seconds=deadline)
                        run_engine(engine, path, lifecycle=lifecycle)
                        lifecycle.progress(completed=1, total=1)
                        next_scan = time.monotonic() + min(30, engine.config.interval_seconds)
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    return
                lifecycle.phase("idle", deadline_seconds=max(60, poll_seconds + 30))
                if stop:
                    stop.wait(poll_seconds)
                else:
                    time.sleep(poll_seconds)
