from __future__ import annotations

import gzip
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from seed_agent.audit import AuditLogger
from seed_agent.maintenance import (
    archive_audit_jsonl,
    backup_sqlite_database,
    restore_sqlite_database,
    storage_health,
    verify_sqlite_database,
)
from seed_agent.models import Decision, LifecycleState
from seed_agent.state import StateStore

_LEGACY_CANDIDATES_SCHEMA = """
CREATE TABLE candidates (
  stable_id TEXT PRIMARY KEY,
  site TEXT NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  score INTEGER,
  torrent_hash TEXT,
  first_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_candidates_state ON candidates(state);
CREATE INDEX idx_candidates_hash ON candidates(torrent_hash);
"""


def _create_database(path: Path, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)


def test_sqlite_backup_verify_and_restore_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        "demo:1",
        "Original",
        "demo",
        LifecycleState.DISCOVERED,
        score=None,
        torrent_hash=None,
    )
    backup_path = tmp_path / ".seed-agent" / "backups" / "state-test.db"

    backup = backup_sqlite_database(state_path, backup_path)
    store.upsert_candidate(
        "demo:2",
        "Later",
        "demo",
        LifecycleState.DISCOVERED,
        score=None,
        torrent_hash=None,
    )
    preview = restore_sqlite_database(state_path, backup_path, execute=False)
    restored = restore_sqlite_database(state_path, backup_path, execute=True)
    restored_store = StateStore(state_path)

    assert backup["valid"] is True
    assert preview["status"] == "dry_run"
    assert restored["status"] == "restored"
    assert restored_store.get_candidate("demo:1") is not None
    assert restored_store.get_candidate("demo:2") is None
    assert verify_sqlite_database(state_path)["valid"] is True


def test_sqlite_verify_and_restore_migratable_legacy_schema(tmp_path: Path) -> None:
    state_path = tmp_path / "state.db"
    StateStore(state_path)
    backup_path = tmp_path / "legacy.db"
    _create_database(backup_path, _LEGACY_CANDIDATES_SCHEMA)
    with sqlite3.connect(backup_path) as conn:
        conn.execute(
            """
            INSERT INTO candidates (
              stable_id, site, title, state, score, torrent_hash,
              first_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy:1",
                "legacy",
                "Legacy candidate",
                "discovered",
                None,
                None,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    verification = verify_sqlite_database(backup_path)
    restored = restore_sqlite_database(state_path, backup_path, execute=True)

    assert verification["valid"] is True
    assert verification["schema_status"] == "migratable"
    assert restored["status"] == "restored"
    assert restored["restored"]["schema_status"] == "current"
    assert StateStore(state_path).get_candidate("legacy:1") is not None


@pytest.mark.parametrize(
    ("schema", "case"),
    [
        ("CREATE TABLE candidates (stable_id TEXT PRIMARY KEY);", "missing_columns"),
        (
            _LEGACY_CANDIDATES_SCHEMA.replace("stable_id TEXT PRIMARY KEY", "stable_id TEXT"),
            "wrong_primary_key",
        ),
        (
            _LEGACY_CANDIDATES_SCHEMA
            + "CREATE TABLE release_candidates (forged TEXT PRIMARY KEY);",
            "forged_runtime_table",
        ),
    ],
)
def test_sqlite_verify_rejects_incompatible_runtime_schema(
    tmp_path: Path,
    schema: str,
    case: str,
) -> None:
    path = tmp_path / f"{case}.db"
    _create_database(path, schema)

    verification = verify_sqlite_database(path)

    assert verification["valid"] is False
    assert verification["schema_status"] == "incompatible"
    assert verification["schema_error"]


def test_sqlite_restore_rejects_incompatible_backup_without_replacing_current(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        "current:1",
        "Current",
        "demo",
        LifecycleState.DISCOVERED,
        score=None,
        torrent_hash=None,
    )
    backup_path = tmp_path / "forged.db"
    _create_database(backup_path, "CREATE TABLE candidates (stable_id TEXT PRIMARY KEY);")

    result = restore_sqlite_database(state_path, backup_path, execute=True)

    assert result["status"] == "invalid_backup"
    assert StateStore(state_path).get_candidate("current:1") is not None


def test_sqlite_restore_is_blocked_by_active_scheduler_lease(tmp_path: Path) -> None:
    state_path = tmp_path / "state.db"
    store = StateStore(state_path)
    backup_path = tmp_path / "backup.db"
    backup_sqlite_database(state_path, backup_path)
    store.acquire_scheduler_lease(
        "active-owner",
        ttl_seconds=3600,
        now=datetime.now(UTC),
    )

    result = restore_sqlite_database(state_path, backup_path, execute=True)

    assert result["status"] == "blocked_active_scheduler"
    assert result["active_scheduler_lease"]["owner_id"] == "active-owner"


def test_audit_archive_preserves_jsonl_and_allows_new_writes(tmp_path: Path) -> None:
    audit_path = tmp_path / ".seed-agent" / "audit.jsonl"
    logger = AuditLogger(audit_path)
    logger.write(Decision(action="test.one", target_id="one", execute=False, reason="one"))
    logger.write(Decision(action="test.two", target_id="two", execute=False, reason="two"))

    preview = archive_audit_jsonl(
        audit_path,
        tmp_path / ".seed-agent" / "audit-archives",
        execute=False,
    )
    archived = archive_audit_jsonl(
        audit_path,
        tmp_path / ".seed-agent" / "audit-archives",
        execute=True,
    )
    archive_path = Path(archived["archive"])
    archived_text = gzip.decompress(archive_path.read_bytes()).decode("utf-8")
    logger.write(Decision(action="test.three", target_id="three", execute=False, reason="three"))

    assert preview["status"] == "dry_run"
    assert archived["status"] == "archived"
    assert archived_text.count("\n") == 2
    assert "test.one" in archived_text
    assert "test.two" in archived_text
    assert "test.three" in audit_path.read_text(encoding="utf-8")
    assert "test.one" not in audit_path.read_text(encoding="utf-8")


def test_storage_health_reports_wal_backup_and_archive_state(tmp_path: Path) -> None:
    runtime_root = tmp_path / ".seed-agent"
    state_path = runtime_root / "state.db"
    StateStore(state_path)
    backup_sqlite_database(state_path, runtime_root / "backups" / "state-test.db")
    (runtime_root / "audit-archives").mkdir(parents=True)
    (runtime_root / "audit-archives" / "audit-test.jsonl.gz").write_bytes(b"archive")

    health = storage_health(runtime_root)

    assert health["database"]["valid"] is True
    assert health["backup_count"] == 1
    assert health["audit_archive_count"] == 1
    assert health["latest_backup"]["path"].endswith("state-test.db")
