"""Explicit bounded consistent media export/import; never initializes or changes seed state."""

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from seed_agent.media_import import filesystem as fs
from seed_agent.media_import import roots
from seed_agent.media_import.schema import SCHEMA
from seed_agent.media_import.store import MediaStore, bounded_lock

MAX_ROWS = 10_000
MAX_BYTES = 32_000_000


def table_columns():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(SCHEMA)
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        return {
            name: [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')] for name in tables
        }


def digest(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def validate_snapshot(payload, profiles):
    if payload.get("schema") != "media-export-v1" or set(payload.get("tables", {})) != set(
        table_columns()
    ):
        raise ValueError("unsupported/incomplete media export schema")
    rows = payload["tables"]
    count = sum(len(values) for values in rows.values())
    if count > MAX_ROWS or payload["counts"] != {t: len(v) for t, v in rows.items()}:
        raise ValueError("media export counts/row budget mismatch")
    for name, columns in table_columns().items():
        if any(set(row) != set(columns) for row in rows[name]):
            raise ValueError("media export column mismatch")
    sources = {r["id"]: r for r in rows["media_source_files"]}
    artifacts = {r["id"]: r for r in rows["media_artifacts"]}
    if len(sources) != len(rows["media_source_files"]) or len(artifacts) != len(
        rows["media_artifacts"]
    ):
        raise ValueError("duplicate media identities")
    for row in rows["media_artifact_sources"]:
        if row["source_id"] not in sources or row["artifact_id"] not in artifacts:
            raise ValueError("orphan artifact/source reference")
    for table in [
        "media_import_jobs",
        "media_review_decisions",
        "media_subtitle_jobs",
        "media_reconcile_actions",
    ]:
        for row in rows[table]:
            if row["source_id"] not in sources:
                raise ValueError("orphan media job/decision")
            if (
                table == "media_subtitle_jobs"
                and row["generation"] != sources[row["source_id"]]["generation"]
            ):
                raise ValueError("subtitle source generation mismatch")
    for row in rows["media_publications"]:
        if row["artifact_id"] not in artifacts or row["source_id"] not in sources:
            raise ValueError("orphan publication")
        if row["status"] != "done":
            raise ValueError("drain/recover media publications before migration")
    profile_map = {p.name: p for p in profiles}
    for row in rows["media_source_files"]:
        path = Path(row["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe stored source path")
    for row in artifacts.values():
        profile = profile_map.get(row["profile"])
        if profile is None:
            if row["owned"] and row["status"] in {"active", "publishing", "deleting", "retiring"}:
                raise ValueError("owned receipt has no configured profile")
            continue
        target = Path(row["path"])
        root = Path(profile.target_root)
        if not target.is_relative_to(root) or ".." in target.parts:
            raise ValueError("receipt escapes target root")
        if row["owned"] and row["status"] == "active":
            expected = json.loads(row["receipt_json"])
            fs.root_health(
                root, profile.target_marker or profile.marker, profile.target_marker_value
            )
            if fs.receipt(root, target, digest="digest" in expected) != expected:
                raise ValueError("owned receipt cannot be verified for migration")
        if row["status"] in {"publishing", "deleting", "retiring"}:
            raise ValueError("drain/recover media writes before migration")
    for row in rows["media_owned_directories"]:
        profile = profile_map.get(row["profile"])
        path = Path(row["path"])
        if profile is None:
            raise ValueError("owned directory has no configured profile")
        root = Path(profile.target_root)
        if path == root or not path.is_relative_to(root) or ".." in path.parts:
            raise ValueError("owned directory escapes target root")
        fs.root_health(root, profile.target_marker or profile.marker, profile.target_marker_value)
        if fs.identity(path) != row["identity"]:
            raise ValueError("owned directory identity changed")


def export_snapshot(source: Path, profiles, *, output: Path | None = None):
    # Also stop/drain the legacy service for cutover: this lease protects the
    # export itself, not future writes after the snapshot has been returned.
    with bounded_lock(Path(str(source) + ".media.lock"), exclusive=True):
        return _export_snapshot(source, profiles, output=output)


def _export_snapshot(source: Path, profiles, *, output: Path | None = None):
    if not source.is_file() or source.is_symlink():
        raise ValueError("missing/unsafe legacy source database")
    columns = table_columns()
    values = {}
    remaining = MAX_ROWS
    # One read transaction captures every table at the same WAL snapshot.
    with closing(
        sqlite3.connect(f"file:{source.absolute()}?mode=ro&cache=private", uri=True, timeout=0.25)
    ) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        for table, names in columns.items():
            quoted = ",".join('"' + name + '"' for name in names)
            fetched = conn.execute(
                f'SELECT {quoted} FROM "{table}" LIMIT ?', (remaining + 1,)
            ).fetchall()
            if len(fetched) > remaining:
                raise ValueError("migration row budget exceeded")
            values[table] = [dict(row) for row in fetched]
            remaining -= len(fetched)
        conn.rollback()
    payload = {
        "schema": "media-export-v1",
        "counts": {t: len(v) for t, v in values.items()},
        "tables": values,
    }
    validate_snapshot(payload, profiles)
    wrapper = {"digest": digest(payload), "payload": payload}
    encoded = json.dumps(wrapper, sort_keys=True, ensure_ascii=False).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("migration export byte budget exceeded")
    if output is not None:
        if any(
            output.absolute().is_relative_to(Path(root).absolute())
            for p in profiles
            for root in [p.source_root, p.target_root]
        ):
            raise ValueError("migration export must be outside media roots")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".media-export-", dir=output.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temp, output)
        finally:
            temp.unlink(missing_ok=True)
    return {
        "status": "exported" if output else "preview",
        "digest": wrapper["digest"],
        "counts": payload["counts"],
        "bytes": len(encoded),
    }


def import_snapshot(export: Path, target: Path, profiles, *, execute=False):
    if export.is_symlink():
        raise ValueError("unsafe export file")
    with export.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("migration import byte budget exceeded")
    wrapper = json.loads(raw)
    if wrapper.get("digest") != digest(wrapper["payload"]):
        raise ValueError("media export digest mismatch")
    validate_snapshot(wrapper["payload"], profiles)
    if not execute:
        return {
            "status": "preview",
            "counts": wrapper["payload"]["counts"],
            "digest": wrapper["digest"],
        }
    if target.absolute() == export.absolute():
        raise ValueError("migration target collides with export")
    if any(
        target.absolute().is_relative_to(Path(root).absolute())
        for p in profiles
        for root in [p.source_root, p.target_root]
    ):
        raise ValueError("media state must be outside media roots")
    descriptors = {
        p.name: roots.describe(
            p, route="legacy:" + p.name, revision="legacy-export:" + wrapper["digest"]
        )
        for p in profiles
    }
    store = MediaStore(target)
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute(
            "SELECT counts_json FROM media_migrations WHERE export_digest=?", (wrapper["digest"],)
        ).fetchone()
        if previous:
            return {
                "status": "already_imported",
                "counts": json.loads(previous[0]),
                "digest": wrapper["digest"],
            }
        for table in table_columns():
            if (
                table != "media_schema"
                and conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
            ):
                raise ValueError("target has media history; refuse merge/overwrite")
        for table, columns in table_columns().items():
            if table == "media_schema":
                continue
            sql = (
                f'INSERT INTO "{table}" ('
                + ",".join('"' + n + '"' for n in columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")"
            )
            conn.executemany(
                sql, [[r[n] for n in columns] for r in wrapper["payload"]["tables"][table]]
            )
        # Old in-flight claims/config acknowledgements have no authority in the new store.
        for item in wrapper["payload"]["tables"]["media_artifacts"]:
            descriptor = descriptors.get(item["profile"])
            if descriptor and Path(item["path"]).is_relative_to(Path(descriptor["root"])):
                roots.record_artifact(conn, item["id"], descriptor)
        for item in wrapper["payload"]["tables"]["media_import_jobs"]:
            source = next(
                s
                for s in wrapper["payload"]["tables"]["media_source_files"]
                if s["id"] == item["source_id"]
            )
            descriptor = descriptors.get(source["profile"])
            if (
                descriptor
                and item["target"]
                and Path(item["target"]).is_relative_to(Path(descriptor["root"]))
            ):
                conn.execute(
                    "INSERT INTO media_plan_routes VALUES(?,?,?)",
                    (item["source_id"], item["revision"], json.dumps(descriptor, sort_keys=True)),
                )
        for item in wrapper["payload"]["tables"]["media_owned_directories"]:
            conn.execute(
                "INSERT INTO media_directory_roots VALUES(?,?)",
                (item["path"], json.dumps(descriptors[item["profile"]], sort_keys=True)),
            )
        conn.execute(
            "UPDATE media_subtitle_jobs SET claim_token=NULL,"
            "status=CASE WHEN status='running' THEN 'retrying' ELSE status END"
        )
        counts = wrapper["payload"]["counts"]
        conn.execute(
            "INSERT INTO media_migrations VALUES(?,?,?)",
            (wrapper["digest"], time.time(), json.dumps(counts, sort_keys=True)),
        )
    return {
        "status": "imported",
        "digest": wrapper["digest"],
        "counts": counts,
        "epoch": store.epoch(),
    }
