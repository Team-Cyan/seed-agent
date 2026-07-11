from __future__ import annotations

import fcntl
import gzip
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def verify_sqlite_database(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "path": str(path), "error": "database file is missing"}
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            tables = sorted(
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    """
                )
            )
    except sqlite3.Error as exc:
        return {"valid": False, "path": str(path), "error": str(exc)}
    required = {"candidates", "scheduler_runs", "scheduler_leases"}
    missing = sorted(required - set(tables))
    return {
        "valid": integrity == "ok" and not missing,
        "path": str(path),
        "integrity": integrity,
        "tables": tables,
        "missing_required_tables": missing,
        "size_bytes": path.stat().st_size,
    }


def backup_sqlite_database(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(source) as source_conn, sqlite3.connect(temporary) as target_conn:
            source_conn.backup(target_conn)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return verify_sqlite_database(destination)


def restore_sqlite_database(
    current: Path,
    backup: Path,
    *,
    execute: bool,
) -> dict[str, Any]:
    verification = verify_sqlite_database(backup)
    lease = _active_scheduler_lease(current)
    payload = {
        "execute": execute,
        "current": str(current),
        "backup": str(backup),
        "verification": verification,
        "active_scheduler_lease": lease,
    }
    if not verification["valid"]:
        return {**payload, "status": "invalid_backup"}
    if lease is not None:
        return {**payload, "status": "blocked_active_scheduler"}
    if not execute:
        return {**payload, "status": "dry_run"}
    restored = backup_sqlite_database(backup, current.with_suffix(".restore.tmp"))
    if not restored["valid"]:
        current.with_suffix(".restore.tmp").unlink(missing_ok=True)
        return {**payload, "status": "invalid_restored_copy"}
    os.replace(current.with_suffix(".restore.tmp"), current)
    for suffix in ("-wal", "-shm"):
        Path(f"{current}{suffix}").unlink(missing_ok=True)
    return {**payload, "status": "restored", "restored": verify_sqlite_database(current)}


def archive_audit_jsonl(
    audit_path: Path,
    archive_dir: Path,
    *,
    execute: bool,
) -> dict[str, Any]:
    size_bytes = audit_path.stat().st_size if audit_path.exists() else 0
    payload = {
        "execute": execute,
        "audit_path": str(audit_path),
        "size_bytes": size_bytes,
        "archive_dir": str(archive_dir),
    }
    if size_bytes == 0:
        return {**payload, "status": "empty"}
    if not execute:
        return {**payload, "status": "dry_run"}
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = archive_dir / f"audit-{timestamp}.jsonl.gz"
    if destination.exists():
        raise FileExistsError(f"audit archive already exists: {destination}")
    temporary = archive_dir / f".{destination.name}.tmp"
    with audit_path.open("a+b") as source:
        fcntl.flock(source.fileno(), fcntl.LOCK_EX)
        try:
            source.seek(0)
            content = source.read()
            compressed = gzip.compress(content, mtime=0)
            with temporary.open("xb") as target:
                target.write(compressed)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            source.seek(0)
            source.truncate()
            source.flush()
            os.fsync(source.fileno())
        finally:
            temporary.unlink(missing_ok=True)
            fcntl.flock(source.fileno(), fcntl.LOCK_UN)
    return {
        **payload,
        "status": "archived",
        "archive": str(destination),
        "archive_size_bytes": destination.stat().st_size,
    }


def storage_health(runtime_root: Path) -> dict[str, Any]:
    state_path = runtime_root / "state.db"
    backups = sorted((runtime_root / "backups").glob("state-*.db"), reverse=True)
    archives = sorted((runtime_root / "audit-archives").glob("audit-*.jsonl.gz"), reverse=True)
    return {
        "database": verify_sqlite_database(state_path),
        "wal_size_bytes": _size(Path(f"{state_path}-wal")),
        "shm_size_bytes": _size(Path(f"{state_path}-shm")),
        "audit_size_bytes": _size(runtime_root / "audit.jsonl"),
        "latest_backup": _file_summary(backups[0]) if backups else None,
        "backup_count": len(backups),
        "latest_audit_archive": _file_summary(archives[0]) if archives else None,
        "audit_archive_count": len(archives),
    }


def enforce_retention(directory: Path, pattern: str, keep: int) -> list[str]:
    removed: list[str] = []
    for path in sorted(directory.glob(pattern), reverse=True)[max(keep, 1) :]:
        path.unlink(missing_ok=True)
        removed.append(str(path))
    return removed


def _active_scheduler_lease(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scheduler_leases WHERE lease_name = 'schedule-run'"
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    lease = dict(row)
    try:
        expires_at = datetime.fromisoformat(str(lease["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if expires_at <= datetime.now(UTC):
        return None
    return lease


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _file_summary(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }
