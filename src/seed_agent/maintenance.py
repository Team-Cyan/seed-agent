from __future__ import annotations

import fcntl
import gzip
import os
import re
import sqlite3
import tempfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


def verify_sqlite_database(path: Path) -> dict[str, Any]:
    if not path.is_file():
        error = "database file is missing"
        return {
            "valid": False,
            "path": str(path),
            "error": error,
            "schema_status": "missing",
            "schema_error": error,
        }
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            integrity_rows = [
                str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall()
            ]
            integrity = "; ".join(integrity_rows)
            tables = sorted(
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    """
                )
            )
            if integrity_rows == ["ok"]:
                schema_status, schema_error = _runtime_schema_status(conn)
            else:
                schema_status = "incompatible"
                schema_error = f"integrity check failed: {integrity}"
    except sqlite3.Error as exc:
        error = str(exc)
        return {
            "valid": False,
            "path": str(path),
            "error": error,
            "schema_status": "unreadable",
            "schema_error": error,
        }
    required = set(_expected_runtime_schema()["tables"])
    missing = sorted(required - set(tables))
    return {
        "valid": integrity_rows == ["ok"] and schema_status in {"current", "migratable"},
        "path": str(path),
        "integrity": integrity,
        "tables": tables,
        "missing_required_tables": missing,
        "schema_status": schema_status,
        "schema_error": schema_error,
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
    restore_copy = current.with_suffix(".restore.tmp")
    _remove_sqlite_files(restore_copy)
    restored = backup_sqlite_database(backup, restore_copy)
    if not restored["valid"]:
        _remove_sqlite_files(restore_copy)
        return {**payload, "status": "invalid_restored_copy"}
    try:
        from seed_agent.state import StateStore

        StateStore(restore_copy)
        _checkpoint_sqlite_database(restore_copy)
    except (OSError, sqlite3.Error) as exc:
        _remove_sqlite_files(restore_copy)
        return {
            **payload,
            "status": "invalid_restored_copy",
            "restore_error": str(exc),
        }
    migrated = verify_sqlite_database(restore_copy)
    if not migrated["valid"] or migrated["schema_status"] != "current":
        _remove_sqlite_files(restore_copy)
        return {
            **payload,
            "status": "invalid_restored_copy",
            "restored_copy": migrated,
        }
    os.replace(restore_copy, current)
    _remove_sqlite_sidecars(restore_copy)
    for suffix in ("-wal", "-shm"):
        Path(f"{current}{suffix}").unlink(missing_ok=True)
    return {**payload, "status": "restored", "restored": verify_sqlite_database(current)}


@lru_cache(maxsize=1)
def _expected_runtime_schema() -> dict[str, Any]:
    from seed_agent.state import StateStore

    with tempfile.TemporaryDirectory(prefix="seed-agent-schema-") as directory:
        path = Path(directory) / "expected.db"
        StateStore(path)
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            return _schema_signature(conn)


def _runtime_schema_status(conn: sqlite3.Connection) -> tuple[str, str | None]:
    source = _schema_signature(conn)
    expected = _expected_runtime_schema()
    if source == expected:
        return "current", None
    if "candidates" not in source["tables"]:
        return "incompatible", "missing candidates schema anchor"
    unsupported = sorted(
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE type IN ('trigger', 'view') AND name NOT LIKE 'sqlite_%'
            """
        )
    )
    if unsupported:
        return "incompatible", f"unsupported schema objects: {unsupported}"
    try:
        migrated = _migrated_schema_signature(conn)
    except (OSError, sqlite3.Error) as exc:
        return "incompatible", f"StateStore migration failed: {exc}"
    if migrated != expected:
        return "incompatible", _schema_difference(expected, migrated)
    return "migratable", None


def _migrated_schema_signature(source: sqlite3.Connection) -> dict[str, Any]:
    from seed_agent.state import StateStore

    schema_rows = source.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE type IN ('table', 'index')
          AND name NOT LIKE 'sqlite_%'
          AND sql IS NOT NULL
        ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name
        """
    ).fetchall()
    with tempfile.TemporaryDirectory(prefix="seed-agent-migration-") as directory:
        path = Path(directory) / "migrated.db"
        with sqlite3.connect(path) as migrated_conn:
            for _, _, sql in schema_rows:
                migrated_conn.execute(str(sql))
        StateStore(path)
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as migrated_conn:
            return _schema_signature(migrated_conn)


def _schema_signature(conn: sqlite3.Connection) -> dict[str, Any]:
    table_rows = conn.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    table_flags = {
        str(row[1]): {"without_rowid": bool(row[4]), "strict": bool(row[5])}
        for row in conn.execute("PRAGMA table_list").fetchall()
        if str(row[2]) == "table" and not str(row[1]).startswith("sqlite_")
    }
    tables: dict[str, Any] = {}
    for raw_name, raw_sql in table_rows:
        name = str(raw_name)
        quoted = _quote_identifier(name)
        columns = {
            str(row[1]): {
                "type": str(row[2]).upper(),
                "not_null": bool(row[3]),
                "default": row[4],
                "primary_key_position": int(row[5]),
                "hidden": int(row[6]),
            }
            for row in conn.execute(f"PRAGMA table_xinfo({quoted})").fetchall()
        }
        indexes: dict[str, Any] = {}
        for index_row in conn.execute(f"PRAGMA index_list({quoted})").fetchall():
            index_name = str(index_row[1])
            index_quoted = _quote_identifier(index_name)
            indexes[index_name] = {
                "unique": bool(index_row[2]),
                "origin": str(index_row[3]),
                "partial": bool(index_row[4]),
                "columns": [
                    {
                        "name": row[2],
                        "descending": bool(row[3]),
                        "collation": row[4],
                        "key": bool(row[5]),
                    }
                    for row in conn.execute(f"PRAGMA index_xinfo({index_quoted})").fetchall()
                ],
            }
        sql = str(raw_sql or "")
        tables[name] = {
            "columns": columns,
            "indexes": indexes,
            "foreign_keys": [
                tuple(row) for row in conn.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
            ],
            **table_flags.get(name, {"without_rowid": False, "strict": False}),
            "has_check_constraint": bool(re.search(r"\bCHECK\s*\(", sql, re.IGNORECASE)),
            "has_explicit_collation": bool(re.search(r"\bCOLLATE\b", sql, re.IGNORECASE)),
        }
    return {"tables": tables}


def _schema_difference(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    expected_tables = expected["tables"]
    actual_tables = actual["tables"]
    details: list[str] = []
    missing = sorted(set(expected_tables) - set(actual_tables))
    unexpected = sorted(set(actual_tables) - set(expected_tables))
    if missing:
        details.append(f"missing tables: {missing}")
    if unexpected:
        details.append(f"unexpected tables: {unexpected}")
    for name in sorted(set(expected_tables).intersection(actual_tables)):
        expected_table = expected_tables[name]
        actual_table = actual_tables[name]
        if expected_table == actual_table:
            continue
        expected_columns = expected_table["columns"]
        actual_columns = actual_table["columns"]
        missing_columns = sorted(set(expected_columns) - set(actual_columns))
        unexpected_columns = sorted(set(actual_columns) - set(expected_columns))
        changed_columns = sorted(
            column
            for column in set(expected_columns).intersection(actual_columns)
            if expected_columns[column] != actual_columns[column]
        )
        if missing_columns:
            details.append(f"{name} missing columns: {missing_columns}")
        if unexpected_columns:
            details.append(f"{name} unexpected columns: {unexpected_columns}")
        if changed_columns:
            details.append(f"{name} incompatible columns: {changed_columns}")
        if expected_table["indexes"] != actual_table["indexes"]:
            details.append(f"{name} indexes or primary key differ")
        for key in (
            "foreign_keys",
            "without_rowid",
            "strict",
            "has_check_constraint",
            "has_explicit_collation",
        ):
            if expected_table[key] != actual_table[key]:
                details.append(f"{name} {key} differs")
    return "; ".join(details[:8]) or "runtime schema differs from StateStore schema"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    _remove_sqlite_sidecars(path)


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _checkpoint_sqlite_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if checkpoint is None or int(checkpoint[0]) != 0:
        raise sqlite3.OperationalError(f"failed to checkpoint restored database: {checkpoint}")


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
