from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.downloaders.base import DownloaderStatus
from seed_agent.models import (
    Decision,
    LifecycleState,
    ManagedTorrent,
    ScoreBreakdown,
    TorrentCandidate,
)
from seed_agent.policies.category_policy import PoolUsage
from seed_agent.state import StateStore


def _config(
    secret_ref: str | None = None,
    *,
    discovery_overrides: dict[str, object] | None = None,
) -> SeedAgentConfig:
    discovery_data = {
        "discounts": ["free", "2xfree"],
        "min_left_time_minutes": 120,
        "min_leechers": 8,
        "target_seed_leecher_ratio": 10,
        "allow_hr": False,
    }
    if discovery_overrides:
        discovery_data.update(discovery_overrides)
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
        pt_filters=DiscoveryConfig(**discovery_data),
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
                }
            ],
            "budget_pools": [{"name": "downloads", "max_size_tib": 10}],
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


def _config_file(
    tmp_path: Path,
    secret_ref: str | None = None,
    *,
    discovery_extra: str = "",
) -> Path:
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
{discovery_extra}
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


def _secret_file(tmp_path: Path, secret_ref: str) -> Path:
    path = tmp_path / secret_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
base_url: https://qb.example
username: alice
password: s3cr3t
""",
        encoding="utf-8",
    )
    return path


def test_enqueue_batch_hard_pool_limit_is_exact_to_one_byte() -> None:
    from seed_agent import cli

    first = _scored(candidate=_candidate(size_bytes=1), score=95)
    second = _scored(
        candidate=_candidate(
            source_url="https://tracker.example/details.php?id=2",
            download_url="https://tracker.example/download.php?id=2",
            size_bytes=1,
        ),
        score=90,
    )

    batches = cli._enqueue_candidate_batches(
        [second, first],
        _config(),
        [],
        PoolUsage(pool_name="downloads", size_bytes=1023, max_size_bytes=1024),
        None,
    )

    assert [(batch[0][0].candidate.stable_id, batch[1]) for batch in batches] == [
        (first.candidate.stable_id, False),
        (second.candidate.stable_id, True),
    ]


def test_capacity_guard_triggers_prune_when_mutable_pool_is_over_budget(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    torrent = ManagedTorrent(
        hash="over-budget",
        name="Over budget",
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

    class FakeDownloader:
        async def list_torrents(self, category=None, tags=None):
            return [torrent]

    calls: list[dict[str, object]] = []

    def fake_prune(path: Path, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"execute": False, "hard_cap_satisfied": False}

    monkeypatch.setattr(cli, "load_config", lambda path: _config())
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: FakeDownloader())
    monkeypatch.setattr(cli, "_prune_payload", fake_prune)

    payload = cli._capacity_guard_payload(tmp_path / "config.yaml", execute=False)

    assert payload["triggered"] is True
    assert payload["trigger_over_budget_pools"] == ["downloads"]
    assert calls == [
        {
            "execute": False,
            "completed_low_upload_requires_reclamation": True,
            "fail_closed_unknown_incomplete": True,
        }
    ]


def test_capacity_guard_wait_checks_between_full_cycles(monkeypatch) -> None:
    from seed_agent import cli

    sleeps: list[int] = []
    checks: list[bool] = []

    class FakeLeaseHeartbeat:
        def ensure_owned(self) -> None:
            checks.append(True)

    monkeypatch.setattr(cli.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        cli,
        "_capacity_guard_payload",
        lambda path, *, execute: {
            "command": "capacity-guard",
            "execute": execute,
            "triggered": False,
        },
    )
    monkeypatch.setattr(cli, "_print_json", lambda payload: None)

    cli._wait_for_next_schedule_cycle(
        Path("config.yaml"),
        execute=True,
        interval_seconds=130,
        guard_interval_seconds=60,
        lease_heartbeat=FakeLeaseHeartbeat(),
    )

    assert sleeps == [60, 60, 10]
    assert checks == [True, True]


def test_capacity_guard_wait_survives_transient_downloader_failure(monkeypatch) -> None:
    from seed_agent import cli

    outputs: list[dict[str, object]] = []
    attempts = 0

    class FakeLeaseHeartbeat:
        def ensure_owned(self) -> None:
            return None

    def guard(path: Path, *, execute: bool) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("qB temporarily unavailable")
        return {
            "command": "capacity-guard",
            "execute": execute,
            "triggered": False,
            "hard_cap_satisfied": True,
        }

    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(cli, "_capacity_guard_payload", guard)
    monkeypatch.setattr(cli, "_print_json", outputs.append)

    cli._wait_for_next_schedule_cycle(
        Path("config.yaml"),
        execute=True,
        interval_seconds=130,
        guard_interval_seconds=60,
        lease_heartbeat=FakeLeaseHeartbeat(),
    )

    assert attempts == 2
    assert outputs[0]["error"] == "qB temporarily unavailable"
    assert outputs[1]["hard_cap_satisfied"] is True


def _json_output(result) -> dict[str, object]:
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    return parsed


def test_run_once_dry_run_updates_state_and_redacts_audit(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()

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
        assert policy.name == "seed"
        assert pool_usage is None
        return [
            Decision(
                action="qb.enqueue",
                target_id=_scored().candidate_id,
                execute=False,
                reason="dry run decision",
                new_state={
                    "candidate_title": _scored().candidate.title,
                    "download_url": _scored().candidate.download_url,
                },
            )
        ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "run-once"
    assert payload["execute"] is False
    assert payload["enqueued"] == 1

    state_path = tmp_path / ".seed-agent" / "state.db"
    audit_path = tmp_path / ".seed-agent" / "audit.jsonl"
    assert state_path.exists()
    assert audit_path.exists()

    store = StateStore(state_path)
    row = store.get_candidate(_candidate().stable_id)
    assert row is not None
    assert row["state"] == LifecycleState.SCORED.value
    assert row["score"] == 95
    assert row["torrent_hash"] is None

    audit = audit_path.read_text(encoding="utf-8")
    assert "passkey=secret" not in audit
    assert "download.php?id=1" in audit


def test_run_once_execute_reads_secret_and_preserves_state_monotonically(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    secret_ref = "local/secrets/qb.yaml"
    config_path = _config_file(tmp_path, secret_ref=secret_ref)
    _secret_file(tmp_path, secret_ref)

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    qb_calls: list[tuple[str, str, str]] = []

    class FakeQbittorrentClient:
        def __init__(self, base_url: str, username: str, password: str) -> None:
            qb_calls.append((base_url, username, password))

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

    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "QbittorrentClient", FakeQbittorrentClient)

    result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "run-once"
    assert payload["execute"] is True
    assert payload["enqueued"] == 1
    assert qb_calls == [("https://qb.example", "alice", "s3cr3t")]

    state_path = tmp_path / ".seed-agent" / "state.db"
    audit_path = tmp_path / ".seed-agent" / "audit.jsonl"
    assert state_path.exists()
    assert audit_path.exists()

    store = StateStore(state_path)
    row = store.get_candidate(_candidate().stable_id)
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value
    assert row["score"] == 95
    assert row["torrent_hash"] == "0123456789abcdef0123456789abcdef01234567"

    async def fake_dry_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_dry_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    monkeypatch.setattr(cli, "discover_candidates", fake_dry_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_dry_score_candidates)

    dry_result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path)],
    )

    assert dry_result.exit_code == 0
    dry_payload = _json_output(dry_result)
    assert dry_payload["execute"] is False

    preserved = store.get_candidate(_candidate().stable_id)
    assert preserved is not None
    assert preserved["state"] == LifecycleState.ENQUEUED.value
    assert preserved["score"] == 95
    assert preserved["torrent_hash"] == "0123456789abcdef0123456789abcdef01234567"

    audit = audit_path.read_text(encoding="utf-8")
    assert "passkey=secret" not in audit
    assert "download.php?id=1" in audit


def test_run_once_execute_marks_enqueued_without_hash_and_preserves_it_on_dry_run(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    class FakeDownloader:
        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return []

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

    def fake_build_downloader(config: SeedAgentConfig):
        return FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "build_downloader", fake_build_downloader)

    execute_result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert execute_result.exit_code == 0
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    row = store.get_candidate(_candidate().stable_id)
    assert row is not None
    assert row["state"] == LifecycleState.ENQUEUED.value
    assert row["torrent_hash"] is None

    dry_run_result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert dry_run_result.exit_code == 0
    preserved = store.get_candidate(_candidate().stable_id)
    assert preserved is not None
    assert preserved["state"] == LifecycleState.ENQUEUED.value
    assert preserved["torrent_hash"] is None


def test_run_once_execute_resolves_hash_when_qb_add_returns_ok_only(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    class FakeDownloader:
        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            now = datetime.now(UTC)
            return [
                ManagedTorrent(
                    hash="fedcba9876543210fedcba9876543210fedcba98",
                    name=_candidate().title,
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="downloading",
                    size_bytes=_candidate().size_bytes,
                    uploaded_bytes=0,
                    downloaded_bytes=0,
                    added_at=now,
                    completed_at=None,
                    last_activity_at=now,
                    save_path="/downloads/seed",
                    metadata={},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

    def fake_build_downloader(config: SeedAgentConfig):
        return FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "build_downloader", fake_build_downloader)

    result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    row = store.get_candidate(_candidate().stable_id)
    assert row is not None
    assert row["state"] == LifecycleState.DOWNLOADING.value
    assert row["torrent_hash"] == "fedcba9876543210fedcba9876543210fedcba98"


def test_run_once_execute_failure_persists_prior_state_and_audit(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    first = _candidate(title="First", source_url="https://tracker.example/details.php?id=1")
    second = _candidate(
        title="Second",
        source_url="https://tracker.example/details.php?id=2",
        download_url="https://tracker.example/download.php?id=2&passkey=secret",
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [first, second]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=first), _scored(candidate=second)]

    class FakeDownloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            self.calls.append(url)
            if len(self.calls) == 2:
                raise RuntimeError("add failed")
            return "0123456789abcdef0123456789abcdef01234567"

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return []

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 1
    payload = _json_output(result)
    assert payload["error"] == "qBittorrent enqueue batch failed"
    assert payload["enqueued"] == 1
    assert [decision["action"] for decision in payload["decisions"]] == [
        "qb.enqueue",
        "qb.enqueue.failed",
    ]

    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    first_row = store.get_candidate(first.stable_id)
    second_row = store.get_candidate(second.stable_id)
    assert first_row is not None
    assert first_row["state"] == LifecycleState.ENQUEUED.value
    assert second_row is not None
    assert second_row["state"] == LifecycleState.SCORED.value

    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "qb.enqueue" in audit
    assert "qb.enqueue.failed" in audit
    assert "passkey=secret" not in audit


def test_run_once_execute_missing_secret_exits_non_zero(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/missing.yaml")

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)

    result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert result.exit_code != 0
    assert "missing downloader secret" in result.output


def test_run_once_skips_previously_enqueued_candidate(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    candidate = _candidate()
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        candidate.stable_id,
        candidate.title,
        candidate.site,
        LifecycleState.ENQUEUED,
        score=95,
        torrent_hash=None,
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidate)]

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
        assert list(scored) == []
        return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["accepted"] == 0
    assert payload["skipped_existing"] == 1
    assert payload["enqueued"] == 0


def test_run_once_links_existing_live_torrent_before_enqueue(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config(secret_ref="local/secrets/qb.yaml")
    candidate = _candidate(size_bytes=123456789)
    live_hash = "ad4cd6aa5a69c100ad876b3751d49d1589da8fd4"

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidate)]

    class FakeDownloader:
        def __init__(self) -> None:
            self.add_calls = 0

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            self.add_calls += 1
            raise AssertionError("existing live torrent must be linked before add_url")

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash=live_hash,
                    name=candidate.title,
                    category="seed",
                    tags={"seed-agent", "seed", "site:demo-free"},
                    state="downloading",
                    size_bytes=candidate.size_bytes,
                    uploaded_bytes=0,
                    downloaded_bytes=1024,
                    added_at=datetime.now(UTC),
                    metadata={"amount_left_bytes": candidate.size_bytes - 1024},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

    downloader = FakeDownloader()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["accepted"] == 0
    assert payload["skipped_existing"] == 1
    assert payload["enqueued"] == 0
    assert downloader.add_calls == 0

    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    row = store.get_candidate(candidate.stable_id)
    assert row is not None
    assert row["state"] == LifecycleState.DOWNLOADING.value
    assert row["torrent_hash"] == live_hash


def test_run_once_rejects_candidate_below_execute_free_window(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path)
    config = _config()
    candidate = _candidate(left_time_minutes=45)

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [candidate]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidate)]

    async def fake_enqueue_candidates(*args, **kwargs):
        return []

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)

    result = CliRunner().invoke(
        cli.app,
        [
            "run-once",
            "--config",
            str(config_path),
            "--min-free-window-minutes",
            "180",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["accepted"] == 0
    assert payload["enqueued"] == 0
    assert any(
        "left_time 45 < execute safety 180" in reason for reason in payload["scores"][0]["reasons"]
    )


def test_run_once_dry_run_pauses_enqueue_when_runtime_download_gate_exceeded(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(
        tmp_path,
        secret_ref="local/secrets/qb.yaml",
        discovery_extra="  max_active_downloads: 1\n",
    )
    config = _config(
        secret_ref="local/secrets/qb.yaml",
        discovery_overrides={"max_active_downloads": 1},
    )

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
        assert paused is True
        assert pool_usage is not None
        assert pause_reasons == ["active downloads 1 >= max 1"]
        return []

    class FakeDownloader:
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-active",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="downloading",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=1,
                    downloaded_bytes=1,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"dlspeed_bps": 1024, "amount_left_bytes": 2 * 1024**3},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert "active downloads 1 >= max 1" in payload["enqueue_blocked_reasons"]
    assert payload["decisions"] == []


def test_run_once_dry_run_uses_raw_amount_left_for_runtime_gate(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(
        tmp_path,
        secret_ref="local/secrets/qb.yaml",
        discovery_extra="  max_total_amount_left_gb: 1.0\n",
    )
    config = _config(
        secret_ref="local/secrets/qb.yaml",
        discovery_overrides={"max_total_amount_left_gb": 1.0},
    )

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
        assert paused is True
        assert pool_usage is not None
        assert pause_reasons == [
            "remaining download budget reserved for higher-score candidates (1.0004 GiB / max 1.0)"
        ]
        return []

    class FakeDownloader:
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-active",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="stalledDL",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=1,
                    downloaded_bytes=1,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"dlspeed_bps": 0, "amount_left_bytes": int(1.0004 * 1024**3)},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["total_amount_left_gb"] == 1.0
    assert payload["runtime_activity"]["total_download_liability_gb"] == 1.0
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert payload["enqueue_blocked_reasons"] == [
        "remaining download budget reserved for higher-score candidates (1.0004 GiB / max 1.0)"
    ]


def test_run_once_pauses_when_existing_download_liability_exceeds_free_disk(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidates[0])]

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
        assert paused is True
        assert pause_reasons == ["free disk 15.0 GiB below existing remaining download 20.0 GiB"]
        return []

    class FakeDownloader:
        async def get_status(self) -> DownloaderStatus:
            return DownloaderStatus(free_space_bytes=15 * 1024**3)

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-active",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="stalledDL",
                    size_bytes=30 * 1024**3,
                    uploaded_bytes=0,
                    downloaded_bytes=10 * 1024**3,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"dlspeed_bps": 0, "amount_left_bytes": 20 * 1024**3},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert payload["enqueue_blocked_reasons"] == [
        "free disk 15.0 GiB below existing remaining download 20.0 GiB"
    ]
    assert payload["downloader_status"]["free_space_gb"] == 15.0
    assert payload["downloader_status"]["existing_download_liability_gb"] == 20.0
    assert payload["downloader_status"]["available_for_new_downloads_gb"] == 0.0
    assert payload["downloader_status"]["over_existing_liability"] is True


def test_run_once_capacity_prune_refreshes_runtime_before_enqueue(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(
        tmp_path,
        secret_ref="local/secrets/qb.yaml",
        discovery_extra="  max_total_amount_left_gb: 1.0\n",
    )
    config = _config(
        secret_ref="local/secrets/qb.yaml",
        discovery_overrides={"max_total_amount_left_gb": 1.0},
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate(size_bytes=int(0.5 * 1024**3))]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidates[0])]

    enqueue_calls: list[tuple[bool, list[str] | None]] = []

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
        enqueue_calls.append((paused, pause_reasons))
        return [
            Decision(
                action="qb.enqueue",
                target_id=scored[0].candidate_id,
                execute=False,
                reason="dry run decision",
            )
        ]

    class FakeDownloader:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            self.list_calls += 1
            if self.list_calls == 1:
                return [
                    ManagedTorrent(
                        hash="seed-active",
                        name="Managed Torrent",
                        category="seed",
                        tags={"seed-agent", "seed"},
                        state="stalledDL",
                        size_bytes=10 * 1024**3,
                        uploaded_bytes=0,
                        downloaded_bytes=1,
                        added_at=datetime.now(UTC),
                        last_activity_at=datetime.now(UTC),
                        metadata={
                            "dlspeed_bps": 0,
                            "amount_left_bytes": int(1.0004 * 1024**3),
                        },
                    )
                ]
            return []

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    prune_calls: list[dict[str, object]] = []

    def fake_prune_payload(
        config_path_value: Path,
        *,
        execute: bool,
        free_window_min_remaining_minutes: int | None = None,
        force_space_reclamation: bool = False,
        completed_low_upload_requires_reclamation: bool = False,
        reclaim_targets_by_pool: dict[str, int] | None = None,
    ) -> dict[str, object]:
        prune_calls.append(
            {
                "execute": execute,
                "force_space_reclamation": force_space_reclamation,
                "completed_low_upload_requires_reclamation": (
                    completed_low_upload_requires_reclamation
                ),
                "reclaim_targets_by_pool": reclaim_targets_by_pool,
            }
        )
        return {
            "command": "prune",
            "config": str(config_path_value),
            "execute": execute,
            "force_space_reclamation": force_space_reclamation,
            "completed_low_upload_requires_reclamation": (
                completed_low_upload_requires_reclamation
            ),
            "reclaim_targets_by_pool": reclaim_targets_by_pool,
            "managed_count": 1,
            "pool_usage": {},
            "decisions": [{"action": "qb.cleanup.delete"}],
            "preview": [],
        }

    downloader = FakeDownloader()
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: downloader)
    monkeypatch.setattr(cli, "_prune_payload", fake_prune_payload)

    payload = cli._run_once_payload(
        config_path,
        execute=False,
        min_free_window_minutes=None,
        require_known_free_window=False,
        prune=False,
        capacity_prune=True,
    )

    assert len(prune_calls) == 1
    assert prune_calls[0]["execute"] is False
    assert prune_calls[0]["force_space_reclamation"] is True
    assert prune_calls[0]["completed_low_upload_requires_reclamation"] is True
    reclaim_targets = prune_calls[0]["reclaim_targets_by_pool"]
    assert isinstance(reclaim_targets, dict)
    assert int(reclaim_targets["downloads"]) > 0
    assert enqueue_calls == [(False, [])]
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert "enqueue_paused_reasons" not in payload
    assert payload["capacity_prune"]["force_space_reclamation"] is True


def test_run_once_dry_run_ignores_zero_progress_stopped_queue_for_runtime_gate(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(
        tmp_path,
        secret_ref="local/secrets/qb.yaml",
        discovery_extra="  max_total_amount_left_gb: 1.0\n",
    )
    config = _config(
        secret_ref="local/secrets/qb.yaml",
        discovery_overrides={"max_total_amount_left_gb": 1.0},
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate(size_bytes=int(0.5 * 1024**3))]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored(candidate=candidates[0])]

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
        assert paused is False
        assert pause_reasons == []
        return []

    class FakeDownloader:
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-queued",
                    name="Queued Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="stoppedDL",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=0,
                    downloaded_bytes=0,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"dlspeed_bps": 0, "amount_left_bytes": int(1.0004 * 1024**3)},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["total_amount_left_gb"] == 1.0
    assert payload["runtime_activity"]["total_download_liability_gb"] == 0.0
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert "enqueue_paused_reasons" not in payload


def test_run_once_dry_run_starts_higher_score_candidates_before_pausing_over_budget(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(
        tmp_path,
        secret_ref="local/secrets/qb.yaml",
        discovery_extra="  max_total_amount_left_gb: 15.0\n",
    )
    config = _config(
        secret_ref="local/secrets/qb.yaml",
        discovery_overrides={"max_total_amount_left_gb": 15.0},
    )

    high = _candidate(title="High", size_bytes=10 * 1024**3)
    low = _candidate(
        title="Low", source_url="https://tracker.example/details.php?id=2", size_bytes=10 * 1024**3
    )
    calls: list[tuple[list[str], bool]] = []

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [low, high]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [
            _scored(candidate=low, score=80),
            _scored(candidate=high, score=95),
        ]

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
        calls.append(([item.candidate.title for item in scored], paused))
        return []

    class FakeDownloader:
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return []

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    assert calls == [(["High"], False), (["Low"], True)]


def test_run_once_dry_run_counts_stalled_downloads_for_runtime_gate(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(
        tmp_path,
        secret_ref="local/secrets/qb.yaml",
        discovery_extra="  max_active_downloads: 1\n",
    )
    config = _config(
        secret_ref="local/secrets/qb.yaml",
        discovery_overrides={"max_active_downloads": 1},
    )

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
        assert paused is True
        assert pause_reasons == ["active downloads 1 >= max 1"]
        return []

    class FakeDownloader:
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-stalled",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="stalledDL",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=1,
                    downloaded_bytes=1,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"dlspeed_bps": 0, "amount_left_bytes": 2 * 1024**3},
                )
            ]

        async def pause(self, hash: str) -> None:
            return None

        async def delete(self, hash: str, delete_files: bool) -> None:
            return None

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "score_candidates", fake_score_candidates)
    monkeypatch.setattr(cli, "enqueue_candidates", fake_enqueue_candidates)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["run-once", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["active_download_count"] == 1
    assert payload["runtime_activity"]["stalled_download_count"] == 1
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert payload["enqueue_blocked_reasons"] == ["active downloads 1 >= max 1"]
