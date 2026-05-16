from __future__ import annotations

import json
import sqlite3
from asyncio import run
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from seed_agent.actions.pt import _discover_site_candidates, score_candidates
from seed_agent.config import SiteConfig, load_config
from seed_agent.web.settings import (
    TrackerDraft,
    build_tracker_status,
    save_tracker_draft,
    tracker_draft_to_config,
)

STATIC_ROOT = Path(__file__).parent / "static"


def make_handler(config_path: Path) -> type[BaseHTTPRequestHandler]:
    resolved_config_path = config_path
    root = _repo_root_for_config(resolved_config_path)

    class SeedAgentWebHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/config":
                config = load_config(resolved_config_path)
                self._send_json(
                    {
                        "config_path": str(resolved_config_path),
                        "trackers": [_tracker_summary(site, root) for site in config.sites],
                    }
                )
                return
            if self.path == "/api/state/summary":
                self._send_json(_state_summary_payload(resolved_config_path, root))
                return
            if self.path == "/api/pools":
                self._send_json(_pools_payload(resolved_config_path))
                return
            if self.path == "/api/health":
                self._send_json(_health_payload(root))
                return
            if self.path == "/":
                self._send_static("index.html")
                return
            if self.path.startswith("/static/"):
                self._send_static(self.path.removeprefix("/static/"))
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            try:
                self._do_post()
            except Exception as exc:
                self._send_json(
                    {"status": [{"level": "warning", "message": _friendly_error(exc)}]},
                    status=HTTPStatus.BAD_REQUEST,
                )

        def _do_post(self) -> None:
            if self.path == "/api/trackers/validate":
                draft = TrackerDraft.model_validate(self._read_json())
                self._send_json({"status": build_tracker_status(draft, root)})
                return
            if self.path == "/api/trackers":
                draft = TrackerDraft.model_validate(self._read_json())
                site = save_tracker_draft(resolved_config_path, draft)
                self._send_json(
                    {
                        "tracker": _tracker_summary(site, root),
                        "status": build_tracker_status(draft, root),
                    }
                )
                return
            if self.path == "/api/trackers/site-probe":
                draft = TrackerDraft.model_validate(self._read_json())
                self._send_json(_site_probe_payload(draft, resolved_config_path, root))
                return
            if self.path == "/api/trackers/dry-run":
                draft = TrackerDraft.model_validate(self._read_json())
                self._send_json(_dry_run_payload(draft, resolved_config_path, root))
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                raise ValueError("request body must be a JSON object")
            return loaded

        def _send_json(
            self,
            payload: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self._send_bytes(raw, content_type="application/json", status=status)

        def _send_bytes(
            self,
            payload: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_static(self, asset_name: str) -> None:
            if "/" in asset_name or "\\" in asset_name:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            path = STATIC_ROOT / asset_name
            if not path.exists() or not path.is_file():
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = _content_type_for(path)
            self._send_bytes(path.read_bytes(), content_type=content_type)

    return SeedAgentWebHandler


def serve(config_path: Path, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(config_path))
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _tracker_summary(site: SiteConfig, root: Path) -> dict[str, Any]:
    api_key_ref = site.api_key_ref
    return {
        "name": site.name,
        "type": site.type,
        "enabled": site.enabled,
        "rss_url": site.rss_url,
        "discovery_mode": site.discovery_mode,
        "api_key_ref": api_key_ref,
        "cookie_ref": site.cookie_ref,
        "has_api_key": bool(api_key_ref and _resolve_repo_path(api_key_ref, root).exists()),
    }


def _site_probe_payload(
    draft: TrackerDraft,
    config_path: Path,
    root: Path,
) -> dict[str, Any]:
    status = build_tracker_status(draft, root)
    if _has_blocking_tracker_status(status):
        return {
            "status": status,
            "summary": {"command": "site-probe", "discovered": 0},
        }
    try:
        site = tracker_draft_to_config(draft)
        config = load_config(config_path)
        candidates = run(_discover_site_candidates(site, config.config_dir))
    except Exception as exc:
        return {
            "status": [*status, {"level": "warning", "message": _friendly_error(exc)}],
            "summary": {"command": "site-probe", "discovered": 0},
        }
    return {
        "status": [
            *status,
            {"level": "ok", "message": f"site-probe: {len(candidates)} discovered"},
        ],
        "summary": {"command": "site-probe", "discovered": len(candidates)},
    }


def _dry_run_payload(
    draft: TrackerDraft,
    config_path: Path,
    root: Path,
) -> dict[str, Any]:
    status = build_tracker_status(draft, root)
    if _has_blocking_tracker_status(status):
        return {
            "status": status,
            "summary": {"command": "dry-run", "discovered": 0, "accepted": 0},
        }
    try:
        site = tracker_draft_to_config(draft)
        config = load_config(config_path)
        candidates = run(_discover_site_candidates(site, config.config_dir))
        scored = score_candidates(candidates, config.discovery, config.scoring)
    except Exception as exc:
        return {
            "status": [*status, {"level": "warning", "message": _friendly_error(exc)}],
            "summary": {"command": "dry-run", "discovered": 0, "accepted": 0},
        }
    accepted = sum(1 for item in scored if item.accepted)
    return {
        "status": [
            *status,
            {"level": "ok", "message": f"dry-run: {accepted} accepted"},
        ],
        "summary": {
            "command": "dry-run",
            "discovered": len(candidates),
            "accepted": accepted,
        },
    }


def _state_summary_payload(config_path: Path, root: Path) -> dict[str, Any]:
    state_path = _state_db_path(root)
    payload: dict[str, Any] = {
        "config_path": str(config_path),
        "state_path": str(state_path),
        "state_exists": state_path.exists(),
        "candidates": {"total": 0, "by_state": {}},
        "intents": {"total": 0, "by_state": {}},
        "release_candidates": {"total": 0},
        "torrent_runtime": {"total": 0},
    }
    if not state_path.exists():
        return payload
    with sqlite3.connect(state_path) as conn:
        payload["candidates"] = _table_state_counts(conn, "candidates", "state")
        payload["intents"] = _table_state_counts(conn, "intents", "state")
        payload["release_candidates"] = {"total": _table_count(conn, "release_candidates")}
        payload["torrent_runtime"] = {"total": _table_count(conn, "torrent_runtime")}
    return payload


def _pools_payload(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    policies_by_pool: dict[str, list[dict[str, Any]]] = {}
    for policy in config.downloader.category_policies:
        policies_by_pool.setdefault(policy.budget_pool, []).append(
            {
                "name": policy.name,
                "mode": policy.mode,
                "delete_enabled": policy.delete_enabled,
                "over_budget_behavior": policy.over_budget_behavior,
            }
        )
    return {
        "budget_pools": [
            {
                "name": pool.name,
                "max_size_tib": pool.max_size_tib,
                "category_policies": policies_by_pool.get(pool.name, []),
            }
            for pool in config.downloader.budget_pools
        ],
        "default_category": config.downloader.default_category,
        "runtime": {
            "available": False,
            "reason": "live downloader polling is not exposed by the read-only web API",
        },
    }


def _health_payload(root: Path) -> dict[str, Any]:
    heartbeat_path = root / "state" / "schedule-heartbeat.json"
    payload: dict[str, Any] = {
        "status": "unknown",
        "heartbeat_file": str(heartbeat_path),
        "heartbeat_exists": heartbeat_path.exists(),
    }
    if not heartbeat_path.exists():
        payload["status"] = "missing_heartbeat"
        return payload
    try:
        heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        payload.update({"status": "invalid_heartbeat", "error": exc.msg})
        return payload
    updated_at = _parse_iso_datetime(heartbeat.get("updated_at"))
    if updated_at is None:
        payload.update({"status": "invalid_heartbeat", "heartbeat": heartbeat})
        return payload
    age_minutes = (datetime.now(UTC) - updated_at).total_seconds() / 60
    payload.update(
        {
            "status": "ok" if age_minutes <= 90 else "stale",
            "age_minutes": round(age_minutes, 2),
            "max_staleness_minutes": 90,
            "heartbeat": heartbeat,
        }
    )
    return payload


def _state_db_path(root: Path) -> Path:
    return root / ".seed-agent" / "state.db"


def _table_state_counts(
    conn: sqlite3.Connection,
    table_name: str,
    state_column: str,
) -> dict[str, Any]:
    if not _table_exists(conn, table_name):
        return {"total": 0, "by_state": {}}
    rows = conn.execute(
        f"SELECT {state_column}, COUNT(*) FROM {table_name} GROUP BY {state_column}"
    ).fetchall()
    by_state = {str(state): int(count) for state, count in rows}
    return {"total": sum(by_state.values()), "by_state": by_state}


def _table_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _repo_root_for_config(config_path: Path) -> Path:
    config_dir = config_path.resolve().parent
    if config_dir.name == "config":
        return config_dir.parent
    return config_dir


def _resolve_repo_path(path_value: str, root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return root / path


def _content_type_for(path: Path) -> str:
    if path.suffix == ".html":
        return "text/html; charset=utf-8"
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    if path.suffix == ".js":
        return "text/javascript; charset=utf-8"
    return "application/octet-stream"


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if "api_key_ref is required when discovery_mode=api" in message:
        return "api_key_ref is required when discovery_mode=api"
    if "type is required" in message:
        return "type is required"
    if "tracker name is required" in message:
        return "tracker name is required"
    return message


def _has_blocking_tracker_status(status: list[dict[str, str]]) -> bool:
    blocking_messages = {
        "type is required",
        "tracker name is required",
        "api_key_ref is required when discovery_mode=api",
    }
    return any(item["message"] in blocking_messages for item in status)
