from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from socketserver import TCPServer
from threading import Thread
from typing import Any

from seed_agent.actions.intent import ingest_events
from seed_agent.models import (
    Discount,
    IntentKind,
    IntentSource,
    IntentState,
    LifecycleState,
    RankedRelease,
    ReleaseCandidate,
    ResourceIntent,
)
from seed_agent.sources.base import SourceIntentEvent
from seed_agent.state import StateStore
from seed_agent.web.app import make_handler
from seed_agent.web.settings import (
    TrackerDraft,
    build_tracker_status,
    save_tracker_draft,
    tracker_draft_to_config,
)


def test_mteam_tracker_draft_keeps_secret_value_out_of_config() -> None:
    draft = TrackerDraft(
        type="mteam",
        name="mt",
        enabled=True,
        rss_url="https://rss.example/feed",
        discovery_mode="api",
        api_key_ref="local/secrets/mt.api-key",
        api_key_value="secret-token",
        auth_header="x-api-key",
        cookie_ref="local/secrets/mt.cookie",
    )

    site = tracker_draft_to_config(draft)

    assert site.name == "mt"
    assert site.type == "mteam"
    assert site.api_key_ref == "local/secrets/mt.api-key"
    assert site.auth_header == "x-api-key"
    assert site.cookie_ref == "local/secrets/mt.cookie"
    assert "secret-token" not in site.model_dump_json()


def test_tracker_status_reports_missing_required_fields() -> None:
    draft = TrackerDraft(type=None, name="")

    status = build_tracker_status(draft, root=Path("/tmp/seed-agent"))

    assert {"level": "warning", "message": "type is required"} in status
    assert {"level": "warning", "message": "tracker name is required"} in status


def test_save_tracker_draft_writes_config_ref_and_secret_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    secrets_dir = tmp_path / "local" / "secrets"
    config_dir.mkdir()
    secrets_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites: []
pt_filters:
  discounts: [free]
  min_left_time_minutes: 120
  min_leechers: 1
  target_seed_leecher_ratio: 100
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
  target: local
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: [seed-agent]
  budget_pools:
    - name: downloads
      max_size_tib: 1
  secret_ref: null
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""".lstrip(),
        encoding="utf-8",
    )

    save_tracker_draft(
        config_path,
        TrackerDraft(
            type="mteam",
            name="mt",
            enabled=True,
            rss_url="https://rss.example/feed",
            discovery_mode="api",
            api_key_ref="local/secrets/mt.api-key",
            api_key_value="secret-token",
        ),
    )

    saved = config_path.read_text(encoding="utf-8")
    assert "api_key_ref: local/secrets/mt.api-key" in saved
    assert "auth_header: x-api-key" in saved
    assert "secret-token" not in saved
    assert (tmp_path / "local" / "secrets" / "mt.api-key").read_text(
        encoding="utf-8"
    ) == "secret-token"


def test_http_config_redacts_secret_values(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    (tmp_path / "local" / "secrets").mkdir(parents=True)
    (tmp_path / "local" / "secrets" / "mt.api-key").write_text(
        "secret-token",
        encoding="utf-8",
    )
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "tracker_sites: []",
            """
tracker_sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.example/feed
    discovery_mode: api
    api_key_ref: local/secrets/mt.api-key
    api_discovery:
      mode: adult
""".strip(),
        ),
        encoding="utf-8",
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(base_url, "GET", "/api/config")

    assert payload["trackers"][0]["name"] == "mt"
    assert payload["sections"]["download_client"]["target"] == "local"
    assert payload["sections"]["want_decision"]["inbox_ref"] == "local/inbox/intents.jsonl"
    assert payload["runtime_root"] == str(tmp_path)
    assert payload["trackers"][0]["has_api_key"] is True
    assert "secret-token" not in json.dumps(payload)


def test_http_status_payloads_expose_runtime_provenance(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    heartbeat_path = tmp_path / "state" / "schedule-heartbeat.json"
    heartbeat_path.parent.mkdir()
    heartbeat_path.write_text(
        json.dumps(
            {
                "command": "schedule-run",
                "cycle": 4,
                "updated_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    with _running_server(config_path) as base_url:
        config_payload = _request_json(base_url, "GET", "/api/config")
        state_payload = _request_json(base_url, "GET", "/api/state/summary")
        health_payload = _request_json(base_url, "GET", "/api/health")

    assert config_payload["config_path"] == str(config_path)
    assert config_payload["runtime_root"] == str(tmp_path)
    assert config_payload["state_path"] == str(tmp_path / ".seed-agent" / "state.db")
    assert config_payload["heartbeat_file"] == str(heartbeat_path)
    assert state_payload["config_path"] == str(config_path)
    assert state_payload["runtime_root"] == str(tmp_path)
    assert state_payload["state_path"] == str(tmp_path / ".seed-agent" / "state.db")
    assert state_payload["heartbeat_file"] == str(heartbeat_path)
    assert health_payload["runtime_root"] == str(tmp_path)
    assert health_payload["state_path"] == str(tmp_path / ".seed-agent" / "state.db")
    assert health_payload["heartbeat_file"] == str(heartbeat_path)


def test_http_post_can_require_web_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_minimal_config(tmp_path)
    monkeypatch.setenv("SEED_AGENT_WEB_TOKEN", "local-token")

    with _running_server(config_path) as base_url:
        blocked = _request_json(
            base_url,
            "POST",
            "/api/trackers/validate",
            {"type": "mteam", "name": "mt"},
            expected_status=401,
        )
        allowed = _request_json(
            base_url,
            "POST",
            "/api/trackers/validate",
            {"type": "mteam", "name": "mt"},
            headers={"X-Seed-Agent-Token": "local-token"},
        )

    assert blocked["error"] == "unauthorized"
    assert "status" in allowed


def test_http_ops_payload_exposes_scheduler_and_tracker_state(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.start_scheduler_run(
        run_id="sched-web",
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
    store.finish_scheduler_run(run_id="sched-web", status="success", summary={})
    store.record_tracker_api_event(
        site="mteam",
        endpoint="torrent/search",
        event="rate_limited",
        rate_limited=True,
    )
    store.record_want_search_run(
        intent_id="intent-web",
        source="web",
        status="searched",
        search_enabled=True,
        results_count=2,
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(base_url, "GET", "/api/ops")

    assert payload["state_exists"] is True
    assert payload["scheduler_runs"][0]["run_id"] == "sched-web"
    assert payload["tracker_api_events"][0]["site"] == "mteam"
    assert payload["want_search_runs"][0]["intent_id"] == "intent-web"


def test_http_config_section_save_updates_safe_phase2_fields(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "want_decision",
                "data": {
                    "confirmation_threshold": 0.7,
                    "auto_enqueue_threshold": 0.9,
                    "ambiguity_gap": 0.05,
                    "default_resolution": "2160p",
                    "preferred_languages": ["zh", "ja"],
                    "inbox_ref": "local/inbox/phase2.jsonl",
                },
            },
        )

    assert payload["section"] == "want_decision"
    assert payload["status"] == [{"level": "ok", "message": "want_decision config saved"}]
    saved = config_path.read_text(encoding="utf-8")
    assert "default_resolution: 2160p" in saved
    assert "local/inbox/phase2.jsonl" in saved
    assert "secret-token" not in saved


def test_http_wants_lists_canonical_source_rows_without_manual_add(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    douban_intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="葬送的芙莉莲 2023",
                source_event_id="douban:35797709",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={
                    "douban_user_name": "LancerC",
                    "media_type": "anime",
                    "douban_wish_date": "2025-01-02",
                    "external_ids": {"douban": "35797709"},
                    "source_config_id": "douban-me",
                    "source_label": "豆瓣-我",
                },
            ),
            SourceIntentEvent(
                source=IntentSource.IMDB_WATCHLIST,
                raw_text="Frieren Beyond Journey's End 2023",
                source_event_id="imdb:tt22248376",
                requested_at=datetime(2025, 1, 4, tzinfo=UTC),
                metadata={
                    "media_type": "anime",
                    "external_ids": {"douban": "35797709", "imdb": "tt22248376"},
                    "source_config_id": "imdb-weekend",
                    "source_label": "IMDb-周末清单",
                },
            ),
        ],
        store,
    )[0][0]

    with _running_server(config_path) as base_url:
        initial = _request_json(base_url, "GET", "/api/wants")
        manual_payload = _request_json(
            base_url,
            "POST",
            "/api/wants",
            {"raw_text": "请以你的名字呼唤我 2017 Remux", "media_type": "movie"},
            expected_status=404,
        )

    assert initial["items"][0]["intent_id"] == douban_intent.intent_id
    assert initial["items"][0]["source_label"] == "豆瓣-我 +1"
    assert initial["items"][0]["media_type"] == "anime"
    assert initial["items"][0]["added_at"].startswith("2025-01-02")
    assert initial["items"][0]["added_at_precision"] == "date"
    assert initial["total"] == 1
    assert manual_payload["error"] == "not found"


def test_http_wants_search_runs_filtered_search_without_downloader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    class FakeSearchProvider:
        async def search(self, intent):
            return []

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="葬送的芙莉莲 2023",
                source_event_id="douban:35797709",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={
                    "media_type": "anime",
                    "external_ids": {"douban": "35797709"},
                    "source_config_id": "douban-me",
                    "source_label": "豆瓣-我",
                },
            )
        ],
        store,
    )[0][0]
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "douban-me", "media_type": "anime"},
        )

    row = store.get_intent(intent.intent_id)
    assert payload["searched"] == 1
    assert row is not None
    assert row["state"] == IntentState.CONFIRMATION_REQUIRED.value
    assert row["selected_release_id"] is None
    search_runs = store.list_want_search_runs(intent_id=intent.intent_id)
    assert len(search_runs) == 1
    assert search_runs[0]["status"] == "searched"
    assert search_runs[0]["results_count"] == 0


def test_http_wants_search_records_ranked_release_history_without_downloader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    class FakeSearchProvider:
        async def search(self, intent):
            return [
                ReleaseCandidate(
                    release_id="demo:https://tracker.example/details/1",
                    site="demo",
                    title="葬送的芙莉莲 2023 S01 1080p",
                    source_url="https://tracker.example/details/1",
                    download_url="https://tracker.example/download/1",
                    size_bytes=12 * 1024**3,
                    seeders=20,
                    leechers=8,
                    discount=Discount.FREE,
                )
            ]

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="葬送的芙莉莲 2023",
                source_event_id="douban:35797709",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={
                    "media_type": "anime",
                    "external_ids": {"douban": "35797709"},
                    "source_config_id": "douban-me",
                    "source_label": "豆瓣-我",
                },
            )
        ],
        store,
    )[0][0]
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "douban-me", "media_type": "anime"},
        )

    ranked = store.list_release_candidates(intent.intent_id)
    search_runs = store.list_want_search_runs(intent_id=intent.intent_id)
    row = store.get_intent(intent.intent_id)

    assert payload["searched"] == 1
    assert len(ranked) == 1
    assert ranked[0]["release_id"] == "demo:https://tracker.example/details/1"
    assert len(search_runs) == 1
    assert search_runs[0]["status"] == "searched"
    assert search_runs[0]["results_count"] == 1
    assert search_runs[0]["best_score"] == ranked[0]["score"]
    assert row is not None
    assert row["selected_release_id"] is None
    assert row["state"] == IntentState.CONFIRMATION_REQUIRED.value


def test_http_wants_search_skips_enqueued_wants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    calls = 0

    class FakeSearchProvider:
        async def search(self, intent):
            nonlocal calls
            calls += 1
            return []

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="已下载电影 2024",
                source_event_id="douban:skip",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={"source_config_id": "douban-me", "media_type": "movie"},
            )
        ],
        store,
    )[0][0]
    store.update_intent_state(intent.intent_id, IntentState.ENQUEUED)
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "douban-me", "media_type": "movie"},
        )

    assert payload["searched"] == 0
    assert calls == 0


def test_http_wants_search_skips_during_schedule_backoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    def fail_build_providers(config):
        raise AssertionError("providers should not be built during schedule backoff")

    config_path = _write_minimal_config(tmp_path)
    backoff_dir = tmp_path / ".seed-agent"
    backoff_dir.mkdir(parents=True)
    backoff_dir.joinpath("schedule-backoff.json").write_text(
        json.dumps(
            {
                "active": True,
                "created_at": datetime.now(UTC).isoformat(),
                "until": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                "reason": "mteam request too frequent",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "_build_want_search_providers", fail_build_providers)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "all"},
        )

    assert payload["synced"] == 0
    assert payload["searched"] == 0
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["active"] is True


def test_http_wants_search_skips_during_sqlite_tracker_backoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    def fail_build_providers(config):
        raise AssertionError("providers should not be built during tracker backoff")

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="退避批量 2024",
                source_event_id="douban:bulk-backoff",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={"source_config_id": "douban-me", "media_type": "movie"},
            )
        ],
        store,
    )[0][0]
    store.set_tracker_backoff(
        site="mteam",
        endpoint="torrent/genDlToken",
        until=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        reason="mteam request too frequent",
        source="test",
        run_id="sched-test",
    )
    monkeypatch.setattr(web_app, "_build_want_search_providers", fail_build_providers)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "all"},
        )

    assert payload["synced"] == 0
    assert payload["searched"] == 0
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["active"] is True
    assert payload["schedule_backoff"]["endpoint"] == "torrent/genDlToken"
    assert not (tmp_path / ".seed-agent" / "schedule-backoff.json").exists()
    search_runs = store.list_want_search_runs(intent_id=intent.intent_id)
    assert len(search_runs) == 1
    assert search_runs[0]["status"] == "skipped_backoff"
    assert bool(search_runs[0]["backoff_active"]) is True


def test_http_single_want_search_searches_one_item(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    calls: list[str] = []

    class FakeSearchProvider:
        async def search(self, intent):
            calls.append(intent.intent_id)
            return []

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    first = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="单条搜索 2024",
                source_event_id="douban:single",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={"source_config_id": "douban-me", "media_type": "movie"},
            ),
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="另一条 2024",
                source_event_id="douban:other",
                requested_at=datetime(2025, 1, 3, tzinfo=UTC),
                metadata={"source_config_id": "douban-me", "media_type": "movie"},
            ),
        ],
        store,
    )[0][0]
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{first.intent_id}/search",
        )

    assert payload["searched"] == 1
    assert calls == [first.intent_id]


def test_http_single_want_search_skips_during_schedule_backoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    def fail_build_providers(config):
        raise AssertionError("providers should not be built during schedule backoff")

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="退避单条 2024",
                source_event_id="douban:single-backoff",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={"source_config_id": "douban-me", "media_type": "movie"},
            )
        ],
        store,
    )[0][0]
    backoff_dir = tmp_path / ".seed-agent"
    backoff_dir.mkdir(parents=True, exist_ok=True)
    backoff_dir.joinpath("schedule-backoff.json").write_text(
        json.dumps(
            {
                "active": True,
                "created_at": datetime.now(UTC).isoformat(),
                "until": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                "reason": "mteam request too frequent",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "_build_want_search_providers", fail_build_providers)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/search",
        )

    assert payload["searched"] == 0
    assert payload["skipped"] == 1
    assert payload["skipped_by_backoff"] is True
    assert payload["schedule_backoff"]["active"] is True


def test_http_single_want_search_skips_enqueued_item(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    calls = 0

    class FakeSearchProvider:
        async def search(self, intent):
            nonlocal calls
            calls += 1
            return []

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="已入队单条 2024",
                source_event_id="douban:single-skip",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={"source_config_id": "douban-me", "media_type": "movie"},
            )
        ],
        store,
    )[0][0]
    store.update_intent_state(intent.intent_id, IntentState.ENQUEUED)
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/search",
        )

    assert payload["searched"] == 0
    assert payload["skipped"] == 1
    assert calls == 0


def test_http_wants_sync_ingests_configured_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    config_path = _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        web_app,
        "_read_configured_want_source_events",
        lambda config: [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="葬送的芙莉莲 2023",
                source_event_id="douban:35797709",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={
                    "media_type": "anime",
                    "external_ids": {"douban": "35797709"},
                    "source_config_id": "douban-me",
                    "source_label": "豆瓣-我",
                },
            )
        ],
    )

    with _running_server(config_path) as base_url:
        sync_payload = _request_json(base_url, "POST", "/api/wants/sync")
        wants_payload = _request_json(base_url, "GET", "/api/wants")

    assert sync_payload["ingested"] == 1
    assert sync_payload["total"] == 1
    assert wants_payload["total"] == 1
    assert wants_payload["items"][0]["source_label"] == "豆瓣-我"


def test_http_wants_search_syncs_sources_before_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    class FakeSearchProvider:
        async def search(self, intent):
            return []

    config_path = _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        web_app,
        "_read_configured_want_source_events",
        lambda config: [
            SourceIntentEvent(
                source=IntentSource.IMDB_WATCHLIST,
                raw_text="Frieren Beyond Journey's End 2023",
                source_event_id="imdb:tt22248376",
                requested_at=datetime(2025, 1, 4, tzinfo=UTC),
                metadata={
                    "media_type": "anime",
                    "external_ids": {"imdb": "tt22248376"},
                    "source_config_id": "imdb-weekend",
                    "source_label": "IMDb-周末清单",
                },
            )
        ],
    )
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "imdb-weekend", "media_type": "anime"},
        )
        wants_payload = _request_json(base_url, "GET", "/api/wants")

    assert payload["synced"] == 1
    assert payload["searched"] == 1
    assert wants_payload["total"] == 1
    assert wants_payload["items"][0]["source_label"] == "IMDb-周末清单"


def test_http_wants_search_ranks_canonical_after_release_id_merge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    class MappingSearchProvider:
        async def search(self, intent):
            return [
                ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/1",
                    site="mt",
                    title="Call Me by Your Name 2017 BluRay",
                    source_url="https://kp.m-team.cc/detail/1",
                    download_url="mteam-api://torrent/1",
                    size_bytes=44 * 1024**3,
                    seeders=10,
                    leechers=2,
                    discount=Discount.NORMAL,
                    metadata={"external_ids": {"douban": "26799731", "imdb": "tt5726616"}},
                )
            ]

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    older = ResourceIntent(
        intent_id="douban_wanted:older",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Call Me by Your Name 2017",
        kind=IntentKind.MOVIE,
        title="Call Me by Your Name",
        year=2017,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        metadata={"external_ids": {"douban": "26799731"}},
    )
    store.upsert_intent(older)
    store.upsert_intent_alias("douban:26799731", older.intent_id)
    newer = ingest_events(
        [
            SourceIntentEvent(
                source=IntentSource.IMDB_WATCHLIST,
                raw_text="Call Me by Your Name 2017",
                source_event_id="imdb:tt5726616",
                requested_at=datetime(2025, 1, 5, tzinfo=UTC),
                metadata={
                    "media_type": "movie",
                    "external_ids": {"imdb": "tt5726616"},
                    "source_config_id": "imdb-weekend",
                    "source_label": "IMDb-周末清单",
                },
            )
        ],
        store,
    )[0][0]
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [MappingSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/wants/search",
            {"source": "imdb-weekend", "media_type": "movie"},
        )

    assert payload["searched"] == 1
    assert store.get_intent(newer.intent_id) is None
    assert store.get_intent(older.intent_id)["state"] == IntentState.CONFIRMATION_REQUIRED.value
    assert [row["intent_id"] for row in store.list_release_candidates(older.intent_id)] == [
        older.intent_id
    ]


def test_http_want_candidates_show_matching_and_lower_match_releases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.web import app as web_app

    class FakeSearchProvider:
        async def search(self, intent):
            return [
                ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/740962",
                    site="mt",
                    title="Call Me by Your Name 2017 2160p UHD Blu-ray REMUX HEVC",
                    source_url="https://kp.m-team.cc/detail/740962",
                    download_url="mteam-api://torrent/740962",
                    size_bytes=66 * 1024**3,
                    seeders=12,
                    leechers=3,
                    discount=Discount.NORMAL,
                    metadata={
                        "mteam_torrent_id": "740962",
                        "download_url_source": "mteam_api_deferred",
                        "mteam_tags": ["Blu-ray", "4K", "H.265/HEVC", "DTS-HD MA"],
                        "mteam_raw_tags": {
                            "medium": "0",
                            "standard": "6",
                            "video_codec": "16",
                            "audio_codec": "11",
                        },
                    },
                ),
                ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/99",
                    site="mt",
                    title="Call Me by Your Name 2017 1080p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/99",
                    download_url="mteam-api://torrent/99",
                    size_bytes=8 * 1024**3,
                    seeders=100,
                    leechers=1,
                    discount=Discount.FREE,
                    metadata={
                        "mteam_torrent_id": "99",
                        "download_url_source": "mteam_api_deferred",
                        "mteam_tags": ["WEB-DL", "1080p"],
                    },
                ),
            ]

    config_path = _write_minimal_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
release_preferences:
  quality_tag_scores:
    remux: 20
    webdl: -30
want_decision:
  default_resolution: null
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        web_app,
        "_read_configured_want_source_events",
        lambda config: [
            SourceIntentEvent(
                source=IntentSource.DOUBAN_WANTED,
                raw_text="请以你的名字呼唤我 Call Me by Your Name 2017",
                source_event_id="douban:26799731",
                requested_at=datetime(2025, 1, 2, tzinfo=UTC),
                metadata={
                    "media_type": "movie",
                    "external_ids": {"douban": "26799731"},
                    "source_config_id": "douban-me",
                    "source_label": "豆瓣-我",
                },
            )
        ],
    )
    monkeypatch.setattr(
        web_app,
        "_build_want_search_providers",
        lambda config: [FakeSearchProvider()],
    )

    with _running_server(config_path) as base_url:
        _request_json(base_url, "POST", "/api/wants/search", {"source": "all"})
        wants_payload = _request_json(base_url, "GET", "/api/wants")
        intent_id = wants_payload["items"][0]["intent_id"]
        candidates_payload = _request_json(
            base_url,
            "GET",
            f"/api/wants/{intent_id}/candidates",
        )

    assert candidates_payload["total"] == 2
    assert candidates_payload["items"][0]["matches_requirements"] is True
    assert candidates_payload["items"][0]["status_label"] == "符合偏好"
    assert candidates_payload["items"][0]["official_tags"] == [
        "Blu-ray",
        "4K",
        "H.265/HEVC",
        "DTS-HD MA",
    ]
    assert candidates_payload["items"][0]["size_gb"] == 66.0
    assert candidates_payload["items"][1]["matches_requirements"] is False
    assert candidates_payload["items"][1]["status_label"] == "不符合偏好"
    assert "quality tag score -30: WEB-DL" in candidates_payload["items"][1]["reasons"]


def test_http_wants_payload_includes_best_candidate_score(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ResourceIntent(
        intent_id="douban_wanted:housemaid",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="家政服务 The Housemaid 2025",
        kind=IntentKind.MOVIE,
        title="家政服务 The Housemaid",
        year=2025,
        requested_at=datetime(2026, 6, 6, tzinfo=UTC),
        state=IntentState.CONFIRMATION_REQUIRED,
    )
    store.upsert_intent(intent)
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/low",
                    site="mt",
                    title="The Housemaid 2025 1080p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/low",
                    download_url="mteam-api://torrent/low",
                    size_bytes=8 * 1024**3,
                    seeders=5,
                    leechers=1,
                    discount=Discount.NORMAL,
                ),
                score=8,
                confidence=0.08,
                accepted=False,
                confirmation_required=True,
                reasons=[],
                risks=["weak title match"],
            ),
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/high",
                    site="mt",
                    title="The Housemaid 2025 2160p BluRay Remux",
                    source_url="https://kp.m-team.cc/detail/high",
                    download_url="mteam-api://torrent/high",
                    size_bytes=42 * 1024**3,
                    seeders=10,
                    leechers=3,
                    discount=Discount.FREE,
                ),
                score=86,
                confidence=0.86,
                accepted=True,
                confirmation_required=False,
                reasons=["title tokens matched"],
                risks=[],
            ),
        ]
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(base_url, "GET", "/api/wants")

    assert payload["items"][0]["release_count"] == 2
    assert payload["items"][0]["best_candidate_score"] == 86


def test_http_want_enqueue_can_select_lower_match_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ResourceIntent(
        intent_id="douban_wanted:call-me-by-your-name",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Call Me by Your Name 2017",
        kind=IntentKind.MOVIE,
        title="Call Me by Your Name",
        year=2017,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        state=IntentState.CONFIRMATION_REQUIRED,
    )
    store.upsert_intent(intent)
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/99",
                    site="mt",
                    title="Call Me by Your Name 2017 1080p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/99",
                    download_url="https://tracker.example/download?id=99",
                    size_bytes=8 * 1024**3,
                    seeders=100,
                    leechers=1,
                    discount=Discount.FREE,
                ),
                score=40,
                confidence=0.4,
                accepted=False,
                confirmation_required=True,
                reasons=["title tokens matched", "quality tag score -20: WEB-DL"],
                risks=[],
            )
        ]
    )

    class FakeDownloader:
        calls: list[tuple[str, str, list[str]]] = []

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            self.calls.append((url, category, tags))
            return "0123456789abcdef0123456789abcdef01234567"

        async def list_torrents(self, category=None, tags=None):
            return []

    downloader = FakeDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    with _running_server(config_path) as base_url:
        preview_payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/enqueue",
            {"release_id": "mt:https://kp.m-team.cc/detail/99", "execute": "false"},
        )
        assert preview_payload["execute"] is False
        assert preview_payload["selected"]["release_id"] == "mt:https://kp.m-team.cc/detail/99"
        assert preview_payload["enqueued"] == 0
        assert [item["action"] for item in preview_payload["decisions"]] == ["qb.enqueue"]
        assert preview_payload["decisions"][0]["execute"] is False
        assert preview_payload["runtime_activity"]["managed_count"] == 0
        assert preview_payload["status"][0]["level"] == "ok"
        assert downloader.calls == []
        preview_row = store.get_intent(intent.intent_id)
        assert preview_row["selected_release_id"] is None
        assert preview_row["state"] == IntentState.CONFIRMATION_REQUIRED.value

        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/enqueue",
            {"release_id": "mt:https://kp.m-team.cc/detail/99", "execute": True},
        )

    assert payload["execute"] is True
    assert payload["selected"]["release_id"] == "mt:https://kp.m-team.cc/detail/99"
    assert payload["enqueued"] == 1
    assert any(item["action"] == "qb.enqueue" for item in payload["decisions"])
    assert downloader.calls == [
        (
            "https://tracker.example/download?id=99",
            "seed",
            ["seed-agent"],
        )
    ]
    row = store.get_intent(intent.intent_id)
    assert row["selected_release_id"] == "mt:https://kp.m-team.cc/detail/99"
    assert row["state"] == IntentState.ENQUEUED.value


def test_http_want_enqueue_preview_does_not_mutate_downloader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ResourceIntent(
        intent_id="douban_wanted:preview-only",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Preview Only 2025",
        kind=IntentKind.MOVIE,
        title="Preview Only",
        year=2025,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        state=IntentState.CONFIRMATION_REQUIRED,
    )
    store.upsert_intent(intent)
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/100",
                    site="mt",
                    title="Preview Only 2025 2160p Remux",
                    source_url="https://kp.m-team.cc/detail/100",
                    download_url="https://tracker.example/download?id=100",
                    size_bytes=40 * 1024**3,
                    seeders=30,
                    leechers=2,
                    discount=Discount.FREE,
                ),
                score=91,
                confidence=0.91,
                accepted=True,
                confirmation_required=False,
                reasons=["title tokens matched"],
                risks=[],
            )
        ]
    )

    class FakeDownloader:
        calls: list[str] = []
        list_calls = 0

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            self.calls.append(url)
            return "0123456789abcdef0123456789abcdef01234567"

        async def list_torrents(self, category=None, tags=None):
            self.list_calls += 1
            return []

    downloader = FakeDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/enqueue",
            {"release_id": "mt:https://kp.m-team.cc/detail/100"},
        )

    assert payload["execute"] is False
    assert payload["selected"]["release_id"] == "mt:https://kp.m-team.cc/detail/100"
    assert payload["enqueued"] == 0
    assert [item["action"] for item in payload["decisions"]] == ["qb.enqueue"]
    assert payload["decisions"][0]["execute"] is False
    assert payload["runtime_activity"]["managed_count"] == 0
    assert downloader.calls == []
    assert downloader.list_calls == 0
    assert not (tmp_path / "audit.jsonl").exists()
    row = store.get_intent(intent.intent_id)
    assert row["selected_release_id"] is None
    assert row["state"] == IntentState.CONFIRMATION_REQUIRED.value


def test_http_want_enqueue_failure_returns_actionable_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ResourceIntent(
        intent_id="douban_wanted:spider-noir",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Spider Noir 2026",
        kind=IntentKind.SHOW,
        title="Spider Noir",
        year=2026,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        state=IntentState.CONFIRMATION_REQUIRED,
    )
    store.upsert_intent(intent)
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/99",
                    site="mt",
                    title="Spider-Noir 2026 S01 2160p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/99",
                    download_url="https://tracker.example/download?id=99",
                    size_bytes=36 * 1024**3,
                    seeders=701,
                    leechers=3,
                    discount=Discount.FREE,
                ),
                score=59,
                confidence=0.59,
                accepted=False,
                confirmation_required=True,
                reasons=["title tokens matched", "quality tag score -20: WEB-DL"],
                risks=[],
            )
        ]
    )

    class FailingDownloader:
        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            raise RuntimeError("qB add response closed after request")

        async def list_torrents(self, category=None, tags=None):
            return []

    monkeypatch.setattr(cli, "build_downloader", lambda loaded: FailingDownloader())

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/enqueue",
            {"release_id": "mt:https://kp.m-team.cc/detail/99", "execute": True},
            expected_status=400,
        )

    assert payload["error"] == "qBittorrent enqueue batch failed"
    assert payload["execute"] is True
    assert payload["enqueued"] == 0
    assert [item["action"] for item in payload["decisions"]] == [
        "qb.enqueue.failed",
    ]
    assert "qB add response closed" in payload["decisions"][0]["reason"]
    assert payload["status"][0]["level"] == "warning"
    assert "qB add response closed" in payload["status"][0]["message"]


def test_http_config_section_preview_returns_diff_without_writing(
    tmp_path: Path,
) -> None:
    config_path = _write_minimal_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections/preview",
            {
                "section": "want_decision",
                "data": {
                    "confirmation_threshold": 0.7,
                    "auto_enqueue_threshold": 0.9,
                    "ambiguity_gap": 0.05,
                    "default_resolution": "2160p",
                    "preferred_languages": ["zh", "ja"],
                    "inbox_ref": "local/inbox/phase2.jsonl",
                },
            },
        )

    assert config_path.read_text(encoding="utf-8") == before
    assert payload["section"] == "want_decision"
    assert payload["data"]["default_resolution"] == "2160p"
    assert payload["status"] == [
        {"level": "ok", "message": "want_decision config preview ready"}
    ]
    assert "-  default_resolution: 1080p" in payload["diff"]
    assert "+  default_resolution: 2160p" in payload["diff"]
    assert "secret-token" not in json.dumps(payload)


def test_http_config_section_save_updates_search_and_source_refs_without_secrets(
    tmp_path: Path,
) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        search_payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "release_preferences",
                "data": {
                    "site_priority": {"mt": 30, "demo": 10},
                    "max_results_per_site": 12,
                    "prefer_free": True,
                    "reject_hr_by_default": False,
                    "quality_tag_scores": {
                        "remux": 20,
                        "dolby_vision": 15,
                        "webdl": -10,
                    },
                },
            },
        )
        sources_payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "want_sources",
                "data": {
                    "telegram": {
                        "enabled": True,
                        "secret_ref": "local/secrets/telegram.yaml",
                    },
                    "wechat_bridge": {
                        "enabled": False,
                        "secret_ref": "local/secrets/wechat-bridge.yaml",
                    },
                    "douban_wanted": {
                        "enabled": True,
                        "export_ref": "local/inbox/douban-wanted.json",
                        "user_name": "LancerC",
                        "max_pages": 2,
                    },
                    "subscription": {
                        "enabled": False,
                        "rules_ref": "config/subscriptions.yaml",
                    },
                },
            },
        )

    assert search_payload["data"]["site_priority"] == {"mt": 30, "demo": 10}
    assert search_payload["data"]["quality_tag_scores"] == {
        "remux": 20,
        "dolby_vision": 15,
        "webdl": -10,
    }
    assert sources_payload["data"]["telegram"]["enabled"] is True
    assert sources_payload["data"]["douban_wanted"]["user_name"] == "LancerC"
    assert sources_payload["data"]["douban_wanted"]["max_pages"] == 2
    saved = config_path.read_text(encoding="utf-8")
    assert "secret_ref: local/secrets/telegram.yaml" in saved
    assert "token:" not in saved
    assert "secret-token" not in saved


def test_http_config_section_save_updates_downloader_visual_fields(
    tmp_path: Path,
) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "download_client",
                "data": {
                    "type": "qbittorrent",
                    "target": "local",
                    "default_category": "seed",
                    "secret_ref": None,
                    "media_category_map": {
                        "movie": "movie",
                        "tv": "tv",
                        "anime": "anime",
                    },
                    "category_policies": [
                        {
                            "name": "seed",
                            "mode": "mutable",
                            "budget_pool": "downloads",
                            "delete_enabled": True,
                            "over_budget_behavior": "add_paused",
                            "tags": ["seed-agent"],
                        },
                        {
                            "name": "movie",
                            "mode": "add_only",
                            "budget_pool": "media",
                            "delete_enabled": False,
                            "over_budget_behavior": "add_paused",
                            "tags": ["seed-agent", "movie"],
                        },
                        {
                            "name": "tv",
                            "mode": "add_only",
                            "budget_pool": "media",
                            "delete_enabled": False,
                            "over_budget_behavior": "add_paused",
                            "tags": ["seed-agent", "tv"],
                        },
                        {
                            "name": "anime",
                            "mode": "add_only",
                            "budget_pool": "media",
                            "delete_enabled": False,
                            "over_budget_behavior": "add_paused",
                            "tags": ["seed-agent", "anime"],
                        },
                    ],
                    "budget_pools": [
                        {"name": "downloads", "max_size_tib": 1},
                        {"name": "media", "max_size_tib": 10},
                    ],
                },
            },
        )

    assert payload["data"]["media_category_map"] == {
        "movie": "movie",
        "tv": "tv",
        "anime": "anime",
    }
    assert [item["name"] for item in payload["data"]["category_policies"]] == [
        "seed",
        "movie",
        "tv",
        "anime",
    ]
    saved = config_path.read_text(encoding="utf-8")
    assert "media_category_map:" in saved
    assert "anime: anime" in saved
    assert "max_size_tib: 10" in saved


def test_http_config_exposes_and_saves_section_yaml_without_splitting_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_minimal_config(tmp_path)
    monkeypatch.setenv("SEED_AGENT_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("SEED_AGENT_PRUNE", "true")

    with _running_server(config_path) as base_url:
        initial = _request_json(base_url, "GET", "/api/config")
        preview = _request_json(
            base_url,
            "POST",
            "/api/config/sections/yaml/preview",
            {
                "section": "release_preferences",
                "yaml": """
release_preferences:
  site_priority:
    mt: 30
  max_results_per_site: 6
  prefer_free: true
  reject_hr_by_default: true
  quality_tag_scores:
    remux: 20
    webdl: -10
""".strip(),
            },
        )
        saved = _request_json(
            base_url,
            "POST",
            "/api/config/sections/yaml",
            {
                "section": "release_preferences",
                "yaml": """
release_preferences:
  site_priority:
    mt: 30
  max_results_per_site: 6
  prefer_free: true
  reject_hr_by_default: true
  quality_tag_scores:
    remux: 20
    webdl: -10
""".strip(),
            },
        )

    assert "section_yamls" in initial
    assert "release_preferences:" in initial["section_yamls"]["release_preferences"]
    assert "scheduler:" in initial["section_yamls"]["scheduler"]
    assert initial["sections"]["scheduler"]["intent_search_mode"] == "daily"
    assert initial["scheduler_environment_overrides"] == {
        "interval_minutes": 30,
        "prune_enabled": True,
    }
    assert "config_yaml" in initial
    assert preview["section"] == "release_preferences"
    assert "+  max_results_per_site: 6" in preview["diff"]
    assert "release_preferences:" in preview["yaml"]
    assert saved["data"]["max_results_per_site"] == 6
    assert saved["data"]["quality_tag_scores"] == {"remux": 20, "webdl": -10}
    assert "max_results_per_site: 6" in config_path.read_text(encoding="utf-8")


def test_http_config_section_save_rejects_invalid_threshold_order(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "want_decision",
                "data": {
                    "confirmation_threshold": 0.95,
                    "auto_enqueue_threshold": 0.9,
                    "ambiguity_gap": 0.05,
                    "default_resolution": "1080p",
                    "preferred_languages": ["zh"],
                    "inbox_ref": "local/inbox/intents.jsonl",
                },
            },
            expected_status=400,
        )

    assert payload["status"][0]["level"] == "warning"
    assert "auto_enqueue_threshold" in payload["status"][0]["message"]


def test_http_state_summary_reports_local_state_counts(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    store.upsert_candidate(
        "candidate-1",
        "mteam",
        "Queued Candidate",
        LifecycleState.ENQUEUED,
        score=80,
        torrent_hash="hash-1",
    )
    store.upsert_candidate(
        "candidate-2",
        "mteam",
        "Scored Candidate",
        LifecycleState.SCORED,
        score=75,
        torrent_hash=None,
    )
    store._upsert_torrent_runtime(  # type: ignore[attr-defined]
        "hash-1",
        paused_at=None,
        uploaded_bytes=10,
        downloaded_bytes=20,
        upspeed_bps=0,
        dlspeed_bps=0,
        no_upload_since_at=None,
        seen_at=datetime.now(UTC).isoformat(),
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(base_url, "GET", "/api/state/summary")

    assert payload["state_exists"] is True
    assert payload["candidates"] == {
        "total": 2,
        "by_state": {"enqueued": 1, "scored": 1},
    }
    assert payload["torrent_runtime"] == {"total": 1}
    assert payload["release_candidates"] == {"total": 0}


def test_http_health_reports_recent_heartbeat(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    heartbeat_path = tmp_path / "state" / "schedule-heartbeat.json"
    heartbeat_path.parent.mkdir()
    heartbeat_path.write_text(
        json.dumps(
            {
                "command": "schedule-run",
                "cycle": 4,
                "updated_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    with _running_server(config_path) as base_url:
        payload = _request_json(base_url, "GET", "/api/health")

    assert payload["status"] == "ok"
    assert payload["heartbeat_exists"] is True
    assert payload["heartbeat"]["cycle"] == 4
    assert payload["age_minutes"] < 10


def test_http_pools_reports_configured_budget_pools_without_live_polling(
    tmp_path: Path,
) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(base_url, "GET", "/api/pools")

    assert payload["default_category"] == "seed"
    assert payload["budget_pools"] == [
        {
            "name": "downloads",
            "max_size_tib": 1.0,
            "category_policies": [
                {
                    "name": "seed",
                    "mode": "mutable",
                    "delete_enabled": True,
                    "over_budget_behavior": "add_paused",
                }
            ],
        }
    ]
    assert payload["runtime"]["available"] is False


def test_http_root_serves_static_ui(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        connection = HTTPConnection(base_url)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()

    assert response.status == 200
    assert "Seed Agent Settings" in body
    assert "/static/app.js" in body


def test_http_tracker_validate_returns_tracker_local_status(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/trackers/validate",
            {"type": None, "name": ""},
        )

    assert {"level": "warning", "message": "type is required"} in payload["status"]
    assert {"level": "warning", "message": "tracker name is required"} in payload["status"]


def test_http_tracker_validate_reports_api_mode_missing_key_ref(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/trackers/validate",
            {
                "type": "mteam",
                "name": "mt",
                "enabled": True,
                "rss_url": "",
                "discovery_mode": "api",
                "api_key_ref": None,
                "api_key_value": None,
                "auth_header": "x-api-key",
                "cookie_ref": None,
            },
        )

    assert {
        "level": "warning",
        "message": "api_key_ref is required when discovery_mode=api",
    } in payload["status"]


def test_http_tracker_save_returns_json_error_for_invalid_draft(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/trackers",
            {
                "type": "mteam",
                "name": "mt",
                "enabled": True,
                "rss_url": "",
                "discovery_mode": "api",
                "api_key_ref": None,
                "api_key_value": None,
                "auth_header": "x-api-key",
                "cookie_ref": None,
            },
            expected_status=400,
        )

    assert payload["status"][0]["level"] == "warning"
    assert "api_key_ref is required" in payload["status"][0]["message"]


def test_http_tracker_save_writes_config_and_secret(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/trackers",
            {
                "type": "mteam",
                "name": "mt",
                "enabled": True,
                "rss_url": "https://rss.example/feed",
                "discovery_mode": "api",
                "api_key_ref": "local/secrets/mt.api-key",
                "api_key_value": "secret-token",
            },
        )

    assert payload["tracker"]["name"] == "mt"
    assert "secret-token" not in config_path.read_text(encoding="utf-8")
    assert (tmp_path / "local" / "secrets" / "mt.api-key").read_text(
        encoding="utf-8"
    ) == "secret-token"


def test_http_tracker_save_rejects_secret_ref_outside_local_secrets(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    outside_ref = f"../{tmp_path.name}-outside.api-key"
    outside_path = tmp_path.parent / f"{tmp_path.name}-outside.api-key"
    before = config_path.read_text(encoding="utf-8")

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/trackers",
            {
                "type": "mteam",
                "name": "mt",
                "enabled": True,
                "rss_url": "https://rss.example/feed",
                "discovery_mode": "api",
                "api_key_ref": outside_ref,
                "api_key_value": "secret-token",
            },
            expected_status=400,
        )

    assert "local/secrets" in payload["status"][0]["message"]
    assert config_path.read_text(encoding="utf-8") == before
    assert not outside_path.exists()


def test_http_tracker_save_generates_api_key_ref_when_secret_value_is_provided(
    tmp_path: Path,
) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/trackers",
            {
                "type": "mteam",
                "name": "mt ui",
                "enabled": True,
                "rss_url": "",
                "discovery_mode": "api",
                "api_key_ref": None,
                "api_key_value": "secret-token",
                "auth_header": "x-api-key",
                "cookie_ref": None,
            },
        )

    assert payload["tracker"]["api_key_ref"] == "local/secrets/mt-ui.api-key"
    assert (tmp_path / "local" / "secrets" / "mt-ui.api-key").read_text(
        encoding="utf-8"
    ) == "secret-token"


def _write_minimal_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites: []
pt_filters:
  discounts: [free]
  min_left_time_minutes: 120
  min_leechers: 1
  target_seed_leecher_ratio: 100
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
  target: local
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: [seed-agent]
  budget_pools:
    - name: downloads
      max_size_tib: 1
  secret_ref: null
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""".lstrip(),
        encoding="utf-8",
    )
    return config_path


class _TestServer(TCPServer):
    allow_reuse_address = True


class _running_server:
    def __init__(self, config_path: Path) -> None:
        self._server = _TestServer(("127.0.0.1", 0), make_handler(config_path))
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        host, port = self._server.server_address
        return f"{host}:{port}"

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _request_json(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    expected_status: int = 200,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    connection = HTTPConnection(base_url)
    raw_body = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = dict(headers or {})
    if raw_body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=raw_body, headers=request_headers)
    response = connection.getresponse()
    data = json.loads(response.read().decode("utf-8"))
    connection.close()
    assert response.status == expected_status, data
    return data
