"""Short durable command submission; no provider, mount scan or inline execution."""

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from seed_agent.config_views import load_view
from seed_agent.media_import.runtime import media_state_path
from seed_agent.media_import.store import MediaStore

ACTIONS = {
    "scan",
    "subtitles",
    "subtitle-search",
    "review",
    "subtitle-select",
    "series-preview",
    "series-review",
}
MAX_PENDING = 100
MAX_PAYLOAD = 32_000


def baseline(store, action, payload):
    if action in {"scan", "subtitles"}:
        return None
    with store._connect() as conn:
        source_id = payload.get("source_id")
        evidence = []
        if action == "subtitle-select":
            found = conn.execute(
                "SELECT source_id,generation,payload_json,plan_revision,target "
                "FROM media_subtitle_jobs WHERE id=?",
                (payload.get("job_id"),),
            ).fetchone()
            if not found:
                raise ValueError("unknown subtitle job")
            source_id = found[0]
            evidence.append(found)
        if action == "series-review":
            found = conn.execute(
                "SELECT payload_json FROM media_events WHERE id=? "
                "AND event='series_review_preview'",
                (payload.get("preview_id"),),
            ).fetchone()
            if not found:
                raise ValueError("unknown series preview")
            evidence.append(found)
        else:
            for sql in [
                "SELECT fingerprint,generation,missing_count,status "
                "FROM media_source_files WHERE id=?",
                "SELECT revision,target,status FROM media_import_jobs WHERE source_id=?",
                "SELECT revision,fingerprint FROM media_review_decisions WHERE source_id=?",
            ]:
                record = conn.execute(sql, (source_id,)).fetchone()
                if action == "subtitle-search":
                    if sql.startswith("SELECT fingerprint") and (
                        not record
                        or record[0] != payload["fingerprint"]
                        or record[1] != payload["generation"]
                        or record[2]
                        or record[3] != "imported"
                    ):
                        raise ValueError("subtitle source baseline changed")
                    if sql.startswith("SELECT revision,target") and (
                        not record or record[2] != "imported"
                    ):
                        raise ValueError("subtitle source is not imported")
                evidence.append(record)
        return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def command_store(path: Path, *, read_only=False):
    view = load_view(path, "media")
    return view, MediaStore(media_state_path(view), initialize=False, read_only=read_only)


def submit(path: Path, action, payload=None, *, execute=False):
    if type(execute) is not bool:
        raise ValueError("execute must be boolean")
    if action not in ACTIONS:
        raise ValueError("unknown media command")
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("media command body must be an object")
    if any(key.startswith("_") for key in payload):
        raise ValueError("reserved media command field")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_PAYLOAD:
        raise ValueError("media command body exceeds limit")
    if action == "subtitle-search":
        if set(payload) != {"source_id", "generation", "fingerprint"}:
            raise ValueError("subtitle search requires exact source ID/generation/fingerprint")
        if (
            not isinstance(payload["source_id"], str)
            or type(payload["generation"]) is not int
            or payload["generation"] < 1
            or not isinstance(payload["fingerprint"], str)
        ):
            raise ValueError("invalid subtitle source fence")
    view, store = command_store(path)
    if not view.config.media_import.enabled:
        raise ValueError("media is disabled")
    payload = {**payload, "_baseline": baseline(store, action, payload)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    modes = {
        kind: getattr(view.config.media_import, kind + "_policy") if execute else "preview"
        for kind in ["import", "subtitle", "reconcile"]
    }
    epoch = store.epoch()
    key = hashlib.sha256(
        json.dumps(
            [action, encoded, modes, view.source_id, view.effective_revision, epoch, execute],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT id,status FROM media_commands WHERE coalesce_key=? "
            "AND status IN ('queued','running') ORDER BY created LIMIT 1",
            (key,),
        ).fetchone()
        if prior:
            return {"command_id": prior[0], "status": prior[1], "coalesced": True}
        if (
            conn.execute(
                "SELECT COUNT(*) FROM media_commands WHERE status IN ('queued','running')"
            ).fetchone()[0]
            >= MAX_PENDING
        ):
            raise ValueError("media command queue is full")
        command_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO media_commands(id,coalesce_key,action,payload_json,config_source,"
            "config_revision,epoch,modes_json,status,created) VALUES(?,?,?,?,?,?,?,?,'queued',?)",
            (
                command_id,
                key,
                action,
                encoded,
                view.source_id,
                view.effective_revision,
                epoch,
                json.dumps(modes),
                time.time(),
            ),
        )
    return {"command_id": command_id, "status": "queued", "coalesced": False}


def status(path, command_id=None, *, limit=50):
    _, store = command_store(path, read_only=True)
    with store._connect(row_factory=sqlite3.Row) as conn:
        if command_id:
            records = conn.execute(
                "SELECT * FROM media_commands WHERE id=?", (command_id,)
            ).fetchall()
        else:
            records = conn.execute(
                "SELECT * FROM media_commands ORDER BY created DESC LIMIT ?",
                (min(100, max(1, limit)),),
            ).fetchall()
    return [
        {
            "id": row["id"],
            "action": row["action"],
            "status": row["status"],
            "created": row["created"],
            "claimed": row["claimed"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }
        for row in records
    ]
