import json

import pytest
import yaml
from test_media_import import media as media
from test_media_runtime import media_config

from seed_agent.config import atomic_write_text
from seed_agent.media_import.commands import status, submit
from seed_agent.media_import.maintenance import backup_media_database, restore_media_database
from seed_agent.media_import.runtime import build_engine
from seed_agent.media_import.worker import claim, process_one, recover_commands, worker_lease


def test_command_coalescing_mode_pin_queue_cap_and_restart(tmp_path, monkeypatch):
    config, _, _ = media_config(tmp_path)
    first = submit(config, "scan")
    assert submit(config, "scan")["command_id"] == first["command_id"]
    assert submit(config, "scan", execute=True)["command_id"] != first["command_id"]
    monkeypatch.setattr("seed_agent.media_import.commands.MAX_PENDING", 2)
    with pytest.raises(ValueError, match="full"):
        submit(config, "subtitles")
    command = claim(config)
    assert command["id"] == first["command_id"]
    recover_commands(config)
    assert status(config, first["command_id"])[0]["status"] == "interrupted"


def test_worker_exclusive_lease_and_stale_revision(tmp_path):
    config, _, _ = media_config(tmp_path)
    with worker_lease(config), pytest.raises(TimeoutError):
        with worker_lease(config):
            pytest.fail("concurrent worker acquired lease")
    command = submit(config, "scan", execute=True)
    raw = yaml.safe_load(config.read_text())
    raw["media_import"]["subtitle_policy"] = "execute"
    atomic_write_text(config, yaml.safe_dump(raw))
    assert process_one(config)["status"] == "failed"
    assert status(config, command["command_id"])[0]["result"]["error_type"] == "ValueError"


def test_media_restore_supersedes_queued_and_running_commands(tmp_path):
    config, _, _ = media_config(tmp_path)
    submit(config, "scan")
    submit(config, "subtitles")
    claim(config)
    engine, _ = build_engine(config)
    backup = tmp_path / "commands-backup.db"
    backup_media_database(engine.store.path, backup)
    restore_media_database(engine.store.path, backup, execute=True)
    assert all(c["status"] == "superseded" for c in status(config))
    assert process_one(config) is None


def test_preview_scan_cannot_gain_execute_after_submission(tmp_path):
    config, source, target = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["media_import"]["import_policy"] = "execute"
    atomic_write_text(config, yaml.safe_dump(raw))
    submit(config, "scan")
    command = claim(config)
    assert json.loads(command["modes_json"])["import"] == "preview"
    assert not list(target.rglob("*.mkv"))


def test_incomplete_inventory_does_not_advance_missing_counts(media):
    engine, source, _, _ = media
    (source / "one.mkv").write_bytes(b"one")
    (source / "two.mkv").write_bytes(b"two")
    engine.scan(engine.config.profiles[0].name, force=True)
    before = engine.snapshot()["sources"]
    engine.config.max_inventory_files = 1
    result = engine.scan(engine.config.profiles[0].name, force=True)
    assert result["status"] == "failed"
    assert engine.snapshot()["sources"] == before


def test_media_pagination_keeps_related_rows_on_source_page(media):
    from test_media_import import import_three

    import_three(media)
    engine, *_ = media
    page = engine.snapshot(limit=1, offset=1)
    assert len(page["sources"]) == 1 and page["pagination"]["total"] == 3
    assert {r["source_id"] for r in page["artifact_sources"]} == {page["sources"][0]["id"]}
    assert len(page["artifacts"]) == 1


def test_legacy_export_rejects_active_writer(media, tmp_path):
    from seed_agent.media_import.migration import export_snapshot

    engine, *_ = media
    with engine.lease(), pytest.raises(TimeoutError):
        export_snapshot(engine.store.path, engine.config.profiles, output=tmp_path / "export.json")
    assert not (tmp_path / "export.json").exists()


def test_blocked_worker_does_not_delay_seed_cycle_or_capacity_deadlines(tmp_path, monkeypatch):
    import threading
    import time
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from seed_agent import cli
    from seed_agent.media_import import worker

    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["download_client"] = {
        "type": "qbittorrent",
        "target": "local",
        "default_category": "seed",
        "category_policies": [
            {
                "name": "seed",
                "mode": "mutable",
                "budget_pool": "downloads",
                "delete_enabled": True,
                "over_budget_behavior": "add_paused",
                "tags": ["seed-agent"],
            }
        ],
        "budget_pools": [{"name": "downloads", "max_size_tib": 1}],
    }
    raw["scheduler"] = {
        "tracker_backfill_enabled": False,
        "prune_enabled": False,
        "intent_enabled": False,
    }
    atomic_write_text(config, yaml.safe_dump(raw))
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"status": "complete"}

    monkeypatch.setattr(worker, "run_engine", blocked)
    submit(config, "scan")
    thread = threading.Thread(target=process_one, args=(config,))
    thread.start()
    try:
        assert entered.wait(1)
        called = []
        monkeypatch.setattr(
            cli,
            "_run_once_payload",
            lambda *a, **k: called.append(time.monotonic()) or {"decisions": []},
        )
        started = time.monotonic()
        run = CliRunner().invoke(
            cli.app, ["schedule-run", "--config", str(config), "--max-cycles", "1"]
        )
        assert run.exit_code == 0, run.output
        assert len(called) == 1 and called[0] - started < 1
        assert thread.is_alive()  # provider is still blocked while seed advanced
        ticks = [0]
        deadlines = []
        monkeypatch.setattr(
            cli.time, "sleep", lambda seconds: ticks.__setitem__(0, ticks[0] + seconds)
        )
        monkeypatch.setattr(
            cli,
            "_capacity_guard_payload",
            lambda *a, **k: (
                deadlines.append(ticks[0]) or {"command": "capacity-guard", "triggered": False}
            ),
        )
        cli._wait_for_next_schedule_cycle(
            config,
            execute=False,
            interval_seconds=31,
            guard_interval_seconds=10,
            lease_heartbeat=SimpleNamespace(ensure_owned=lambda: None),
        )
        assert deadlines == [10, 20, 30]
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()


def test_queued_review_rejects_changed_plan_without_overwriting_new_decision(
    media, tmp_path, monkeypatch
):
    from test_media_import import import_three

    import_three(media)
    engine, *_ = media
    source = engine.snapshot()["sources"][0]
    config = tmp_path / "command-config.yaml"
    atomic_write_text(
        config, yaml.safe_dump({"media_import": engine.config.model_dump(mode="json")})
    )
    # Use the existing independent fixture store through a media config path.
    raw = yaml.safe_load(config.read_text())
    raw["media_import"]["state_path"] = str(engine.store.path)
    atomic_write_text(config, yaml.safe_dump(raw))
    mapping = json.loads(source["mapping_json"])
    submit(
        config,
        "review",
        {
            "source_id": source["id"],
            "fingerprint": source["fingerprint"],
            "mapping": mapping,
            "ready": True,
        },
    )
    engine.review(source["id"], mapping, fingerprint=source["fingerprint"], ready=True)
    before = engine.snapshot()["sources"][0]["review_revision"]
    assert process_one(config)["status"] == "failed"
    assert engine.snapshot()["sources"][0]["review_revision"] == before


def test_preview_worker_scan_plans_without_link_then_explicit_execute_links(tmp_path, monkeypatch):
    from seed_agent.media_import import worker
    from seed_agent.media_import.metadata import Mapping

    config, source, target = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["media_import"]["import_policy"] = "execute"
    raw["media_import"]["profiles"][0].update(
        readiness="completed_folder", completed_contract_acknowledged=True
    )
    atomic_write_text(config, yaml.safe_dump(raw))
    original = worker.build_engine

    def fixture_engine(*args, **kwargs):
        engine, root = original(*args, **kwargs)

        class Metadata:
            def identify(self, path, profile):
                return Mapping(
                    media_type="movie", tmdb_id=1, original_title="Example", year=2024
                ), []

        engine.metadata = Metadata()
        engine.probe = lambda path: {"duration": 100, "fps": 24, "streams": []}
        return engine, root

    monkeypatch.setattr(worker, "build_engine", fixture_engine)
    video = source / "Example.2024.mkv"
    video.write_bytes(b"fixture-video")
    before = video.stat()
    for _ in range(2):
        submit(config, "scan")
        assert process_one(config)["status"] == "complete"
    assert not list(target.rglob("*.mkv"))
    submit(config, "scan", execute=True)
    assert process_one(config)["status"] == "complete"
    linked = list(target.rglob("*.mkv"))
    assert len(linked) == 1 and linked[0].stat().st_ino == video.stat().st_ino == before.st_ino


def test_serve_records_single_role_lifecycle_and_clean_stop(tmp_path):
    from seed_agent.media_import.role_health import media_role_status
    from seed_agent.media_import.worker import serve

    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["deployment"] = {"source_id": "worker-lifecycle-fixture"}
    config.write_text(yaml.safe_dump(raw))
    serve(config, max_cycles=1)
    report = media_role_status(config)
    assert report["worker"]["status"] == "stopped"
    assert report["worker"]["phase"] == "poster-batch"
    assert report["worker"]["progress"] == {"completed": 1, "total": 1}
    assert not report["healthy"]


def test_media_role_cli_never_loads_seed_config(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from seed_agent import cli

    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["deployment"] = {"source_id": "cli-lifecycle-fixture"}
    raw["download_client"] = {"invalid_seed_only_field": True}
    config.write_text(yaml.safe_dump(raw))

    def forbidden(*a, **k):
        raise AssertionError("seed config loaded")

    monkeypatch.setattr(cli, "load_config", forbidden)
    runner = CliRunner()
    status = runner.invoke(cli.app, ["runtime-status", "--role", "media", "--config", str(config)])
    assert status.exit_code == 0, status.output
    assert "worker" in json.loads(status.output)
    health = runner.invoke(cli.app, ["healthcheck", "--role", "media", "--config", str(config)])
    assert health.exit_code == 1
    assert json.loads(health.output)["healthy"] is False
