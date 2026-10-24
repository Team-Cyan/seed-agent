import json

import pytest
import yaml
from test_media_runtime import media_config

from seed_agent.config_views import load_view
from seed_agent.media_import.role_health import MediaWorkerLifecycle, media_role_status
from seed_agent.media_import.runtime import media_state_path
from seed_agent.media_import.store import MediaStore


@pytest.fixture
def lifecycle_fixture(tmp_path):
    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["deployment"] = {"source_id": "role-health-fixture"}
    config.write_text(yaml.safe_dump(raw))
    view = load_view(config, "media", require_identity=True)
    store = MediaStore(media_state_path(view), initialize=False)
    store.record_applied(view)
    return config, view, store


def test_phase_deadline_distinguishes_slow_provider_from_frozen_work(lifecycle_fixture):
    config, view, store = lifecycle_fixture
    now = [1000.0]
    with MediaWorkerLifecycle(store, view, clock=lambda: now[0]) as life:
        life.phase("provider", deadline_seconds=300, completed=0, total=2)
        now[0] += 120
        life.heartbeat()
        report = media_role_status(config, now=now[0])
        assert report["healthy"]
        assert report["progress_age_seconds"] == 120
        # A heartbeat thread and even new counters do not renew business deadline.
        now[0] += 181
        life.heartbeat()
        life.progress(completed=1, total=2)
        report = media_role_status(config, now=now[0])
        assert report["checks"]["liveness"]
        assert not report["checks"]["phase_deadline"]
        assert not report["healthy"]
    report = media_role_status(config, now=now[0])
    assert report["worker"]["status"] == "stopped"
    assert not report["healthy"]


def test_stale_worker_and_failure_are_visible_without_exception_text(lifecycle_fixture):
    config, view, store = lifecycle_fixture
    with pytest.raises(RuntimeError, match="private"):
        with MediaWorkerLifecycle(store, view, clock=lambda: 1000) as life:
            life.phase("scan", deadline_seconds=600)
            report = media_role_status(config, now=1061)
            assert not report["healthy"] and not report["checks"]["liveness"]
            raise RuntimeError("private credential contents")
    report = media_role_status(config, now=1001)
    assert report["worker"]["status"] == "failed"
    assert report["worker"]["error_type"] == "RuntimeError"
    assert "private" not in json.dumps(report)
    assert report["restart_budget"] == "unavailable"


def test_old_instance_and_restore_epoch_cannot_overwrite_new_status(lifecycle_fixture):
    config, view, store = lifecycle_fixture
    old = MediaWorkerLifecycle(store, view).start()
    new = MediaWorkerLifecycle(store, view).start()
    try:
        with pytest.raises(ValueError, match="superseded"):
            old.heartbeat()
        with pytest.raises(ValueError, match="superseded"):
            old.apply(view)
        with pytest.raises(ValueError, match="superseded"):
            old.stopped()
        assert media_role_status(config)["worker"]["instance_id"] == new.instance_id
        with store._connect() as conn:
            conn.execute("UPDATE media_control SET epoch='restored' WHERE id=1")
        with pytest.raises(ValueError, match="epoch"):
            new.progress(completed=2)
        with pytest.raises(ValueError, match="epoch"):
            new.stopped()
        assert not media_role_status(config)["checks"]["worker_configuration"]
    finally:
        old._stop.set()
        new._stop.set()


def test_health_is_read_only_and_has_no_engine_provider_or_seed_access(
    lifecycle_fixture, monkeypatch
):
    config, view, store = lifecycle_fixture
    with MediaWorkerLifecycle(store, view) as life:
        life.phase("idle", deadline_seconds=60)

        # Health must not use MediaStore's lock/chmod/initialization boundary.
        def forbidden(*args, **kwargs):
            raise AssertionError("writer invoked")

        monkeypatch.setattr(MediaStore, "_connect", forbidden)
        before = (store.path.read_bytes(), store.path.stat().st_mtime_ns, store.path.stat().st_mode)
        report = media_role_status(config)
        after = (store.path.read_bytes(), store.path.stat().st_mtime_ns, store.path.stat().st_mode)
        assert report["healthy"]
        assert before == after
        assert {p.name for p in store.path.parent.iterdir()} <= {
            "state.db",
            "state.db.access.lock",
            "state.db-wal",
            "state.db-shm",
        }
        assert not (view.workspace / ".seed-agent").exists()
        monkeypatch.undo()


def test_missing_corrupt_config_and_state_fail_closed_without_creation(tmp_path, lifecycle_fixture):
    missing = tmp_path / "absent" / "config.yaml"
    assert not media_role_status(missing)["healthy"]
    assert not missing.parent.exists()
    config, _, store = lifecycle_fixture
    config.write_text("media_import: [secret-value]")
    result = media_role_status(config)
    assert not result["healthy"]
    assert result["error"]["code"] == "invalid_configuration"
    assert "secret-value" not in json.dumps(result)
    # Separate valid config with a corrupt state never initializes/replaces it.
    config.write_text("deployment: {source_id: fixture}\nmedia_import: {enabled: false}\n")
    path = media_state_path(load_view(config, "media"))
    assert path == store.path
    path.write_bytes(b"not sqlite")
    assert media_role_status(config)["error"]["code"] == "invalid_media_state"
    assert path.read_bytes() == b"not sqlite"


def test_revision_schema_and_image_drift_fail_closed(lifecycle_fixture, monkeypatch):
    config, view, store = lifecycle_fixture
    with MediaWorkerLifecycle(store, view) as life:
        life.phase("idle", deadline_seconds=60)
        raw = yaml.safe_load(config.read_text())
        raw["unrelated-seed-section"] = {"enabled": True}
        config.write_text(yaml.safe_dump(raw))
        assert not media_role_status(config)["healthy"]
        changed = load_view(config, "media")
        assert changed.effective_revision == view.effective_revision
        store.record_applied(changed)
        life.apply(changed)
        assert media_role_status(config)["healthy"]
        monkeypatch.setenv("SEED_AGENT_IMAGE_DIGEST", "sha256:different-image")
        assert not media_role_status(config)["healthy"]
        monkeypatch.delenv("SEED_AGENT_IMAGE_DIGEST")
        with store._connect() as conn:
            conn.execute("UPDATE media_control SET schema_version=999")
        assert media_role_status(config)["error"]["code"] == "invalid_media_state"


def test_queue_status_uses_counts_and_oldest_age_only(lifecycle_fixture):
    config, view, store = lifecycle_fixture
    with MediaWorkerLifecycle(store, view, clock=lambda: 1000) as life:
        life.phase("idle", deadline_seconds=60)
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO media_commands VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "id",
                    "key",
                    "scan",
                    '{"private":"hidden"}',
                    view.source_id,
                    view.effective_revision,
                    store.epoch(),
                    "{}",
                    "queued",
                    950,
                    None,
                    None,
                    None,
                ),
            )
        report = media_role_status(config, now=1000)
        assert report["queue"] == {
            "counts": {"queued": 1},
            "oldest_queued_at": 950,
            "oldest_queued_age_seconds": 50,
        }
        assert "hidden" not in json.dumps(report)


def test_bounded_diagnostics_reject_invalid_progress_deadline_and_payload(lifecycle_fixture):
    config, view, store = lifecycle_fixture
    with MediaWorkerLifecycle(store, view) as life:
        for duration in [0, float("nan"), float("inf"), 86401]:
            with pytest.raises(ValueError):
                life.phase("provider", deadline_seconds=duration)
        with pytest.raises(ValueError):
            life.progress(completed=3, total=1)
        with store._connect() as conn:
            conn.execute(
                "UPDATE media_runtime_status SET payload_json=? WHERE role='media'", ('"bad"',)
            )
        assert not media_role_status(config)["healthy"]
        with store._connect() as conn:
            conn.execute(
                "UPDATE media_runtime_status SET payload_json=? WHERE role='media'", ("x" * 32769,)
            )
        assert not media_role_status(config)["healthy"]


def test_heartbeat_recovers_from_real_short_sqlite_write_contention(lifecycle_fixture, monkeypatch):
    import sqlite3
    import threading

    config, view, store = lifecycle_fixture
    failed, recovered = threading.Event(), threading.Event()
    with MediaWorkerLifecycle(store, view, heartbeat_seconds=0.01) as life:
        life.phase("scan", deadline_seconds=60)
        original = life.heartbeat

        def heartbeat():
            try:
                result = original()
            except sqlite3.OperationalError:
                failed.set()
                raise
            if failed.is_set():
                recovered.set()
            return result

        monkeypatch.setattr(life, "heartbeat", heartbeat)
        with sqlite3.connect(store.path) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE media_control SET schema_version=schema_version")
            assert failed.wait(2), "real SQLite writer must block at least one heartbeat"
            writer.commit()
        assert recovered.wait(2), "heartbeat must recover after short writer contention"
        assert not life._background_failed
        assert media_role_status(config)["healthy"]


def test_heartbeat_fatal_token_fence_stops_without_retry(lifecycle_fixture):
    import time

    _, view, store = lifecycle_fixture
    old = MediaWorkerLifecycle(store, view, heartbeat_seconds=0.01).start()
    with MediaWorkerLifecycle(store, view) as new:
        deadline = time.monotonic() + 1
        while not old._background_failed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert old._background_failed
        assert not old._thread.is_alive()
        assert new.instance_id != old.instance_id
        with pytest.raises(RuntimeError, match="heartbeat failed"):
            old.phase("idle", deadline_seconds=30)
    old._stop.set()


def test_persistent_lock_failure_stops_heartbeats_after_bounded_horizon(
    lifecycle_fixture, monkeypatch
):
    import sqlite3
    import time

    _, view, store = lifecycle_fixture
    life = MediaWorkerLifecycle(store, view, heartbeat_seconds=0.01).start()
    life.phase("scan", deadline_seconds=60)
    # Exercise the expiration branch without waiting an actual minute. The
    # underlying SQLite contention is real and bounded by the store timeout.
    life._last_heartbeat_success = time.monotonic() - 61
    with sqlite3.connect(store.path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE media_control SET schema_version=schema_version")
        life._thread.join(timeout=2)
        assert life._background_failed
        assert not life._thread.is_alive()
        writer.commit()
    with pytest.raises(RuntimeError, match="heartbeat failed"):
        life.heartbeat()
    # Teardown records the final failure after lock release; no hidden retry.
    life.failed(TimeoutError())
