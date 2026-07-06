from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx

from seed_agent.models import ManagedTorrent


class TransmissionError(RuntimeError):
    pass


class TransmissionClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session_id: str | None = None

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        auth = (self.username, self.password) if self.username and self.password else None
        async with httpx.AsyncClient(timeout=self.timeout, auth=auth) as client:
            yield client

    async def add_url(
        self,
        url: str,
        category: str,
        tags: list[str],
        *,
        paused: bool = False,
    ) -> str | None:
        labels = sorted({label for label in [category, *tags] if label})
        payload = await self._rpc(
            "torrent-add",
            {"filename": url, "paused": paused, "labels": labels},
        )
        arguments = _dict_value(payload.get("arguments"))
        for key in ("torrent-added", "torrent-duplicate"):
            result = _dict_value(arguments.get(key))
            torrent_hash = _optional_str(result.get("hashString"))
            if torrent_hash:
                return torrent_hash
        return None

    async def list_torrents(
        self,
        category: str | None = None,
        tags: set[str] | None = None,
    ) -> list[ManagedTorrent]:
        payload = await self._rpc(
            "torrent-get",
            {
                "fields": [
                    "id",
                    "hashString",
                    "name",
                    "labels",
                    "status",
                    "totalSize",
                    "uploadedEver",
                    "downloadedEver",
                    "addedDate",
                    "doneDate",
                    "activityDate",
                    "downloadDir",
                    "rateUpload",
                    "rateDownload",
                    "leftUntilDone",
                ]
            },
        )
        arguments = _dict_value(payload.get("arguments"))
        rows = arguments.get("torrents")
        if not isinstance(rows, list):
            return []
        torrents = [_torrent_from_row(row, requested_category=category) for row in rows]
        if category is not None:
            torrents = [torrent for torrent in torrents if category in torrent.tags]
        if tags is not None:
            torrents = [torrent for torrent in torrents if tags.intersection(torrent.tags)]
        return torrents

    async def pause(self, hash: str) -> None:
        await self._rpc("torrent-stop", {"ids": [hash]})

    async def delete(self, hash: str, delete_files: bool) -> None:
        await self._rpc(
            "torrent-remove",
            {"ids": [hash], "delete-local-data": delete_files},
        )

    async def _rpc(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._client() as client:
            return await self._post_rpc(client, method, arguments or {}, retry_session=True)

    async def _post_rpc(
        self,
        client: httpx.AsyncClient,
        method: str,
        arguments: dict[str, Any],
        *,
        retry_session: bool,
    ) -> dict[str, Any]:
        headers = {}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id
        response = await client.post(
            _rpc_url(self.base_url),
            json={"method": method, "arguments": arguments},
            headers=headers,
        )
        if response.status_code == 409 and retry_session:
            self._session_id = response.headers.get("X-Transmission-Session-Id")
            if self._session_id:
                return await self._post_rpc(
                    client,
                    method,
                    arguments,
                    retry_session=False,
                )
        if not 200 <= response.status_code < 300:
            raise TransmissionError(
                f"Transmission {method} failed: HTTP {response.status_code}: {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise TransmissionError(f"Transmission {method} failed: non-object response")
        result = str(payload.get("result") or "")
        if result != "success":
            raise TransmissionError(f"Transmission {method} failed: {result or 'unknown error'}")
        return payload


def _rpc_url(base_url: str) -> str:
    if base_url.endswith("/transmission/rpc"):
        return base_url
    return f"{base_url}/transmission/rpc"


def _torrent_from_row(row: Any, *, requested_category: str | None) -> ManagedTorrent:
    data = _dict_value(row)
    labels = _labels(data.get("labels"))
    metadata: dict[str, Any] = {"transmission_labels": sorted(labels)}
    upspeed = _int_value(data.get("rateUpload"))
    dlspeed = _int_value(data.get("rateDownload"))
    amount_left = _int_value(data.get("leftUntilDone"))
    if upspeed is not None:
        metadata["upspeed_bps"] = upspeed
    if dlspeed is not None:
        metadata["dlspeed_bps"] = dlspeed
    if amount_left is not None:
        metadata["amount_left_bytes"] = amount_left
    return ManagedTorrent(
        hash=str(data.get("hashString") or ""),
        name=str(data.get("name") or ""),
        category=(
            requested_category
            if requested_category in labels
            else _category_from_labels(labels)
        ),
        tags=labels,
        state=_status_name(data.get("status")),
        size_bytes=_int_value(data.get("totalSize")) or 0,
        uploaded_bytes=_int_value(data.get("uploadedEver")) or 0,
        downloaded_bytes=_int_value(data.get("downloadedEver")) or 0,
        added_at=_timestamp(data.get("addedDate")) or datetime.fromtimestamp(0, tz=UTC),
        completed_at=_timestamp(data.get("doneDate")),
        last_activity_at=_timestamp(data.get("activityDate")),
        save_path=_optional_str(data.get("downloadDir")),
        metadata=metadata,
    )


def _status_name(value: Any) -> str:
    names = {
        0: "stopped",
        1: "check_wait",
        2: "checking",
        3: "download_wait",
        4: "downloading",
        5: "seed_wait",
        6: "seeding",
    }
    number = _int_value(value)
    if number is None:
        return "unknown"
    return names.get(number, str(number))


def _labels(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _category_from_labels(labels: set[str]) -> str | None:
    for label in sorted(labels):
        if label != "seed-agent":
            return label
    return None


def _timestamp(value: Any) -> datetime | None:
    number = _int_value(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=UTC)


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
