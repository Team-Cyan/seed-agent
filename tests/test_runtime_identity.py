import os
import stat

import pytest
from typer.testing import CliRunner

from seed_agent import cli
from seed_agent.media_import.role_health import _read_state
from seed_agent.media_import.store import MediaStore
from seed_agent.runtime_identity import RuntimeIdentityError, verify_runtime_identity
from seed_agent.state import StateStore
from seed_agent.web.app import _read_state_connection


def mismatch(monkeypatch):
    monkeypatch.setenv("PUID", str(os.geteuid() + 1))
    monkeypatch.setenv("PGID", str(os.getegid()))


@pytest.mark.parametrize("store", [MediaStore, StateStore])
def test_constructor_identity_failure_has_no_filesystem_effect(tmp_path, monkeypatch, store):
    mismatch(monkeypatch)
    path = tmp_path / "missing" / "private" / "state.db"
    with pytest.raises(RuntimeIdentityError):
        store(path)
    assert not path.parent.parent.exists()
    existing = tmp_path / "state.db"
    existing.write_bytes(b"untouched")
    existing.chmod(0o664)
    before = (existing.read_bytes(), existing.stat())
    with pytest.raises(RuntimeIdentityError):
        store(existing, initialize=False)
    assert existing.read_bytes() == before[0]
    assert stat.S_IMODE(existing.stat().st_mode) == 0o664
    assert existing.stat().st_mtime_ns == before[1].st_mtime_ns
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.db"]


@pytest.mark.parametrize("store", [MediaStore, StateStore])
def test_connection_rechecks_identity_before_lock_or_privacy(tmp_path, monkeypatch, store):
    monkeypatch.delenv("PUID", raising=False)
    monkeypatch.delenv("PGID", raising=False)
    path = tmp_path / "state.db"
    path.write_bytes(b"untouched")
    obj = store(path, initialize=False)
    path.chmod(0o664)
    mismatch(monkeypatch)
    with pytest.raises(RuntimeIdentityError), obj._connect():
        pytest.fail("connection must not open")
    assert stat.S_IMODE(path.stat().st_mode) == 0o664
    assert not path.with_name("state.db.access.lock").exists()


@pytest.mark.parametrize(
    "reader", [_read_state, cli._state_database_health, _read_state_connection]
)
def test_direct_readers_reject_before_sqlite(tmp_path, monkeypatch, reader):
    mismatch(monkeypatch)
    path = tmp_path / "not-created.db"
    with pytest.raises(RuntimeIdentityError):
        value = reader(path)
        if reader is _read_state_connection:
            with value:
                pytest.fail("reader must not open")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "uid,gid",
    [("", "1"), ("1", ""), ("-1", "2"), ("a", "2"), ("9" * 5000, "2"), ("4294967295", "2")],
)
def test_bad_pair_fails_closed(monkeypatch, uid, gid):
    monkeypatch.setenv("PUID", uid)
    monkeypatch.setenv("PGID", gid)
    with pytest.raises(RuntimeIdentityError):
        verify_runtime_identity()


def test_actual_and_saved_identity_not_marker(monkeypatch):
    mismatch(monkeypatch)
    monkeypatch.setenv("SEED_AGENT_PRIVILEGES_DROPPED", "true")
    with pytest.raises(RuntimeIdentityError):
        verify_runtime_identity()
    monkeypatch.setenv("PUID", str(os.geteuid()))
    monkeypatch.setenv("PGID", str(os.getegid()))
    verify_runtime_identity()
    if hasattr(os, "getresuid"):
        monkeypatch.setattr(os, "getresuid", lambda: (0, os.geteuid(), 0))
        if os.geteuid() != 0:
            with pytest.raises(RuntimeIdentityError):
                verify_runtime_identity()


@pytest.mark.parametrize("role", ["seed", "media"])
@pytest.mark.parametrize("command", ["healthcheck", "runtime-status"])
def test_direct_cli_identity_failure_is_unhealthy_before_config(
    tmp_path, monkeypatch, role, command
):
    mismatch(monkeypatch)
    result = CliRunner().invoke(
        cli.app, [command, "--role", role, "--config", str(tmp_path / "absent")]
    )
    assert result.exit_code == 2
    assert "process identity" in result.output
    assert not list(tmp_path.iterdir())
    assert CliRunner().invoke(cli.app, ["--version"]).exit_code == 0


def test_env_absent_standalone_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("PUID", raising=False)
    monkeypatch.delenv("PGID", raising=False)
    verify_runtime_identity()
    assert StateStore(tmp_path / "seed.db")
    assert MediaStore(tmp_path / "media.db")
