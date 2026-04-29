from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import (
    Decision,
    LifecycleState,
    ManagedTorrent,
    ScoreBreakdown,
    TorrentCandidate,
)
from seed_agent.state import StateStore


def _config(secret_ref: str | None = None) -> SeedAgentConfig:
    return SeedAgentConfig(
        mode="balanced",
        sites=[
            {
                "name": "demo-free",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss.php",
                "cookie_ref": None,
            }
        ],
        discovery=DiscoveryConfig(
            discounts=["free", "2xfree"],
            min_left_time_minutes=120,
            min_leechers=8,
            max_seeders=80,
            allow_hr=False,
        ),
        scoring=ScoringConfig(
            min_score_to_enqueue=70,
            weights={
                "discount": 30,
                "leechers": 25,
                "seeders": 15,
                "left_time": 15,
                "size": 10,
                "site_history": 5,
            },
        ),
        downloader={
            "type": "qbittorrent",
            "target": "unraid-qb",
            "default_category": "seed",
            "category_policies": [
                {
                    "name": "seed",
                    "mode": "mutable",
                    "budget_pool": "downloads",
                    "delete_enabled": True,
                    "over_budget_behavior": "add_paused",
                    "tags": ["seed-agent", "seed"],
                },
                {
                    "name": "movie",
                    "mode": "add_only",
                    "budget_pool": "media",
                    "delete_enabled": False,
                    "over_budget_behavior": "add_paused",
                    "tags": ["seed-agent", "movie"],
                },
            ],
            "budget_pools": [
                {"name": "downloads", "max_size_tib": 10},
                {"name": "media", "max_size_tib": 10},
            ],
            "secret_ref": secret_ref,
        },
        cleanup={
            "cold_after_days": 7,
            "min_upload_delta_gb": 1,
            "protect_hr": True,
            "protect_manual": True,
            "protect_media_library": True,
            "pause_before_delete_hours": 24,
        },
    )


def _candidate(**overrides: object) -> TorrentCandidate:
    data: dict[str, object] = {
        "site": "demo-free",
        "title": "High Confidence Torrent",
        "source_url": "https://tracker.example/details.php?id=1",
        "download_url": "https://tracker.example/download.php?id=1&passkey=secret",
        "size_bytes": 10 * 1024 * 1024 * 1024,
        "seeders": 20,
        "leechers": 30,
        "discount": "free",
        "left_time_minutes": 240,
        "hr": False,
    }
    data.update(overrides)
    return TorrentCandidate(**data)


def _scored(**overrides: object) -> ScoreBreakdown:
    candidate = overrides.pop("candidate", _candidate())
    data: dict[str, object] = {
        "candidate_id": candidate.stable_id,
        "score": 95,
        "accepted": True,
        "reasons": ["discount free accepted", "leechers strong"],
        "candidate": candidate,
    }
    data.update(overrides)
    return ScoreBreakdown(**data)


def _managed_torrent(**overrides: object) -> ManagedTorrent:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "hash": "abcd1234",
        "name": "Managed Torrent",
        "category": "seed",
        "tags": {"seed-agent", "seed"},
        "state": "uploading",
        "size_bytes": 10 * 1024 * 1024 * 1024,
        "uploaded_bytes": 512 * 1024 * 1024,
        "downloaded_bytes": 10 * 1024 * 1024 * 1024,
        "added_at": now - timedelta(days=10),
        "completed_at": now - timedelta(days=10),
        "last_activity_at": now - timedelta(days=10),
        "save_path": "/mnt/data",
        "metadata": {},
    }
    data.update(overrides)
    return ManagedTorrent(**data)


def _config_file(tmp_path: Path, secret_ref: str | None = None) -> Path:
    secret_line = "null" if secret_ref is None else secret_ref
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode: balanced
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
discovery:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  max_seeders: 80
  allow_hr: false
scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
downloader:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: ["seed-agent", "movie"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
  secret_ref: {secret_line}
cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )
    return path


def _json_output(result) -> dict[str, object]:
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    return parsed


def test_cli_help_lists_phase_one_commands() -> None:
    from seed_agent.cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "discover" in result.output
    assert "score" in result.output
    assert "enqueue" in result.output
    assert "review" in result.output
    assert "prune" in result.output
    assert "daily-report" in result.output
    assert "run-once" in result.output
    assert "healthcheck" in result.output
    assert "schedule-run" in result.output
    assert "site-probe" in result.output


def test_enqueue_help_includes_execute_flag() -> None:
    from seed_agent.cli import app

    result = CliRunner().invoke(app, ["enqueue", "--help"])

    assert result.exit_code == 0
    assert "--execute" in result.output


@pytest.mark.parametrize("command", ["prune", "run-once"])
def test_mutating_command_help_includes_execute_flag(command: str) -> None:
    from seed_agent.cli import app

    result = CliRunner().invoke(app, [command, "--help"])

    assert result.exit_code == 0
    assert "--execute" in result.output


def test_schedule_run_help_includes_interval_and_free_window_flags() -> None:
    from seed_agent.cli import app

    result = CliRunner().invoke(app, ["schedule-run", "--help"])

    assert result.exit_code == 0
    assert "--interval-minutes" in result.output
    assert "min-free-window" in result.output
    assert "require-known-free" in result.output
    assert "heartbeat-file" in result.output


def test_discover_command_prints_safe_output_without_raw_download_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    config = _config()

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)

    result = CliRunner().invoke(cli.app, ["discover", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "discover"
    assert payload["candidates"][0]["title"] == "High Confidence Torrent"
    assert payload["candidates"][0]["sparse"] is False
    assert payload["candidates"][0]["detail_enriched"] is False
    assert "passkey" not in result.output
    assert _candidate().download_url not in result.output
    assert "download_url" not in result.output


def test_schedule_run_executes_single_cycle_and_emits_schedule_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    heartbeat_path = tmp_path / "state" / "heartbeat.json"
    seen: list[tuple[Path, bool, int | None, bool]] = []

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
    ) -> dict[str, object]:
        seen.append(
            (
                config_path_value,
                execute,
                min_free_window_minutes,
                require_known_free_window,
            )
        )
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 1,
            "scored": 1,
            "accepted": 1,
            "enqueued": 1,
            "scores": [],
            "decisions": [],
        }

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--execute",
            "--interval-minutes",
            "15",
            "--min-free-window-minutes",
            "180",
            "--heartbeat-file",
            str(heartbeat_path),
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "schedule-run"
    assert payload["cycle"] == 1
    assert payload["interval_minutes"] == 15
    assert payload["min_free_window_minutes"] == 180
    assert payload["require_known_free_window"] is True
    assert payload["heartbeat_file"] == str(heartbeat_path)
    assert seen == [(config_path, True, 180, True)]
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["cycle"] == 1
    assert heartbeat["interval_minutes"] == 15
    assert heartbeat["accepted"] == 1
    assert heartbeat["enqueued"] == 1


def test_healthcheck_reports_recent_heartbeat(tmp_path: Path) -> None:
    from seed_agent.cli import app

    config_path = _config_file(tmp_path)
    heartbeat_path = tmp_path / "state" / "heartbeat.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "cycle": 2,
                "interval_minutes": 30,
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "healthcheck",
            "--config",
            str(config_path),
            "--heartbeat-file",
            str(heartbeat_path),
            "--max-staleness-minutes",
            "90",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "healthcheck"
    assert payload["status"] == "ok"
    assert payload["heartbeat"]["cycle"] == 2
    assert payload["heartbeat"]["interval_minutes"] == 30


def test_healthcheck_fails_for_stale_heartbeat(tmp_path: Path) -> None:
    from seed_agent.cli import app

    config_path = _config_file(tmp_path)
    heartbeat_path = tmp_path / "state" / "heartbeat.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at": (datetime.now(UTC) - timedelta(hours=4)).isoformat(),
                "cycle": 2,
                "interval_minutes": 30,
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "healthcheck",
            "--config",
            str(config_path),
            "--heartbeat-file",
            str(heartbeat_path),
            "--max-staleness-minutes",
            "90",
        ],
    )

    assert result.exit_code == 1
    payload = _json_output(result)
    assert payload["command"] == "healthcheck"
    assert payload["status"] == "error"
    assert "heartbeat stale" in payload["error"]


def test_site_probe_reports_sparse_and_enriched_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "cookie_ref": "local/secrets/mt.cookie",
                    "api_key_ref": "local/secrets/mt.api-key",
                    "discovery_mode": "api",
                    "api_discovery": {
                        "mode": "adult",
                        "only_free": True,
                        "sort_field": "downloads",
                        "sort_order": "desc",
                        "page_size": 50,
                        "min_seeders": 0,
                        "max_seeders": 200,
                        "min_leechers": 0,
                        "min_times_completed": 0,
                    },
                }
            ],
        }
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [
            _candidate(
                site="mt",
                source_url="https://kp.m-team.cc/detail/1",
                metadata={"rss_sparse_candidate": True},
            ),
            _candidate(
                site="mt",
                title="Enriched",
                source_url="https://kp.m-team.cc/detail/2",
                metadata={"rss_sparse_candidate": True, "mteam_detail_enriched": True},
            ),
        ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "_read_secret_ref", lambda secret_ref, config_dir: "secret-api-key")
    monkeypatch.setattr(cli, "_read_cookie_ref", lambda cookie_ref, config_dir: None)

    result = CliRunner().invoke(cli.app, ["site-probe", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "site-probe"
    mt = payload["sites"]["mt"]
    assert mt["site_type"] == "mteam"
    assert mt["access_mode"] == "api_key"
    assert mt["discovery_mode"] == "api"
    assert mt["discovered"] == 2
    assert mt["sparse"] == 2
    assert mt["detail_enriched"] == 1
    assert mt["sample_titles"] == ["High Confidence Torrent", "Enriched"]


def test_mutating_dry_run_does_not_require_qb_secret_or_real_downloader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path, secret_ref=None)
    config = _config()
    events: list[Decision] = []

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    async def fake_enqueue_candidates(
        scored,
        downloader,
        policy,
        execute,
        *,
        paused=False,
        pool_usage=None,
        pause_reasons=None,
    ):
        assert execute is False
        assert pool_usage is None
        return [
            Decision(
                action="qb.enqueue",
                target_id=_scored().candidate_id,
                execute=False,
                reason="dry run",
                new_state={"candidate_title": _scored().candidate.title},
            )
        ]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("real downloader helper should not be called in dry-run")

    def fake_write_audit_decisions(config: SeedAgentConfig, decisions: list[Decision]) -> None:
        events.extend(decisions)

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "build_downloader", fail_if_called)
    monkeypatch.setattr(cli, "_write_audit_decisions", fake_write_audit_decisions)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "prune"
    assert payload["managed_count"] == 0
    assert payload["decisions"] == []
    assert events == []
    assert "download_url" not in result.output
    assert "passkey" not in result.output


def test_enqueue_dry_run_uses_default_category_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path, secret_ref=None)
    config = _config()
    events: list[Decision] = []

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    async def fake_enqueue_candidates(
        scored,
        downloader,
        policy,
        execute,
        *,
        paused=False,
        pool_usage=None,
        pause_reasons=None,
    ):
        assert policy.name == "seed"
        assert list(policy.tags) == ["seed-agent", "seed"]
        assert execute is False
        assert paused is False
        assert pool_usage is None
        return [
            Decision(
                action="qb.enqueue",
                target_id=_scored().candidate_id,
                execute=False,
                reason="dry run",
                new_state={"candidate_title": _scored().candidate.title},
            )
        ]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("real downloader helper should not be called in dry-run")

    def fake_write_audit_decisions(config: SeedAgentConfig, decisions: list[Decision]) -> None:
        events.extend(decisions)

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "build_downloader", fail_if_called)
    monkeypatch.setattr(cli, "_write_audit_decisions", fake_write_audit_decisions)

    result = CliRunner().invoke(cli.app, ["enqueue", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "enqueue"
    assert payload["enqueued"] == 1
    assert events
    assert "passkey" not in result.output


def test_prune_execute_updates_state_to_paused_for_cold_managed_torrent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="abcd1234",
    )

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="abcd1234")]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(
        cli.app, ["prune", "--config", str(config_path), "--execute"]
    )

    assert result.exit_code == 0
    assert downloader.calls == [("pause", "abcd1234", None)]
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.PAUSED.value


def test_prune_execute_updates_state_to_deleted_for_old_paused_torrent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="abcd1234",
    )

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="abcd1234",
                    state="pausedUP",
                    metadata={"paused_at": datetime.now(UTC) - timedelta(days=10)},
                )
            ]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(
        cli.app, ["prune", "--config", str(config_path), "--execute"]
    )

    assert result.exit_code == 0
    assert downloader.calls == [("delete", "abcd1234", True)]
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.DELETED.value


def test_prune_execute_uses_persisted_pause_timestamp_for_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.PAUSED,
        score=95,
        torrent_hash="abcd1234",
    )
    store.mark_torrent_paused("abcd1234", datetime.now(UTC) - timedelta(days=10))

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="abcd1234", state="pausedUP", metadata={})]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(
        cli.app, ["prune", "--config", str(config_path), "--execute"]
    )

    assert result.exit_code == 0
    assert downloader.calls == [("delete", "abcd1234", True)]
    assert store.get_torrent_runtime("abcd1234") is None


def test_cli_runtime_files_follow_config_workspace_not_invocation_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    workspace = tmp_path / "workspace"
    runtime_cwd = tmp_path / "elsewhere"
    workspace.mkdir()
    runtime_cwd.mkdir()
    config_path = _config_file(workspace)
    monkeypatch.chdir(runtime_cwd)

    result = CliRunner().invoke(
        cli.app,
        ["intent-add", "Inception 2010 1080p", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert (workspace / ".seed-agent" / "state.db").exists()
    assert (workspace / ".seed-agent" / "audit.jsonl").exists()
    assert not (runtime_cwd / ".seed-agent" / "state.db").exists()


def test_prune_dry_run_does_not_update_state_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="abcd1234",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("build_downloader should not be called in dry-run")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", fail_if_called)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value


def test_prune_dry_run_previews_live_torrents_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="abcd1234",
    )

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, object]] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="abcd1234")]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["managed_count"] == 1
    assert payload["decisions"][0]["action"] == "qb.cleanup.pause"
    assert payload["decisions"][0]["execute"] is False
    assert downloader.calls == []
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value


def test_prune_dry_run_keeps_recently_uploaded_torrent_from_runtime_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="abcd1234",
    )

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="abcd1234",
                    uploaded_bytes=15 * 1024**3,
                    metadata={"upspeed_bps": 0, "dlspeed_bps": 0},
                )
            ]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run prune must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run prune must not delete torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    store._upsert_torrent_runtime(  # type: ignore[attr-defined]
        "abcd1234",
        uploaded_bytes=13 * 1024**3,
        downloaded_bytes=10 * 1024**3,
        upspeed_bps=0,
        dlspeed_bps=0,
        seen_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["decisions"][0]["action"] == "qb.cleanup.keep"
    assert "recent upload 2.00 GiB >= min 1.00 GiB" in payload["decisions"][0]["reason"]


def test_prune_pool_usage_includes_add_only_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            if category == "seed":
                return [
                    _managed_torrent(
                        hash="seed-hash",
                        category="seed",
                        size_bytes=1 * 1024**4,
                    )
                ]
            if category == "movie":
                return [
                    _managed_torrent(
                        hash="movie-hash",
                        category="movie",
                        tags={"seed-agent", "movie"},
                        size_bytes=2 * 1024**4,
                    )
                ]
            return []

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run prune must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run prune must not delete torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["managed_count"] == 1
    assert payload["pool_usage"]["downloads"]["size_tib"] == 1.0
    assert payload["pool_usage"]["media"]["size_tib"] == 2.0
    assert [decision["target_id"] for decision in payload["decisions"]] == ["seed-hash"]


def test_review_reports_runtime_activity_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            if category == "seed":
                return [
                    _managed_torrent(
                        hash="seed-active",
                        state="uploading",
                        metadata={
                            "upspeed_bps": 2 * 1024**2,
                            "dlspeed_bps": 0,
                            "uploaded_session_bytes": 3 * 1024**3,
                            "amount_left_bytes": 0,
                        },
                    ),
                    _managed_torrent(
                        hash="seed-downloading",
                        state="downloading",
                        metadata={
                            "upspeed_bps": 0,
                            "dlspeed_bps": 4 * 1024**2,
                            "uploaded_session_bytes": 0,
                            "amount_left_bytes": 5 * 1024**3,
                        },
                    ),
                ]
            if category == "movie":
                return [
                    _managed_torrent(
                        hash="movie-paused",
                        category="movie",
                        tags={"seed-agent", "movie"},
                        state="pausedUP",
                        metadata={},
                    )
                ]
            return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["review", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["managed_count"] == 3
    assert payload["runtime_activity"]["active_upload_count"] == 1
    assert payload["runtime_activity"]["active_download_count"] == 1
    assert payload["runtime_activity"]["paused_count"] == 1
    assert payload["runtime_activity"]["total_upspeed_mib_s"] == 2.0
    assert payload["runtime_activity"]["total_dlspeed_mib_s"] == 4.0
    assert payload["runtime_activity"]["total_amount_left_gb"] == 5.0
    active = payload["managed_torrents"][0]
    assert "upspeed_mib_s" in active
    assert "uploaded_session_gb" in active


def test_run_once_dry_run_reports_runtime_activity_and_default_pool_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    async def fake_enqueue_candidates(
        scored,
        downloader,
        policy,
        execute,
        *,
        paused=False,
        pool_usage=None,
        pause_reasons=None,
    ):
        assert execute is False
        assert paused is False
        assert pool_usage is not None
        return []

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="seed-active",
                    state="uploading",
                    metadata={
                        "upspeed_bps": 1024**2,
                        "dlspeed_bps": 512 * 1024,
                        "amount_left_bytes": 2 * 1024**3,
                    },
                )
            ]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run run-once must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run run-once must not delete torrents")

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            raise AssertionError("dry-run run-once must not add torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["managed_count"] == 1
    assert payload["runtime_activity"]["active_upload_count"] == 1
    assert payload["runtime_activity"]["active_download_count"] == 1
    assert payload["default_pool_usage"]["over_budget"] is False
    assert payload["enqueue_paused_by_pool_policy"] is False


def test_enqueue_dry_run_reports_runtime_activity_and_default_pool_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    async def fake_enqueue_candidates(
        scored,
        downloader,
        policy,
        execute,
        *,
        paused=False,
        pool_usage=None,
        pause_reasons=None,
    ):
        assert execute is False
        assert pool_usage is not None
        return []

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="seed-active",
                    state="uploading",
                    metadata={
                        "upspeed_bps": 2 * 1024**2,
                        "dlspeed_bps": 0,
                        "amount_left_bytes": 0,
                    },
                )
            ]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run enqueue must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run enqueue must not delete torrents")

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            raise AssertionError("dry-run enqueue must not add torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["enqueue", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["managed_count"] == 1
    assert payload["runtime_activity"]["active_upload_count"] == 1
    assert payload["default_pool_usage"]["over_budget"] is False
    assert payload["enqueue_paused_by_pool_policy"] is False


def test_prune_execute_failure_persists_prior_state_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    state_path = tmp_path / ".seed-agent" / "state.db"
    store = StateStore(state_path)
    first_id = "demo-free:https://tracker.example/details.php?id=1"
    second_id = "demo-free:https://tracker.example/details.php?id=2"
    store.upsert_candidate(
        stable_id=first_id,
        title="First Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="first",
    )
    store.upsert_candidate(
        stable_id=second_id,
        title="Second Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=90,
        torrent_hash="second",
    )

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="first"), _managed_torrent(hash="second")]

        async def pause(self, hash: str) -> None:
            self.calls.append(hash)
            if hash == "second":
                raise RuntimeError("pause failed")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("delete should not be called")

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(
        cli.app, ["prune", "--config", str(config_path), "--execute"]
    )

    assert result.exit_code == 1
    payload = _json_output(result)
    assert payload["error"] == "qBittorrent cleanup batch failed"
    assert [decision["action"] for decision in payload["decisions"]] == [
        "qb.cleanup.pause",
        "qb.cleanup.pause.failed",
    ]
    assert store.get_candidate(first_id)["state"] == LifecycleState.PAUSED.value
    assert store.get_candidate(second_id)["state"] == LifecycleState.ENQUEUED.value
    audit_path = tmp_path / ".seed-agent" / "audit.jsonl"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "qb.cleanup.pause" in audit_text
    assert "qb.cleanup.pause.failed" in audit_text


def test_execute_commands_fail_when_downloader_secret_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path, secret_ref=None)
    config = _config()

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)

    commands = [
        ["enqueue", "--config", str(config_path), "--execute"],
        ["prune", "--config", str(config_path), "--execute"],
        ["run-once", "--config", str(config_path), "--execute"],
    ]

    for command in commands:
        result = CliRunner().invoke(cli.app, command)
        assert result.exit_code != 0
        assert "missing downloader secret" in result.output
        assert str(config_path) not in result.output
        assert "passkey" not in result.output


def test_build_downloader_resolves_repo_relative_secret_for_config_dir_named_config(
    tmp_path: Path,
) -> None:
    from seed_agent.cli import build_downloader
    from seed_agent.config import load_config

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    secret_dir = tmp_path / "local" / "secrets"
    secret_dir.mkdir(parents=True)

    config_path = config_dir / "example.yaml"
    config_path.write_text(
        """
mode: balanced
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
discovery:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  max_seeders: 80
  allow_hr: false
scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
downloader:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: local/secrets/qb.yaml
cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )
    (secret_dir / "qb.yaml").write_text(
        "base_url: http://qb.local:8080\nusername: alice\npassword: secret\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    downloader = build_downloader(config)

    assert downloader.base_url == "http://qb.local:8080"
    assert downloader.username == "alice"
    assert downloader.password == "secret"


def test_run_once_invoke_with_execute_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    events: list[Decision] = []

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    async def fake_enqueue_candidates(
        scored,
        downloader,
        policy,
        execute,
        *,
        paused=False,
        pool_usage=None,
        pause_reasons=None,
    ):
        assert execute is True
        assert policy.name == "seed"
        return [
            Decision(
                action="qb.enqueue",
                target_id=_scored().candidate_id,
                execute=True,
                reason="executed",
                new_state={"candidate_title": _scored().candidate.title},
            )
        ]

    class FakeDownloader:
        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return "0123456789abcdef0123456789abcdef01234567"

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return []

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

    def fake_build_downloader(config: SeedAgentConfig):
        return FakeDownloader()

    def fake_write_audit_decisions(config: SeedAgentConfig, decisions: list[Decision]) -> None:
        events.extend(decisions)

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "build_downloader", fake_build_downloader)
    monkeypatch.setattr(cli, "_write_audit_decisions", fake_write_audit_decisions)

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path), "--execute"])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "run-once"
    assert events
