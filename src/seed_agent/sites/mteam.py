from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx

from seed_agent.models import TorrentCandidate

DetailFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]


class MTeamApiClient:
    API_BASE_URL = "https://api.m-team.cc/api"
    VERSION = "1.1.4"
    WEB_VERSION = "1140"
    SECRET = "HLkPcWmycL57mfJt"

    def __init__(
        self,
        *,
        cookie: str | None = None,
        api_key: str | None = None,
        visitor_id: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.cookie = cookie
        self.api_key = api_key
        self.visitor_id = visitor_id or str(uuid.uuid4())
        self.timeout = timeout

    async def fetch_torrent_detail(self, torrent_id: str) -> dict[str, Any] | None:
        if self.api_key:
            return await self._fetch_torrent_detail_with_api_key(torrent_id)
        if not self.cookie:
            return None

        timestamp = int(time.time() * 1000)
        params = {
            "id": torrent_id,
            "_timestamp": str(timestamp),
            "_sgin": _request_signature("GET", "/api/torrent/detail", timestamp),
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.cookie,
            "Referer": "https://kp.m-team.cc/",
            "Origin": "https://kp.m-team.cc",
            "User-Agent": "Mozilla/5.0",
            "ts": str(int(time.time())),
            "visitorId": self.visitor_id,
            "version": self.VERSION,
            "webVersion": self.WEB_VERSION,
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/torrent/detail",
                params=params,
                headers=headers,
            )
            response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            return None
        if int(payload.get("code", -1)) != 0:
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        data["_auth_mode"] = "cookie"
        return data

    async def _fetch_torrent_detail_with_api_key(self, torrent_id: str) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0",
            "x-api-key": self.api_key or "",
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.post(
                f"{self.API_BASE_URL}/torrent/detail",
                params={"id": torrent_id},
                headers=headers,
            )
            response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            return None
        if str(payload.get("code")) != "0":
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        data["_auth_mode"] = "api_key"
        return data


async def enrich_candidates(
    candidates: list[TorrentCandidate],
    *,
    cookie: str | None,
    api_key: str | None = None,
    fetch_detail: DetailFetcher | None = None,
) -> list[TorrentCandidate]:
    if not candidates or (not cookie and not api_key):
        return candidates

    fetch = fetch_detail
    if fetch is None:
        client = MTeamApiClient(cookie=cookie, api_key=api_key)
        fetch = client.fetch_torrent_detail

    enriched: list[TorrentCandidate] = []
    for candidate in candidates:
        torrent_id = extract_torrent_id(candidate.source_url)
        if torrent_id is None:
            enriched.append(candidate)
            continue

        detail = await fetch(torrent_id)
        if detail is None:
            enriched.append(candidate)
            continue
        enriched.append(_merge_detail(candidate, detail))

    return enriched


def extract_torrent_id(url: str) -> str | None:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "detail" and path_parts[1].isdigit():
        return path_parts[1]

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in {"id", "tid", "torrentId"} and value.isdigit():
            return value
    return None


def _merge_detail(candidate: TorrentCandidate, detail: dict[str, Any]) -> TorrentCandidate:
    status = detail.get("status")
    status_data = status if isinstance(status, dict) else {}
    metadata = dict(candidate.metadata)
    metadata["mteam_detail_enriched"] = True
    metadata["mteam_detail_auth_mode"] = detail.get("_auth_mode", "unknown")

    times_completed = _coerce_int(status_data.get("timesCompleted"))
    if times_completed is not None:
        metadata["times_completed"] = times_completed

    missing_fields = metadata.get("rss_missing_fields")
    if isinstance(missing_fields, dict):
        updated_missing = {
            key: value
            for key, value in missing_fields.items()
            if key not in {"size", "seeders", "leechers"}
        }
        if updated_missing:
            metadata["rss_missing_fields"] = updated_missing
        else:
            metadata.pop("rss_missing_fields", None)
    metadata.pop("rss_sparse_candidate", None)

    size_bytes = _coerce_int(detail.get("size")) or candidate.size_bytes
    seeders = _coerce_int(status_data.get("seeders")) or candidate.seeders
    leechers = _coerce_int(status_data.get("leechers")) or candidate.leechers

    return candidate.model_copy(
        update={
            "size_bytes": size_bytes,
            "seeders": seeders,
            "leechers": leechers,
            "metadata": metadata,
        }
    )


def _request_signature(method: str, path: str, timestamp_ms: int) -> str:
    payload = f"{method.upper()}&{path}&{timestamp_ms}".encode()
    digest = hmac.new(MTeamApiClient.SECRET.encode(), payload, hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None
