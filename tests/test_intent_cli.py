import json
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.models import IntentState
from seed_agent.state import StateStore


def _write_config(tmp_path: Path) -> Path:
    inbox = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
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
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: null
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
want_decision:
  confirmation_threshold: 0.82
  auto_enqueue_threshold: 0.94
  ambiguity_gap: 0.08
  default_resolution: 1080p
  preferred_languages: ["zh", "en"]
  inbox_ref: {inbox.relative_to(tmp_path).as_posix()}
""",
        encoding="utf-8",
    )
    return path


def _json_output(result) -> dict[str, object]:
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    return parsed


def test_intent_add_cli_persists_intent_and_writes_audit(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        ["intent-add", "Inception 2010 1080p", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "intent-add"
    assert payload["intent"]["title"] == "Inception"
    assert payload["intent"]["year"] == 2010
    assert payload["decision"]["action"] == "intent.ingest"
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    assert store.get_intent(payload["intent"]["intent_id"]) is not None
    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "intent.ingest" in audit


def test_intent_add_cli_redacts_sensitive_text(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "intent-add",
            "movie Secret passkey=abc123 2020 1080p",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert "passkey=abc123" not in result.output
    assert "passkey=<redacted>" not in result.output


def test_intent_inbox_cli_ingests_configured_jsonl(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    inbox = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox.write_text(
        "\n".join(
            [
                json.dumps({"id": "movie-1", "text": "Inception 2010 1080p"}),
                json.dumps({"id": "show-1", "text": "show Severance S02E03 2160p"}),
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli.app, ["intent-inbox", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "intent-inbox"
    assert payload["ingested"] == 2
    assert [item["title"] for item in payload["intents"]] == ["Inception", "Severance"]
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    assert len(store.list_intents_by_state(IntentState.NORMALIZED)) == 2


def test_intent_commands_show_in_help() -> None:
    from seed_agent.cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "intent-add" in result.output
    assert "intent-inbox" in result.output
    assert "intent-search" in result.output
    assert "intent-rank" in result.output
    assert "intent-review" in result.output
    assert "intent-confirm" not in result.output
    assert "intent-reject" in result.output
    assert "intent-enqueue" in result.output
    assert "intent-run-once" in result.output

    enqueue_help = CliRunner().invoke(app, ["intent-enqueue", "--help"])
    assert enqueue_help.exit_code == 0
    assert "--release-id" in enqueue_help.output
