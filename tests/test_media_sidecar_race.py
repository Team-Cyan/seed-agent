import errno
import os
import sqlite3
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from seed_agent.media_import.store import MediaStore, _restrict_sidecar


def test_disappearing_sidecar_is_harmless(tmp_path, monkeypatch):
    sidecar = tmp_path / "state.db-wal"
    sidecar.write_bytes(b"fixture")
    original = os.chmod

    def remove_before_chmod(path, mode, **kwargs):
        sidecar.unlink()
        original(path, mode, **kwargs)

    monkeypatch.setattr(os, "chmod", remove_before_chmod)
    _restrict_sidecar(sidecar)
    assert not sidecar.exists()


def test_symlink_replacement_never_changes_victim(tmp_path, monkeypatch):
    sidecar = tmp_path / "state.db-shm"
    sidecar.write_bytes(b"fixture")
    victim = tmp_path / "manual"
    victim.write_bytes(b"keep")
    victim.chmod(0o644)
    original = os.chmod

    def replace_before_chmod(path, mode, **kwargs):
        sidecar.unlink()
        sidecar.symlink_to(victim)
        original(path, mode, **kwargs)

    monkeypatch.setattr(os, "chmod", replace_before_chmod)
    try:
        _restrict_sidecar(sidecar)
    except NotImplementedError, OSError:
        # Linux rejects chmod of a symlink; macOS can chmod the link itself.
        pass
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644


def test_permission_failure_is_not_swallowed(tmp_path, monkeypatch):
    sidecar = tmp_path / "state.db-wal"
    sidecar.touch()

    def denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "fixture denied")

    monkeypatch.setattr(os, "chmod", denied)
    with pytest.raises(PermissionError):
        _restrict_sidecar(sidecar)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_nonregular_sidecar_is_rejected_without_blocking(tmp_path, kind):
    sidecar = tmp_path / "state.db-journal"
    if kind == "symlink":
        victim = tmp_path / "manual"
        victim.touch()
        sidecar.symlink_to(victim)
    else:
        os.mkfifo(sidecar)
    with pytest.raises(ValueError, match="regular file"):
        _restrict_sidecar(sidecar)


def test_store_connection_preserves_existing_sqlite_read_lock(tmp_path):
    path = tmp_path / "state.db"
    reader = sqlite3.connect(path)
    try:
        reader.execute("CREATE TABLE t(n)")
        reader.execute("INSERT INTO t VALUES(0)")
        reader.commit()
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM t").fetchall()
        store = MediaStore(path, initialize=False)
        with store._connect() as conn:
            assert conn.execute("SELECT * FROM t").fetchone() == (0,)
        child = (
            "import sqlite3,sys; c=sqlite3.connect(sys.argv[1],timeout=.05); "
            'c.execute("UPDATE t SET n=1"); c.commit()'
        )
        result = subprocess.run(
            [sys.executable, "-c", child, str(path)], capture_output=True, text=True, timeout=5
        )
        assert reader.in_transaction
        assert result.returncode != 0 and "database is locked" in result.stderr
    finally:
        reader.close()


def test_restrict_shm_preserves_process_posix_locks(tmp_path):
    import fcntl

    path = tmp_path / "state.db-shm"
    path.touch()
    with path.open("r+b") as locked:
        fcntl.lockf(locked, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 123)
        _restrict_sidecar(path)
        child = (
            'import fcntl,sys; f=open(sys.argv[1],"r+b"); '
            "fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB,1,123)"
        )
        result = subprocess.run(
            [sys.executable, "-c", child, str(path)], capture_output=True, text=True, timeout=5
        )
        assert result.returncode != 0 and "BlockingIOError" in result.stderr


def test_real_sqlite_concurrent_connection_close_sidecars(tmp_path):
    store = MediaStore(tmp_path / "state.db", timeout=2)

    def read_repeatedly(_):
        for _ in range(100):
            with store._connect() as conn:
                assert conn.execute("SELECT schema_version FROM media_control").fetchone() == (4,)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(read_repeatedly, range(8)))
