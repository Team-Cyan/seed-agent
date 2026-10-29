"""Independent, bounded media-only SQLite and restore epoch; no seed initialization."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
import time
import uuid
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path

from seed_agent.media_import import sqlite_io
from seed_agent.media_import.schema import SCHEMA
from seed_agent.runtime_identity import verify_runtime_identity

CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_control (
 id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, schema_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS media_runtime_status (
 role TEXT PRIMARY KEY, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_migrations (
 export_digest TEXT PRIMARY KEY, imported_at REAL NOT NULL, counts_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_commands (
 id TEXT PRIMARY KEY, coalesce_key TEXT NOT NULL, action TEXT NOT NULL,
 payload_json TEXT NOT NULL, config_source TEXT NOT NULL, config_revision TEXT NOT NULL,
 epoch TEXT NOT NULL, modes_json TEXT NOT NULL, status TEXT NOT NULL,
 created REAL NOT NULL, claimed REAL, claim_token TEXT, result_json TEXT
);
CREATE INDEX IF NOT EXISTS media_commands_pending ON media_commands(status,created);
CREATE TABLE IF NOT EXISTS media_inventory_stage (
 run_id INTEGER NOT NULL, path TEXT NOT NULL, fingerprint TEXT NOT NULL,
 PRIMARY KEY(run_id,path)
);
CREATE TABLE IF NOT EXISTS media_work_cursor (
 profile TEXT PRIMARY KEY, source_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_plan_routes (
 source_id TEXT NOT NULL, revision INTEGER NOT NULL, descriptor_json TEXT NOT NULL,
 PRIMARY KEY(source_id,revision)
);
CREATE TABLE IF NOT EXISTS media_artifact_roots (
 artifact_id TEXT PRIMARY KEY, descriptor_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_directory_roots (
 path TEXT PRIMARY KEY, descriptor_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_publication_fences (
 artifact_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_output_exclusions (path TEXT PRIMARY KEY);
"""


@lru_cache(maxsize=1)
def expected_signature():
    from seed_agent.maintenance import _schema_signature

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(SCHEMA + CONTROL_SCHEMA)
        return _schema_signature(conn)


def validate_schema(conn):
    from seed_agent.maintenance import _schema_signature

    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1"
    ).fetchone():
        raise ValueError("media state contains unsupported views/triggers")
    if _schema_signature(conn) != expected_signature():
        raise ValueError("media schema mismatch; explicit migration required")


@contextmanager
def bounded_lock(path: Path, *, exclusive=False, timeout=0.25):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("media access lock timeout") from None
                time.sleep(0.01)
        yield
    finally:
        os.close(fd)


def _restrict_sidecar(path: Path):
    # Closing an extra DB/SHM descriptor drops this process's SQLite POSIX
    # locks. Use no-follow path operations, never open these files ourselves.
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("media sidecar must be a regular file")
        os.chmod(path, 0o600, follow_symlinks=False)
    except FileNotFoundError:
        # SQLite removes sidecars when the last connection closes.
        return


class MediaStore:
    schema_version = 4

    def __init__(self, path: Path, *, initialize=True, read_only=False, timeout=0.25):
        verify_runtime_identity()
        self.path = Path(path)
        self.read_only = read_only
        self.timeout = timeout
        self._initializing = initialize
        if read_only and initialize:
            raise ValueError("read-only media store cannot initialize")
        if self.path.is_symlink():
            raise ValueError("media state must not be a symlink")
        if (read_only or not initialize) and not self.path.is_file():
            raise FileNotFoundError(self.path)
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if initialize:
            self._initialize()
        self._initializing = False

    def _initialize(self):
        with self._connect() as conn:
            existing = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if any(not t.startswith(("media_", "sqlite_")) for t in existing):
                raise ValueError("media state points to a non-media database")
            if "media_control" in existing:
                version = conn.execute(
                    "SELECT schema_version FROM media_control WHERE id=1"
                ).fetchone()
                if not version or version[0] != self.schema_version:
                    raise ValueError(
                        "unsupported media schema version; explicit migration required"
                    )
            elif existing:
                raise ValueError("legacy media state requires explicit export/import migration")
            if existing:
                validate_schema(conn)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA + CONTROL_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO media_control VALUES(1,?,?)",
                (uuid.uuid4().hex, self.schema_version),
            )

    @contextmanager
    def _connect(self, *, row_factory=None):
        verify_runtime_identity()
        with bounded_lock(
            Path(str(self.path) + ".access.lock"),
            exclusive=self._initializing,
            timeout=self.timeout,
        ):
            if not self.read_only:
                if self._initializing:
                    try:
                        fd = os.open(
                            self.path,
                            os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                            0o600,
                        )
                    except FileExistsError:
                        pass
                    else:
                        os.close(fd)
                if not stat.S_ISREG(self.path.lstat().st_mode):
                    raise ValueError("media state must be a regular file")
                os.chmod(self.path, 0o600, follow_symlinks=False)
            elif not stat.S_ISREG(self.path.lstat().st_mode):
                raise ValueError("media state must be a regular file")
            token = sqlite_io.begin(self.path)
            try:
                conn = sqlite3.connect(
                    f"file:{self.path.absolute()}?mode=ro&cache=private"
                    if self.read_only
                    else self.path,
                    uri=self.read_only,
                    timeout=self.timeout,
                )
            except BaseException as exc:
                sqlite_io.failure(token, "connect", exc)
                raise
            phase = "busy-timeout"
            token = sqlite_io.begin(self.path)
            try:
                conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
                if self.read_only:
                    phase = "query-only"
                    token = sqlite_io.begin(self.path)
                    conn.execute("PRAGMA query_only=ON")
                if row_factory:
                    conn.row_factory = row_factory
                phase = "body"
                token = sqlite_io.begin(self.path)
                yield conn
                if not self.read_only:
                    phase = "commit"
                    token = sqlite_io.begin(self.path)
                    conn.commit()
            except BaseException as exc:
                sqlite_io.failure(token, phase, exc)
                if not self.read_only:
                    rollback_token = sqlite_io.begin(self.path)
                    try:
                        conn.rollback()
                    except BaseException as rollback_exc:
                        sqlite_io.failure(rollback_token, "rollback", rollback_exc)
                        raise
                raise
            finally:
                close_token = sqlite_io.begin(self.path)
                try:
                    conn.close()
                except BaseException as close_exc:
                    sqlite_io.failure(close_token, "close", close_exc)
                    raise
                if not self.read_only:
                    for suffix in ["-wal", "-shm", "-journal"]:
                        sidecar = Path(str(self.path) + suffix)
                        _restrict_sidecar(sidecar)

    def epoch(self):
        with self._connect() as conn:
            row = conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()
            if not row:
                raise ValueError("media restore epoch missing")
            return row[0]

    def record_applied(self, view):
        observation = {
            **view.observation(),
            "media_schema_version": self.schema_version,
            "state_epoch": self.epoch(),
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO media_runtime_status VALUES('media',?) "
                "ON CONFLICT(role) DO UPDATE SET payload_json=excluded.payload_json",
                (json.dumps(observation, sort_keys=True),),
            )
        return observation

    def applied_status(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM media_runtime_status WHERE role='media'"
            ).fetchone()
        return (
            json.loads(row[0])
            if row
            else {"role": "media", "applied_revision": None, "status": "not_applied"}
        )
