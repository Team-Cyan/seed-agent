"""Persist explicit completion evidence independently of media identity."""

import json
import sqlite3
from pathlib import Path

from seed_agent.media_import import filesystem as fs


def confirm(engine, source_id, generation, fingerprint, *, completion_confirmed):
    if completion_confirmed is not True or type(generation) is not int or generation < 1:
        raise ValueError("exact source generation and explicit confirmation required")
    if not isinstance(source_id, str) or not isinstance(fingerprint, str):
        raise ValueError("invalid source identity")
    with engine.lease():
        with engine.store._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT * FROM media_source_files WHERE id=?", (source_id,)
            ).fetchone()
            if not row:
                raise ValueError("unknown source")
            source = dict(row)
            latest = conn.execute(
                "SELECT MAX(generation) FROM media_source_files WHERE profile=? AND path=?",
                (source["profile"], source["path"]),
            ).fetchone()[0]
            previous = conn.execute(
                "SELECT root_identity FROM media_scan_runs WHERE profile=? AND status='complete' "
                "ORDER BY id DESC LIMIT 1",
                (source["profile"],),
            ).fetchone()
        if (
            source["generation"] != generation
            or source["fingerprint"] != fingerprint
            or source["missing_count"]
            or source["status"] == "removed"
            or source["stable_count"] < 2
            or latest != generation
        ):
            raise ValueError("source generation unavailable or unstable")
        profile = engine.profile(source["profile"])
        root = Path(profile.source_root)
        root_id = fs.root_health(root, profile.marker, profile.marker_value)
        if not previous:
            raise ValueError("complete source observation required")
        prior = json.loads(previous[0])
        if isinstance(prior, list):
            prior = prior[0]
        if prior != root_id:
            raise ValueError("source root identity changed")
        path = root / source["path"]
        receipt = fs.receipt(root, path)
        measured = json.dumps(
            [receipt["dev"], receipt["ino"], receipt["size"], receipt["mtime_ns"]]
        )
        if (
            engine.clock() - receipt["mtime_ns"] / 1_000_000_000 < profile.min_age_seconds
            or measured != fingerprint
            or fs.root_health(root, profile.marker, profile.marker_value) != root_id
        ):
            raise ValueError("source fingerprint/root changed or minimum age not met")
        if engine.config_guard is not None:
            from seed_agent.config_views import load_view

            view = load_view(engine.config_guard.view.path, "media")
            if (
                view.source_id != engine.config_guard.view.source_id
                or view.effective_revision != engine.config_guard.view.effective_revision
                or not view.config.media_import.enabled
            ):
                raise ValueError("configuration changed")
        with engine.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT generation,fingerprint,missing_count,status,stable_count "
                "FROM media_source_files WHERE id=?",
                (source_id,),
            ).fetchone()
            epoch = conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()
            if (
                current != (generation, fingerprint, 0, source["status"], source["stable_count"])
                or not epoch
                or epoch[0] != engine.store_epoch
            ):
                raise ValueError("source or restore epoch changed")
            conn.execute(
                "INSERT INTO media_completion_reviews VALUES(?,?,?,'operator',?) "
                "ON CONFLICT(source_id) DO UPDATE SET generation=excluded.generation, "
                "fingerprint=excluded.fingerprint,basis=excluded.basis,created=excluded.created",
                (source_id, generation, fingerprint, engine.clock()),
            )
            conn.execute(
                "UPDATE media_source_files SET readiness='operator' WHERE id=?", (source_id,)
            )
            engine.event(
                conn,
                source_id,
                "completion_confirmed",
                {"generation": generation, "fingerprint": fingerprint, "basis": "operator"},
            )
    return {
        "source_id": source_id,
        "generation": generation,
        "fingerprint": fingerprint,
        "readiness": "operator",
    }
