from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

SENSITIVE_QUERY_KEYS = {
    "passkey",
    "password",
    "passphrase",
    "token",
    "auth",
    "rsskey",
    "uid",
    "secret",
    "cookie",
}
SENSITIVE_QUERY_EXACT_KEYS = {
    "authkey",
    "pass_key",
    "torrent_pass",
    "torrentpass",
    "download_key",
    "downloadkey",
    "secure",
    "signature",
    "sign",
    "hash",
}
SENSITIVE_QUERY_TOKEN_KEYS = {"pass", "token", "secret", "auth", "cookie"}
QUERY_KEY_SPLIT_RE = re.compile(r"[^a-z0-9]+")


class Discount(StrEnum):
    FREE = "free"
    TWO_X_FREE = "2xfree"
    HALF = "50%"
    TWO_X_HALF = "2x50%"
    NORMAL = "normal"


class LifecycleState(StrEnum):
    DISCOVERED = "discovered"
    SCORED = "scored"
    ENQUEUED = "enqueued"
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    COLD = "cold"
    PAUSED = "paused"
    DELETED = "deleted"


class IntentSource(StrEnum):
    CLI = "cli"
    FILE_INBOX = "file_inbox"
    TELEGRAM = "telegram"
    WECHAT_BRIDGE = "wechat_bridge"
    DOUBAN_WANTED = "douban_wanted"
    SUBSCRIPTION = "subscription"


class IntentKind(StrEnum):
    MOVIE = "movie"
    SHOW = "show"
    EPISODE = "episode"
    UNKNOWN = "unknown"


class IntentState(StrEnum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    SEARCHED = "searched"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    ENQUEUED = "enqueued"
    FAILED = "failed"


def safe_url_identity(url: str) -> str:
    parts = urlsplit(url)
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if _is_safe_query_key(key)
    ]
    netloc = _safe_netloc(parts)
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(safe_query), ""))


def _safe_netloc(parts) -> str:
    hostname = parts.hostname
    if hostname is None:
        return parts.netloc
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if parts.port is not None:
        return f"{hostname}:{parts.port}"
    return hostname


def _is_safe_query_key(key: str) -> bool:
    lower_key = key.lower()
    if lower_key in SENSITIVE_QUERY_KEYS:
        return False
    if lower_key in SENSITIVE_QUERY_EXACT_KEYS:
        return False
    key_parts = [part for part in QUERY_KEY_SPLIT_RE.split(lower_key) if part]
    if any(part in SENSITIVE_QUERY_TOKEN_KEYS for part in key_parts):
        return False
    return True


class TorrentCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    title: str
    source_url: str
    download_url: str
    size_bytes: int = Field(ge=0)
    seeders: int = Field(ge=0)
    leechers: int = Field(ge=0)
    discount: Discount = Discount.NORMAL
    left_time_minutes: int | None = Field(default=None, ge=0)
    hr: bool = False
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("discount", mode="before")
    @classmethod
    def normalize_discount(cls, value: str | Discount) -> Discount:
        if isinstance(value, Discount):
            return value
        if not isinstance(value, str):
            raise ValueError("discount must be a string or Discount value")
        normalized = value.strip().lower().replace(" ", "")
        aliases = {
            "": Discount.NORMAL,
            "free": Discount.FREE,
            "2xfree": Discount.TWO_X_FREE,
            "2x_free": Discount.TWO_X_FREE,
            "50%": Discount.HALF,
            "half": Discount.HALF,
            "2x50%": Discount.TWO_X_HALF,
            "normal": Discount.NORMAL,
            "none": Discount.NORMAL,
        }
        if normalized not in aliases:
            raise ValueError(f"unknown discount label: {value}")
        return aliases[normalized]

    @property
    def stable_id(self) -> str:
        return f"{self.site}:{safe_url_identity(self.source_url)}"


class ResourceIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent_id: str = Field(min_length=1)
    source: IntentSource
    raw_text: str = Field(min_length=1)
    kind: IntentKind = IntentKind.UNKNOWN
    title: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1800, le=2200)
    season: int | None = Field(default=None, ge=1)
    episode: int | None = Field(default=None, ge=1)
    resolution: str | None = None
    quality: str | None = None
    language: str | None = None
    requested_at: datetime
    state: IntentState = IntentState.RECEIVED
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReleaseCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    release_id: str = Field(min_length=1)
    site: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str
    download_url: str
    size_bytes: int = Field(ge=0)
    seeders: int = Field(ge=0)
    leechers: int = Field(ge=0)
    discount: Discount = Discount.NORMAL
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("discount", mode="before")
    @classmethod
    def normalize_discount(cls, value: str | Discount) -> Discount:
        return TorrentCandidate.normalize_discount(value)


class RankedRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent_id: str = Field(min_length=1)
    release: ReleaseCandidate
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    accepted: bool
    confirmation_required: bool
    reasons: list[str]
    risks: list[str]


class ScoreBreakdown(BaseModel):
    candidate_id: str
    score: int = Field(ge=0, le=100)
    accepted: bool
    reasons: list[str]
    candidate: TorrentCandidate


class ManagedTorrent(BaseModel):
    hash: str
    name: str
    category: str | None = None
    tags: set[str] = Field(default_factory=set)
    state: str
    size_bytes: int = Field(ge=0)
    uploaded_bytes: int = Field(ge=0)
    downloaded_bytes: int = Field(ge=0)
    added_at: datetime
    completed_at: datetime | None = None
    last_activity_at: datetime | None = None
    save_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    action: str
    target_id: str
    execute: bool
    reason: str
    old_state: dict[str, Any] = Field(default_factory=dict)
    new_state: dict[str, Any] = Field(default_factory=dict)
    confirmation_required: bool = False
    confirmation_received: bool = False
    rollback: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
