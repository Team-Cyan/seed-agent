"""Short durable command submission; no provider, mount scan or inline execution."""

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from seed_agent.config_views import load_view
from seed_agent.media_import.runtime import media_state_path
from seed_agent.media_import.store import MediaStore

ACTIONS = {
    "scan",
    "subtitles",
    "subtitle-search",
    "subtitle-import",
    "review",
    "subtitle-select",
    "series-preview",
    "series-review",
    "featurette-preview",
    "featurette-publish",
    "variant-preview",
    "variant-switch",
    "completion-confirm",
}
MAX_PENDING = 100
MAX_PAYLOAD = 32_000


def baseline(store, action, payload, *, connection=None):
    expected = payload.get("_expected_sources")
    prior_baseline = payload.get("_baseline")
    if expected is None and isinstance(prior_baseline, dict):
        expected = prior_baseline.get("source_fences")
    if action in {"scan", "subtitles"} and not expected:
        return None
    with nullcontext(connection) if connection is not None else store._connect() as conn:
        source_id = payload.get("source_id")
        evidence = []
        if expected:
            for item in expected:
                evidence.append(
                    conn.execute(
                        "SELECT s.generation,s.fingerprint,s.missing_count,s.status,"
                        "(SELECT MAX(generation) FROM media_source_files "
                        "WHERE profile=s.profile AND path=s.path) "
                        "FROM media_source_files s WHERE s.id=?",
                        (item["source_id"],),
                    ).fetchone()
                )
        if action == "variant-switch":
            found = conn.execute(
                "SELECT payload_json FROM media_events WHERE id=? AND event='variant_preview'",
                (payload.get("preview_id"),),
            ).fetchone()
            if not found:
                raise ValueError("unknown variant preview")
            evidence.append(found)
        if action == "variant-preview":
            for sql in (
                "SELECT fingerprint,generation,missing_count,status "
                "FROM media_source_files WHERE id=?",
                "SELECT revision,target,status,mapping_json FROM media_import_jobs "
                "WHERE source_id=?",
                "SELECT revision,fingerprint FROM media_review_decisions WHERE source_id=?",
            ):
                evidence.append(conn.execute(sql, (payload.get("new_source_id"),)).fetchone())
        if action == "featurette-publish":
            found = conn.execute(
                "SELECT payload_json FROM media_events WHERE id=? AND event='featurette_preview'",
                (payload.get("preview_id"),),
            ).fetchone()
            if not found:
                raise ValueError("unknown featurette preview")
            evidence.append(found)
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
                if action in {"subtitle-search", "subtitle-import"}:
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
            if action == "subtitle-import" and payload.get("preview_id") is not None:
                preview = conn.execute(
                    "SELECT payload_json FROM media_events WHERE id=? AND source_id=? "
                    "AND event='subtitle_local_preview'",
                    (payload["preview_id"], source_id),
                ).fetchone()
                if not preview:
                    raise ValueError("unknown local subtitle preview")
                evidence.append(preview)
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        return {"source_fences": expected, "digest": digest} if expected else digest


def command_store(path: Path, *, read_only=False):
    view = load_view(path, "media")
    return view, MediaStore(media_state_path(view), initialize=False, read_only=read_only)


def submit(
    path: Path, action, payload=None, *, execute=False, expected_sources=None, expected_context=None
):
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
    if action == "completion-confirm":
        required = {"source_id", "generation", "fingerprint", "completion_confirmed"}
        if (
            not execute
            or not required <= payload.keys()
            or set(payload) - required - {"client_request_id"}
        ):
            raise ValueError("completion confirmation requires explicit execution and exact source")
        if (
            type(payload["generation"]) is not int
            or payload["generation"] < 1
            or not isinstance(payload["source_id"], str)
            or not isinstance(payload["fingerprint"], str)
            or payload["completion_confirmed"] is not True
        ):
            raise ValueError("invalid completion confirmation")
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
    if action == "subtitle-import":
        from seed_agent.media_import.subtitles.local_import import validate_request

        validate_request(payload, execute=execute)
    if expected_sources is not None:
        if not isinstance(expected_sources, list) or not 1 <= len(expected_sources) <= 6:
            raise ValueError("expected sources must contain 1 to 6 source fences")
        ids = set()
        for item in expected_sources:
            if (
                not isinstance(item, dict)
                or set(item) != {"source_id", "generation", "fingerprint"}
                or not isinstance(item["source_id"], str)
                or not item["source_id"]
                or type(item["generation"]) is not int
                or item["generation"] < 1
                or not isinstance(item["fingerprint"], str)
                or not item["fingerprint"]
                or item["source_id"] in ids
            ):
                raise ValueError("invalid or duplicate expected source fence")
            ids.add(item["source_id"])
        expected_sources = sorted(
            (dict(item) for item in expected_sources), key=lambda item: item["source_id"]
        )
    if expected_context is not None:
        if (
            not isinstance(expected_context, dict)
            or set(expected_context) != {"source_id", "config_revision", "epoch"}
            or not isinstance(expected_context["source_id"], str)
            or not expected_context["source_id"]
            or not isinstance(expected_context["config_revision"], str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_context["config_revision"])
            or not isinstance(expected_context["epoch"], str)
            or not re.fullmatch(r"[0-9a-fA-F]{32}", expected_context["epoch"])
        ):
            raise ValueError("invalid expected media context")
        expected_context = dict(expected_context)
    view, store = command_store(path)
    if expected_context is not None and (
        view.source_id != expected_context["source_id"]
        or view.effective_revision != expected_context["config_revision"]
    ):
        raise ValueError("expected media configuration changed")
    if not view.config.media_import.enabled:
        raise ValueError("media is disabled")
    modes = {
        kind: getattr(view.config.media_import, kind + "_policy") if execute else "preview"
        for kind in ["import", "subtitle", "reconcile"]
    }
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        epoch_row = conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()
        if not epoch_row:
            raise ValueError("media restore epoch missing")
        epoch = epoch_row[0]
        if expected_context is not None and epoch != expected_context["epoch"]:
            raise ValueError("expected media restore epoch changed")
        for item in expected_sources or []:
            current = conn.execute(
                "SELECT s.generation,s.fingerprint,s.missing_count,s.status,"
                "(SELECT MAX(generation) FROM media_source_files "
                "WHERE profile=s.profile AND path=s.path) "
                "FROM media_source_files s WHERE s.id=?",
                (item["source_id"],),
            ).fetchone()
            if (
                not current
                or current[0] != item["generation"]
                or current[1] != item["fingerprint"]
                or current[2] != 0
                or current[3] == "removed"
                or current[4] != item["generation"]
            ):
                raise ValueError("expected source baseline changed")
        baseline_payload = {**payload, "_expected_sources": expected_sources}
        payload = {
            **payload,
            "_baseline": baseline(store, action, baseline_payload, connection=conn),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > MAX_PAYLOAD:
            raise ValueError("media command body exceeds limit")
        key = hashlib.sha256(
            json.dumps(
                [action, encoded, modes, view.source_id, view.effective_revision, epoch, execute],
                sort_keys=True,
            ).encode()
        ).hexdigest()
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
