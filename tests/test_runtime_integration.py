from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from support.fakes import RecordingDownloader, StaticSearchProvider
from typer.testing import CliRunner

from seed_agent.models import Discount, ManagedTorrent, ReleaseCandidate
from seed_agent.state import StateStore


def test_scheduler_lease_heartbeat_renews_during_long_cycle() -> None:
    from seed_agent.cli import _SchedulerLeaseHeartbeat

    renewed = threading.Event()

    class RecordingLeaseStore:
        def acquire_scheduler_lease(
            self,
            owner_id: str,
            *,
            ttl_seconds: int,
        ) -> dict[str, object]:
            renewed.set()
            return {
                "acquired": True,
                "owner_id": owner_id,
                "expires_at": str(ttl_seconds),
            }

    heartbeat = _SchedulerLeaseHeartbeat(
        RecordingLeaseStore(),  # type: ignore[arg-type]
        "scheduler-test",
        ttl_seconds=1,
    )
    heartbeat.start()
    try:
        assert renewed.wait(timeout=2)
        heartbeat.ensure_owned()
    finally:
        heartbeat.stop()


def test_scheduler_cycle_uses_local_fakes_and_persists_all_phases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    raw = yaml.safe_load(Path("config/example.yaml").read_text(encoding="utf-8"))
    raw["tracker_sites"] = []
    raw["download_client"]["secret_ref"] = None
    raw["scheduler"].update(
        {
            "tracker_backfill_enabled": False,
            "intent_search_mode": "every_cycle",
            "intent_execute": False,
            "prune_enabled": True,
        }
    )
    raw["want_decision"]["inbox_ref"] = "local/inbox/intents.jsonl"
    raw["want_sources"]["want_lists"] = []
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    inbox_path = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        json.dumps(
            {
                "id": "integration-intent",
                "text": "Inception 2010 1080p",
                "requested_at": "2026-07-11T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    torrent = ManagedTorrent(
        hash="integration-seed",
        name="Cold Seed",
        category="seed",
        tags={"seed-agent", "seed"},
        state="uploading",
        size_bytes=20 * 1024**3,
        uploaded_bytes=0,
        downloaded_bytes=20 * 1024**3,
        added_at=datetime.now(UTC) - timedelta(days=10),
        completed_at=datetime.now(UTC) - timedelta(days=9),
        metadata={"recent_upload_gb": 0.0},
    )
    downloader = RecordingDownloader([torrent], free_space_bytes=2 * 1024**4)
    provider = StaticSearchProvider(
        [
            ReleaseCandidate(
                release_id="demo:inception",
                site="demo",
                title="Inception 2010 1080p Remux",
                source_url="https://tracker.invalid/details/1",
                download_url="https://tracker.invalid/download/1",
                size_bytes=20 * 1024**3,
                seeders=20,
                leechers=10,
                discount=Discount.FREE,
            )
        ]
    )
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: downloader)
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [provider])

    heartbeat_path = tmp_path / "runtime" / "heartbeat.json"
    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--heartbeat-file",
            str(heartbeat_path),
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout.splitlines()[-1])
    run_id = summary["run_id"]
    assert summary["intent_search_enabled"] is True
    assert summary["prune"]["managed_count"] == 1
    assert heartbeat_path.exists()
    assert provider.queries
    assert downloader.added == []
    assert downloader.paused == []
    assert downloader.deleted == []

    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    events = sorted(
        store.list_scheduler_run_events(run_id=run_id, limit=50),
        key=lambda row: row["id"],
    )
    assert [(row["phase"], row["event"]) for row in events] == [
        ("backoff_check", "inactive"),
        ("prune", "start"),
        ("prune", "end"),
        ("pt_discovery", "start"),
        ("pt_enqueue", "end"),
        ("intent_search", "start"),
        ("intent_search", "end"),
    ]
    assert {row["run_id"] for row in events} == {run_id}
    assert store.get_scheduler_lease() is None


def test_scheduler_cli_rejects_second_owner_before_runtime_work(tmp_path: Path) -> None:
    from seed_agent import cli

    raw = yaml.safe_load(Path("config/example.yaml").read_text(encoding="utf-8"))
    raw["tracker_sites"] = []
    raw["download_client"]["secret_ref"] = None
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.acquire_scheduler_lease("already-running", ttl_seconds=3600)

    result = CliRunner().invoke(
        cli.app,
        ["schedule-run", "--config", str(config_path), "--max-cycles", "1"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == "scheduler lease is already held"
    assert payload["scheduler_lease"]["owner_id"] == "already-running"
    assert store.list_scheduler_runs() == []
