import json
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.models import Discount, IntentState, ReleaseCandidate
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
intent:
  confirmation_threshold: 0.82
  auto_enqueue_threshold: 0.94
  ambiguity_gap: 0.08
  default_resolution: 1080p
  preferred_languages: ["zh", "en"]
  inbox_ref: local/inbox/intents.jsonl
search:
  site_priority:
    demo-free: 5
  max_results_per_site: 20
  prefer_free: true
  reject_hr_by_default: true
""",
        encoding="utf-8",
    )
    return path


def _json_output(result) -> dict[str, object]:
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    return parsed


class _FakeSearchProvider:
    async def search(self, intent):
        return [
            ReleaseCandidate(
                release_id=f"demo-free:{intent.intent_id}:1",
                site="demo-free",
                title="Inception 2010 1080p BluRay",
                source_url="https://tracker.example/details.php?id=1",
                download_url="https://tracker.example/download.php?id=1&passkey=secret",
                size_bytes=12 * 1024 * 1024 * 1024,
                seeders=30,
                leechers=8,
                discount=Discount.FREE,
            )
        ]


def test_intent_search_rank_and_review_cli_flow(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    config_path = _write_config(tmp_path)

    add_result = CliRunner().invoke(
        cli.app,
        ["intent-add", "Inception 2010 1080p", "--config", str(config_path)],
    )
    assert add_result.exit_code == 0
    intent_id = _json_output(add_result)["intent"]["intent_id"]

    search_result = CliRunner().invoke(
        cli.app,
        ["intent-search", str(intent_id), "--config", str(config_path)],
    )
    assert search_result.exit_code == 0
    search_payload = _json_output(search_result)
    assert search_payload["command"] == "intent-search"
    assert search_payload["found"] == 1
    assert "passkey=secret" not in search_result.output
    assert search_payload["decision"]["action"] == "intent.search"

    rank_result = CliRunner().invoke(
        cli.app,
        ["intent-rank", str(intent_id), "--config", str(config_path)],
    )
    assert rank_result.exit_code == 0
    rank_payload = _json_output(rank_result)
    assert rank_payload["command"] == "intent-rank"
    assert rank_payload["ranked"] == 1
    assert rank_payload["candidates"][0]["accepted"] is True
    assert rank_payload["candidates"][0]["score"] >= 90

    review_result = CliRunner().invoke(
        cli.app,
        ["intent-review", "--config", str(config_path)],
    )
    assert review_result.exit_code == 0
    review_payload = _json_output(review_result)
    assert review_payload["command"] == "intent-review"
    assert review_payload["count"] == 1
    assert review_payload["intents"][0]["candidate_count"] == 1

    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    assert len(store.list_intents_by_state(IntentState.SEARCHED)) == 1
    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "intent.search" in audit
    assert "intent.rank" in audit


def test_intent_search_missing_intent_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        ["intent-search", "missing", "--config", str(config_path)],
    )

    assert result.exit_code != 0
    assert "unknown intent: missing" in result.output


def test_build_search_providers_uses_mteam_api_for_intent_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.search.mteam import MTeamSearchProvider

    monkeypatch.chdir(tmp_path)
    secret = tmp_path / "local" / "secrets" / "mt.api-key"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret-api-key", encoding="utf-8")
    config_path = _write_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            """
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
""",
            """
sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.example/fallback
    discovery_mode: api
    api_key_ref: local/secrets/mt.api-key
    api_discovery:
      mode: movie
      only_free: false
      sort_field: seeders
      sort_order: desc
""",
        ),
        encoding="utf-8",
    )
    loaded = cli.load_config(config_path)

    providers = cli._build_search_providers(loaded)

    assert len(providers) == 1
    assert isinstance(providers[0], MTeamSearchProvider)
