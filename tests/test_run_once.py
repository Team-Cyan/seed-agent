from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import Decision, LifecycleState, ScoreBreakdown, TorrentCandidate
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
            "category": "pt-auto",
            "tags": ["seed-agent", "pt-auto"],
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
  category: pt-auto
  tags: ["seed-agent", "pt-auto"]
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


def test_run_once_dry_run_updates_state_and_redacts_audit(
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

    async def fake_enqueue_candidates(scored, downloader, category, tags, execute):
        assert execute is False
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


def test_run_once_execute_updates_state_with_hash(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)

    config_path = _config_file(tmp_path, secret_ref="local/secrets/qb.yaml")
    config = _config(secret_ref="local/secrets/qb.yaml")

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [_candidate()]

    def fake_score_candidates(candidates, discovery_config, scoring_config):
        return [_scored()]

    class FakeDownloader:
        async def add_url(self, url: str, category: str, tags: list[str]) -> str | None:
            return "0123456789abcdef0123456789abcdef01234567"

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

    result = CliRunner().invoke(
        cli.app,
        ["run-once", "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "run-once"
    assert payload["execute"] is True
    assert payload["enqueued"] == 1

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

    audit = audit_path.read_text(encoding="utf-8")
    assert "passkey=secret" not in audit
    assert "download.php?id=1" in audit
