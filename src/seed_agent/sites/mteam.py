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
from pydantic import BaseModel, ConfigDict, Field

from seed_agent.models import Discount, TorrentCandidate

DetailFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]
DiscoverFetcher = Callable[..., Awaitable[list[TorrentCandidate]]]
DownloadUrlFetcher = Callable[[str], Awaitable[str | None]]

DEFERRED_DOWNLOAD_URL_PREFIX = "mteam-api://torrent/"
MTEAM_RATE_LIMIT_MARKERS = ("請求過於頻繁", "请求过于频繁")


class MTeamApiResponseError(RuntimeError):
    def __init__(self, *, endpoint: str, code: str, message: str) -> None:
        self.endpoint = endpoint
        self.code = code
        self.message = message
        super().__init__(f"{endpoint} failed: code={code} message={message}")

    @property
    def rate_limited(self) -> bool:
        return is_mteam_rate_limit_message(self.message)


def is_mteam_rate_limit_message(message: str) -> bool:
    return any(marker in message for marker in MTEAM_RATE_LIMIT_MARKERS)


class MTeamApiDiscoveryOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: str | None = "adult"
    page_number: int = 1
    only_free: bool = True
    discount: str | None = None
    sort_field: str = "downloads"
    sort_order: str = "desc"
    page_size: int = 50
    max_pages: int = 1
    last_id: int | None = None
    keyword: str | None = None
    categories: list[int] = Field(default_factory=list)
    imdb: str | None = None
    douban: str | None = None
    dmm_code: str | None = None
    author: int | None = None
    sources: list[int] = Field(default_factory=list)
    mediums: list[int] = Field(default_factory=list)
    standards: list[int] = Field(default_factory=list)
    video_codecs: list[int] = Field(default_factory=list)
    audio_codecs: list[int] = Field(default_factory=list)
    teams: list[int] = Field(default_factory=list)
    processings: list[int] = Field(default_factory=list)
    countries: list[int] = Field(default_factory=list)
    labels: int | None = None
    labels_new: list[str] = Field(default_factory=list)
    visible: int = 1
    only_fav: bool | None = None
    offer: bool | None = None
    hot: bool | None = None
    upload_date_start: str | None = None
    upload_date_end: str | None = None
    dmm_field: str | None = None
    dmm_keyword: str | None = None
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
        api_key_header: str = "x-api-key",
        visitor_id: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.cookie = cookie
        self.api_key = api_key
        self.api_key_header = api_key_header
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

        candidates: list[TorrentCandidate] = []
        seen_ids: set[str] = set()
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            for page_number in range(
                options.page_number,
                options.page_number + options.max_pages,
            ):
                page_options = options.model_copy(update={"page_number": page_number})
                page_candidates = await self._discover_torrent_page(
                    client,
                    site=site,
                    options=page_options,
                )
                if not page_candidates:
                    break
                for candidate in page_candidates:
                    if candidate.stable_id in seen_ids:
                        continue
                    candidates.append(candidate)
                    seen_ids.add(candidate.stable_id)
        return candidates

    async def _discover_torrent_page(
        self,
        client: httpx.AsyncClient,
        *,
        site: str,
        options: MTeamApiDiscoveryOptions,
    ) -> list[TorrentCandidate]:
        candidates: list[TorrentCandidate] = []
        response = await client.post(
            f"{self.API_BASE_URL}/torrent/search",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Referer": "https://kp.m-team.cc/browse",
                "User-Agent": "Mozilla/5.0",
                self.api_key_header: self.api_key or "",
            },
            json=_search_payload(options),
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise MTeamApiResponseError(
                endpoint="torrent/search",
                code="invalid_response",
                message="expected object response",
            )
        if str(payload.get("code")) != "0":
            raise MTeamApiResponseError(
                endpoint="torrent/search",
                code=str(payload.get("code")),
                message=str(payload.get("message") or ""),
            )

        rows = _extract_search_rows(payload)
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
            self.api_key_header: self.api_key or "",
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
            self.api_key_header: self.api_key,
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.post(
                f"{self.API_BASE_URL}/torrent/genDlToken",
                headers=headers,
                content=f"id={torrent_id}",
            )
            response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise MTeamApiResponseError(
                endpoint="torrent/genDlToken",
                code="invalid_response",
                message="expected object response",
            )
        if str(payload.get("code")) != "0":
            raise MTeamApiResponseError(
                endpoint="torrent/genDlToken",
                code=str(payload.get("code")),
                message=str(payload.get("message") or ""),
            )
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

        status = row.get("status")
        status_data = status if isinstance(status, dict) else {}
        times_completed = _coerce_int(status_data.get("timesCompleted")) or 0
        discount = _normalize_discount_label(_row_discount(row))
        left_time_minutes = _left_time_minutes_from_api_row(row)
        torrent_id_text = str(torrent_id)
        metadata: dict[str, Any] = {
            "mteam_discovery_mode": "api",
            "mteam_torrent_id": torrent_id_text,
            "times_completed": times_completed,
            "download_url_source": "mteam_api_deferred",
        }
        external_ids = _external_ids_from_api_row(row)
        if external_ids:
            metadata["external_ids"] = external_ids
        tag_summary = _mteam_tag_summary_from_api_row(row)
        if tag_summary["labels"]:
            metadata["mteam_tags"] = tag_summary["labels"]
        if tag_summary["raw"]:
            metadata["mteam_raw_tags"] = tag_summary["raw"]
        if left_time_minutes is None and discount in {Discount.FREE, Discount.TWO_X_FREE}:
            metadata["left_time_source"] = _left_time_source_from_api_row(row)

        return TorrentCandidate(
            site=site,
            title=title,
            source_url=f"https://kp.m-team.cc/detail/{torrent_id}",
            download_url=f"{DEFERRED_DOWNLOAD_URL_PREFIX}{torrent_id_text}",
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
    api_key_header: str = "x-api-key",
    fetch_detail: DetailFetcher | None = None,
) -> list[TorrentCandidate]:
    if not candidates or (not cookie and not api_key):
        return candidates

    fetch = fetch_detail
    if fetch is None:
        client = MTeamApiClient(cookie=cookie, api_key=api_key, api_key_header=api_key_header)
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
    api_key_header: str = "x-api-key",
    discover: DiscoverFetcher | None = None,
    fetch_detail: DetailFetcher | None = None,
) -> list[TorrentCandidate]:
    client = MTeamApiClient(cookie=cookie, api_key=api_key, api_key_header=api_key_header)
    discover_fn = discover or client.discover_torrents
    candidates = await discover_fn(site=site, options=options)
    if fetch_detail is None:
        return candidates
    return await enrich_candidates(
        candidates,
        cookie=cookie,
        api_key=api_key,
        api_key_header=api_key_header,
        fetch_detail=fetch_detail,
    )


def has_deferred_download_url(candidate: TorrentCandidate) -> bool:
    return (
        candidate.download_url.startswith(DEFERRED_DOWNLOAD_URL_PREFIX)
        and candidate.metadata.get("download_url_source") == "mteam_api_deferred"
    )


async def resolve_deferred_download_url(
    candidate: TorrentCandidate,
    *,
    api_key: str,
    api_key_header: str = "x-api-key",
    fetch_download_url: DownloadUrlFetcher | None = None,
) -> TorrentCandidate | None:
    if not has_deferred_download_url(candidate):
        return candidate

    torrent_id = str(candidate.metadata.get("mteam_torrent_id") or "").strip()
    if not torrent_id:
        torrent_id = extract_torrent_id(candidate.source_url) or ""
    if not torrent_id:
        return None

    fetch = (
        fetch_download_url
        or MTeamApiClient(api_key=api_key, api_key_header=api_key_header).fetch_download_url
    )
    download_url = await fetch(torrent_id)
    if not download_url:
        return None

    metadata = dict(candidate.metadata)
    metadata["download_url_source"] = "mteam_api"
    return candidate.model_copy(
        update={
            "download_url": download_url,
            "metadata": metadata,
        }
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
    left_time_minutes = _left_time_minutes_from_api_row(detail)
    if left_time_minutes is not None:
        metadata.pop("left_time_source", None)
    elif candidate.discount in {Discount.FREE, Discount.TWO_X_FREE}:
        metadata["left_time_source"] = _left_time_source_from_api_row(detail)

    return candidate.model_copy(
        update={
            "size_bytes": size_bytes,
            "seeders": seeders,
            "leechers": leechers,
            "left_time_minutes": (
                left_time_minutes if left_time_minutes is not None else candidate.left_time_minutes
            ),
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


def _left_time_source_from_api_row(row: dict[str, Any]) -> str:
    if _has_explicit_open_ended_discount(row):
        return "mteam_api_unlimited"
    return "mteam_api_missing"


def _has_explicit_open_ended_discount(row: dict[str, Any]) -> bool:
    open_ended_fields = (
        "freeEndTime",
        "freeEndDate",
        "discountEndTime",
        "discountEndDate",
        "discountExpireTime",
        "discountExpireDate",
        "promotionEndTime",
        "promotionEndDate",
    )
    for container in _api_row_containers(row):
        for field in open_ended_fields:
            if field in container and container.get(field) is None:
                return True
    return False


def _external_ids_from_api_row(row: dict[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for container in _api_row_containers(row):
        douban = _optional_id(container.get("douban") or container.get("doubanId"))
        imdb = _optional_id(container.get("imdb") or container.get("imdbId"))
        if douban:
            ids["douban"] = douban
        if imdb:
            ids["imdb"] = imdb
    return ids


def _optional_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


MTEAM_TAG_LABELS: dict[str, dict[str, str]] = {
    "medium": {
        "0": "Blu-ray",
        "10": "WEB-DL",
    },
    "standard": {
        "1": "1080p",
        "6": "4K",
    },
    "videoCodec": {
        "1": "H.264/x264",
        "16": "H.265/HEVC",
    },
    "audioCodec": {
        "3": "DTS",
        "6": "AAC",
        "7": "TrueHD",
        "11": "DTS-HD MA",
    },
}


def _mteam_tag_summary_from_api_row(row: dict[str, Any]) -> dict[str, Any]:
    labels: list[str] = []
    raw: dict[str, Any] = {}
    raw_names = {
        "medium": "medium",
        "standard": "standard",
        "videoCodec": "video_codec",
        "audioCodec": "audio_codec",
    }
    for field in ("medium", "standard", "videoCodec", "audioCodec"):
        value = _optional_id(row.get(field))
        if value is None:
            continue
        raw[raw_names[field]] = value
        labels.append(MTEAM_TAG_LABELS.get(field, {}).get(value, f"{field}:{value}"))
    labels_new = row.get("labelsNew")
    if isinstance(labels_new, list):
        clean_labels = [str(item).strip() for item in labels_new if str(item).strip()]
        if clean_labels:
            raw["labels_new"] = clean_labels
            labels.extend(clean_labels)
    return {"labels": _dedupe_labels(labels), "raw": raw}


def _dedupe_labels(labels: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        normalized = str(label).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _api_row_containers(row: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [row]
    for key in ("status", "discount", "discountInfo", "promotion", "promotionInfo"):
        value = row.get(key)
        if isinstance(value, dict):
            containers.append(value)
    return containers


def _search_payload(options: MTeamApiDiscoveryOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "visible": options.visible,
        "pageNumber": options.page_number,
        "pageSize": options.page_size,
        "sortDirection": options.sort_order.upper(),
        "sortField": _api_sort_field(options.sort_field),
    }
    _put_optional(payload, "mode", options.mode)
    _put_optional(payload, "lastId", options.last_id)
    _put_optional(payload, "keyword", options.keyword)
    _put_optional_list(payload, "categories", options.categories)
    _put_optional(payload, "imdb", options.imdb)
    _put_optional(payload, "douban", options.douban)
    _put_optional(payload, "dmmCode", options.dmm_code)
    _put_optional(payload, "author", options.author)
    _put_optional_list(payload, "sources", options.sources)
    _put_optional_list(payload, "mediums", options.mediums)
    _put_optional_list(payload, "standards", options.standards)
    _put_optional_list(payload, "videoCodecs", options.video_codecs)
    _put_optional_list(payload, "audioCodecs", options.audio_codecs)
    _put_optional_list(payload, "teams", options.teams)
    _put_optional_list(payload, "processings", options.processings)
    _put_optional_list(payload, "countries", options.countries)
    _put_optional(payload, "labels", options.labels)
    _put_optional_list(payload, "labelsNew", options.labels_new)
    _put_optional(payload, "onlyFav", options.only_fav)
    _put_optional(payload, "offer", options.offer)
    _put_optional(payload, "hot", options.hot)
    _put_optional(payload, "uploadDateStart", options.upload_date_start)
    _put_optional(payload, "uploadDateEnd", options.upload_date_end)
    _put_optional(payload, "dmmField", options.dmm_field)
    _put_optional(payload, "dmmKeyword", options.dmm_keyword)

    discount = options.discount
    if discount is None and options.only_free:
        discount = "FREE"
    _put_optional(payload, "discount", discount)
    return payload


def _api_sort_field(sort_field: str) -> str:
    aliases = {
        "created_date": "CREATED_DATE",
        "createdDate": "CREATED_DATE",
        "downloads": "TIMES_COMPLETED",
        "times_completed": "TIMES_COMPLETED",
        "seeders": "SEEDERS",
        "leechers": "LEECHERS",
        "size": "SIZE",
        "name": "NAME",
    }
    return aliases.get(sort_field, sort_field)


def _put_optional(payload: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    payload[key] = value


def _put_optional_list(payload: dict[str, Any], key: str, value: list[Any]) -> None:
    if value:
        payload[key] = value


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
    if options.max_seeders not in {None, 0} and seeders > options.max_seeders:
        return False
    if leechers < options.min_leechers:
        return False
    if times_completed < options.min_times_completed:
        return False
    return True


def _row_discount(row: dict[str, Any]) -> Any:
    discount = row.get("discount")
    if discount:
        return discount
    status = row.get("status")
    if isinstance(status, dict):
        return status.get("discount")
    return None


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
