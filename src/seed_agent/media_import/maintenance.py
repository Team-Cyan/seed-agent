"""Media-only snapshots and epoch-fenced restore; seed locks/tables are never involved."""

import json
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path

from seed_agent.media_import.store import MediaStore, bounded_lock, validate_schema


def verify_media_database(path: Path):
    if not path.is_file() or path.is_symlink():
        return {"valid": False, "error": "missing/unsafe media state"}
    try:
        store = MediaStore(path, initialize=False, read_only=True)
        with store._connect() as conn:
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                return {"valid": False, "error": "media integrity failed"}
            actual = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            version = conn.execute("SELECT schema_version FROM media_control WHERE id=1").fetchone()
            if not version or version[0] != MediaStore.schema_version:
                return {"valid": False, "error": "unsupported media schema"}
            validate_schema(conn)
            return {
                "valid": True,
                "schema_version": version[0],
                "tables": sorted(actual),
                "epoch": store.epoch(),
            }
    except OSError, ValueError, sqlite3.Error:
        return {"valid": False, "error": "unreadable media state"}


def backup_media_database(source: Path, destination: Path):
    checked = verify_media_database(source)
    if not checked["valid"]:
        raise ValueError(checked["error"])
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".media-backup-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        store = MediaStore(source, initialize=False, read_only=True)
        with store._connect() as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
        checked = verify_media_database(temporary)
        if not checked["valid"]:
            raise ValueError(checked["error"])
        os.chmod(temporary, 0o600)
        # Exclusive publication cannot replace another backup.
        os.link(temporary, destination)
        return {**checked, "path": str(destination)}
    finally:
        temporary.unlink(missing_ok=True)


def restore_media_database(current: Path, backup: Path, *, execute=False):
    checked = verify_media_database(backup)
    if not checked["valid"]:
        return {"status": "invalid_backup", "verification": checked}
    if not execute:
        return {"status": "preview", "verification": checked}
    with (
        bounded_lock(Path(str(current) + ".media.lock"), exclusive=True),
        bounded_lock(Path(str(current) + ".access.lock"), exclusive=True),
    ):
        fd, name = tempfile.mkstemp(prefix=".media-restore-", dir=current.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            budget_keys = set()
            if current.exists():
                with closing(sqlite3.connect(current, timeout=0.25)) as old:
                    budget_keys.update(
                        r[0]
                        for r in old.execute(
                            "SELECT provider FROM media_provider_state "
                            "WHERE provider LIKE '%:download-budget'"
                        )
                    )
            with (
                closing(sqlite3.connect(f"file:{backup.absolute()}?mode=ro", uri=True)) as src,
                closing(sqlite3.connect(temporary)) as dst,
            ):
                src.backup(dst)
                epoch = uuid.uuid4().hex
                dst.execute("UPDATE media_control SET epoch=? WHERE id=1", (epoch,))
                dst.execute(
                    "UPDATE media_subtitle_jobs SET claim_token=NULL,"
                    "status=CASE WHEN status='running' THEN 'retrying' ELSE status END,"
                    "next_attempt=CASE WHEN status='running' THEN 0 ELSE next_attempt END"
                )
                budget_keys.update(
                    r[0]
                    for r in dst.execute(
                        "SELECT provider FROM media_provider_state "
                        "WHERE provider LIKE '%:download-budget'"
                    )
                )
                for provider in budget_keys:
                    # A restored snapshot cannot refund downloads made after it.
                    dst.execute(
                        "INSERT INTO media_provider_state VALUES(?,?,?) ON CONFLICT(provider) "
                        "DO UPDATE SET next_request=excluded.next_request,status=excluded.status",
                        (
                            provider,
                            time.time() + 86400,
                            json.dumps({"remaining": 0, "reservation": "restore_wait"}),
                        ),
                    )
                dst.execute("DELETE FROM media_runtime_status")
                dst.execute(
                    "UPDATE media_commands SET status='superseded',claim_token=NULL "
                    "WHERE status IN ('queued','running')"
                )
                dst.commit()
            os.chmod(temporary, 0o600)
            # All media connections obey access.lock; checkpoint the old inode before replacing.
            if current.exists():
                with closing(sqlite3.connect(current, timeout=0.25)) as old:
                    result = old.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if result and result[0]:
                        raise TimeoutError("media reader prevents restore")
                for suffix in ["-wal", "-shm"]:
                    Path(str(current) + suffix).unlink(missing_ok=True)
            os.replace(temporary, current)
            return {"status": "restored", "epoch": epoch}
        finally:
            temporary.unlink(missing_ok=True)
