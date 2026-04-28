from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx
from pydantic import BaseModel, ConfigDict

from seed_agent.models import Discount, TorrentCandidate

DetailFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]
DiscoverFetcher = Callable[[str, "MTeamApiDiscoveryOptions"], Awaitable[list[TorrentCandidate]]]


class MTeamApiDiscoveryOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: str = "adult"
    only_free: bool = True
    sort_field: str = "downloads"
    sort_order: str = "desc"
    page_size: int = 50
    min_seeders: int = 0
    max_seeders: int | None = 200
    min_leechers: int = 0
    min_times_completed: int = 0


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

    async def discover_torrents(
        self,
        *,
        site: str,
        options: MTeamApiDiscoveryOptions,
    ) -> list[TorrentCandidate]:
        if not self.api_key:
            return []

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://kp.m-team.cc/browse",
            "User-Agent": "Mozilla/5.0",
            "x-api-key": self.api_key,
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.post(
                f"{self.API_BASE_URL}/torrent/search",
                headers=headers,
                json=_search_payload(options),
            )
            response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            return []

        rows = _extract_search_rows(payload)
        candidates: list[TorrentCandidate] = []
        for row in rows:
            if not _row_meets_thresholds(row, options):
                continue
            candidate = await self._candidate_from_search_row(site, row)
            if candidate is None:
                continue
            candidates.append(candidate)
        return candidates

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

    async def fetch_download_url(self, torrent_id: str) -> str | None:
        if not self.api_key:
            return None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
            "x-api-key": self.api_key,
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.post(
                f"{self.API_BASE_URL}/torrent/genDlToken",
                headers=headers,
                content=f"id={torrent_id}",
            )
            response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            return None
        data = payload.get("data")
        if not isinstance(data, str):
            return None
        return data.strip() or None

    async def _candidate_from_search_row(
        self, site: str, row: dict[str, Any]
    ) -> TorrentCandidate | None:
        torrent_id = _coerce_int(row.get("id"))
        title = str(row.get("name") or "").strip()
        if torrent_id is None or not title:
            return None

        download_url = await self.fetch_download_url(str(torrent_id))
        if not download_url:
            return None

        status = row.get("status")
        status_data = status if isinstance(status, dict) else {}
        times_completed = _coerce_int(status_data.get("timesCompleted")) or 0
        discount = _normalize_discount_label(row.get("discount"))
        left_time_minutes = _left_time_minutes_from_api_row(row)
        metadata: dict[str, Any] = {
            "mteam_discovery_mode": "api",
            "times_completed": times_completed,
        }
        if left_time_minutes is None and discount in {Discount.FREE, Discount.TWO_X_FREE}:
            metadata["left_time_source"] = "mteam_api_missing"

        return TorrentCandidate(
            site=site,
            title=title,
            source_url=f"https://kp.m-team.cc/detail/{torrent_id}",
            download_url=download_url,
            size_bytes=_coerce_int(row.get("size")) or 0,
            seeders=_coerce_int(status_data.get("seeders")) or 0,
            leechers=_coerce_int(status_data.get("leechers")) or 0,
            discount=discount,
            left_time_minutes=left_time_minutes,
            published_at=_parse_api_datetime(row.get("createdDate")),
            metadata=metadata,
        )


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


async def fetch_api_candidates(
    *,
    site: str,
    api_key: str,
    options: MTeamApiDiscoveryOptions,
    cookie: str | None = None,
    discover: DiscoverFetcher | None = None,
    fetch_detail: DetailFetcher | None = None,
) -> list[TorrentCandidate]:
    client = MTeamApiClient(cookie=cookie, api_key=api_key)
    discover_fn = discover or client.discover_torrents
    candidates = await discover_fn(site, options)
    return await enrich_candidates(
        candidates,
        cookie=cookie,
        api_key=api_key,
        fetch_detail=fetch_detail or client.fetch_torrent_detail,
    )


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


def _left_time_minutes_from_api_row(row: dict[str, Any]) -> int | None:
    minute_fields = (
        "left_time_minutes",
        "leftTimeMinutes",
        "leftTime",
        "freeLeftTimeMinutes",
        "discountLeftTimeMinutes",
        "promotionLeftTimeMinutes",
    )
    end_fields = (
        "freeEndTime",
        "freeEndDate",
        "discountEndTime",
        "discountEndDate",
        "discountExpireTime",
        "discountExpireDate",
        "promotionEndTime",
        "promotionEndDate",
        "endTime",
        "endDate",
    )
    for container in _api_row_containers(row):
        for field in minute_fields:
            minutes = _coerce_int(container.get(field))
            if minutes is not None:
                return minutes
        for field in end_fields:
            end_at = _parse_api_datetime(container.get(field))
            if end_at is None:
                continue
            return max(0, int((end_at - datetime.now(UTC)).total_seconds() // 60))
    return None


def _api_row_containers(row: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [row]
    for key in ("status", "discount", "discountInfo", "promotion", "promotionInfo"):
        value = row.get(key)
        if isinstance(value, dict):
            containers.append(value)
    return containers


def _search_payload(options: MTeamApiDiscoveryOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": options.mode,
        "visible": 1,
        "pageNumber": 1,
        "pageSize": options.page_size,
        "sortDirection": options.sort_order.upper(),
        "sortField": options.sort_field,
    }
    if options.only_free:
        payload["discount"] = "FREE"
    return payload


def _extract_search_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    nested = data.get("data")
    if isinstance(nested, list):
        return [row for row in nested if isinstance(row, dict)]
    return []


def _row_meets_thresholds(row: dict[str, Any], options: MTeamApiDiscoveryOptions) -> bool:
    status = row.get("status")
    status_data = status if isinstance(status, dict) else {}
    seeders = _coerce_int(status_data.get("seeders")) or 0
    leechers = _coerce_int(status_data.get("leechers")) or 0
    times_completed = _coerce_int(status_data.get("timesCompleted")) or 0
    if seeders < options.min_seeders:
        return False
    if options.max_seeders is not None and seeders > options.max_seeders:
        return False
    if leechers < options.min_leechers:
        return False
    if times_completed < options.min_times_completed:
        return False
    return True


def _normalize_discount_label(value: Any) -> Discount:
    text = str(value or "").strip().lower()
    if text in {"free", "freeleech"}:
        return Discount.FREE
    if text in {"2xfree", "two_x_free"}:
        return Discount.TWO_X_FREE
    if text in {"50%", "half"}:
        return Discount.HALF
    if text in {"2x50%", "two_x_half"}:
        return Discount.TWO_X_HALF
    return Discount.NORMAL


def _parse_api_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    timestamp = _coerce_int(text)
    if timestamp is not None:
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
