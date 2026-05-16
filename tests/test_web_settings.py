from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from socketserver import TCPServer
from threading import Thread
from typing import Any

from seed_agent.models import LifecycleState
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
sites: []
discovery:
  discounts: [free]
  min_left_time_minutes: 120
  min_leechers: 1
  max_seeders: 100
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
cleanup:
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
            "sites: []",
            """
sites:
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
    assert payload["sections"]["downloader"]["target"] == "local"
    assert payload["sections"]["intent"]["inbox_ref"] == "local/inbox/intents.jsonl"
    assert payload["trackers"][0]["has_api_key"] is True
    assert "secret-token" not in json.dumps(payload)


def test_http_config_section_save_updates_safe_phase2_fields(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "intent",
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

    assert payload["section"] == "intent"
    assert payload["status"] == [{"level": "ok", "message": "intent config saved"}]
    saved = config_path.read_text(encoding="utf-8")
    assert "default_resolution: 2160p" in saved
    assert "local/inbox/phase2.jsonl" in saved
    assert "secret-token" not in saved


def test_http_config_section_save_rejects_invalid_threshold_order(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            "/api/config/sections",
            {
                "section": "intent",
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
sites: []
discovery:
  discounts: [free]
  min_left_time_minutes: 120
  min_leechers: 1
  max_seeders: 100
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
cleanup:
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
) -> dict[str, Any]:
    connection = HTTPConnection(base_url)
    raw_body = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if raw_body is not None else {}
    connection.request(method, path, body=raw_body, headers=headers)
    response = connection.getresponse()
    data = json.loads(response.read().decode("utf-8"))
    connection.close()
    assert response.status == expected_status, data
    return data
