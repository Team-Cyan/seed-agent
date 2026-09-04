from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import httpx

from seed_agent.downloaders.base import DownloaderStatus
from seed_agent.models import ManagedTorrent
from seed_agent.observability import get_logger, log_event

logger = get_logger("downloader.qbittorrent")


class QbittorrentError(RuntimeError):
    pass


class QbittorrentClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                await self._login(client)
                yield client
            except httpx.HTTPError as exc:
                log_event(logger, logging.WARNING, "qb.connection.failed",
                          error_type=type(exc).__name__, error=str(exc))
                raise

    async def _login(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        self._ensure_success(response, "qBittorrent login")
        body = response.text.strip()
        if body.startswith("Ok"):
            return
        if response.status_code == 204 and response.headers.get("set-cookie"):
            return
        raise QbittorrentError(f"qBittorrent login failed: unexpected response body: {body!r}")

    def _ensure_success(self, response: httpx.Response, action: str) -> None:
        log_event(
            logger,
            logging.DEBUG if 200 <= response.status_code < 300 else logging.WARNING,
            "qb.request.completed",
            operation=action,
            status_code=response.status_code,
        )
        if 200 <= response.status_code < 300:
            return
        body = response.text.strip()
        raise QbittorrentError(f"{action} failed: HTTP {response.status_code}: {body}")

    async def _post_form(
        self, client: httpx.AsyncClient, path: str, data: dict[str, Any]
    ) -> httpx.Response:
        response = await client.post(path, data=data)
        self._ensure_success(response, f"qBittorrent request to {path}")
        return response

    async def add_url(
        self,
        url: str,
        category: str,
        tags: list[str],
        *,
        paused: bool = False,
    ) -> str | None:
        async with self._client() as client:
            response = await self._post_form(
                client,
                "/api/v2/torrents/add",
                {
                    "urls": url,
                    "category": category,
                    "tags": ",".join(tags),
                    "stopped": "true" if paused else "false",
                },
            )
            return _extract_add_hash(response)

    async def list_torrents(
        self, category: str | None = None, tags: set[str] | None = None
    ) -> list[ManagedTorrent]:
        async with self._client() as client:
            params: dict[str, str] = {}
            if category is not None:
                params["category"] = category
            response = await client.get("/api/v2/torrents/info", params=params or None)
            self._ensure_success(response, "qBittorrent request to /api/v2/torrents/info")
            torrents = [_torrent_from_row(row) for row in response.json()]
            if category is not None:
                torrents = [torrent for torrent in torrents if torrent.category == category]
            if tags is not None:
                torrents = [torrent for torrent in torrents if tags.intersection(torrent.tags)]
            return torrents

    async def get_status(self) -> DownloaderStatus:
        async with self._client() as client:
            response = await client.get("/api/v2/sync/maindata")
            self._ensure_success(response, "qBittorrent request to /api/v2/sync/maindata")
            payload = response.json()
            if not isinstance(payload, dict):
                raise QbittorrentError("qBittorrent status response is not an object")
            server_state = payload.get("server_state")
            if not isinstance(server_state, dict):
                return DownloaderStatus()
            free_space = _optional_int_value(server_state.get("free_space_on_disk"))
            return DownloaderStatus(free_space_bytes=free_space)

    async def pause(self, hash: str) -> None:
        async with self._client() as client:
            await self._post_form(client, "/api/v2/torrents/stop", {"hashes": hash})

    async def delete(self, hash: str, delete_files: bool) -> None:
        async with self._client() as client:
            await self._post_form(
                client,
                "/api/v2/torrents/delete",
                {
                    "hashes": hash,
                    "deleteFiles": "true" if delete_files else "false",
                },
            )


def _extract_add_hash(response: httpx.Response) -> str | None:
    body = response.text.strip()
    if not body or body.startswith("Ok"):
        return None
    if _looks_like_info_hash(body):
        return body
    json_result = _extract_json_add_result(body)
    if json_result is not _UNRECOGNIZED_ADD_RESULT:
        return json_result
    raise QbittorrentError(
        "qBittorrent add torrent failed: "
        f"unexpected response body: {_safe_response_excerpt(body)}"
    )


_UNRECOGNIZED_ADD_RESULT = object()


def _extract_json_add_result(body: str) -> str | None | object:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _UNRECOGNIZED_ADD_RESULT
    if not isinstance(payload, dict):
        return _UNRECOGNIZED_ADD_RESULT

    added_torrent_ids = payload.get("added_torrent_ids")
    if isinstance(added_torrent_ids, list):
        for torrent_id in added_torrent_ids:
            if isinstance(torrent_id, str) and _looks_like_info_hash(torrent_id):
                return torrent_id

    failure_count = _optional_int(payload.get("failure_count"))
    pending_count = _optional_int(payload.get("pending_count"))
    success_count = _optional_int(payload.get("success_count"))
    if failure_count == 0 and ((pending_count or 0) > 0 or (success_count or 0) > 0):
        return None
    return _UNRECOGNIZED_ADD_RESULT


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_int_value(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _looks_like_info_hash(value: str) -> bool:
    if len(value) != 40:
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value)


_SENSITIVE_RESPONSE_PARAM_RE = re.compile(
    r"(?i)(passkey|token|apikey|api_key|auth|sid|session)=([^&\s'\"<>]+)"
)


def _safe_response_excerpt(value: str, *, limit: int = 300) -> str:
    compact = " ".join(value.strip().split())
    redacted = _SENSITIVE_RESPONSE_PARAM_RE.sub(r"\1=<redacted>", compact)
    if len(redacted) > limit:
        redacted = redacted[: limit - 3] + "..."
    return repr(redacted)


def _torrent_from_row(row: dict[str, Any]) -> ManagedTorrent:
    added_on = row.get("added_on")
    if added_on is None:
        raise QbittorrentError("qBittorrent torrent row is missing added_on")
    uploaded = int(row.get("uploaded") or row.get("uploaded_session") or 0)
    uploaded_session = row.get("uploaded_session")
    metadata: dict[str, Any] = {}
    if uploaded_session is not None:
        metadata["uploaded_session_bytes"] = int(uploaded_session)
    upspeed = row.get("upspeed")
    if upspeed is not None:
        metadata["upspeed_bps"] = int(upspeed)
    dlspeed = row.get("dlspeed")
    if dlspeed is not None:
        metadata["dlspeed_bps"] = int(dlspeed)
    tracker = _normalize_optional_str(row.get("tracker"))
    if tracker is not None:
        metadata["tracker"] = tracker
    amount_left = row.get("amount_left")
    if amount_left is not None:
        metadata["amount_left_bytes"] = int(amount_left)
    tags = _parse_tags(row.get("tags"))
    if _looks_like_hr_tag(tags):
        metadata["hr"] = True
    save_path = _normalize_optional_str(row.get("save_path"))
    if save_path is not None and _looks_like_media_library_path(save_path):
        metadata["media_library"] = True
    return ManagedTorrent(
        hash=str(row.get("hash") or ""),
        name=str(row.get("name") or ""),
        category=_normalize_optional_str(row.get("category")),
        tags=tags,
        state=str(row.get("state") or ""),
        size_bytes=int(row.get("size") or 0),
        uploaded_bytes=uploaded,
        downloaded_bytes=int(row.get("downloaded") or 0),
        added_at=datetime.fromtimestamp(int(added_on), tz=UTC),
        completed_at=_optional_datetime(row.get("completion_on")),
        last_activity_at=_optional_datetime(row.get("last_activity")),
        save_path=save_path,
        metadata=metadata,
    )


def _parse_tags(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    if not isinstance(value, str):
        return {str(value).strip()} if str(value).strip() else set()
    return {part.strip() for part in value.split(",") if part.strip()}


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _looks_like_hr_tag(tags: set[str]) -> bool:
    normalized = {tag.strip().lower() for tag in tags}
    clear_tags = {"hr", "h&r", "hit-and-run", "hit and run", "hit_and_run"}
    return bool(normalized.intersection(clear_tags))


def _looks_like_media_library_path(save_path: str) -> bool:
    path = PurePosixPath(save_path.replace("\\", "/"))
    segments = {segment.lower() for segment in path.parts if segment not in {"/", ""}}
    return bool(segments.intersection({"media", "library", "movies", "tv", "shows"}))


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    timestamp = int(value)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)
