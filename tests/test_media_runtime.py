import json
from http.client import HTTPConnection

import pytest
import yaml
from test_web_settings import _running_server, _write_minimal_config
from typer.testing import CliRunner

from seed_agent import cli
from seed_agent.config import load_config
from seed_agent.media_import.runtime import build_engine


def media_config(tmp_path):
    config_path = _write_minimal_config(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config.pop("download_client")
    source, target = tmp_path / "source", tmp_path / "library"
    source.mkdir()
    target.mkdir()
    for path in [source, target]:
        (path / ".media-volume").write_text("fixture")
    config["media_import"] = {
        "enabled": True,
        "profiles": [
            {
                "name": "movie",
                "source_root": str(source),
                "target_root": str(target),
                "marker_value": "fixture",
                "target_marker_value": "fixture",
                "media_type": "movie",
                "min_age_seconds": 0,
            }
        ],
    }
    config_path.write_text(yaml.safe_dump(config))
    build_engine(config_path, initialize=True)
    return config_path, source, target


def test_media_cli_without_downloader_config(tmp_path):
    config, source, target = media_config(tmp_path)
    assert load_config(config).download_client is None
    (source / "Example.2024.mkv").write_bytes(b"not yet confirmed ready")
    for _ in range(2):
        result = CliRunner().invoke(cli.app, ["media-scan", "--config", str(config)])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "queued"
        from seed_agent.media_import.worker import process_one

        assert process_one(config)["status"] == "complete"
    assert not list(target.rglob("*.mkv"))
    status = CliRunner().invoke(cli.app, ["media-status", "--config", str(config)])
    assert status.exit_code == 0
    assert json.loads(status.output)["sources"][0]["readiness"] == "completion_unverified"


def test_media_web_get_is_read_only_and_review_persists(tmp_path):
    config, source, _ = media_config(tmp_path)
    (source / "Example.2024.mkv").write_bytes(b"fixture")
    engine, _ = build_engine(config)
    engine.scan("movie", force=True)
    engine.scan("movie", force=True)
    source_row = engine.snapshot()["sources"][0]
    with _running_server(config) as host:
        conn = HTTPConnection(host)
        conn.request("GET", "/api/media")
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["sources"][0]["id"] == source_row["id"]
        mapping = {"media_type": "movie", "tmdb_id": 1, "original_title": "Example", "year": 2024}
        conn.request(
            "POST",
            "/api/media/review",
            json.dumps(
                {
                    "source_id": source_row["id"],
                    "mapping": mapping,
                    "fingerprint": source_row["fingerprint"],
                    "ready": True,
                }
            ),
            {"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        assert response.status == 202, response.read()
        payload = json.loads(response.read())
        assert payload["status"] == "queued"
        from seed_agent.media_import.worker import process_one

        completed = process_one(config)
        assert "Example (2024)" in completed["result"]["new_target"]
        conn.close()
    reloaded, _ = build_engine(config)
    with reloaded.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_review_decisions").fetchone()[0] == 1


def test_media_scheduler_and_runtime_status_without_downloader(tmp_path):
    config, source, _ = media_config(tmp_path)
    (source / "Example.mkv").write_bytes(b"fixture")
    status = CliRunner().invoke(cli.app, ["runtime-status", "--config", str(config)])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["download_client"] is None
    run = CliRunner().invoke(
        cli.app, ["schedule-run", "--config", str(config), "--max-cycles", "1"]
    )
    assert run.exit_code == 0, run.output
    payload = next(
        value
        for line in reversed(run.stdout.splitlines())
        if (value := json.loads(line)).get("command") == "schedule-run"
    )
    assert payload["media_import"]["status"] == "worker_required"


@pytest.mark.parametrize("network_failure", ["timeout", "connect", "status"])
@pytest.mark.parametrize("backoff_active", [False, True])
def test_seed_scheduler_never_invokes_media_network(
    tmp_path, monkeypatch, network_failure, backoff_active
):
    import httpx

    from seed_agent.media_import import runtime
    from seed_agent.state import StateStore

    config_path = _write_minimal_config(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config["media_import"] = {"enabled": True, "profiles": []}
    config["scheduler"] = {
        "tracker_backfill_enabled": False,
        "prune_enabled": False,
        "intent_enabled": False,
    }
    config_path.write_text(yaml.safe_dump(config))

    def fail(*args, **kwargs):
        if network_failure == "timeout":
            raise httpx.ReadTimeout("synthetic TMDB timeout")
        if network_failure == "connect":
            raise httpx.ConnectError("synthetic TMDB connection failure")
        request = httpx.Request("GET", "https://metadata.example/fixture")
        raise httpx.HTTPStatusError("synthetic 503", request=request, response=httpx.Response(503))

    seed_calls = []

    def seed(*args, **kwargs):
        seed_calls.append(True)
        return {"command": "run-once", "execute": False, "decisions": []}

    monkeypatch.setattr(runtime, "run", fail)
    monkeypatch.setattr(cli, "_run_once_payload", seed)
    monkeypatch.setattr(
        cli,
        "_schedule_backoff_status",
        lambda *args: {"active": backoff_active, "reason": "fixture"},
    )
    heartbeat = tmp_path / "heartbeat.json"
    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--max-cycles",
            "1",
            "--heartbeat-file",
            str(heartbeat),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = next(
        value
        for line in reversed(result.stdout.splitlines())
        if (value := json.loads(line)).get("command") == "schedule-run"
    )
    assert summary["media_import"]["status"] == "worker_required"
    assert len(seed_calls) == (0 if backoff_active else 1)
    assert "error" not in summary
    assert heartbeat.is_file()
    heartbeat_data = json.loads(heartbeat.read_text())
    assert heartbeat_data["cycle"] == 1
    assert heartbeat_data["error"] is None
    assert bool(heartbeat_data["skipped_by_backoff"]) is backoff_active
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    assert store.get_scheduler_lease() is None
