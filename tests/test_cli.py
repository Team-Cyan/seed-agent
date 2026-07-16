from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import (
    Decision,
    LifecycleState,
    ManagedTorrent,
    ScoreBreakdown,
    TorrentCandidate,
)
from seed_agent.policies.category_policy import PoolUsage
from seed_agent.state import StateStore

_HELP_ENV = {"COLUMNS": "160", "GITHUB_ACTIONS": ""}


def _invoke_help(app: object, args: list[str]) -> object:
    return CliRunner().invoke(app, args, env=_HELP_ENV)


def _config(secret_ref: str | None = None) -> SeedAgentConfig:
    return SeedAgentConfig(
        mode="balanced",
        tracker_sites=[
            {
                "name": "demo-free",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss.php",
                "cookie_ref": None,
            }
        ],
        pt_filters=DiscoveryConfig(
            discounts=["free", "2xfree"],
            min_left_time_minutes=120,
            min_leechers=8,
            target_seed_leecher_ratio=10,
            allow_hr=False,
        ),
        pt_scoring=ScoringConfig(
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
        download_client={
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
        seed_cleanup={
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


def test_pt_batch_rejects_large_candidate_without_blocking_smaller_fit() -> None:
    from seed_agent.cli import _enqueue_candidate_batches

    config = _config()
    max_size_bytes = 10 * 1024**4
    pool_usage = PoolUsage(
        pool_name="downloads",
        size_bytes=max_size_bytes - 6 * 1024**3,
        max_size_bytes=max_size_bytes,
    )
    large = _scored(
        score=100,
        candidate=_candidate(
            title="Large paused candidate",
            source_url="https://tracker.example/details.php?id=large",
            download_url="https://tracker.example/download.php?id=large",
            size_bytes=10 * 1024**3,
        ),
    )
    small = _scored(
        score=90,
        candidate=_candidate(
            title="Small candidate after paused liability",
            source_url="https://tracker.example/details.php?id=small",
            download_url="https://tracker.example/download.php?id=small",
            size_bytes=1024**3,
        ),
    )

    batches = _enqueue_candidate_batches(
        [small, large],
        config,
        [],
        pool_usage,
        None,
    )

    assert len(batches) == 2
    assert batches[0] == ([small], False, [])
    assert batches[1][0] == [large]
    assert batches[1][1] is True
    assert "budget pool downloads capacity reserved" in batches[1][2][0]


def test_apply_free_window_safety_allows_mteam_unlimited_window() -> None:
    from seed_agent.cli import _apply_free_window_safety

    candidate = _candidate(
        site="mteam",
        left_time_minutes=None,
        metadata={
            "mteam_discovery_mode": "api",
            "left_time_source": "mteam_api_unlimited",
        },
    )

    adjusted = _apply_free_window_safety(
        [_scored(candidate=candidate)],
        min_free_window_minutes=180,
        require_known_free_window=True,
    )

    assert adjusted[0].accepted is True
    assert adjusted[0].score == 95
    assert "left_time required for execute safety" not in adjusted[0].reasons


def test_candidate_free_window_uses_far_future_for_unlimited_mteam_api() -> None:
    from seed_agent.cli import _candidate_free_window_expires_at

    candidate = _candidate(
        site="mteam",
        left_time_minutes=None,
        metadata={
            "mteam_discovery_mode": "api",
            "left_time_source": "mteam_api_unlimited",
        },
    )

    assert _candidate_free_window_expires_at(candidate) == "9999-12-31T23:59:59+00:00"


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


def _managed_incomplete_torrent(**overrides: object) -> ManagedTorrent:
    data: dict[str, object] = {
        "state": "downloading",
        "uploaded_bytes": 512 * 1024 * 1024,
        "downloaded_bytes": 5 * 1024 * 1024 * 1024,
        "completed_at": None,
        "metadata": {
            "amount_left_bytes": 5 * 1024 * 1024 * 1024,
            "recent_upload_gb": 0.2,
        },
    }
    data.update(overrides)
    return _managed_torrent(**data)


def test_qb_only_backfill_targets_prioritize_unknown_incomplete_risk(
    tmp_path: Path,
) -> None:
    from seed_agent import cli

    store = StateStore(tmp_path / "state.db")
    torrents = [
        _managed_torrent(
            hash="completed-new",
            name="Completed New",
            added_at=datetime(2026, 7, 10, tzinfo=UTC),
            state="stalledUP",
            metadata={"amount_left_bytes": 0},
        ),
        _managed_torrent(
            hash="incomplete-small",
            name="Incomplete Small",
            added_at=datetime(2026, 7, 8, tzinfo=UTC),
            completed_at=None,
            state="stoppedDL",
            downloaded_bytes=1 * 1024**3,
            metadata={"amount_left_bytes": 3 * 1024**3},
        ),
        _managed_torrent(
            hash="incomplete-large",
            name="Incomplete Large",
            added_at=datetime(2026, 7, 8, tzinfo=UTC),
            completed_at=None,
            state="stoppedDL",
            downloaded_bytes=1 * 1024**3,
            metadata={"amount_left_bytes": 30 * 1024**3},
        ),
    ]
    for torrent in torrents:
        store.upsert_candidate(
            stable_id=f"qb:{torrent.hash}",
            title=torrent.name,
            site="qb",
            state=LifecycleState.DOWNLOADING,
            score=None,
            torrent_hash=torrent.hash,
        )

    targets = cli._qb_only_backfill_targets(store, torrents)

    assert [item.hash for item in targets] == [
        "incomplete-large",
        "incomplete-small",
        "completed-new",
    ]


def test_backfill_targets_refresh_tracked_incomplete_but_not_tracked_completed(
    tmp_path: Path,
) -> None:
    from seed_agent import cli

    store = StateStore(tmp_path / "state.db")
    incomplete = _managed_incomplete_torrent(hash="tracked-incomplete")
    completed = _managed_torrent(hash="tracked-completed", metadata={"amount_left_bytes": 0})
    for torrent in (incomplete, completed):
        store.upsert_candidate(
            stable_id=f"mteam:https://kp.m-team.cc/detail/{torrent.hash}",
            title=torrent.name,
            site="mteam",
            state=LifecycleState.DOWNLOADING,
            score=None,
            torrent_hash=torrent.hash,
        )

    targets = cli._qb_only_backfill_targets(store, [completed, incomplete])

    assert [item.hash for item in targets] == ["tracked-incomplete"]


def test_mteam_torrent_id_from_tracker_decodes_credential() -> None:
    from seed_agent import cli

    credential = base64.b64encode(b"sign=abc&t=1783531016&tid=1206069&uid=305694").decode()
    torrent = _managed_torrent(
        metadata={
            "tracker": f"https://tracker.m-team.io/announce?credential={credential}",
        }
    )

    assert cli._mteam_torrent_id_from_tracker(torrent) == "1206069"


def test_live_reconciliation_links_unlinked_candidate_by_tracker_tid(
    tmp_path: Path,
) -> None:
    from seed_agent import cli

    store = StateStore(tmp_path / "state.db")
    store.upsert_candidate(
        stable_id="mteam:https://kp.m-team.cc/detail/1206069",
        title="Tracker Title That Differs From qB",
        site="mteam",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash=None,
        discount="free",
    )
    credential = base64.b64encode(b"sign=abc&t=1783531016&tid=1206069&uid=305694").decode()
    torrent = _managed_incomplete_torrent(
        hash="live-hash",
        name="Renamed qB Content Root",
        metadata={
            "amount_left_bytes": 5 * 1024**3,
            "tracker": f"https://tracker.m-team.io/announce?credential={credential}",
        },
    )

    result = cli._persist_live_torrent_candidates(store, [torrent])

    assert result["linked_existing_candidates"] == 1
    rows = store.list_by_torrent_hash("live-hash")
    assert [row["stable_id"] for row in rows] == ["mteam:https://kp.m-team.cc/detail/1206069"]


@pytest.mark.asyncio
async def test_find_mteam_match_uses_tracker_tid_before_keyword_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    calls: list[str] = []

    class FakeMTeamApiClient:
        def __init__(self, **kwargs: object) -> None:
            calls.append("init")

        async def fetch_torrent_detail(self, torrent_id: str) -> dict[str, object]:
            calls.append(f"detail:{torrent_id}")
            return {
                "id": torrent_id,
                "name": "Risky Incomplete Torrent",
                "size": 42 * 1024**3,
                "discount": "NORMAL",
                "status": {"seeders": 1, "leechers": 0},
            }

        async def _candidate_from_search_row(
            self, site: str, row: dict[str, object]
        ) -> TorrentCandidate | None:
            return TorrentCandidate(
                site=site,
                title=str(row["name"]),
                source_url=f"https://kp.m-team.cc/detail/{row['id']}",
                download_url=f"mteam-api://torrent/{row['id']}",
                size_bytes=int(row["size"]),
                seeders=1,
                leechers=0,
                discount="normal",
                metadata={"mteam_torrent_id": str(row["id"])},
            )

    async def fail_keyword_search(**kwargs: object) -> list[TorrentCandidate]:
        raise AssertionError("keyword search should not run when tracker tid is available")

    monkeypatch.setattr(cli, "MTeamApiClient", FakeMTeamApiClient)
    monkeypatch.setattr(cli, "fetch_mteam_api_candidates", fail_keyword_search)
    credential = base64.b64encode(b"sign=abc&t=1783531016&tid=1206069&uid=305694").decode()
    torrent = _managed_incomplete_torrent(
        name="Risky Incomplete Torrent",
        metadata={
            "amount_left_bytes": 10 * 1024**3,
            "tracker": f"https://tracker.m-team.io/announce?credential={credential}",
        },
    )
    request_budget = {"remaining": 2, "used": 0}

    result = await cli._find_mteam_match_for_torrent(
        site_name="mteam",
        site_mode="adult",
        api_key="secret",
        api_key_header="x-api-key",
        torrent=torrent,
        request_budget=request_budget,
    )

    assert result["status"] == "matched"
    assert result["candidate"].discount.value == "normal"
    assert result["candidate"].metadata["backfill_match_source"] == "tracker_tid"
    assert request_budget == {"remaining": 1, "used": 1}
    assert calls == ["init", "detail:1206069"]


def _config_file(tmp_path: Path, secret_ref: str | None = None) -> Path:
    secret_line = "null" if secret_ref is None else secret_ref
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
mode: balanced
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  target_seed_leecher_ratio: 10
  allow_hr: false
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
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
seed_cleanup:
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
    lines = [line for line in result.output.splitlines() if line.strip()]
    parsed = json.loads(lines[-1])
    assert isinstance(parsed, dict)
    return parsed


def test_cli_help_lists_phase_one_commands() -> None:
    from seed_agent.cli import app

    result = _invoke_help(app, ["--help"])

    assert result.exit_code == 0
    assert "discover" in result.output
    assert "score" in result.output
    assert "enqueue" in result.output
    assert "review" in result.output
    assert "prune" in result.output
    assert "daily-report" in result.output
    assert "run-once" in result.output
    assert "healthcheck" in result.output
    assert "runtime-status" in result.output
    assert "schedule-run" in result.output
    assert "site-probe" in result.output


def test_cli_version_option_reports_package_version() -> None:
    from seed_agent import __version__
    from seed_agent.cli import app

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_enqueue_help_includes_execute_flag() -> None:
    from seed_agent.cli import app

    result = _invoke_help(app, ["enqueue", "--help"])

    assert result.exit_code == 0
    assert "--execute" in result.output


@pytest.mark.parametrize("command", ["prune", "run-once"])
def test_mutating_command_help_includes_execute_flag(command: str) -> None:
    from seed_agent.cli import app

    result = _invoke_help(app, [command, "--help"])

    assert result.exit_code == 0
    assert "--execute" in result.output


def test_schedule_run_help_includes_interval_and_free_window_flags() -> None:
    from seed_agent.cli import app

    result = _invoke_help(app, ["schedule-run", "--help"])

    assert result.exit_code == 0
    assert "--interval-minutes" in result.output
    assert "min-free-window" in result.output
    assert "require-known-free" in result.output
    assert "heartbeat-file" in result.output


def test_web_help_includes_local_server_options() -> None:
    from seed_agent.cli import app

    result = _invoke_help(app, ["web", "--help"])

    assert result.exit_code == 0
    assert "--config" in result.output
    assert "--host" in result.output
    assert "--port" in result.output


def test_web_reports_actionable_port_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    import seed_agent.web.app as web_app
    from seed_agent.cli import app

    config_path = tmp_path / "config.yaml"
    config_path.write_text("mode: balanced\ntracker_sites: []\n", encoding="utf-8")

    def raise_port_conflict(config: Path, host: str, port: int) -> None:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(web_app, "serve", raise_port_conflict)

    result = CliRunner().invoke(
        app,
        ["web", "--config", str(config_path), "--host", "127.0.0.1", "--port", "8765"],
    )

    assert result.exit_code == 1
    assert "Port 8765 is already in use on 127.0.0.1" in result.output
    assert "--port 8766" in result.output


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
    from seed_agent import __version__, cli

    config_path = _config_file(tmp_path)
    heartbeat_path = tmp_path / "state" / "heartbeat.json"
    seen: list[tuple[Path, bool, int | None, bool]] = []
    startup_heartbeats: list[dict[str, object]] = []

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        assert prune is False
        assert capacity_prune is False
        startup_heartbeats.append(json.loads(heartbeat_path.read_text(encoding="utf-8")))
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
            "scores": [{"candidate_id": "large-detail"}],
            "decisions": [{"action": "qb.enqueue"}],
        }

    intent_seen: list[tuple[Path, bool]] = []

    def fake_intent_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        search_ingested: bool = True,
        run_id: str | None = None,
    ) -> dict[str, object]:
        intent_seen.append((config_path_value, execute, search_ingested))
        return {
            "command": "intent-run-once",
            "config": str(config_path_value),
            "execute": execute,
            "search_enabled": search_ingested,
            "ingested": 2,
            "searched": 2 if search_ingested else 0,
            "ranked": 2 if search_ingested else 0,
            "enqueue_candidates": 1 if search_ingested else 0,
            "decisions": [{"action": "intent.search"}],
        }

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fake_intent_run_once_payload)
    monkeypatch.setattr(cli, "_scheduled_intent_search_due", lambda *args, **kwargs: False)
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
    assert payload["intent_enabled"] is True
    assert payload["intent_execute"] is False
    assert payload["heartbeat_file"] == str(heartbeat_path)
    assert payload["scores_count"] == 1
    assert payload["decisions_count"] == 1
    assert "scores" not in payload
    assert "decisions" not in payload
    assert "prune" not in payload
    assert payload["intent"] == {
        "command": "intent-run-once",
        "run_id": None,
        "execute": False,
        "search_enabled": False,
        "ingested": 2,
        "searched": 0,
        "ranked": 0,
        "enqueue_candidates": 0,
        "decisions_count": 1,
    }
    assert seen == [(config_path, True, 180, True)]
    assert intent_seen == [(config_path, False, False)]
    assert startup_heartbeats == [
        {
            "accepted": None,
            "command": "schedule-run",
            "config": str(config_path),
            "cycle": 1,
            "enqueued": None,
            "error": None,
            "execute": True,
            "interval_minutes": 15,
            "intent": None,
            "intent_search_enabled": None,
            "phase": "running",
            "run_id": startup_heartbeats[0]["run_id"],
            "schedule_backoff": None,
            "skipped_by_backoff": False,
            "updated_at": startup_heartbeats[0]["updated_at"],
            "version": __version__,
        }
    ]
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["cycle"] == 1
    assert heartbeat["interval_minutes"] == 15
    assert heartbeat["phase"] is None
    assert heartbeat["accepted"] == 1
    assert heartbeat["enqueued"] == 1
    assert isinstance(heartbeat["run_id"], str)
    assert heartbeat["run_id"].startswith("sched-")
    assert heartbeat["intent"]["searched"] == 0
    assert heartbeat["intent_search_enabled"] is False


def test_schedule_run_can_skip_intent_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    intent_called = False

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        assert prune is False
        assert capacity_prune is False
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
        }

    def fake_intent_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        search_ingested: bool = True,
        run_id: str | None = None,
    ) -> dict[str, object]:
        nonlocal intent_called
        intent_called = True
        return {"command": "intent-run-once", "execute": execute}

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fake_intent_run_once_payload)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--no-intent",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["intent_enabled"] is False
    assert "intent" not in payload
    assert intent_called is False


def test_schedule_run_uses_yaml_scheduler_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["scheduler"] = {
        "interval_minutes": 7,
        "min_free_window_minutes": 90,
        "require_known_free_window": False,
        "prune_enabled": False,
        "tracker_backfill_enabled": False,
        "intent_enabled": False,
    }
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        seen.update(
            {
                "min_free_window_minutes": min_free_window_minutes,
                "require_known_free_window": require_known_free_window,
                "capacity_prune": capacity_prune,
            }
        )
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
        }

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)

    result = CliRunner().invoke(
        cli.app,
        ["schedule-run", "--config", str(config_path), "--max-cycles", "1"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["interval_minutes"] == 7
    assert payload["prune_enabled"] is False
    assert payload["tracker_backfill_enabled"] is False
    assert payload["intent_enabled"] is False
    assert seen == {
        "min_free_window_minutes": 90,
        "require_known_free_window": False,
        "capacity_prune": False,
    }


def test_scheduled_intent_search_runs_once_after_daily_hour() -> None:
    from seed_agent import cli

    assert (
        cli._scheduled_intent_search_due(
            datetime(2026, 7, 3, 0, 15),
        )
        is True
    )
    assert (
        cli._scheduled_intent_search_due(
            datetime(2026, 7, 3, 1, 0),
            last_search_at=datetime(2026, 7, 3, 0, 15),
        )
        is False
    )
    assert cli._scheduled_intent_search_due(datetime(2026, 7, 3, 22, 0), hour=23) is False
    assert (
        cli._scheduled_intent_search_due(
            datetime(2026, 7, 3, 23, 30),
            hour=23,
            last_search_at=datetime(2026, 7, 2, 23, 45),
        )
        is True
    )
    assert cli._scheduled_intent_search_due(datetime(2026, 7, 3, 1, 0), mode="every_cycle") is True


def test_scheduler_status_warns_when_tracker_backfill_is_unresolved() -> None:
    from seed_agent import cli

    assert (
        cli._schedule_run_status({"tracker_source_backfill": {"summary": {"not_found": 1}}})
        == "warning"
    )


def test_schedule_rate_limit_backoff_uses_next_midnight_after_24h(
    tmp_path: Path,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    local_tz = datetime.now().astimezone().tzinfo
    now = datetime(2026, 7, 3, 21, 30, tzinfo=local_tz)

    status = cli._record_schedule_rate_limit_backoff(
        config_path,
        reason="mteam request too frequent",
        now=now,
    )

    until = datetime.fromisoformat(status["until"])
    assert status["active"] is True
    assert until.hour == 0
    assert until.minute == 0
    assert until >= now + timedelta(hours=24)
    assert until - now < timedelta(hours=48)
    assert (tmp_path / ".seed-agent" / "schedule-backoff.json").exists()


def test_schedule_run_records_backoff_and_skips_intent_after_mteam_rate_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    intent_called = False

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
            "discovery_warnings": [
                {
                    "site": "mteam",
                    "message": "torrent/search failed: code=1 message=請求過於頻繁",
                }
            ],
        }

    def fake_intent_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        search_ingested: bool = True,
        run_id: str | None = None,
    ) -> dict[str, object]:
        nonlocal intent_called
        intent_called = True
        return {"command": "intent-run-once", "execute": execute}

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fake_intent_run_once_payload)

    result = CliRunner().invoke(
        cli.app,
        ["schedule-run", "--config", str(config_path), "--max-cycles", "1"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["active"] is True
    assert payload["intent_search_enabled"] is False
    assert payload["intent"]["skipped_by_backoff"] is True
    assert payload["intent"]["searched"] == 0
    assert intent_called is False
    assert (tmp_path / ".seed-agent" / "schedule-backoff.json").exists()
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    backoff = store.get_tracker_backoff("mteam", "torrent/search")
    assert backoff is not None
    assert bool(backoff["active"]) is True
    assert backoff["run_id"] == payload["run_id"]
    events = store.list_tracker_api_events(site="mteam")
    assert len(events) == 1
    assert events[0]["event"] == "rate_limited"
    assert bool(events[0]["rate_limited"]) is True


def test_schedule_run_records_network_backoff_after_mteam_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
            "discovery_warnings": [
                {
                    "site": "mteam",
                    "error_type": "ReadTimeout",
                    "message": "ReadTimeout",
                    "endpoint": "torrent/search",
                    "rate_limited": False,
                }
            ],
        }

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(
        cli,
        "_intent_run_once_payload",
        lambda *args, **kwargs: pytest.fail("intent should be skipped after network backoff"),
    )

    result = CliRunner().invoke(
        cli.app,
        ["schedule-run", "--config", str(config_path), "--max-cycles", "1"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["active"] is True
    assert payload["schedule_backoff"]["endpoint"] == "torrent/search"
    assert payload["schedule_backoff"]["reason"] == "mteam api unavailable"
    assert payload["intent"]["skipped_by_backoff"] is True
    assert not (tmp_path / ".seed-agent" / "schedule-backoff.json").exists()

    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    backoff = store.get_tracker_backoff("mteam", "torrent/search")
    assert backoff is not None
    assert bool(backoff["active"]) is True
    assert backoff["source"] == "schedule_network"
    events = store.list_tracker_api_events(site="mteam")
    assert len(events) == 1
    assert events[0]["event"] == "unavailable"
    assert bool(events[0]["rate_limited"]) is False


def test_schedule_run_prunes_after_tracker_backfill_network_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    prune_calls: list[int | None] = []

    def fake_tracker_source_backfill_payload(
        loaded,
        *,
        execute: bool,
        limit: int | None,
        category: str | None,
        max_api_requests: int | None,
    ) -> dict[str, object]:
        return {
            "command": "tracker-source-backfill",
            "execute": execute,
            "category": category,
            "live_torrent_count": 2,
            "qbonly_candidates": 2,
            "api_requests_used": 1,
            "api_requests_remaining": 0,
            "max_api_requests": max_api_requests,
            "summary": {"unavailable": 1, "skipped": 1},
            "results": [
                {"status": "unavailable", "reason": "ReadTimeout"},
                {"status": "skipped", "reason": "api request budget exhausted"},
            ],
        }

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None = None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
        fail_closed_unknown_incomplete: bool = False,
    ) -> dict[str, object]:
        prune_calls.append(free_window_min_remaining_minutes)
        assert fail_closed_unknown_incomplete is True
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "managed_count": 1,
            "pool_usage": {},
            "decisions": [],
            "preview": [],
        }

    monkeypatch.setattr(
        cli,
        "_tracker_source_backfill_payload",
        fake_tracker_source_backfill_payload,
    )
    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)
    monkeypatch.setattr(
        cli,
        "_run_once_payload",
        lambda *args, **kwargs: pytest.fail("run-once should be skipped"),
    )
    monkeypatch.setattr(
        cli,
        "_intent_run_once_payload",
        lambda *args, **kwargs: pytest.fail("intent should be skipped"),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--prune",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert prune_calls == [120]
    assert payload["prune"]["command"] == "prune"
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["reason"] == "mteam api unavailable"
    assert payload["tracker_source_backfill"]["summary"]["unavailable"] == 1


def test_schedule_run_skips_work_while_backoff_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    cli._record_schedule_rate_limit_backoff(
        config_path,
        reason="mteam request too frequent",
        now=datetime.now().astimezone(),
    )

    def fail_run_once_payload(*args: object, **kwargs: object) -> dict[str, object]:
        pytest.fail("run-once should be skipped during schedule backoff")

    prune_calls: list[int | None] = []

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None = None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
        fail_closed_unknown_incomplete: bool = False,
    ) -> dict[str, object]:
        prune_calls.append(free_window_min_remaining_minutes)
        assert execute is False
        assert force_space_reclamation is False
        assert completed_low_upload_requires_reclamation is True
        assert fail_closed_unknown_incomplete is True
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "managed_count": 1,
            "pool_usage": {},
            "decisions": [],
            "preview": [],
        }

    def fail_intent_run_once_payload(*args: object, **kwargs: object) -> dict[str, object]:
        pytest.fail("intent should be skipped during schedule backoff")

    monkeypatch.setattr(cli, "_run_once_payload", fail_run_once_payload)
    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fail_intent_run_once_payload)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--prune",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["skipped_by_backoff"] is True
    assert payload["discovered"] == 0
    assert payload["accepted"] == 0
    assert payload["enqueued"] == 0
    assert prune_calls == [120]
    assert payload["prune"]["command"] == "prune"
    assert payload["intent"]["skipped_by_backoff"] is True
    assert payload["intent_search_enabled"] is False


def test_schedule_run_skips_work_from_sqlite_tracker_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/genDlToken",
        until=(datetime.now(UTC) + timedelta(hours=25)).isoformat(),
        reason="mteam request too frequent",
        source="test",
        run_id="sched-test",
    )

    def fail_run_once_payload(*args: object, **kwargs: object) -> dict[str, object]:
        pytest.fail("run-once should be skipped during sqlite tracker backoff")

    def fail_intent_run_once_payload(*args: object, **kwargs: object) -> dict[str, object]:
        pytest.fail("intent should be skipped during sqlite tracker backoff")

    monkeypatch.setattr(cli, "_run_once_payload", fail_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fail_intent_run_once_payload)

    result = CliRunner().invoke(
        cli.app,
        ["schedule-run", "--config", str(config_path), "--max-cycles", "1"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["active"] is True
    assert payload["schedule_backoff"]["endpoint"] == "torrent/genDlToken"
    assert not (tmp_path / ".seed-agent" / "schedule-backoff.json").exists()


def test_scheduler_report_reads_runs_events_backoff_and_want_history(tmp_path: Path) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.start_scheduler_run(
        run_id="sched-test",
        command="schedule-run",
        config=str(config_path),
        execute=False,
        interval_minutes=60,
        prune_enabled=True,
        intent_enabled=True,
        intent_execute=False,
        backoff_active=False,
        backoff_until=None,
    )
    store.record_scheduler_event(
        run_id="sched-test",
        phase="pt_discovery",
        event="start",
    )
    store.finish_scheduler_run(run_id="sched-test", status="success", summary={})
    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/search",
        until=(datetime.now(UTC) + timedelta(hours=25)).isoformat(),
        reason="mteam request too frequent",
        source="test",
        run_id="sched-test",
    )
    store.record_want_search_run(
        intent_id="intent-1",
        source="test",
        status="skipped_backoff",
        search_enabled=False,
        results_count=0,
        backoff_active=True,
    )

    result = CliRunner().invoke(
        cli.app,
        ["scheduler-report", "--config", str(config_path), "--run-id", "sched-test"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "scheduler-report"
    assert payload["backoff"]["active"] is True
    assert payload["runs"][0]["run_id"] == "sched-test"
    assert payload["events"][0]["phase"] == "pt_discovery"
    assert payload["want_search_runs"][0]["status"] == "skipped_backoff"


def test_tracker_api_report_filters_events(tmp_path: Path) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.record_tracker_api_event(
        site="mteam",
        endpoint="torrent/search",
        event="rate_limited",
        rate_limited=True,
        message="too frequent",
    )
    store.record_tracker_api_event(
        site="other",
        endpoint="torrent/search",
        event="ok",
    )

    result = CliRunner().invoke(
        cli.app,
        ["tracker-api-report", "--config", str(config_path), "--site", "mteam"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "tracker-api-report"
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["rate_limited"] == 1
    assert payload["events"][0]["site"] == "mteam"


def test_config_status_and_runtime_doctor_are_read_only(tmp_path: Path) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)

    status_result = CliRunner().invoke(
        cli.app,
        ["config-status", "--config", str(config_path)],
    )
    doctor_result = CliRunner().invoke(
        cli.app,
        ["runtime-doctor", "--config", str(config_path)],
    )

    assert status_result.exit_code == 0
    status_payload = _json_output(status_result)
    assert status_payload["command"] == "config-status"
    assert status_payload["state_exists"] is True
    assert "pt_filters" in status_payload
    assert doctor_result.exit_code == 0
    doctor_payload = _json_output(doctor_result)
    assert doctor_payload["command"] == "runtime-doctor"
    assert any(item["name"] == "config" for item in doctor_payload["checks"])


def test_contribution_report_sorts_low_contribution_torrents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)

    def fake_managed_torrents(config, *, store):
        return [
            ManagedTorrent(
                name="large-zero",
                hash="zero",
                category="seed",
                tags=["seed-agent"],
                size_bytes=180 * 1024**3,
                downloaded_bytes=180 * 1024**3,
                uploaded_bytes=0,
                state="stalledUP",
                progress=1.0,
                added_at=datetime.now(UTC),
            ),
            ManagedTorrent(
                name="useful",
                hash="useful",
                category="seed",
                tags=["seed-agent"],
                size_bytes=20 * 1024**3,
                downloaded_bytes=20 * 1024**3,
                uploaded_bytes=40 * 1024**3,
                state="uploading",
                progress=1.0,
                added_at=datetime.now(UTC),
                metadata={"recent_upload_gb": 2.0},
            ),
        ], 0

    monkeypatch.setattr(
        cli,
        "_managed_torrents_for_report_with_reconciliation",
        fake_managed_torrents,
    )

    result = CliRunner().invoke(
        cli.app,
        ["contribution-report", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "contribution-report"
    assert payload["summary"]["zero_upload_large_count"] == 1
    assert payload["lowest_contribution"][0]["name"] == "large-zero"


def test_schedule_run_can_execute_intent_cycle_when_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    seen_execute: list[bool] = []

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        assert prune is False
        assert capacity_prune is False
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
        }

    def fake_intent_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        search_ingested: bool = True,
        run_id: str | None = None,
    ) -> dict[str, object]:
        seen_execute.append(execute)
        return {
            "command": "intent-run-once",
            "config": str(config_path_value),
            "execute": execute,
            "search_enabled": search_ingested,
            "ingested": 0,
            "searched": 0,
            "ranked": 0,
            "enqueue_candidates": 0,
            "decisions": [],
        }

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fake_intent_run_once_payload)
    monkeypatch.setattr(cli, "_scheduled_intent_search_due", lambda *args, **kwargs: False)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--intent-execute",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["intent_execute"] is True
    assert payload["intent"]["execute"] is True
    assert payload["intent"]["search_enabled"] is False
    assert seen_execute == [True]


def test_schedule_run_daemon_keeps_running_after_cycle_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    heartbeat_path = tmp_path / "state" / "heartbeat.json"

    class StopSchedule(Exception):
        pass

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "error": "qBittorrent enqueue batch failed",
            "discovered": 1,
            "scored": 1,
            "accepted": 1,
            "enqueued": 0,
        }

    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: (_ for _ in ()).throw(StopSchedule))

    with pytest.raises(StopSchedule):
        cli.schedule_run(
            config=config_path,
            heartbeat_file=heartbeat_path,
            max_cycles=None,
        )

    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["error"] == "qBittorrent enqueue batch failed"
    assert heartbeat["cycle"] == 1


def test_intent_run_once_reports_source_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref=None)
    config = _config(secret_ref=None)

    class FakeIntentResult:
        ingested = []
        searched = []
        ranked = []
        enqueue_selected = []
        decisions = []

    async def fake_run_intent_once(**kwargs):
        assert kwargs["source_events"] == []
        return FakeIntentResult()

    def fail_read_configured_source_events(loaded):
        raise RuntimeError("douban 403")

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_read_configured_source_events", fail_read_configured_source_events)
    monkeypatch.setattr(cli, "run_intent_once", fake_run_intent_once)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["intent-run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["source_warnings"] == [
        {
            "source": "configured_sources",
            "error_type": "RuntimeError",
            "message": "douban 403",
        }
    ]


def test_schedule_run_can_prune_each_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
scheduler:
  tracker_backfill_limit: 20
  tracker_backfill_max_api_requests: 20
""",
        encoding="utf-8",
    )
    seen: list[tuple[str, object]] = []

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None = None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
    ) -> dict[str, object]:
        seen.append(("prune", free_window_min_remaining_minutes))
        assert force_space_reclamation is False
        assert completed_low_upload_requires_reclamation is True
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "force_space_reclamation": force_space_reclamation,
            "completed_low_upload_requires_reclamation": (
                completed_low_upload_requires_reclamation
            ),
            "managed_count": 1,
            "pool_usage": {},
            "decisions": [],
            "preview": [],
        }

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        seen.append(("run_once", (prune, capacity_prune)))
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
        }

    def fake_intent_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        search_ingested: bool = True,
        run_id: str | None = None,
    ) -> dict[str, object]:
        seen.append(("intent", execute))
        return {
            "command": "intent-run-once",
            "config": str(config_path_value),
            "execute": execute,
            "search_enabled": search_ingested,
            "ingested": 0,
            "searched": 0,
            "ranked": 0,
            "enqueue_candidates": 0,
            "decisions": [],
        }

    def fake_tracker_source_backfill_payload(
        loaded,
        *,
        execute: bool,
        limit: int | None,
        category: str | None,
        max_api_requests: int | None,
    ) -> dict[str, object]:
        seen.append(("tracker_backfill", (limit, category, max_api_requests)))
        return {
            "command": "tracker-source-backfill",
            "execute": execute,
            "category": category,
            "live_torrent_count": 0,
            "qbonly_candidates": 0,
            "api_requests_used": 0,
            "api_requests_remaining": max_api_requests,
            "max_api_requests": max_api_requests,
            "summary": {},
            "results": [],
        }

    monkeypatch.setattr(
        cli,
        "_tracker_source_backfill_payload",
        fake_tracker_source_backfill_payload,
    )
    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)
    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fake_intent_run_once_payload)
    monkeypatch.setattr(cli, "_scheduled_intent_search_due", lambda *args, **kwargs: False)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--prune",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert seen == [
        ("tracker_backfill", (None, None, None)),
        ("prune", 120),
        ("run_once", (False, True)),
        ("intent", False),
    ]
    assert payload["intent_search_enabled"] is False
    assert payload["prune"]["command"] == "prune"
    assert payload["tracker_source_backfill"]["command"] == "tracker-source-backfill"


def test_schedule_run_passes_terminal_unknown_incomplete_hashes_to_prune(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    risky_hashes: list[set[str]] = []

    monkeypatch.setattr(
        cli,
        "_tracker_source_backfill_payload",
        lambda *args, **kwargs: {
            "command": "tracker-source-backfill",
            "execute": False,
            "live_torrent_count": 1,
            "qbonly_candidates": 1,
            "api_requests_used": 1,
            "api_requests_remaining": 5,
            "max_api_requests": 6,
            "summary": {"not_found": 1},
            "results": [
                {
                    "hash": "risky-incomplete",
                    "incomplete": True,
                    "status": "not_found",
                    "reason": "no unique title/size match",
                }
            ],
        },
    )

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None = None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
        unknown_free_risk_hashes: set[str] | None = None,
    ) -> dict[str, object]:
        risky_hashes.append(set(unknown_free_risk_hashes or set()))
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "managed_count": 1,
            "pool_usage": {},
            "decisions": [],
            "preview": [],
        }

    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)
    monkeypatch.setattr(
        cli,
        "_run_once_payload",
        lambda *args, **kwargs: {
            "command": "run-once",
            "execute": False,
            "discovered": 0,
            "scored": 0,
            "accepted": 0,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
        },
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--prune",
            "--no-intent",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert risky_hashes == [{"risky-incomplete"}]
    assert (
        StateStore(tmp_path / ".seed-agent" / "state.db").list_scheduler_runs()[0]["status"]
        == "warning"
    )


def test_category_filtered_backfill_reconciles_against_all_live_torrents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config = _config()
    torrents = [
        _managed_torrent(hash="seed-live", category="seed"),
        _managed_torrent(hash="movie-live", category="movie"),
    ]

    class FakeDownloader:
        async def list_torrents(
            self,
            category: str | None = None,
            tags: set[str] | None = None,
        ) -> list[ManagedTorrent]:
            del category, tags
            return torrents

    reconciled_hashes: list[set[str]] = []
    original_reconcile = StateStore.reconcile_missing_torrents

    def record_reconcile(
        self: StateStore,
        live_hashes: set[str],
        **kwargs: object,
    ) -> int:
        reconciled_hashes.append(set(live_hashes))
        return original_reconcile(self, live_hashes, **kwargs)

    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())
    monkeypatch.setattr(StateStore, "reconcile_missing_torrents", record_reconcile)

    payload = cli._tracker_source_backfill_payload(
        config,
        execute=False,
        limit=0,
        category="seed",
        max_api_requests=0,
    )

    assert reconciled_hashes == [{"seed-live", "movie-live"}]
    assert payload["live_torrent_count"] == 1


def test_prune_capacity_delete_limit_is_shared_across_mutable_categories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    raw = _config().model_dump(mode="json")
    raw["download_client"]["category_policies"].append(
        {
            "name": "seed-alt",
            "mode": "mutable",
            "budget_pool": "downloads",
            "delete_enabled": True,
            "over_budget_behavior": "add_paused",
            "tags": ["seed-agent", "seed-alt"],
        }
    )
    raw["seed_cleanup"]["max_capacity_deletes_per_run"] = 1
    config = SeedAgentConfig.model_validate(raw)

    class EmptyDownloader:
        async def list_torrents(
            self,
            category: str | None = None,
            tags: set[str] | None = None,
        ) -> list[ManagedTorrent]:
            del category, tags
            return []

    limits: list[int | None] = []

    async def fake_prune_cold_torrents(
        torrents: list[ManagedTorrent],
        downloader: object,
        cleanup: object,
        policy: object,
        execute: bool,
        **kwargs: object,
    ) -> list[Decision]:
        del torrents, downloader, cleanup, execute
        limit = kwargs.get("capacity_delete_limit")
        limits.append(limit if isinstance(limit, int) else None)
        if limit == 0:
            return []
        return [
            Decision(
                action="qb.cleanup.delete",
                target_id=str(getattr(policy, "name", "seed")),
                execute=False,
                reason="capacity delete",
                old_state={"size_bytes": 1},
                new_state={
                    "capacity_reclamation": True,
                    "space_reclamation_required": True,
                },
            )
        ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: EmptyDownloader())
    monkeypatch.setattr(cli, "prune_cold_torrents", fake_prune_cold_torrents)

    payload = cli._prune_payload(tmp_path / "config.yaml", execute=False)

    assert limits == [1, 0]
    assert payload["capacity_deletes_remaining"] == 0


def test_prune_execute_fails_closed_when_live_pool_remains_over_hard_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config = _config()
    torrent = ManagedTorrent(
        hash="still-over",
        name="Still over",
        category="seed",
        tags={"seed-agent", "seed"},
        state="stalledUP",
        size_bytes=11 * 1024**4,
        uploaded_bytes=1,
        downloaded_bytes=11 * 1024**4,
        added_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
        metadata={"amount_left_bytes": 0},
    )

    class StaleDownloader:
        async def list_torrents(self, category=None, tags=None):
            return [torrent]

    async def fake_prune(*args: object, **kwargs: object) -> list[Decision]:
        return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: StaleDownloader())
    monkeypatch.setattr(cli, "prune_cold_torrents", fake_prune)

    payload = cli._prune_payload(tmp_path / "config.yaml", execute=True)

    assert payload["hard_cap_satisfied"] is False
    assert payload["hard_cap_violations_by_pool"] == {"downloads": 1024**4}
    assert payload["verified_committed_reclaim_by_pool"]["downloads"] == 0
    assert "hard pool capacity invariant not satisfied" in payload["error"]


def test_schedule_run_persists_phase_order_with_shared_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    intent_run_ids: list[str | None] = []

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None = None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
    ) -> dict[str, object]:
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "force_space_reclamation": force_space_reclamation,
            "completed_low_upload_requires_reclamation": (
                completed_low_upload_requires_reclamation
            ),
            "managed_count": 2,
            "pool_usage": {},
            "decisions": [],
            "preview": [],
        }

    def fake_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        min_free_window_minutes: int | None,
        require_known_free_window: bool,
        prune: bool,
        prune_free_window_min_remaining_minutes: int | None = None,
        capacity_prune: bool = False,
    ) -> dict[str, object]:
        assert prune is False
        assert capacity_prune is True
        return {
            "command": "run-once",
            "config": str(config_path_value),
            "execute": execute,
            "discovered": 3,
            "scored": 2,
            "accepted": 1,
            "enqueued": 0,
            "scores": [],
            "decisions": [],
        }

    def fake_intent_run_once_payload(
        config_path_value: Path,
        *,
        execute: bool,
        search_ingested: bool = True,
        run_id: str | None = None,
    ) -> dict[str, object]:
        intent_run_ids.append(run_id)
        return {
            "command": "intent-run-once",
            "config": str(config_path_value),
            "execute": execute,
            "search_enabled": search_ingested,
            "ingested": 1,
            "searched": 0,
            "ranked": 0,
            "enqueue_candidates": 0,
            "decisions": [],
        }

    def fake_tracker_source_backfill_payload(
        loaded,
        *,
        execute: bool,
        limit: int | None,
        category: str | None,
        max_api_requests: int | None,
    ) -> dict[str, object]:
        return {
            "command": "tracker-source-backfill",
            "execute": execute,
            "category": category,
            "live_torrent_count": 0,
            "qbonly_candidates": 0,
            "api_requests_used": 0,
            "api_requests_remaining": max_api_requests,
            "max_api_requests": max_api_requests,
            "summary": {},
            "results": [],
        }

    monkeypatch.setattr(
        cli,
        "_tracker_source_backfill_payload",
        fake_tracker_source_backfill_payload,
    )
    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)
    monkeypatch.setattr(cli, "_run_once_payload", fake_run_once_payload)
    monkeypatch.setattr(cli, "_intent_run_once_payload", fake_intent_run_once_payload)
    monkeypatch.setattr(cli, "_scheduled_intent_search_due", lambda *args, **kwargs: False)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--prune",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    run_id = payload["run_id"]
    assert intent_run_ids == [run_id]

    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    runs = store.list_scheduler_runs()
    assert runs[0]["run_id"] == run_id
    assert runs[0]["status"] == "success"
    assert runs[0]["discovered"] == 3
    assert runs[0]["intent_ingested"] == 1

    events = sorted(
        store.list_scheduler_run_events(run_id=run_id, limit=20),
        key=lambda row: row["id"],
    )
    assert [(row["phase"], row["event"]) for row in events] == [
        ("backoff_check", "inactive"),
        ("tracker_source_backfill", "start"),
        ("tracker_source_backfill", "end"),
        ("prune", "start"),
        ("prune", "end"),
        ("pt_discovery", "start"),
        ("pt_enqueue", "end"),
        ("intent_source_sync", "start"),
        ("intent_source_sync", "end"),
    ]


def test_schedule_run_prune_uses_twice_interval_as_free_window_horizon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    seen: list[int | None] = []

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
    ) -> dict[str, object]:
        seen.append(free_window_min_remaining_minutes)
        assert force_space_reclamation is False
        assert completed_low_upload_requires_reclamation is True
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "managed_count": 0,
            "pool_usage": {},
            "decisions": [],
        }

    async def fake_discover_candidates(loaded):
        return []

    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: None)
    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)

    result = CliRunner().invoke(
        cli.app,
        [
            "schedule-run",
            "--config",
            str(config_path),
            "--interval-minutes",
            "45",
            "--prune",
            "--max-cycles",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert seen == [90]


def test_schedule_free_window_horizon_keeps_larger_configured_minimum() -> None:
    from seed_agent.cli import _schedule_free_window_safety_minutes

    assert (
        _schedule_free_window_safety_minutes(
            interval_minutes=60,
            configured_minutes=180,
        )
        == 180
    )


def test_execute_enqueue_persists_candidate_free_window_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config(secret_ref="local/secrets/qb.yaml")
    candidate = _candidate(left_time_minutes=240)
    state_path = tmp_path / ".seed-agent" / "state.db"

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidate)]

    async def fake_resolve_deferred_download_urls(scored, loaded, **_):
        return scored

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return []

        async def add_url(
            self,
            url: str,
            category: str,
            tags: list[str],
            *,
            paused: bool = False,
        ) -> str:
            return "abcd1234"

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "resolve_deferred_download_urls", fake_resolve_deferred_download_urls)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path), "--execute"])

    assert result.exit_code == 0
    row = StateStore(state_path).get_candidate(candidate.stable_id)
    assert row is not None
    assert row["free_window_expires_at"] is not None


def test_run_once_persists_candidate_snapshot_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config(secret_ref="local/secrets/qb.yaml")
    candidate = _candidate(seeders=21, leechers=34, left_time_minutes=360)
    state_path = tmp_path / ".seed-agent" / "state.db"

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [
            _scored(
                candidate=candidate,
                score=93,
                reasons=["discount free accepted", "site_history 0.5"],
            )
        ]

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    row = StateStore(state_path).get_candidate(candidate.stable_id)
    assert row is not None
    assert row["size_bytes"] == candidate.size_bytes
    assert row["seeders"] == 21
    assert row["leechers"] == 34
    assert row["discount"] == "free"
    assert row["left_time_minutes"] == 360
    assert row["score"] == 93
    assert row["score_reasons"] == ["discount free accepted", "site_history 0.5"]


def test_run_once_applies_site_history_feedback_before_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config(secret_ref="local/secrets/qb.yaml")
    candidate = _candidate()
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    for index in range(3):
        torrent_hash = f"productive-{index}"
        store.upsert_candidate(
            stable_id=f"demo-free:productive-{index}",
            title=f"Productive {index}",
            site="demo-free",
            state=LifecycleState.SEEDING,
            score=90,
            torrent_hash=torrent_hash,
        )
        store._upsert_torrent_runtime(  # type: ignore[attr-defined]
            torrent_hash,
            uploaded_bytes=4 * 1024**3,
            downloaded_bytes=10 * 1024**3,
            seen_at=datetime.now(UTC).isoformat(),
        )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    seen_metadata: list[dict[str, object]] = []

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        scored_candidate = candidates[0]
        seen_metadata.append(dict(scored_candidate.metadata))
        return [
            _scored(
                candidate=scored_candidate,
                score=95,
                reasons=["discount free accepted", "site_history 0.85"],
            )
        ]

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    assert seen_metadata[0]["site_history_score"] == 0.85
    assert seen_metadata[0]["site_history_source"] == "state_feedback"
    assert seen_metadata[0]["site_history_samples"] == 3


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


def test_runtime_status_reports_version_config_paths_and_heartbeat(tmp_path: Path) -> None:
    from seed_agent import __version__
    from seed_agent.cli import app

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qbittorrent.yaml")
    secret_path = tmp_path / "local" / "secrets" / "qbittorrent.yaml"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(
        "base_url: http://qb.example\nusername: user\npassword: pass\n",
        encoding="utf-8",
    )
    heartbeat_path = tmp_path / "state" / "heartbeat.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "version": __version__,
                "cycle": 3,
                "interval_minutes": 30,
                "config": str(config_path),
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "runtime-status",
            "--config",
            str(config_path),
            "--heartbeat-file",
            str(heartbeat_path),
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "runtime-status"
    assert payload["version"] == __version__
    assert payload["status"] == "ok"
    assert payload["config_exists"] is True
    assert payload["download_client"]["credential_file_present"] is True
    assert payload["heartbeat"]["cycle"] == 3
    assert "password" not in result.output


def test_site_probe_reports_sparse_and_enriched_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "tracker_sites": [
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
    mt = payload["tracker_sites"]["mt"]
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


def test_prune_execute_updates_state_to_deleted_for_cold_incomplete_torrent(
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
            self.deleted = False

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            if self.deleted:
                return []
            return [_managed_incomplete_torrent(hash="abcd1234", size_bytes=11 * 1024**4)]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))
            self.deleted = True

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path), "--execute"])

    assert result.exit_code == 0
    assert downloader.calls == [("delete", "abcd1234", True)]
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.DELETED.value


def test_prune_execute_updates_state_to_deleted_for_old_paused_incomplete_torrent(
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
            self.deleted = False

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            if self.deleted:
                return []
            return [
                _managed_torrent(
                    hash="abcd1234",
                    state="pausedUP",
                    size_bytes=11 * 1024**4,
                    completed_at=None,
                    metadata={
                        "amount_left_bytes": 5 * 1024**3,
                        "recent_upload_gb": 0.2,
                        "paused_at": datetime.now(UTC) - timedelta(days=10),
                    },
                )
            ]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))
            self.deleted = True

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path), "--execute"])

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
            self.deleted = False

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            if self.deleted:
                return []
            return [
                _managed_torrent(
                    hash="abcd1234",
                    state="pausedUP",
                    size_bytes=11 * 1024**4,
                    completed_at=None,
                    downloaded_bytes=5 * 1024**3,
                    metadata={
                        "amount_left_bytes": 5 * 1024**3,
                        "recent_upload_gb": 0.2,
                    },
                )
            ]

        async def pause(self, hash: str) -> None:
            self.calls.append(("pause", hash, None))

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(("delete", hash, delete_files))
            self.deleted = True

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path), "--execute"])

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
            return [_managed_incomplete_torrent(hash="abcd1234", size_bytes=11 * 1024**4)]

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
    assert payload["decisions"][0]["action"] == "qb.cleanup.delete"
    assert payload["decisions"][0]["execute"] is False
    assert payload["preview"][0]["hash"] == "<redacted>"
    assert payload["preview"][0]["name"] == "Managed Torrent"
    assert payload["preview"][0]["candidate_state"] == LifecycleState.ENQUEUED.value
    assert payload["preview"][0]["delete_files_on_delete"] is True
    assert payload["cleanup_evidence"]["delete_count"] == 1
    assert payload["cleanup_evidence"]["by_action"]["qb.cleanup.delete"] == 1
    assert payload["cleanup_evidence"]["delete_samples"][0]["name"] == "Managed Torrent"
    assert downloader.calls == []
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value


def test_prune_preview_includes_joined_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    StateStore(tmp_path / ".seed-agent" / "state.db").upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash="preview-hash",
        free_window_expires_at="2026-05-16T00:00:00+00:00",
        seeders=20,
        leechers=30,
        discount="free",
        left_time_minutes=240,
        score_reasons=["preview evidence"],
    )

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="preview-hash",
                    uploaded_bytes=2 * 1024**3,
                    downloaded_bytes=10 * 1024**3,
                    metadata={
                        "amount_left_bytes": 3 * 1024**3,
                        "recent_upload_gb": 0.25,
                        "no_upload_since_at": datetime(2026, 5, 15, tzinfo=UTC),
                    },
                )
            ]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run should not pause")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run should not delete")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    item = _json_output(result)["preview"][0]
    assert item["ratio"] == 0.2
    assert item["amount_left_gb"] == 3.0
    assert item["recent_upload_gb"] == 0.25
    assert item["no_upload_since_at"] == "2026-05-15T00:00:00+00:00"
    assert item["free_window_expires_at"] == "2026-05-16T00:00:00+00:00"
    assert item["candidate_evidence"]["score"] == 95
    assert item["candidate_evidence"]["score_reasons"] == ["preview evidence"]


def test_prune_links_live_torrent_without_existing_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    store = StateStore(tmp_path / ".seed-agent" / "state.db")

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="legacy-hash", name="Legacy Managed")]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run prune must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run prune must not delete torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    row = store.get_candidate("qb:legacy-hash")
    assert row is not None
    assert row["title"] == "Legacy Managed"
    assert row["torrent_hash"] == "legacy-hash"


def test_prune_links_live_torrent_to_existing_unhashed_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="Free Live Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=95,
        torrent_hash=None,
        free_window_expires_at="2026-05-16T00:00:00+00:00",
        size_bytes=12 * 1024 * 1024 * 1024,
        discount="free",
        score_reasons=["discount free accepted"],
    )

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="live-hash",
                    name="Free Live Torrent",
                    size_bytes=12 * 1024 * 1024 * 1024,
                )
            ]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run prune must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run prune must not delete torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["candidate_reconciliation"]["linked_existing_candidates"] == 1
    assert payload["candidate_reconciliation"]["created_qb_records"] == 0
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["torrent_hash"] == "live-hash"
    assert row["discount"] == "free"
    assert row["free_window_expires_at"] == "2026-05-16T00:00:00+00:00"
    assert store.get_candidate("qb:live-hash") is None
    preview = payload["preview"][0]
    assert preview["candidate_evidence"]["candidate_id"] == (
        "demo-free:https://tracker.example/details.php?id=1"
    )
    assert preview["candidate_evidence"]["discount"] == "free"


def test_prune_marks_deleted_candidate_present_when_seen_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="Live Again",
        site="demo-free",
        state=LifecycleState.DELETED,
        score=95,
        torrent_hash="live-again-hash",
    )

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="live-again-hash")]

        async def pause(self, hash: str) -> None:
            raise AssertionError("dry-run prune must not pause torrents")

        async def delete(self, hash: str, delete_files: bool) -> None:
            raise AssertionError("dry-run prune must not delete torrents")

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path)])

    assert result.exit_code == 0
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.SEEDING.value


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
                    completed_at=None,
                    metadata={
                        "amount_left_bytes": 1 * 1024**3,
                        "upspeed_bps": 0,
                        "dlspeed_bps": 0,
                    },
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
            if category is None:
                return [
                    _managed_torrent(
                        hash="seed-hash",
                        category="seed",
                        size_bytes=1 * 1024**4,
                    ),
                    _managed_torrent(
                        hash="movie-hash",
                        category="movie",
                        tags={"seed-agent", "movie"},
                        size_bytes=2 * 1024**4,
                    ),
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


def test_load_policy_torrents_uses_single_qb_listing_for_multiple_categories() -> None:
    from seed_agent import cli

    config = _config(secret_ref="local/secrets/qb.yaml")

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[tuple[str | None, set[str] | None]] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            self.calls.append((category, tags))
            assert category is None
            return [
                _managed_torrent(hash="seed-hash", category="seed"),
                _managed_torrent(hash="movie-hash", category="movie"),
                _managed_torrent(hash="other-hash", category="other"),
            ]

    downloader = FakeDownloader()

    torrents = cli._load_policy_torrents(downloader, config)

    assert downloader.calls == [(None, None)]
    assert [torrent.hash for torrent in torrents] == ["seed-hash", "movie-hash"]


def test_load_policy_torrents_keeps_category_filter_for_single_category() -> None:
    from seed_agent import cli

    config = _config(secret_ref="local/secrets/qb.yaml")
    seed_policy = config.download_client.category_policies[0]

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[tuple[str | None, set[str] | None]] = []

        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            self.calls.append((category, tags))
            assert category == "seed"
            return [
                _managed_torrent(hash="seed-hash", category="seed"),
                _managed_torrent(hash="other-hash", category="other"),
            ]

    downloader = FakeDownloader()

    torrents = cli._load_policy_torrents(downloader, config, policies=[seed_policy])

    assert downloader.calls == [("seed", None)]
    assert [torrent.hash for torrent in torrents] == ["seed-hash"]


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
            if category is None:
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
                    _managed_torrent(
                        hash="movie-paused",
                        category="movie",
                        tags={"seed-agent", "movie"},
                        state="pausedUP",
                        metadata={},
                    ),
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


def test_review_reports_joined_candidate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    state_path = tmp_path / ".seed-agent" / "state.db"
    StateStore(state_path).upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=93,
        torrent_hash="joined-hash",
        free_window_expires_at="2026-05-16T00:00:00+00:00",
        size_bytes=10 * 1024**3,
        seeders=21,
        leechers=34,
        discount="free",
        left_time_minutes=360,
        score_reasons=["discount free accepted", "site_history 0.5"],
    )

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="joined-hash",
                    uploaded_bytes=5 * 1024**3,
                    downloaded_bytes=10 * 1024**3,
                    metadata={
                        "amount_left_bytes": 0,
                        "upspeed_bps": 1024**2,
                        "no_upload_since_at": datetime(2026, 5, 15, tzinfo=UTC),
                    },
                )
            ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["review", "--config", str(config_path)])

    assert result.exit_code == 0
    torrent = _json_output(result)["managed_torrents"][0]
    assert torrent["ratio"] == 0.5
    assert torrent["completed_at"] is not None
    assert torrent["no_upload_since_at"] == "2026-05-15T00:00:00+00:00"
    evidence = torrent["candidate_evidence"]
    assert evidence["candidate_id"] == "demo-free:https://tracker.example/details.php?id=1"
    assert evidence["candidate_state"] == LifecycleState.ENQUEUED.value
    assert evidence["score"] == 93
    assert evidence["seeders"] == 21
    assert evidence["leechers"] == 34
    assert evidence["discount"] == "free"
    assert evidence["left_time_minutes"] == 360
    assert evidence["free_window_expires_at"] == "2026-05-16T00:00:00+00:00"
    assert evidence["score_reasons"] == ["discount free accepted", "site_history 0.5"]


def test_review_reconciles_missing_qb_torrents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="Missing Torrent",
        site="demo-free",
        state=LifecycleState.SEEDING,
        score=93,
        torrent_hash="missing-hash",
    )
    with store._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE candidates SET updated_at = ? WHERE stable_id = ?",
            (
                (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                "demo-free:https://tracker.example/details.php?id=1",
            ),
        )

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="present-hash")]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["review", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["managed_count"] == 1
    assert payload["missing_from_qb_reconciled"] == 1
    row = store.get_candidate("demo-free:https://tracker.example/details.php?id=1")
    assert row is not None
    assert row["state"] == LifecycleState.DELETED.value
    runtime = store.get_torrent_runtime("missing-hash")
    assert runtime is not None
    assert runtime["missing_from_qb_reason"] == "missing from qB live torrent list"


def test_daily_report_reports_joined_candidate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    StateStore(tmp_path / ".seed-agent" / "state.db").upsert_candidate(
        stable_id="demo-free:https://tracker.example/details.php?id=1",
        title="High Confidence Torrent",
        site="demo-free",
        state=LifecycleState.ENQUEUED,
        score=88,
        torrent_hash="daily-hash",
        seeders=12,
        leechers=8,
        discount="free",
        left_time_minutes=120,
        score_reasons=["daily evidence"],
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return []

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return []

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [_managed_torrent(hash="daily-hash")]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["daily-report", "--config", str(config_path)])

    assert result.exit_code == 0
    evidence = _json_output(result)["managed_torrents"][0]["candidate_evidence"]
    assert evidence["candidate_id"] == "demo-free:https://tracker.example/details.php?id=1"
    assert evidence["score"] == 88
    assert evidence["score_reasons"] == ["daily evidence"]


def test_strategy_report_cli_reports_candidate_distribution_and_runtime_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")
    candidate = _candidate(
        source_url="https://tracker.example/details.php?id=42",
        size_bytes=220 * 1024**3,
        seeders=180,
        leechers=30,
    )
    scored = [
        ScoreBreakdown(
            candidate_id=candidate.stable_id,
            score=91,
            accepted=True,
            reasons=["ok"],
            candidate=candidate,
        )
    ]
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        stable_id=candidate.stable_id,
        title=candidate.title,
        site=candidate.site,
        state=LifecycleState.ENQUEUED,
        score=91,
        torrent_hash="strategy-hash",
        size_bytes=candidate.size_bytes,
        seeders=candidate.seeders,
        leechers=candidate.leechers,
        discount=candidate.discount.value,
        left_time_minutes=candidate.left_time_minutes,
        score_reasons=["strategy evidence"],
    )
    store._upsert_torrent_runtime(  # type: ignore[attr-defined]
        "strategy-hash",
        uploaded_bytes=80 * 1024**3,
        downloaded_bytes=220 * 1024**3,
        seen_at=datetime.now(UTC).isoformat(),
    )
    for index in range(2):
        torrent_hash = f"strategy-extra-{index}"
        store.upsert_candidate(
            stable_id=f"demo-free:strategy-extra-{index}",
            title=f"Strategy Extra {index}",
            site="demo-free",
            state=LifecycleState.SEEDING,
            score=80,
            torrent_hash=torrent_hash,
        )
        store._upsert_torrent_runtime(  # type: ignore[attr-defined]
            torrent_hash,
            uploaded_bytes=2 * 1024**3,
            downloaded_bytes=10 * 1024**3,
            seen_at=datetime.now(UTC).isoformat(),
        )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return scored

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return [
                _managed_torrent(
                    hash="strategy-hash",
                    size_bytes=220 * 1024**3,
                    uploaded_bytes=80 * 1024**3,
                    downloaded_bytes=220 * 1024**3,
                )
            ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())
    monkeypatch.setattr(
        cli,
        "_apply_live_torrent_state",
        lambda store, torrents: pytest.fail("strategy-report must not mutate live state"),
    )

    result = CliRunner().invoke(cli.app, ["strategy-report", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "strategy-report"
    assert payload["report"]["candidate_distribution"]["accepted"] == 1
    assert payload["report"]["candidate_distribution"]["size_gb"]["150+"]["accepted"] == 1
    outcomes = payload["report"]["runtime_outcomes"]
    assert outcomes["managed_torrents"] == 1
    assert outcomes["with_candidate_evidence"] == 1
    assert outcomes["by_candidate_leechers"]["25+"]["avg_uploaded_gb"] == 80.0
    site_history = payload["report"]["site_history"]["demo-free"]
    assert site_history["applied"] is True
    assert site_history["samples"] == 3
    assert site_history["score"] > 0.5


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


def test_run_once_reports_discovery_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref=None)
    config = _config(secret_ref=None)

    async def fake_discover_candidates(config: SeedAgentConfig):
        return []

    class FakeDownloader:
        async def list_torrents(
            self, category: str | None = None, tags: set[str] | None = None
        ) -> list[ManagedTorrent]:
            return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(
        cli,
        "get_last_discovery_warnings",
        lambda: [
            {
                "site": "mt",
                "error_type": "MTeamApiResponseError",
                "message": "torrent/search failed: code=1 message=請求過於頻繁",
                "endpoint": "torrent/search",
                "rate_limited": True,
            }
        ],
    )
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["discovery_warnings"] == [
        {
            "site": "mt",
            "error_type": "MTeamApiResponseError",
            "message": "torrent/search failed: code=1 message=請求過於頻繁",
            "endpoint": "torrent/search",
            "rate_limited": True,
        }
    ]


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
            return [
                _managed_incomplete_torrent(hash="first", size_bytes=6 * 1024**4),
                _managed_incomplete_torrent(hash="second", size_bytes=6 * 1024**4),
            ]

        async def delete(self, hash: str, delete_files: bool) -> None:
            self.calls.append(hash)
            raise RuntimeError("delete failed")

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(cli.app, ["prune", "--config", str(config_path), "--execute"])

    assert result.exit_code == 1
    payload = _json_output(result)
    assert payload["error"] == "qBittorrent cleanup batch failed"
    assert [decision["action"] for decision in payload["decisions"]] == [
        "qb.cleanup.delete.failed",
    ]
    assert store.get_candidate(first_id)["state"] == LifecycleState.ENQUEUED.value
    assert store.get_candidate(second_id)["state"] == LifecycleState.ENQUEUED.value
    audit_path = tmp_path / ".seed-agent" / "audit.jsonl"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "qb.cleanup.delete.failed" in audit_text


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
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  target_seed_leecher_ratio: 10
  allow_hr: false
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
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
seed_cleanup:
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


def test_build_downloader_accepts_transmission_secret(tmp_path: Path) -> None:
    from seed_agent.cli import build_downloader
    from seed_agent.config import load_config
    from seed_agent.downloaders.transmission import TransmissionClient

    secret_dir = tmp_path / "local" / "secrets"
    secret_dir.mkdir(parents=True)
    (secret_dir / "transmission.yaml").write_text(
        "base_url: http://transmission.local:9091\nusername: alice\npassword: secret\n",
        encoding="utf-8",
    )
    config_path = _config_file(tmp_path, secret_ref="local/secrets/transmission.yaml")
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "type: qbittorrent",
            "type: transmission",
        ),
        encoding="utf-8",
    )

    downloader = build_downloader(load_config(config_path))

    assert isinstance(downloader, TransmissionClient)
    assert downloader.base_url == "http://transmission.local:9091"
    assert downloader.username == "alice"
    assert downloader.password == "secret"


def test_read_configured_source_events_polls_telegram_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import IntentSource
    from seed_agent.sources.base import SourceIntentEvent

    config_path = _config_file(tmp_path)
    secret = tmp_path / "local" / "secrets" / "telegram.yaml"
    secret.parent.mkdir(parents=True)
    secret.write_text(
        "bot_token: secret-token\noffset: 100\ntimeout_seconds: 3\nallowed_chat_ids: 12345,999\n",
        encoding="utf-8",
    )
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
want_sources:
  telegram:
    enabled: true
    secret_ref: local/secrets/telegram.yaml
""",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fake_poll(**kwargs):
        calls.append(kwargs)
        return [
            SourceIntentEvent(
                source=IntentSource.TELEGRAM,
                raw_text="Inception 2010",
                source_event_id="telegram:12345:42",
            )
        ]

    monkeypatch.setattr(cli, "poll_telegram_updates", fake_poll)

    events = cli._read_configured_source_events(cli.load_config(config_path))

    assert [event.source for event in events] == [IntentSource.TELEGRAM]
    assert calls == [
        {
            "bot_token": "secret-token",
            "offset": 100,
            "timeout_seconds": 3,
            "allowed_chat_ids": {"12345", "999"},
        }
    ]


def test_config_export_and_import_dry_run_report_changed_sections(tmp_path: Path) -> None:
    from seed_agent.cli import app

    config_path = _config_file(tmp_path)
    rules_path = tmp_path / "rules.yaml"
    export_result = CliRunner().invoke(
        app,
        ["config-export", "--config", str(config_path), "--output", str(rules_path)],
    )

    assert export_result.exit_code == 0
    exported = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    exported["pt_filters"]["min_leechers"] = 12
    rules_path.write_text(yaml.safe_dump(exported, sort_keys=False), encoding="utf-8")

    import_result = CliRunner().invoke(
        app,
        ["config-import", "--config", str(config_path), "--rules", str(rules_path)],
    )

    assert import_result.exit_code == 0
    payload = _json_output(import_result)
    assert payload["status"] == "dry_run"
    assert payload["changed_sections"] == ["pt_filters"]
    assert "min_leechers: 8" in config_path.read_text(encoding="utf-8")


def test_config_import_execute_writes_validated_rules(tmp_path: Path) -> None:
    from seed_agent.cli import app

    config_path = _config_file(tmp_path)
    exported = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    exported["pt_filters"]["min_leechers"] = 12
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(yaml.safe_dump({"rules": exported}, sort_keys=False), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "config-import",
            "--config",
            str(config_path),
            "--rules",
            str(rules_path),
            "--execute",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["status"] == "applied"
    assert "min_leechers: 12" in config_path.read_text(encoding="utf-8")


def test_release_profiles_command_resolves_profile_overrides(tmp_path: Path) -> None:
    from seed_agent.cli import app

    config_path = _config_file(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
release_profiles:
  remux:
    default_resolution: 2160p
    quality_tag_scores:
      remux: 20
    source_ids: ["letterboxd-watchlist"]
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["release-profiles", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["profiles"]["remux"]["default_resolution"] == "2160p"
    assert payload["profiles"]["remux"]["quality_tag_scores"]["remux"] == 20
    assert payload["profiles"]["remux"]["source_ids"] == ["letterboxd-watchlist"]


def test_reseed_report_lists_high_score_missing_candidates(tmp_path: Path) -> None:
    from seed_agent.cli import app

    config_path = _config_file(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        stable_id="demo-free:missing",
        title="Missing Torrent",
        site="demo-free",
        state=LifecycleState.DELETED,
        score=91,
        torrent_hash="missing-hash",
    )
    store._upsert_torrent_runtime(  # type: ignore[attr-defined]
        "missing-hash",
        missing_from_qb_at=datetime.now(UTC).isoformat(),
        missing_from_qb_reason="missing from live list",
    )

    result = CliRunner().invoke(app, ["reseed-report", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["eligible_count"] == 1
    assert payload["candidates"][0]["reason"] == "missing_from_downloader"


def test_headroom_report_projects_accepted_candidate_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _config_file(tmp_path)
    config = _config()
    candidate = _candidate(size_bytes=10 * 1024**3)

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidate, score=95)]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: None)

    result = CliRunner().invoke(cli.app, ["headroom-report", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["accepted"] == 1
    assert payload["accepted_size_gb"] == 10.0
    assert payload["headroom_v2"]["recommended_enqueue_mode"] == "normal"


def test_headroom_report_flags_disk_headroom_after_existing_liability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seed_agent import cli
    from seed_agent.downloaders.base import DownloaderStatus

    monkeypatch.chdir(tmp_path)
    config_path = _config_file(tmp_path)
    config = _config()
    candidate = _candidate(size_bytes=10 * 1024**3)

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidate, score=95)]

    class FakeDownloader:
        async def get_status(self) -> DownloaderStatus:
            return DownloaderStatus(free_space_bytes=15 * 1024**3)

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                _managed_incomplete_torrent(
                    hash="seed-active",
                    size_bytes=8 * 1024**3,
                    downloaded_bytes=0,
                    metadata={"amount_left_bytes": 8 * 1024**3},
                )
            ]

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["headroom-report", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["headroom_v2"]["over_budget_after_accepts"] is False
    assert payload["headroom_v2"]["over_disk_after_accepts"] is True
    assert payload["headroom_v2"]["recommended_enqueue_mode"] == "reject"
    assert payload["downloader_status"]["available_for_new_downloads_gb"] == 7.0


def test_run_once_invoke_with_execute_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
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
