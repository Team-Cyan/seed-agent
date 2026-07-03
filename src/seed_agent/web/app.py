from __future__ import annotations

import json
import sqlite3
from asyncio import run
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from seed_agent.actions.intent import (
    enqueue_intent,
    ingest_events,
    rank_intent,
    search_intent,
)
from seed_agent.actions.pt import _discover_site_candidates, score_candidates
from seed_agent.actions.qb import MutationBatchError
from seed_agent.audit import redact_payload
from seed_agent.config import (
    IntentConfig as SeedIntentConfig,
)
from seed_agent.config import (
    SearchConfig,
    SiteConfig,
    load_config,
)
from seed_agent.models import IntentSource, RankedRelease, ReleaseCandidate
from seed_agent.quality_tags import matching_quality_tag_groups
from seed_agent.search.base import SearchProvider
from seed_agent.state import StateStore
from seed_agent.web.settings import (
    ConfigSectionDraft,
    ConfigSectionYamlDraft,
    TrackerDraft,
    build_tracker_status,
    config_section_yaml_fragment,
    config_section_yamls_payload,
    config_sections_payload,
    normalized_config_yaml,
    preview_config_section,
    preview_config_section_yaml,
    save_config_section,
    save_config_section_yaml,
    save_tracker_draft,
    tracker_draft_to_config,
)

STATIC_ROOT = Path(__file__).parent / "static"
SCHEDULE_BACKOFF_FILE = "schedule-backoff.json"


def make_handler(config_path: Path) -> type[BaseHTTPRequestHandler]:
    resolved_config_path = config_path
    root = _repo_root_for_config(resolved_config_path)

    class SeedAgentWebHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            want_candidates_id = _want_subresource_intent_id(self.path, "candidates")
            if want_candidates_id is not None:
                payload, status = _want_candidates_payload(root, want_candidates_id)
                self._send_json(payload, status=status)
                return
            if self.path == "/api/config":
                config = load_config(resolved_config_path)
                self._send_json(
                    {
                        "config_path": str(resolved_config_path),
                        **_runtime_provenance(root),
                        "trackers": [_tracker_summary(site, root) for site in config.tracker_sites],
                        "sections": config_sections_payload(config),
                        "section_yamls": config_section_yamls_payload(config),
                        "config_yaml": normalized_config_yaml(config),
                    }
                )
                return
            if self.path == "/api/state/summary":
                self._send_json(_state_summary_payload(resolved_config_path, root))
                return
            if self.path == "/api/pools":
                self._send_json(_pools_payload(resolved_config_path))
                return
            if self.path == "/api/wants":
                self._send_json(_wants_payload(root))
                return
            if self.path == "/api/health":
                self._send_json(_health_payload(root))
                return
            if self.path == "/":
                self._send_static("index.html")
                return
            if self.path == "/favicon.ico":
                self._send_bytes(b"", content_type="image/x-icon")
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
            if self.path == "/api/config/sections":
                draft = ConfigSectionDraft.model_validate(self._read_json())
                saved = save_config_section(resolved_config_path, draft)
                updated_config = load_config(resolved_config_path)
                self._send_json(
                    {
                        "section": draft.section,
                        "data": saved,
                        "yaml": config_section_yaml_fragment(draft.section, saved),
                        "section_yamls": config_section_yamls_payload(updated_config),
                        "config_yaml": normalized_config_yaml(updated_config),
                        "status": [{"level": "ok", "message": f"{draft.section} config saved"}],
                    }
                )
                return
            if self.path == "/api/config/sections/preview":
                draft = ConfigSectionDraft.model_validate(self._read_json())
                preview = preview_config_section(resolved_config_path, draft)
                self._send_json(
                    {
                        **preview,
                        "status": [
                            {
                                "level": "ok",
                                "message": f"{draft.section} config preview ready",
                            }
                        ],
                    }
                )
                return
            if self.path == "/api/config/sections/yaml":
                draft = ConfigSectionYamlDraft.model_validate(self._read_json())
                saved = save_config_section_yaml(resolved_config_path, draft)
                updated_config = load_config(resolved_config_path)
                self._send_json(
                    {
                        **saved,
                        "section_yamls": config_section_yamls_payload(updated_config),
                        "config_yaml": normalized_config_yaml(updated_config),
                        "status": [{"level": "ok", "message": f"{draft.section} YAML saved"}],
                    }
                )
                return
            if self.path == "/api/config/sections/yaml/preview":
                draft = ConfigSectionYamlDraft.model_validate(self._read_json())
                preview = preview_config_section_yaml(resolved_config_path, draft)
                self._send_json(
                    {
                        **preview,
                        "status": [
                            {
                                "level": "ok",
                                "message": f"{draft.section} YAML preview ready",
                            }
                        ],
                    }
                )
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
            if self.path == "/api/wants/search":
                self._send_json(
                    _search_wants_payload(self._read_json(), resolved_config_path, root)
                )
                return
            if self.path == "/api/wants/sync":
                self._send_json(_sync_wants_payload(resolved_config_path, root))
                return
            want_search_id = _want_subresource_intent_id(self.path, "search")
            if want_search_id is not None:
                payload, status = _search_single_want_payload(
                    resolved_config_path,
                    root,
                    want_search_id,
                )
                self._send_json(payload, status=status)
                return
            want_enqueue_id = _want_subresource_intent_id(self.path, "enqueue")
            if want_enqueue_id is not None:
                payload, status = _enqueue_want_payload(
                    self._read_json(),
                    resolved_config_path,
                    root,
                    want_enqueue_id,
                )
                self._send_json(payload, status=status)
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
        candidates = run(_discover_site_candidates(site, config.config_dir, config.pt_filters))
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
        candidates = run(_discover_site_candidates(site, config.config_dir, config.pt_filters))
        scored = score_candidates(candidates, config.pt_filters, config.pt_scoring)
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
        **_runtime_provenance(root),
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
    for policy in config.download_client.category_policies:
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
            for pool in config.download_client.budget_pools
        ],
        "default_category": config.download_client.default_category,
        "runtime": {
            "available": False,
            "reason": "live downloader polling is not exposed by the read-only web API",
        },
    }


def _wants_payload(root: Path) -> dict[str, Any]:
    state_path = _state_db_path(root)
    payload: dict[str, Any] = {
        "state_path": str(state_path),
        "state_exists": state_path.exists(),
        "total": 0,
        "items": [],
    }
    if not state_path.exists():
        return payload
    store = StateStore(state_path)
    with sqlite3.connect(state_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "intents"):
            return payload
        release_counts = _intent_release_counts(conn)
        rows = conn.execute(
            """
            SELECT
                intent_id,
                source,
                raw_text,
                title,
                kind,
                state,
                normalized_json,
                selected_release_id,
                created_at,
                updated_at
            FROM intents
            ORDER BY created_at DESC, intent_id ASC
            LIMIT 500
            """
        ).fetchall()
    items = []
    for row in rows:
        if str(row["source"]) == IntentSource.MANUAL.value:
            continue
        intent_id = str(row["intent_id"])
        items.append(
            _want_item(
                dict(row),
                release_counts.get(intent_id, {}),
                store.list_intent_source_evidence(intent_id),
            )
        )
    payload["total"] = len(items)
    payload["items"] = items
    return payload


def _search_wants_payload(body: dict[str, Any], config_path: Path, root: Path) -> dict[str, Any]:
    backoff = _schedule_backoff_status(root)
    if backoff.get("active"):
        return {
            "synced": 0,
            "searched": 0,
            "skipped_by_backoff": True,
            "schedule_backoff": backoff,
            "status": [
                {
                    "level": "warning",
                    "message": "M-Team backoff active; skipped Want List search",
                }
            ],
        }
    sync_payload = _sync_wants_payload(config_path, root)
    state_path = _state_db_path(root)
    if not state_path.exists():
        return {"searched": 0, "status": [{"level": "ok", "message": "no wants"}]}
    payload = _wants_payload(root)
    items = _filter_searchable_want_items(_filter_want_items(payload["items"], body))
    config = load_config(config_path)
    store = StateStore(state_path)
    providers = _build_want_search_providers(config)
    searched = run(
        _search_want_items(
            items,
            store,
            providers,
            config.want_decision,
            config.release_preferences,
        )
    )
    return {
        "synced": sync_payload["ingested"],
        "searched": searched,
        "status": [{"level": "ok", "message": f"searched {searched} wants"}],
    }


def _search_single_want_payload(
    config_path: Path,
    root: Path,
    intent_id: str,
) -> tuple[dict[str, Any], HTTPStatus]:
    state_path = _state_db_path(root)
    if not state_path.exists():
        return {"error": "state db not found"}, HTTPStatus.NOT_FOUND
    store = StateStore(state_path)
    row = store.get_intent(intent_id)
    if row is None:
        return {"error": "want not found"}, HTTPStatus.NOT_FOUND
    backoff = _schedule_backoff_status(root)
    if backoff.get("active"):
        return {
            "searched": 0,
            "skipped": 1,
            "skipped_by_backoff": True,
            "schedule_backoff": backoff,
            "status": [
                {
                    "level": "warning",
                    "message": "M-Team backoff active; skipped Want List search",
                }
            ],
        }, HTTPStatus.OK
    item = _want_item(
        row,
        {"release_count": len(store.list_release_candidates(intent_id))},
        store.list_intent_source_evidence(intent_id),
    )
    if not _want_searchable(item):
        return {
            "searched": 0,
            "skipped": 1,
            "status": [{"level": "ok", "message": "already queued; skipped search"}],
        }, HTTPStatus.OK
    config = load_config(config_path)
    searched = run(
        _search_want_items(
            [item],
            store,
            _build_want_search_providers(config),
            config.want_decision,
            config.release_preferences,
        )
    )
    return {
        "searched": searched,
        "skipped": 0,
        "status": [{"level": "ok", "message": f"searched {searched} want"}],
    }, HTTPStatus.OK


def _sync_wants_payload(config_path: Path, root: Path) -> dict[str, Any]:
    config = load_config(config_path)
    state_path = _state_db_path(root)
    store = StateStore(state_path)
    events = _read_configured_want_source_events(config)
    ingested = ingest_events(events, store)
    payload = _wants_payload(root)
    return {
        "ingested": len(ingested),
        "total": payload["total"],
        "status": [
            {
                "level": "ok",
                "message": f"synced {len(ingested)} configured wants",
            }
        ],
    }


def _want_subresource_intent_id(path: str, action: str) -> str | None:
    parsed_path = urlparse(path).path
    prefix = "/api/wants/"
    suffix = f"/{action}"
    if not parsed_path.startswith(prefix) or not parsed_path.endswith(suffix):
        return None
    raw_intent_id = parsed_path[len(prefix) : -len(suffix)]
    if not raw_intent_id:
        return None
    return unquote(raw_intent_id)


def _want_candidates_payload(root: Path, intent_id: str) -> tuple[dict[str, Any], HTTPStatus]:
    state_path = _state_db_path(root)
    if not state_path.exists():
        return {"error": "state db not found"}, HTTPStatus.NOT_FOUND
    store = StateStore(state_path)
    row = store.get_intent(intent_id)
    if row is None:
        return {"error": "want not found"}, HTTPStatus.NOT_FOUND
    ranked = [_ranked_release_from_row(item) for item in store.list_release_candidates(intent_id)]
    candidates = [_want_candidate_item(item, row.get("selected_release_id")) for item in ranked]
    candidates.sort(
        key=lambda item: (
            0 if item["matches_requirements"] else 1,
            -int(item["score"] or 0),
            str(item["title"]),
        )
    )
    return {
        "intent": _want_item(
            row,
            {"release_count": len(candidates)},
            store.list_intent_source_evidence(intent_id),
        ),
        "total": len(candidates),
        "items": candidates,
    }, HTTPStatus.OK


def _enqueue_want_payload(
    body: dict[str, Any],
    config_path: Path,
    root: Path,
    intent_id: str,
) -> tuple[dict[str, Any], HTTPStatus]:
    from seed_agent.cli import (
        _build_release_download_resolver,
        _default_category_policy,
        _enqueue_pause_reasons,
        _enqueue_runtime_context,
        _intent_category_policy,
        _NullDownloader,
        _pool_usage_item_summary,
        _ranked_release_summary,
        _runtime_activity_summary,
        _write_audit_decisions,
    )

    release_id = str(body.get("release_id") or "").strip()
    if not release_id:
        return {"error": "release_id is required"}, HTTPStatus.BAD_REQUEST
    execute = _truthy_execute(body.get("execute"))
    store = StateStore(_state_db_path(root))
    config = load_config(config_path)
    decisions = []
    try:
        default_policy = _default_category_policy(config)
        if execute:
            downloader, live_torrents, paused, pool_usage, missing_reconciled = (
                _enqueue_runtime_context(
                    config,
                    store=store,
                    execute=execute,
                )
            )
            pause_reasons = _enqueue_pause_reasons(config, live_torrents, pool_usage)
        else:
            downloader = _NullDownloader()
            live_torrents = []
            paused = False
            pool_usage = None
            missing_reconciled = 0
            pause_reasons = []
        release_resolver = _build_release_download_resolver(config) if execute else None
        intent, ranked, enqueue_decisions = run(
            enqueue_intent(
                intent_id,
                store,
                downloader,
                default_policy,
                execute,
                paused=paused,
                pool_usage=pool_usage,
                pause_reasons=pause_reasons,
                release_resolver=release_resolver,
                policy_resolver=lambda intent: _intent_category_policy(config, intent),
                release_id=release_id,
            )
        )
        decisions.extend(enqueue_decisions)
        if execute:
            _write_audit_decisions(config, decisions)
    except ValueError as exc:
        return {"error": str(exc)}, HTTPStatus.BAD_REQUEST
    except MutationBatchError as exc:
        decisions.extend(exc.decisions)
        _write_audit_decisions(config, decisions)
        failed_reasons = [
            item.reason for item in decisions if item.action.endswith(".failed")
        ]
        message = failed_reasons[-1] if failed_reasons else str(exc)
        return {
            "error": str(exc),
            "execute": execute,
            "enqueued": _executed_enqueue_count(decisions),
            "decisions": [_decision_summary_payload(item) for item in decisions],
            "status": [
                {
                    "level": "warning",
                    "message": message,
                }
            ],
        }, HTTPStatus.BAD_REQUEST

    payload: dict[str, Any] = {
        "execute": execute,
        "intent": _want_item(
            store.get_intent(intent.intent_id) or {},
            {"release_count": len(store.list_release_candidates(intent.intent_id))},
            store.list_intent_source_evidence(intent.intent_id),
        ),
        "selected": _ranked_release_summary(ranked),
        "enqueued": _executed_enqueue_count(decisions),
        "decisions": [_decision_summary_payload(item) for item in decisions],
        "runtime_activity": _runtime_activity_summary(live_torrents),
        "missing_from_qb_reconciled": missing_reconciled,
        "status": [
            {
                "level": "ok",
                "message": "已加入 qB" if execute else "入队试运行完成",
            }
        ],
    }
    if pool_usage is not None:
        payload["default_pool_usage"] = _pool_usage_item_summary(pool_usage)
        payload["enqueue_paused_by_pool_policy"] = paused
    if pause_reasons:
        payload["enqueue_paused_reasons"] = pause_reasons
    return payload, HTTPStatus.OK


def _truthy_execute(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def _executed_enqueue_count(decisions: list[Any]) -> int:
    return sum(
        1
        for item in decisions
        if item.action == "qb.enqueue" and bool(getattr(item, "execute", False))
    )


def _read_configured_want_source_events(config) -> list[Any]:
    from seed_agent.cli import _read_configured_source_events

    return _read_configured_source_events(config)


async def _search_want_items(
    items: list[dict[str, Any]],
    store: StateStore,
    providers: list[SearchProvider],
    intent_config: SeedIntentConfig,
    search_config: SearchConfig,
) -> int:
    searched = 0
    for item in items:
        intent_id = str(item.get("intent_id") or "")
        if not intent_id:
            continue
        searched_intent, _, _ = await search_intent(intent_id, store, providers)
        rank_intent(searched_intent.intent_id, store, intent_config, search_config)
        searched += 1
    return searched


def _build_want_search_providers(config) -> list[SearchProvider]:
    from seed_agent.cli import _build_search_providers

    return _build_search_providers(config)


def _filter_want_items(
    items: list[dict[str, Any]],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    source = str(filters.get("source") or "all")
    media_type = str(filters.get("media_type") or "all")
    filtered = items
    if source != "all":
        filtered = [item for item in filtered if source in set(item.get("source_keys") or [])]
    if media_type != "all":
        filtered = [item for item in filtered if item.get("media_type") == media_type]
    return filtered


def _filter_searchable_want_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if _want_searchable(item)]


def _want_searchable(item: dict[str, Any]) -> bool:
    state = str(item.get("state") or "")
    if state == "enqueued":
        return False
    if item.get("selected_release_id"):
        return False
    return True


def _intent_release_counts(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if not _table_exists(conn, "release_candidates"):
        return {}
    rows = conn.execute(
        """
        SELECT
            intent_id,
            COUNT(*) AS release_count,
            MAX(score) AS best_candidate_score,
            MAX(accepted) AS has_accepted,
            MAX(confirmation_required) AS has_confirmation_required
        FROM release_candidates
        GROUP BY intent_id
        """
    ).fetchall()
    return {
        str(row["intent_id"]): {
            "release_count": int(row["release_count"] or 0),
            "best_candidate_score": int(row["best_candidate_score"])
            if row["best_candidate_score"] is not None
            else None,
            "has_accepted": bool(row["has_accepted"]),
            "has_confirmation_required": bool(row["has_confirmation_required"]),
        }
        for row in rows
    }


def _want_item(
    row: dict[str, Any],
    release_count: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = _want_normalized_json(row.get("normalized_json"))
    metadata = normalized.get("metadata") if isinstance(normalized.get("metadata"), dict) else {}
    source = str(row.get("source") or normalized.get("source") or "")
    state = str(row.get("state") or normalized.get("state") or "")
    selected_release_id = row.get("selected_release_id")
    releases = int(release_count.get("release_count") or 0)
    source_label, source_keys, added_at, added_at_precision = _want_source_summary(
        source,
        metadata,
        evidence or [],
    )
    return {
        "intent_id": row.get("intent_id") or normalized.get("intent_id"),
        "title": row.get("title") or normalized.get("title") or row.get("raw_text") or "",
        "raw_text": row.get("raw_text") or normalized.get("raw_text") or "",
        "kind": row.get("kind") or normalized.get("kind") or "unknown",
        "media_type": _want_media_type(normalized, metadata),
        "source": source,
        "source_label": source_label,
        "source_keys": source_keys,
        "added_at": added_at or normalized.get("requested_at") or row.get("created_at"),
        "added_at_precision": added_at_precision
        or _want_timestamp_precision(
            normalized.get("requested_at") or row.get("created_at"),
            source=source,
            metadata=metadata,
        ),
        "state": state,
        "status": _want_download_status(state, releases, bool(selected_release_id)),
        "status_label": _want_download_status_label(state, releases, bool(selected_release_id)),
        "best_candidate_score": release_count.get("best_candidate_score"),
        "selected_release_id": selected_release_id,
        "release_count": releases,
        "updated_at": row.get("updated_at"),
    }


def _ranked_release_from_row(row: dict[str, Any]) -> RankedRelease:
    payload = json.loads(str(row.get("release_json") or "{}"))
    if isinstance(payload, dict) and "release" in payload:
        return RankedRelease.model_validate(payload)
    release = ReleaseCandidate.model_validate(payload)
    return RankedRelease(
        intent_id=str(row.get("intent_id") or ""),
        release=release,
        score=int(row.get("score") or 0),
        confidence=float(row.get("confidence") or 0),
        accepted=bool(row.get("accepted")),
        confirmation_required=bool(row.get("confirmation_required")),
        reasons=[],
        risks=[],
    )


def _want_candidate_item(
    ranked: RankedRelease,
    selected_release_id: Any,
) -> dict[str, Any]:
    release = ranked.release
    metadata = release.metadata if isinstance(release.metadata, dict) else {}
    matches_requirements = _candidate_matches_requirements(ranked)
    return {
        "release_id": release.release_id,
        "site": release.site,
        "title": release.title,
        "source_url": release.source_url,
        "download_url_source": metadata.get("download_url_source"),
        "size_bytes": release.size_bytes,
        "size_gb": round(release.size_bytes / (1024**3), 2),
        "seeders": release.seeders,
        "leechers": release.leechers,
        "discount": release.discount.value,
        "score": ranked.score,
        "confidence": ranked.confidence,
        "accepted": ranked.accepted,
        "confirmation_required": ranked.confirmation_required,
        "matches_requirements": matches_requirements,
        "status_label": "符合偏好" if matches_requirements else "不符合偏好",
        "selected": release.release_id == selected_release_id,
        "reasons": list(ranked.reasons),
        "risks": list(ranked.risks),
        "official_tags": _clean_label_list(metadata.get("mteam_tags")),
        "raw_tags": metadata.get("mteam_raw_tags")
        if isinstance(metadata.get("mteam_raw_tags"), dict)
        else {},
        "inferred_tags": _inferred_release_tags(release.title),
        "mteam_torrent_id": metadata.get("mteam_torrent_id"),
    }


def _candidate_matches_requirements(ranked: RankedRelease) -> bool:
    requirement_risk_prefixes = (
        "resolution missing",
        "season missing",
        "episode missing",
    )
    has_requirement_risk = any(
        any(risk.startswith(prefix) for prefix in requirement_risk_prefixes)
        for risk in ranked.risks
    )
    has_quality_penalty = any(
        reason.startswith("quality tag score -") for reason in ranked.reasons
    )
    return not has_requirement_risk and not has_quality_penalty


def _clean_label_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(text)
    return labels


def _inferred_release_tags(title: str) -> list[str]:
    return [group.label for group in matching_quality_tag_groups([title])]


def _decision_summary_payload(item: Any) -> dict[str, Any]:
    return redact_payload(item.model_dump(mode="json"))


def _want_normalized_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _want_media_type(normalized: dict[str, Any], metadata: dict[str, Any]) -> str:
    media_type = _normalize_want_media_type(metadata.get("media_type") or metadata.get("kind"))
    if media_type != "unknown":
        return media_type
    kind = str(normalized.get("kind") or "").lower()
    if kind in {"show", "episode"}:
        return "tv"
    if kind == "movie":
        return "movie"
    return "unknown"


def _normalize_want_media_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "movie": "movie",
        "film": "movie",
        "电影": "movie",
        "anime": "anime",
        "animation": "anime",
        "动画": "anime",
        "tv": "tv",
        "show": "tv",
        "series": "tv",
        "电视剧": "tv",
        "剧集": "tv",
    }
    return aliases.get(normalized, "unknown")


def _want_source_label(source: str, metadata: dict[str, Any]) -> str:
    label = metadata.get("source_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    if source == IntentSource.DOUBAN_WANTED.value:
        user_name = metadata.get("douban_user_name")
        return f"豆瓣 / {user_name}" if user_name else "豆瓣"
    if source == IntentSource.IMDB_WATCHLIST.value:
        return "IMDb"
    if source == IntentSource.MANUAL.value:
        return "Manual"
    return source or "unknown"


def _want_source_summary(
    source: str,
    metadata: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> tuple[str, list[str], str | None, str | None]:
    if not evidence:
        return (
            _want_source_label(source, metadata),
            [_want_source_key(source, metadata)],
            None,
            None,
        )
    labels: list[str] = []
    keys: list[str] = []
    first_requested_at: str | None = None
    first_precision: str | None = None
    for item in evidence:
        item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        label = item.get("source_label") or _want_source_label(
            str(item.get("source") or ""),
            item_metadata,
        )
        key = _want_source_key(str(item.get("source") or ""), item_metadata)
        requested_at = str(item.get("requested_at") or "") or None
        if label not in labels:
            labels.append(str(label))
        if key not in keys:
            keys.append(key)
        if first_requested_at is None and requested_at is not None:
            first_requested_at = requested_at
            first_precision = _want_timestamp_precision(
                requested_at,
                source=str(item.get("source") or ""),
                metadata=item_metadata,
            )
    first = labels[0] if labels else _want_source_label(source, metadata)
    suffix = f" +{len(labels) - 1}" if len(labels) > 1 else ""
    return f"{first}{suffix}", keys, first_requested_at, first_precision


def _want_timestamp_precision(
    value: Any,
    *,
    source: str,
    metadata: dict[str, Any],
) -> str | None:
    explicit = metadata.get("requested_at_precision") or metadata.get("added_at_precision")
    if explicit in {"date", "datetime"}:
        return str(explicit)
    text = str(value or "")
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return "date"
    source_is_date_only = source in {
        IntentSource.DOUBAN_WANTED.value,
        IntentSource.IMDB_WATCHLIST.value,
    }
    if source_is_date_only and (
        "T00:00:00" in text or " 00:00:00" in text
    ):
        return "date"
    return "datetime"


def _want_source_key(source: str, metadata: dict[str, Any]) -> str:
    config_id = metadata.get("source_config_id")
    if config_id:
        return str(config_id)
    return source or "unknown"


def _want_download_status(state: str, release_count: int, selected: bool) -> str:
    if state == "enqueued" or selected:
        return "queued"
    if state == "failed":
        return "failed"
    if state == "rejected":
        return "rejected"
    if release_count > 0:
        return "found"
    return "pending"


def _want_download_status_label(state: str, release_count: int, selected: bool) -> str:
    status = _want_download_status(state, release_count, selected)
    labels = {
        "queued": "已加入下载队列",
        "found": "已找到候选",
        "pending": "待搜索",
        "failed": "失败",
        "rejected": "已拒绝",
    }
    return labels[status]


def _health_payload(root: Path) -> dict[str, Any]:
    heartbeat_path = _heartbeat_file_path(root)
    payload: dict[str, Any] = {
        "status": "unknown",
        **_runtime_provenance(root),
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


def _schedule_backoff_path(root: Path) -> Path:
    return root / ".seed-agent" / SCHEDULE_BACKOFF_FILE


def _schedule_backoff_status(root: Path) -> dict[str, Any]:
    path = _schedule_backoff_path(root)
    status: dict[str, Any] = {"active": False, "path": str(path)}
    if not path.exists():
        return status
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return status
    if not isinstance(raw, dict):
        return status
    until = _parse_iso_datetime(raw.get("until"))
    if until is None:
        return status
    remaining_minutes = (until - datetime.now(UTC)).total_seconds() / 60
    status.update(
        {
            "active": remaining_minutes > 0,
            "created_at": raw.get("created_at"),
            "until": until.isoformat(),
            "reason": raw.get("reason"),
            "remaining_minutes": round(max(remaining_minutes, 0.0), 2),
        }
    )
    return status


def _heartbeat_file_path(root: Path) -> Path:
    return root / "state" / "schedule-heartbeat.json"


def _runtime_provenance(root: Path) -> dict[str, str]:
    return {
        "runtime_root": str(root),
        "state_path": str(_state_db_path(root)),
        "heartbeat_file": str(_heartbeat_file_path(root)),
    }


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
    if path.suffix == ".svg":
        return "image/svg+xml"
    if path.suffix == ".png":
        return "image/png"
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
