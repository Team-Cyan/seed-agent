"""Explicit offline migration of an independent schema-4 media database."""

import hashlib
import os
import sqlite3
import stat
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

from seed_agent.maintenance import _schema_signature
from seed_agent.media_import.schema import EXTRAS_SCHEMA, SCHEMA, VARIANTS_SCHEMA
from seed_agent.media_import.store import CONTROL_SCHEMA, bounded_lock, validate_schema
from seed_agent.runtime_identity import verify_runtime_identity


def migrate_schema4(path, *, expected_epoch=None, backup=None, expected_backup_sha256=None):
    """Migrate a stopped, backed-up media store; never called by normal startup.

    The caller must first stop all roles and make/verify a consistent backup.
    The worker and media leases prevent cooperating writers during the migration.
    """
    verify_runtime_identity()
    if (backup is None) != (expected_backup_sha256 is None):
        raise ValueError("backup and expected SHA-256 must be supplied together")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("media database must be an existing regular file")
    with closing(sqlite3.connect(":memory:")) as scratch:
        scratch.executescript(SCHEMA + CONTROL_SCHEMA)
        old_signature = _schema_signature(scratch)
    with (
        bounded_lock(Path(str(path) + ".worker.lock"), exclusive=True, timeout=0),
        bounded_lock(Path(str(path) + ".media.lock"), exclusive=True, timeout=0),
        bounded_lock(Path(str(path) + ".access.lock"), exclusive=True, timeout=0),
        closing(sqlite3.connect(path)) as conn,
    ):
        conn.execute("BEGIN EXCLUSIVE")
        current = conn.execute(
            "SELECT epoch,schema_version FROM media_control WHERE id=1"
        ).fetchone()
        if not current or current[1] != 4:
            raise ValueError("expected schema 4")
        if expected_epoch is not None and current[0] != expected_epoch:
            raise ValueError("media epoch changed before migration")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
            raise ValueError("unsupported views/triggers")
        if _schema_signature(conn) != old_signature:
            raise ValueError("schema 4 signature mismatch")
        for query in (
            "SELECT 1 FROM media_commands WHERE status IN ('queued','running') LIMIT 1",
            "SELECT 1 FROM media_publications WHERE status='pending' LIMIT 1",
            "SELECT 1 FROM media_artifacts WHERE status IN "
            "('publishing','deleting','retiring') LIMIT 1",
            # Finished jobs retain claim tokens as stale-publisher fences.
            # Only running state denotes work that must be reconciled offline.
            "SELECT 1 FROM media_subtitle_jobs WHERE status='running' LIMIT 1",
            "SELECT 1 FROM media_reconcile_actions WHERE status='executing' LIMIT 1",
            "SELECT 1 FROM media_scan_runs WHERE status='running' LIMIT 1",
        ):
            if conn.execute(query).fetchone():
                raise ValueError("active media work requires reconciliation before migration")
        if backup is not None:
            _validate_backup(
                conn, Path(backup), expected_backup_sha256, old_signature, current[0], path
            )
        conn.execute(EXTRAS_SCHEMA.strip().rstrip(";"))
        for statement in VARIANTS_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "UPDATE media_control SET schema_version=5, epoch=? WHERE id=1", (uuid.uuid4().hex,)
        )
        conn.execute("DELETE FROM media_runtime_status")
        validate_schema(conn)
        conn.commit()


def _validate_backup(current, backup, expected_hash, signature, epoch, current_path):
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != 64
        or any(c not in "0123456789abcdef" for c in expected_hash)
    ):
        raise ValueError("invalid backup SHA-256")
    fd = os.open(backup, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) == (
            current_path.stat().st_dev,
            current_path.stat().st_ino,
        ):
            raise ValueError("backup must be a separate regular file")
        digest = hashlib.sha256()
        with tempfile.TemporaryDirectory(prefix="media-migration-") as directory:
            copy = Path(directory) / "backup.db"
            with os.fdopen(os.dup(fd), "rb") as src, copy.open("xb") as dst:
                while chunk := src.read(1024 * 1024):
                    digest.update(chunk)
                    dst.write(chunk)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) or digest.hexdigest() != expected_hash:
                raise ValueError("backup SHA-256 or identity changed")
            with closing(sqlite3.connect(f"file:{copy}?mode=ro&immutable=1", uri=True)) as saved:
                if saved.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("backup integrity check failed")
                if saved.execute(
                    "SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')"
                ).fetchone():
                    raise ValueError("backup views/triggers are unsupported")
                if _schema_signature(saved) != signature:
                    raise ValueError("backup schema mismatch")
                if saved.execute(
                    "SELECT epoch,schema_version FROM media_control WHERE id=1"
                ).fetchone() != (epoch, 4):
                    raise ValueError("backup epoch mismatch")
                tables = current.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                for (table,) in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    columns = current.execute(f"PRAGMA table_info({quoted})").fetchall()
                    order = ",".join(str(i + 1) for i in range(len(columns)))
                    sql = f"SELECT * FROM {quoted} ORDER BY {order}"
                    left, right = current.execute(sql), saved.execute(sql)
                    while True:
                        a, b = left.fetchmany(256), right.fetchmany(256)
                        if a != b:
                            raise ValueError("backup logical contents differ from current state")
                        if not a:
                            break
    finally:
        os.close(fd)
