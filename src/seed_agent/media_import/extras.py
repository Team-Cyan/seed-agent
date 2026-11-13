"""Explicit featurette attachments; never run film matching or subtitle jobs."""

import json
import sqlite3
import uuid
from pathlib import Path

from seed_agent.media_import import filesystem as fs
from seed_agent.media_import import roots
from seed_agent.media_import.engine import VIDEO, encode, rows


def projection(engine, source_id, parent_id, filename, *, completion_confirmed):
    if completion_confirmed is not True:
        raise ValueError("explicit source completion confirmation required")
    if not isinstance(filename, str) or Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError("featurette filename must be a single component")
    if Path(filename).suffix.lower() not in VIDEO or filename.startswith("."):
        raise ValueError("invalid featurette filename")
    with engine.store._connect() as conn:
        source = rows(conn, "SELECT * FROM media_source_files WHERE id=?", (source_id,))
        parent = rows(
            conn,
            "SELECT j.*,s.generation,s.fingerprint,s.missing_count FROM media_import_jobs j "
            "JOIN media_source_files s ON s.id=j.source_id WHERE j.source_id=?",
            (parent_id,),
        )
        artifacts = rows(
            conn,
            "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
            "ON r.artifact_id=a.id WHERE r.source_id=? AND a.kind='video' "
            "AND a.status='active'",
            (parent_id,),
        )
        if not source or not parent or len(artifacts) != 1:
            raise ValueError("source and uniquely imported parent required")
        source, parent, artifact = source[0], parent[0], artifacts[0]
        if (
            source_id == parent_id
            or source["missing_count"]
            or source["status"] == "removed"
            or source["stable_count"] < 2
        ):
            raise ValueError("extra source unavailable or unstable")
        if (
            parent["missing_count"]
            or parent["status"] != "imported"
            or artifact["path"] != parent["target"]
            or not artifact["owned"]
        ):
            raise ValueError("parent is not an active imported work")
        mapping = json.loads(parent["mapping_json"])
        if mapping.get("media_type") != "movie":
            raise ValueError("featurette parent must be a confirmed movie")
        if conn.execute(
            "SELECT 1 FROM media_artifact_sources r JOIN media_artifacts a "
            "ON a.id=r.artifact_id WHERE r.source_id=? "
            "AND a.status IN ('active','publishing','deleting')",
            (source_id,),
        ).fetchone():
            raise ValueError("extra source already has publication artifacts")
        if conn.execute(
            "SELECT 1 FROM media_subtitle_jobs WHERE source_id=? LIMIT 1", (source_id,)
        ).fetchone():
            raise ValueError("extra source has existing subtitle jobs")
        descriptor = roots.artifact(conn, artifact["id"])
        parent_fence = engine.publication_fence(conn, parent_id)
    p = engine.profile(source["profile"])
    engine.health(p)
    srcroot = Path(p.source_root)
    source_identity = fs.root_health(srcroot, p.marker, p.marker_value)
    src = srcroot / source["path"]
    if engine.clock() - src.stat().st_mtime < p.min_age_seconds:
        raise ValueError("extra source has not reached minimum age")
    if fs.fingerprint(src) != source["fingerprint"]:
        raise ValueError("extra source changed")
    root = roots.validate(descriptor, artifact["path"])
    parent_receipt = fs.receipt(root, Path(artifact["path"]))
    if parent_receipt != json.loads(artifact["receipt_json"]):
        raise ValueError("parent video receipt changed")
    target = Path(parent["target"]).parent / "Featurettes" / filename
    roots.validate(descriptor, target)
    return {
        "source_id": source_id,
        "generation": source["generation"],
        "fingerprint": source["fingerprint"],
        "source_profile": source["profile"],
        "source_path": source["path"],
        "source_root": str(srcroot),
        "source_identity": source_identity,
        "source_receipt": fs.receipt(srcroot, src),
        "parent_source_id": parent_id,
        "parent_profile": artifact["profile"],
        "parent_artifact_id": artifact["id"],
        "parent_receipt": parent_receipt,
        "parent_fence": parent_fence,
        "target": str(target),
        "descriptor": descriptor,
        "completion_confirmed": True,
    }


def preview(engine, request):
    with engine.lease():
        return _preview(engine, request)


def _preview(engine, request):
    value = projection(
        engine,
        request["source_id"],
        request["parent_source_id"],
        request["filename"],
        completion_confirmed=request.get("completion_confirmed"),
    )
    # Persist the role before the worker can run ordinary matching between preview
    # and publish. Reviewed attachments never acquire publication authority by scan.
    with engine.store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT baseline_json,status FROM media_extra_attachments WHERE source_id=?",
            (value["source_id"],),
        ).fetchone()
        if existing:
            if existing[1] != "reviewed":
                raise ValueError("source already has a publication attachment")
            conn.execute(
                "UPDATE media_extra_attachments SET generation=?,fingerprint=?,"
                "parent_source_id=?,baseline_json=?,target=?,artifact_id=?,created=? "
                "WHERE source_id=? AND status='reviewed'",
                (
                    value["generation"],
                    value["fingerprint"],
                    value["parent_source_id"],
                    encode(value),
                    value["target"],
                    uuid.uuid4().hex,
                    engine.clock(),
                    value["source_id"],
                ),
            )
        else:
            conn.execute(
                "INSERT INTO media_extra_attachments VALUES(?,?,?,?,?,?,?,'reviewed',?)",
                (
                    value["source_id"],
                    value["generation"],
                    value["fingerprint"],
                    value["parent_source_id"],
                    encode(value),
                    value["target"],
                    uuid.uuid4().hex,
                    engine.clock(),
                ),
            )
        engine.event(conn, value["source_id"], "featurette_preview", value)
        preview_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"preview_id": preview_id, "projection": value}


def execute(engine, preview_id):
    if engine.config.import_policy != "execute":
        raise ValueError("featurette publication requires execute policy")
    with engine.lease():
        with engine.store._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM media_events WHERE id=? AND event='featurette_preview'",
                (preview_id,),
            ).fetchone()
        if not row:
            raise ValueError("unknown featurette preview")
        value = json.loads(row[0])
        current = projection(
            engine,
            value["source_id"],
            value["parent_source_id"],
            Path(value["target"]).name,
            completion_confirmed=value["completion_confirmed"],
        )
        if current != value:
            raise ValueError("featurette preview baseline changed")
        with engine.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            attachment = conn.execute(
                "SELECT artifact_id,baseline_json,status FROM media_extra_attachments "
                "WHERE source_id=?",
                (value["source_id"],),
            ).fetchone()
            if not attachment or attachment[1] != encode(value) or attachment[2] != "reviewed":
                raise ValueError("featurette attachment baseline changed")
            aid = attachment[0]
            conn.execute(
                "UPDATE media_extra_attachments SET status='pending' "
                "WHERE source_id=? AND status='reviewed'",
                (value["source_id"],),
            )
        publish(engine, value, aid)
        return {"status": "published", "artifact_id": aid, "target": value["target"]}


def publish(engine, value, aid):
    engine.write_gate("import")
    current = projection(
        engine,
        value["source_id"],
        value["parent_source_id"],
        Path(value["target"]).name,
        completion_confirmed=True,
    )
    if current != value:
        raise ValueError("featurette publication baseline changed")
    root = roots.validate(value["descriptor"], value["target"])
    target = Path(value["target"])
    temp = target.parent / (".media-extra-" + aid)
    p = engine.for_plan(engine.profile(value["parent_profile"]), value["parent_source_id"])
    engine.mkdirs(p, target.parent, root_identity=value["descriptor"]["identity"])
    expected = value["source_receipt"]
    with engine.store._connect() as conn:
        stage = conn.execute(
            "SELECT status FROM media_extra_attachments WHERE artifact_id=?", (aid,)
        ).fetchone()
    if not stage:
        raise ValueError("featurette intent missing")
    stage = stage[0]
    if stage == "pending":
        if temp.exists() or temp.is_symlink() or target.exists() or target.is_symlink():
            raise ValueError("unacknowledged featurette path occupied")
        engine._link(
            Path(value["source_root"]),
            Path(value["source_root"]) / value["source_path"],
            root,
            temp,
            source_identity=value["source_identity"],
            target_identity=value["descriptor"]["identity"],
            expected=expected,
        )
        if fs.receipt(root, temp) != expected:
            raise ValueError("featurette temporary changed")
        with engine.store._connect() as conn:
            conn.execute(
                "UPDATE media_extra_attachments SET status='temporary' "
                "WHERE artifact_id=? AND status='pending'",
                (aid,),
            )
        stage = "temporary"
    if stage == "temporary":
        if fs.receipt(root, temp) != expected:
            raise ValueError("featurette temporary changed")
        if target.exists() or target.is_symlink():
            raise ValueError("unacknowledged featurette target occupied")
        engine._link(
            root,
            temp,
            root,
            target,
            source_identity=value["descriptor"]["identity"],
            target_identity=value["descriptor"]["identity"],
            expected=expected,
        )
        if fs.receipt(root, target) != expected:
            raise ValueError("featurette target changed")
        with engine.store._connect() as conn:
            conn.execute(
                "UPDATE media_extra_attachments SET status='linked' "
                "WHERE artifact_id=? AND status='temporary'",
                (aid,),
            )
        stage = "linked"
    if stage != "linked":
        raise ValueError("invalid featurette publication stage")
    if fs.receipt(root, temp) != expected or fs.receipt(root, target) != expected:
        raise ValueError("featurette publication receipt changed")
    with engine.store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO media_artifacts VALUES(?,?,?,?,1,'active',?,?)",
            (aid, str(target), value["source_profile"], "extra", encode(expected), engine.clock()),
        )
        roots.record_artifact(conn, aid, value["descriptor"])
        conn.execute("INSERT INTO media_artifact_sources VALUES(?,?)", (aid, value["source_id"]))
        conn.execute(
            "UPDATE media_extra_attachments SET status='cleanup' WHERE source_id=?",
            (value["source_id"],),
        )
    cleanup(engine, value, aid)


def cleanup(engine, value, aid):
    engine.write_gate("import")
    root = roots.validate(value["descriptor"], value["target"])
    target = Path(value["target"])
    temp = target.parent / (".media-extra-" + aid)
    with engine.store._connect() as conn:
        fence = engine.publication_fence(conn, value["parent_source_id"])
        record = conn.execute(
            "SELECT status,receipt_json FROM media_artifacts WHERE id=? AND path=?",
            (aid, str(target)),
        ).fetchone()
    if fence != value["parent_fence"] or not record or record[0] != "active":
        raise ValueError("featurette cleanup baseline changed")
    expected = value["source_receipt"]
    if json.loads(record[1]) != expected or fs.receipt(root, target) != expected:
        raise ValueError("featurette published receipt changed")
    if temp.exists() or temp.is_symlink():
        engine._unlink(root, temp, expected, root_identity=value["descriptor"]["identity"])
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_extra_attachments SET status='published' WHERE artifact_id=?", (aid,)
        )


def recover(engine, profile, *, should_yield=None):
    if engine.config.import_policy != "execute":
        return
    with engine.store._connect() as conn:
        pending = conn.execute(
            "SELECT baseline_json,artifact_id,status FROM media_extra_attachments "
            "WHERE status IN ('pending','temporary','linked','cleanup')"
        ).fetchall()
    for encoded, aid, status in pending:
        if should_yield and should_yield():
            return True
        value = json.loads(encoded)
        if value["source_profile"] != profile.name:
            continue
        try:
            if status != "cleanup":
                publish(engine, value, aid)
            else:
                cleanup(engine, value, aid)
        except (OSError, ValueError, sqlite3.IntegrityError) as exc:
            with engine.store._connect() as conn:
                conn.execute(
                    "UPDATE media_extra_attachments SET status='conflict' WHERE artifact_id=?",
                    (aid,),
                )
                engine.event(
                    conn,
                    value["source_id"],
                    "featurette_recovery_conflict",
                    {"error_type": type(exc).__name__},
                )

    return False


def parents(engine, query="", limit=50):
    """Read-only bounded movie parent candidates across all source pages."""
    if not isinstance(query, str) or len(query) > 100:
        raise ValueError("parent query exceeds limit")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("parent limit must be 1..50")
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with engine.store._connect() as conn:
        candidates = rows(
            conn,
            "SELECT s.id,j.mapping_json FROM media_source_files s "
            "JOIN media_import_jobs j ON j.source_id=s.id "
            "WHERE s.status='imported' AND s.missing_count=0 AND j.status='imported' "
            "AND NOT EXISTS (SELECT 1 FROM media_extra_attachments e WHERE e.source_id=s.id) "
            "AND json_extract(j.mapping_json,'$.media_type')='movie' "
            "AND (json_extract(j.mapping_json,'$.original_title') LIKE ? ESCAPE '\\' "
            "OR json_extract(j.mapping_json,'$.localized_title') LIKE ? ESCAPE '\\' "
            "OR json_extract(j.mapping_json,'$.english_title') LIKE ? ESCAPE '\\') "
            "AND (SELECT COUNT(*) FROM media_artifacts a JOIN media_artifact_sources r "
            "ON r.artifact_id=a.id WHERE r.source_id=s.id AND a.kind='video' "
            "AND a.status='active' AND a.path=j.target)=1 "
            "AND EXISTS (SELECT 1 FROM media_artifacts a JOIN media_artifact_sources r "
            "ON r.artifact_id=a.id WHERE r.source_id=s.id AND a.kind='video' "
            "AND a.status='active' AND a.owned=1 AND a.path=j.target) "
            "ORDER BY json_extract(j.mapping_json,'$.original_title'),s.id LIMIT ?",
            (f"%{escaped}%", f"%{escaped}%", f"%{escaped}%", limit),
        )
    return [
        {"source_id": row["id"], "title": mapping["original_title"], "year": mapping["year"]}
        for row in candidates
        for mapping in [json.loads(row["mapping_json"])]
    ]
