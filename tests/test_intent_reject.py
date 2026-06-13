import json
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.actions.intent import add_intent
from seed_agent.models import IntentState
from seed_agent.state import StateStore


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
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
  secret_ref: null
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


def test_intent_reject_updates_local_state_and_audit_only(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)

    result = CliRunner().invoke(
        cli.app,
        ["intent-reject", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "intent-reject"
    assert payload["intent"]["state"] == IntentState.REJECTED.value
    assert payload["decision"]["action"] == "intent.reject"
    row = store.get_intent(intent.intent_id)
    assert row is not None
    assert row["state"] == IntentState.REJECTED.value
    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "intent.reject" in audit
    assert "qb.enqueue" not in audit
