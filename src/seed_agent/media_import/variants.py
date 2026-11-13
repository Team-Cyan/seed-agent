"""Source variant identity and selection state, independent of encode quality."""

import hashlib
import json
import re

from seed_agent.media_import.engine import encode
from seed_agent.media_import.metadata import Mapping


def work_key(mapping):
    value = Mapping.model_validate(mapping)
    identity = {
        "media_type": value.media_type,
        "tmdb_id": value.tmdb_id,
        "season": value.season,
        "episodes": sorted(set(value.episodes)),
        "edition": value.edition,
    }
    if value.media_type not in {"movie", "tv", "anime"}:
        raise ValueError("unsupported variant work type")
    if value.media_type != "movie" and (value.season is None or not value.episodes):
        raise ValueError("variant episode identity incomplete")
    return hashlib.sha256(encode(identity).encode()).hexdigest()


def selection_fence(conn, source_id):
    row = conn.execute(
        "SELECT m.work_key,m.generation,m.fingerprint,s.source_id,s.revision "
        "FROM media_variant_members m JOIN media_variant_selections s ON s.work_key=m.work_key "
        "WHERE m.source_id=?",
        (source_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "work_key": row[0],
        "generation": row[1],
        "fingerprint": row[2],
        "selected_source_id": row[3],
        "selection_revision": row[4],
    }


def selection_snapshot(conn, source_ids):
    if not source_ids:
        return []
    marks = ",".join("?" for _ in source_ids)
    result = []
    for row in conn.execute(
        "SELECT m.source_id,m.work_key,m.generation,m.fingerprint,s.source_id,s.revision "
        "FROM media_variant_members m JOIN media_variant_selections s ON s.work_key=m.work_key "
        f"WHERE m.source_id IN ({marks})",
        source_ids,
    ):
        result.append(
            dict(
                zip(
                    (
                        "source_id",
                        "work_key",
                        "generation",
                        "fingerprint",
                        "selected_source_id",
                        "revision",
                    ),
                    row,
                    strict=True,
                )
            )
        )
    return result


def preview(engine, old_source_id, new_source_id, *, completion_confirmed):
    """Reserve an explicitly reviewed candidate; does not authorize publication."""
    import sqlite3
    from pathlib import Path

    from seed_agent.media_import import filesystem as fs
    from seed_agent.media_import import roots

    if completion_confirmed is not True or old_source_id == new_source_id:
        raise ValueError("distinct sources and completion confirmation required")
    with engine.lease():
        with engine.store._connect(row_factory=sqlite3.Row) as conn:
            entries = []
            for source_id in (old_source_id, new_source_id):
                row = conn.execute(
                    "SELECT s.*,j.mapping_json,j.target,j.revision,j.status AS job_status "
                    "FROM media_source_files s JOIN media_import_jobs j ON j.source_id=s.id "
                    "WHERE s.id=?",
                    (source_id,),
                ).fetchone()
                if not row or row["missing_count"] or row["stable_count"] < 2:
                    raise ValueError("variant source missing or unstable")
                if conn.execute(
                    "SELECT 1 FROM media_extra_attachments WHERE source_id=?", (source_id,)
                ).fetchone():
                    raise ValueError("extra cannot be a primary variant")
                entries.append(dict(row))
            old, new = entries
            if old["status"] != "imported" or old["job_status"] != "imported":
                raise ValueError("old selection must be imported")
            if not old["mapping_json"] or not new["mapping_json"]:
                raise ValueError("both variants require reviewed work identity")
            key = work_key(json.loads(old["mapping_json"]))
            if key != work_key(json.loads(new["mapping_json"])):
                raise ValueError("variant work/episode/edition differ")
            artifact = conn.execute(
                "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
                "ON r.artifact_id=a.id "
                "WHERE r.source_id=? AND a.kind='video' AND a.status='active' AND a.path=?",
                (old_source_id, old["target"]),
            ).fetchall()
            if len(artifact) != 1 or not artifact[0]["owned"]:
                raise ValueError("old video must have one owned active receipt")
            artifact = dict(artifact[0])
            if conn.execute(
                "SELECT 1 FROM media_artifact_sources r JOIN media_artifacts a "
                "ON a.id=r.artifact_id WHERE r.source_id=? "
                "AND a.status IN ('active','publishing','deleting')",
                (new_source_id,),
            ).fetchone():
                raise ValueError("candidate already has publication artifacts")
            if conn.execute(
                "SELECT 1 FROM media_subtitle_jobs WHERE source_id=? AND status!='cancelled'",
                (new_source_id,),
            ).fetchone():
                raise ValueError("candidate already has subtitle jobs")
            descriptor = roots.artifact(conn, artifact["id"])
            if conn.execute(
                "SELECT 1 FROM media_variant_switches WHERE work_key=? AND status!='done' LIMIT 1",
                (key,),
            ).fetchone():
                raise ValueError("unfinished variant switch requires reconciliation")
            selected = conn.execute(
                "SELECT source_id,revision FROM media_variant_selections WHERE work_key=?", (key,)
            ).fetchone()
            if selected and selected["source_id"] != old_source_id:
                raise ValueError("old source is not selected")
        for source in (old, new):
            p = engine.profile(source["profile"])
            engine.health(p)
            path = Path(p.source_root) / source["path"]
            if (
                engine.clock() - path.stat().st_mtime < p.min_age_seconds
                or fs.fingerprint(path) != source["fingerprint"]
            ):
                raise ValueError("variant source changed or too young")
        root = roots.validate(descriptor, old["target"])
        if fs.receipt(root, Path(old["target"])) != json.loads(artifact["receipt_json"]):
            raise ValueError("old video receipt changed")
        with engine.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO media_variant_selections VALUES(?,?,1)", (key, old_source_id)
            )
            for source in (old, new):
                prior = conn.execute(
                    "SELECT work_key,generation,fingerprint FROM media_variant_members "
                    "WHERE source_id=?",
                    (source["id"],),
                ).fetchone()
                member = (key, source["generation"], source["fingerprint"])
                if prior and prior != member:
                    raise ValueError("variant membership changed")
                conn.execute(
                    "INSERT OR IGNORE INTO media_variant_members VALUES(?,?,?,?)",
                    (source["id"], *member),
                )
            conn.execute(
                "UPDATE media_source_files SET status='retained_not_selected' WHERE id=?",
                (new_source_id,),
            )
        value = projection(engine, old_source_id, new_source_id)
        with engine.store._connect() as conn:
            engine.event(conn, new_source_id, "variant_preview", value)
            preview_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"preview_id": preview_id, "projection": value}


def projection(engine, old_id, new_id):
    import sqlite3
    from pathlib import Path

    from seed_agent.media_import import filesystem as fs
    from seed_agent.media_import import roots

    with engine.store._connect(row_factory=sqlite3.Row) as conn:
        sources = []
        for sid in (old_id, new_id):
            source = conn.execute(
                "SELECT s.*,j.mapping_json,j.target,j.revision,j.status AS job_status "
                "FROM media_source_files s JOIN media_import_jobs j ON j.source_id=s.id "
                "WHERE s.id=?",
                (sid,),
            ).fetchone()
            if not source or source["missing_count"] or source["stable_count"] < 2:
                raise ValueError("variant source unavailable")
            sources.append(dict(source))
        old, new = sources
        old_fence = engine.publication_fence(conn, old_id)
        new_fence = engine.publication_fence(conn, new_id)
        selection = old_fence["variant_selection"]
        if not selection or selection["selected_source_id"] != old_id:
            raise ValueError("old selection changed")
        if new_fence["variant_selection"]["work_key"] != selection["work_key"]:
            raise ValueError("variant membership changed")
        artifacts = conn.execute(
            "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r ON r.artifact_id=a.id "
            "WHERE r.source_id=? AND a.status='active' AND a.kind IN ('video','subtitle') "
            "ORDER BY a.kind,a.id",
            (old_id,),
        ).fetchall()
        manifest = []
        for row in artifacts:
            item = dict(row)
            old_path = Path(old["target"])
            item_path = Path(item["path"])
            if item["kind"] == "video" and item_path != old_path:
                continue
            if item["kind"] == "subtitle" and (
                item_path.parent != old_path.parent
                or not item_path.name.startswith(old_path.stem + ".")
            ):
                continue
            if not item["owned"]:
                if item["kind"] == "video":
                    raise ValueError("old video is not owned")
                continue
            supports = conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources WHERE artifact_id=? AND source_id!=?",
                (item["id"], old_id),
            ).fetchone()[0]
            if supports:
                if item["kind"] == "video":
                    raise ValueError("old video has shared ownership")
                continue
            item["descriptor"] = roots.artifact(conn, item["id"])
            item["receipt"] = json.loads(item.pop("receipt_json"))
            manifest.append(item)
        videos = [
            item for item in manifest if item["kind"] == "video" and item["path"] == old["target"]
        ]
        if len(videos) != 1:
            raise ValueError("selected source lacks exact owned video")
        descriptor = videos[0]["descriptor"]
        if any(item["descriptor"] != descriptor for item in manifest):
            raise ValueError("old version assets cross destination roots")
    root = roots.validate(descriptor, old["target"])
    for item in manifest:
        if (
            fs.receipt(root, Path(item["path"]), digest="digest" in item["receipt"])
            != item["receipt"]
        ):
            raise ValueError("old version receipt changed")
    old_profile = engine.profile(old["profile"])
    engine.health(old_profile)
    old_root = Path(old_profile.source_root)
    old_identity = fs.root_health(old_root, old_profile.marker, old_profile.marker_value)
    old_source_path = old_root / old["path"]
    if fs.fingerprint(old_source_path) != old["fingerprint"]:
        raise ValueError("old variant fingerprint changed")
    new_profile = engine.profile(new["profile"])
    engine.health(new_profile)
    source_root = Path(new_profile.source_root)
    source_identity = fs.root_health(source_root, new_profile.marker, new_profile.marker_value)
    source_path = source_root / new["path"]
    if fs.fingerprint(source_path) != new["fingerprint"]:
        raise ValueError("new variant fingerprint changed")
    source_receipt = fs.receipt(source_root, source_path)
    old_path = Path(old["target"])
    suffix = Path(new["path"]).suffix.lower()
    from seed_agent.media_import.engine import VIDEO

    if suffix not in VIDEO:
        raise ValueError("variant source is not a video")
    target = old_path.with_name(
        re.sub(r"\.source-[0-9a-f]{16}$", "", old_path.stem)
        + ".source-"
        + hashlib.sha256(new_id.encode()).hexdigest()[:16]
        + suffix
    )
    roots.validate(descriptor, target)
    return {
        "old_source_id": old_id,
        "new_source_id": new_id,
        "work_key": selection["work_key"],
        "revision": selection["selection_revision"],
        "old_fence": old_fence,
        "new_fence": new_fence,
        "old_manifest": manifest,
        "descriptor": descriptor,
        "target": str(target),
        "old_source_root": str(old_root),
        "old_source_path": str(old_source_path),
        "old_source_identity": old_identity,
        "old_profile": old["profile"],
        "source_root": str(source_root),
        "source_path": str(source_path),
        "source_identity": source_identity,
        "source_receipt": source_receipt,
        "new_profile": new["profile"],
    }


def execute(engine, preview_id):
    """Begin a durable source-qualified switch under the media writer lease."""
    import uuid

    if engine.config.import_policy != "execute":
        raise ValueError("variant switch requires execute import policy")
    with engine.lease():
        with engine.store._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM media_events WHERE id=? AND event='variant_preview'",
                (preview_id,),
            ).fetchone()
        if not row:
            raise ValueError("unknown variant preview")
        value = json.loads(row[0])
        if projection(engine, value["old_source_id"], value["new_source_id"]) != value:
            raise ValueError("variant preview baseline changed")
        sid = uuid.uuid4().hex
        with engine.store._connect() as conn:
            conn.execute(
                "INSERT INTO media_variant_switches VALUES(?,?,?,'pending',?)",
                (sid, value["work_key"], encode(value), engine.clock()),
            )
        advance(engine, sid)
        return {"switch_id": sid, "status": "complete", "target": value["target"]}


def advance(engine, switch_id):
    """Recover only explicitly acknowledged stages; ambiguous names are conflicts."""
    from pathlib import Path

    from seed_agent.media_import import filesystem as fs
    from seed_agent.media_import import roots

    with engine.store._connect() as conn:
        record = conn.execute(
            "SELECT payload_json,status FROM media_variant_switches WHERE id=?", (switch_id,)
        ).fetchone()
    if not record:
        raise ValueError("unknown variant switch")
    value, stage = json.loads(record[0]), record[1]
    root = roots.validate(value["descriptor"], value["target"])
    target = Path(value["target"])
    temporary = target.parent / (".media-variant-" + switch_id)
    expected = value["source_receipt"]
    if stage in {"pending", "temporary", "linked"}:
        if projection(engine, value["old_source_id"], value["new_source_id"]) != value:
            raise ValueError("variant baseline changed")
    if stage == "pending":
        if temporary.exists() or temporary.is_symlink() or target.exists() or target.is_symlink():
            raise ValueError("unknown variant target or temporary")
        engine._link(
            Path(value["source_root"]),
            Path(value["source_path"]),
            root,
            temporary,
            source_identity=value["source_identity"],
            target_identity=value["descriptor"]["identity"],
            expected=expected,
        )
        if fs.receipt(root, temporary) != expected:
            raise ValueError("variant temporary changed")
        with engine.store._connect() as conn:
            conn.execute(
                "UPDATE media_variant_switches SET status='temporary' "
                "WHERE id=? AND status='pending'",
                (switch_id,),
            )
        stage = "temporary"
    if stage == "temporary":
        if fs.receipt(root, temporary) != expected or target.exists() or target.is_symlink():
            raise ValueError("variant target is unknown or temporary changed")
        engine._link(
            root,
            temporary,
            root,
            target,
            source_identity=value["descriptor"]["identity"],
            target_identity=value["descriptor"]["identity"],
            expected=expected,
        )
        if fs.receipt(root, target) != expected:
            raise ValueError("new variant receipt changed")
        with engine.store._connect() as conn:
            conn.execute(
                "UPDATE media_variant_switches SET status='linked' "
                "WHERE id=? AND status='temporary'",
                (switch_id,),
            )
        stage = "linked"
    if stage == "linked":
        if fs.receipt(root, temporary) != expected or fs.receipt(root, target) != expected:
            raise ValueError("variant witnesses changed")
        with engine.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT source_id,revision FROM media_variant_selections WHERE work_key=?",
                (value["work_key"],),
            ).fetchone()
            if current != (value["old_source_id"], value["revision"]):
                raise ValueError("selection revision changed")
            conn.execute(
                "INSERT INTO media_artifacts VALUES(?,?,?,?,1,'active',?,?)",
                (
                    switch_id,
                    str(target),
                    value["new_profile"],
                    "video",
                    encode(expected),
                    engine.clock(),
                ),
            )
            roots.record_artifact(conn, switch_id, value["descriptor"])
            conn.execute(
                "INSERT INTO media_artifact_sources VALUES(?,?)",
                (switch_id, value["new_source_id"]),
            )
            conn.execute(
                "UPDATE media_variant_selections SET source_id=?,revision=revision+1 "
                "WHERE work_key=? AND source_id=? AND revision=?",
                (
                    value["new_source_id"],
                    value["work_key"],
                    value["old_source_id"],
                    value["revision"],
                ),
            )
            conn.execute(
                "UPDATE media_source_files SET status='retained_not_selected' WHERE id=?",
                (value["old_source_id"],),
            )
            conn.execute(
                "UPDATE media_source_files SET status='imported',readiness='operator' WHERE id=?",
                (value["new_source_id"],),
            )
            conn.execute(
                "INSERT INTO media_completion_reviews VALUES(?,?,?,'operator',?) "
                "ON CONFLICT(source_id) DO UPDATE SET generation=excluded.generation, "
                "fingerprint=excluded.fingerprint,basis=excluded.basis,created=excluded.created",
                (
                    value["new_source_id"],
                    value["new_fence"]["generation"],
                    value["new_fence"]["fingerprint"],
                    engine.clock(),
                ),
            )
            engine.event(
                conn,
                value["new_source_id"],
                "variant_completion_confirmed",
                {
                    "generation": value["new_fence"]["generation"],
                    "fingerprint": value["new_fence"]["fingerprint"],
                    "switch_id": switch_id,
                },
            )
            conn.execute(
                "UPDATE media_import_jobs SET status='imported',target=? WHERE source_id=?",
                (str(target), value["new_source_id"]),
            )
            conn.execute(
                "INSERT INTO media_plan_routes(source_id,revision,descriptor_json) VALUES(?,?,?) "
                "ON CONFLICT(source_id,revision) DO UPDATE SET "
                "descriptor_json=excluded.descriptor_json",
                (
                    value["new_source_id"],
                    value["new_fence"]["revision"],
                    encode(value["descriptor"]),
                ),
            )
            conn.execute(
                "UPDATE media_subtitle_jobs SET status='missing',next_attempt=0,claim_token=NULL,"
                "payload_json=? WHERE source_id=? AND status='cancelled'",
                (
                    encode(
                        {
                            "downloaded": [],
                            "digests": [],
                            "discovery_version": 1,
                            "search_state": "not_searched",
                            "external_state": "missing",
                        }
                    ),
                    value["new_source_id"],
                ),
            )
            conn.execute(
                "UPDATE media_subtitle_jobs SET status='cancelled',claim_token=NULL "
                "WHERE source_id=?",
                (value["old_source_id"],),
            )
            conn.execute(
                "UPDATE media_variant_switches SET status='retire' WHERE id=? AND status='linked'",
                (switch_id,),
            )
        stage = "retire"
    if stage == "retire":
        retire(engine, switch_id, value, temporary)
    elif stage != "done":
        raise ValueError("invalid variant switch stage")


def retire(engine, switch_id, value, temporary):
    from pathlib import Path

    from seed_agent.media_import import filesystem as fs
    from seed_agent.media_import import roots

    def check():
        engine.write_gate("import")
        if engine.configuration_revision() != value["old_fence"]["config_revision"]:
            raise ValueError("variant configuration changed")
        with engine.store._connect() as conn:
            selection = conn.execute(
                "SELECT source_id,revision FROM media_variant_selections WHERE work_key=?",
                (value["work_key"],),
            ).fetchone()
            new_fence = engine.publication_fence(conn, value["new_source_id"])
            old_fence = engine.publication_fence(conn, value["old_source_id"])
        if {k: v for k, v in old_fence.items() if k != "variant_selection"} != {
            k: v for k, v in value["old_fence"].items() if k != "variant_selection"
        }:
            raise ValueError("old variant plan changed during retirement")
        if selection != (value["new_source_id"], value["revision"] + 1):
            raise ValueError("variant selection changed during retirement")
        original = value["new_fence"]
        if (
            new_fence["generation"],
            new_fence["fingerprint"],
            new_fence["revision"],
            new_fence["review_revision"],
            new_fence["mapping_json"],
            new_fence["target"],
        ) != (
            original["generation"],
            original["fingerprint"],
            original["revision"],
            original["review_revision"],
            original["mapping_json"],
            value["target"],
        ):
            raise ValueError("new variant plan changed during retirement")
        for profile_name, root_key, path_key, identity_key, fingerprint in (
            (
                value["old_profile"],
                "old_source_root",
                "old_source_path",
                "old_source_identity",
                value["old_fence"]["fingerprint"],
            ),
            (
                value["new_profile"],
                "source_root",
                "source_path",
                "source_identity",
                original["fingerprint"],
            ),
        ):
            profile = engine.profile(profile_name)
            identity = fs.root_health(Path(value[root_key]), profile.marker, profile.marker_value)
            if (
                identity != value[identity_key]
                or fs.fingerprint(Path(value[path_key])) != fingerprint
            ):
                raise ValueError("variant source/root changed during retirement")
        root = roots.validate(value["descriptor"], value["target"])
        if fs.receipt(root, Path(value["target"])) != value["source_receipt"]:
            raise ValueError("new variant target changed during retirement")
        return root

    def save():
        with engine.store._connect() as conn:
            conn.execute(
                "UPDATE media_variant_switches SET payload_json=? WHERE id=? AND status='retire'",
                (encode(value), switch_id),
            )

    for index, item in enumerate(value["old_manifest"]):
        root = check()
        path = Path(item["path"])
        backup = path.parent / (".media-variant-backup-" + switch_id + "-" + str(index))
        state = item.get("retirement", "initial")
        if state == "initial":
            if backup.exists() or backup.is_symlink():
                raise ValueError("unknown variant backup path")
            if fs.receipt(root, path, digest="digest" in item["receipt"]) != item["receipt"]:
                raise ValueError("old version asset changed")
            item["retirement"] = "backup_intent"
            save()
            state = "backup_intent"
        if state == "backup_intent":
            if backup.exists() or backup.is_symlink():
                raise ValueError("unacknowledged variant backup path occupied")
            engine._link(
                root,
                path,
                root,
                backup,
                source_identity=value["descriptor"]["identity"],
                target_identity=value["descriptor"]["identity"],
                expected=item["receipt"],
            )
            if fs.receipt(root, backup, digest="digest" in item["receipt"]) != item["receipt"]:
                raise ValueError("variant backup changed")
            item["retirement"] = "backup_ready"
            save()
            state = "backup_ready"
        if state == "backup_ready":
            if fs.receipt(root, backup, digest="digest" in item["receipt"]) != item["receipt"]:
                raise ValueError("variant backup changed")
            with engine.store._connect() as conn:
                changed = conn.execute(
                    "UPDATE media_artifacts SET status='retiring' WHERE id=? AND status='active'",
                    (item["id"],),
                ).rowcount
                if changed != 1:
                    raise ValueError("old version ownership changed")
                item["retirement"] = "unlink_intent"
                conn.execute(
                    "UPDATE media_variant_switches SET payload_json=? WHERE id=?",
                    (encode(value), switch_id),
                )
            state = "unlink_intent"
        if state == "unlink_intent":
            check()
            if fs.receipt(root, backup, digest="digest" in item["receipt"]) != item["receipt"]:
                raise ValueError("variant backup changed before retirement")
            if path.exists() or path.is_symlink():
                engine._unlink(
                    root, path, item["receipt"], root_identity=value["descriptor"]["identity"]
                )
            with engine.store._connect() as conn:
                conn.execute(
                    "UPDATE media_artifacts SET status='retired' WHERE id=? AND status='retiring'",
                    (item["id"],),
                )
                item["retirement"] = "retired"
                conn.execute(
                    "UPDATE media_variant_switches SET payload_json=? WHERE id=?",
                    (encode(value), switch_id),
                )
    for index, item in enumerate(value["old_manifest"]):
        root = check()
        backup = Path(item["path"]).parent / (
            ".media-variant-backup-" + switch_id + "-" + str(index)
        )
        if item.get("retirement") == "retired":
            item["retirement"] = "backup_cleanup"
            save()
        if item.get("retirement") == "backup_cleanup":
            if backup.exists() or backup.is_symlink():
                engine._unlink(
                    root, backup, item["receipt"], root_identity=value["descriptor"]["identity"]
                )
            item["retirement"] = "done"
            save()
    root = check()
    if temporary.exists() or temporary.is_symlink():
        engine._unlink(
            root, temporary, value["source_receipt"], root_identity=value["descriptor"]["identity"]
        )
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_variant_switches SET status='done' WHERE id=? AND status='retire'",
            (switch_id,),
        )


def recover(engine, *, should_yield=None):
    if engine.config.import_policy != "execute":
        return False
    with engine.store._connect() as conn:
        pending = conn.execute(
            "SELECT id FROM media_variant_switches WHERE status IN "
            "('pending','temporary','linked','retire') ORDER BY created"
        ).fetchall()
    for (switch_id,) in pending:
        if should_yield and should_yield():
            return True
        try:
            advance(engine, switch_id)
        except (OSError, ValueError) as exc:
            with engine.store._connect() as conn:
                prior = conn.execute(
                    "SELECT status FROM media_variant_switches WHERE id=?", (switch_id,)
                ).fetchone()
                conn.execute(
                    "UPDATE media_variant_switches SET status='conflict' WHERE id=?", (switch_id,)
                )
                engine.event(
                    conn,
                    None,
                    "variant_recovery_conflict",
                    {"switch_id": switch_id, "stage": prior[0], "error_type": type(exc).__name__},
                )
    return False
