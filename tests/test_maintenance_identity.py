"""Maintenance public ingress rejects before its own effects, not later Store use."""

import os
import sqlite3
from pathlib import Path

import pytest

from seed_agent.maintenance import (
    backup_sqlite_database,
    restore_sqlite_database,
    verify_sqlite_database,
)
from seed_agent.runtime_identity import RuntimeIdentityError
from seed_agent.state import StateStore


def tree_snapshot(root):
    return {
        str(p.relative_to(root)): (
            p.stat().st_mode,
            p.stat().st_mtime_ns,
            p.read_bytes() if p.is_file() else None,
        )
        for p in [root, *root.rglob("*")]
    }


@pytest.mark.parametrize(
    "operation",
    ["verify-existing", "verify-missing", "backup", "restore-dry-run", "restore-execute"],
)
@pytest.mark.parametrize("existing_destination", [False, True])
def test_wrong_identity_has_zero_maintenance_effects(
    tmp_path, monkeypatch, operation, existing_destination
):
    monkeypatch.delenv("PUID", raising=False)
    monkeypatch.delenv("PGID", raising=False)
    source = tmp_path / "source.db"
    StateStore(source)
    assert verify_sqlite_database(source)["valid"]
    # Nonprivate fixture mode detects a late privacy operation even if bytes match.
    source.chmod(0o664)
    target = tmp_path / "destination" / "nested" / "state.db"
    if existing_destination:
        target.parent.mkdir(parents=True)
        target.write_bytes(b"preserve existing destination")
        target.chmod(0o664)
    before = tree_snapshot(tmp_path)
    monkeypatch.setenv("PUID", str(os.geteuid() + 1))
    monkeypatch.setenv("PGID", str(os.getegid()))
    opens = []

    def forbidden_connect(*args, **kwargs):
        opens.append(True)
        raise AssertionError("SQLite called before identity rejection")

    monkeypatch.setattr(sqlite3, "connect", forbidden_connect)
    with pytest.raises(RuntimeIdentityError):
        if operation.startswith("verify-"):
            verify_sqlite_database(
                source if operation.endswith("existing") else tmp_path / "missing-fixture.db"
            )
        elif operation == "backup":
            backup_sqlite_database(source, target)
        else:
            restore_sqlite_database(target, source, execute=operation.endswith("execute"))
    assert opens == []
    assert tree_snapshot(tmp_path) == before
    assert not Path(str(target) + ".access.lock").exists()


@pytest.mark.parametrize("configured", [False, True])
def test_valid_and_env_absent_maintenance_roundtrip_unchanged(tmp_path, monkeypatch, configured):
    for key in ["PUID", "PGID"]:
        monkeypatch.delenv(key, raising=False)
    if configured:
        monkeypatch.setenv("PUID", str(os.geteuid()))
        monkeypatch.setenv("PGID", str(os.getegid()))
    source, backup, current = [tmp_path / name for name in ["source.db", "backup.db", "current.db"]]
    StateStore(source)
    assert verify_sqlite_database(source)["valid"]
    assert verify_sqlite_database(tmp_path / "missing.db")["schema_status"] == "missing"
    assert backup_sqlite_database(source, backup)["valid"]
    assert restore_sqlite_database(current, backup, execute=False)["status"] == "dry_run"
    assert not current.exists()
    assert restore_sqlite_database(current, backup, execute=True)["status"] == "restored"
    assert verify_sqlite_database(current)["valid"]
