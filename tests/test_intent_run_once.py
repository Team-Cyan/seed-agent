import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.models import Discount, IntentState, ReleaseCandidate
from seed_agent.state import StateStore


def _write_config(tmp_path: Path, *, discovery_extra: str = "") -> Path:
    inbox = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "config.yaml"
    discovery_block = discovery_extra if discovery_extra else ""
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
{discovery_block}\
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
release_preferences:
  site_priority:
    demo-free: 5
  max_results_per_site: 20
  prefer_free: true
  reject_hr_by_default: true
want_sources:
  douban_wanted:
    enabled: false
    export_ref: null
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


class _DummyDownloader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add_url(
        self, url: str, category: str, tags: list[str], *, paused: bool = False
    ) -> str | None:
        self.calls.append(url)
        return "0123456789abcdef0123456789abcdef01234567"


def test_intent_run_once_ingests_searches_ranks_and_dry_run_enqueues(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    inbox = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox.write_text(
        json.dumps({"id": "movie-1", "text": "Inception 2010 1080p"}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli.app,
        ["intent-run-once", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "intent-run-once"
    assert payload["execute"] is False
    assert payload["ingested"] == 1
    assert payload["searched"] == 1
    assert payload["ranked"] == 1
    assert payload["enqueue_candidates"] == 1
    assert payload["runtime_activity"]["managed_count"] == 0
    assert downloader.calls == []
    assert "passkey=secret" not in result.output
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    assert len(store.list_intents_by_state(IntentState.SEARCHED)) == 1
    search_runs = store.list_want_search_runs()
    assert len(search_runs) == 1
    assert search_runs[0]["status"] == "searched"
    assert search_runs[0]["results_count"] == 1
    assert search_runs[0]["best_score"] is not None
    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "intent.ingest" in audit
    assert "intent.search" in audit
    assert "intent.rank" in audit
    assert "qb.enqueue" in audit


def test_intent_run_once_with_missing_inbox_is_noop(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        ["intent-run-once", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["ingested"] == 0
    assert payload["searched"] == 0
    assert payload["decisions"] == []


def test_intent_run_once_ingests_configured_douban_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import IntentSource
    from seed_agent.sources.base import SourceIntentEvent

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    monkeypatch.setattr(
        cli,
        "_read_configured_source_events",
        lambda config, **kwargs: [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="Inception 2010 1080p",
                source_event_id="douban:1292052",
                metadata={"source_adapter": "douban_wanted_public"},
            )
        ],
    )
    config_path = _write_config(tmp_path)
    content = config_path.read_text(encoding="utf-8").replace(
        "enabled: false\n    export_ref: null",
        "enabled: true\n    export_ref: null\n    user_name: example-user",
    )
    config_path.write_text(content, encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        ["intent-run-once", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["ingested"] == 1
    assert payload["searched"] == 1
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    rows = store.list_intents_by_state(IntentState.SEARCHED)
    assert len(rows) == 1
    assert rows[0]["source"] == IntentSource.DOUBAN_WANTED.value


def test_intent_run_once_ingests_configured_letterboxd_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import IntentSource

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    config_path = _write_config(tmp_path)
    export = tmp_path / "local" / "inbox" / "letterboxd-watchlist.csv"
    export.write_text(
        "Date,Name,Year,Letterboxd URI\n2025-02-01,Inception,2010,https://boxd.it/demo\n",
        encoding="utf-8",
    )
    content = config_path.read_text(encoding="utf-8").replace(
        """
want_sources:
  douban_wanted:
    enabled: false
    export_ref: null
""",
        """
want_sources:
  douban_wanted:
    enabled: false
    export_ref: null
  want_lists:
    - provider: letterboxd
      id: letterboxd-watchlist
      label: Watchlist
      enabled: true
      export_ref: local/inbox/letterboxd-watchlist.csv
""",
    )
    config_path.write_text(content, encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        ["intent-run-once", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["ingested"] == 1
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    rows = store.list_intents_by_state(IntentState.SEARCHED)
    assert len(rows) == 1
    assert rows[0]["source"] == IntentSource.LETTERBOXD.value


def test_intent_run_once_dry_run_reports_runtime_activity_when_qb_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    config_path = _write_config(tmp_path)
    inbox = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox.write_text(
        json.dumps({"id": "movie-1", "text": "Inception 2010 1080p"}),
        encoding="utf-8",
    )

    class FakeDownloader(_DummyDownloader):
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-active",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="downloading",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=1 * 1024**3,
                    downloaded_bytes=8 * 1024**3,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={
                        "upspeed_bps": 0,
                        "dlspeed_bps": 3 * 1024**2,
                        "amount_left_bytes": 4 * 1024**3,
                    },
                )
            ]

    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: FakeDownloader())

    result = CliRunner().invoke(
        cli.app,
        ["intent-run-once", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["managed_count"] == 1
    assert payload["runtime_activity"]["active_download_count"] == 1
    assert payload["runtime_activity"]["total_dlspeed_mib_s"] == 3.0
    assert payload["default_pool_usage"]["over_budget"] is False


def test_intent_run_once_dry_run_reports_pause_reasons_when_runtime_gate_exceeded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_build_search_providers", lambda config: [_FakeSearchProvider()])
    config_path = _write_config(tmp_path, discovery_extra="  max_active_downloads: 0\n")
    inbox = tmp_path / "local" / "inbox" / "intents.jsonl"
    inbox.write_text(
        json.dumps({"id": "movie-1", "text": "Inception 2010 1080p"}),
        encoding="utf-8",
    )

    class FakeDownloader(_DummyDownloader):
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="seed-active",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="downloading",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=1 * 1024**3,
                    downloaded_bytes=8 * 1024**3,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"upspeed_bps": 0, "dlspeed_bps": 1024, "amount_left_bytes": 1},
                )
            ]

    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: FakeDownloader())

    result = CliRunner().invoke(
        cli.app,
        ["intent-run-once", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert payload["enqueue_blocked_reasons"] == ["active downloads 1 >= max 0"]
    assert payload["decisions"][-1]["action"] == "qb.enqueue.rejected"
