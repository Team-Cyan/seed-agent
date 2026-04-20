from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

SENSITIVE_QUERY_KEYS = {"passkey", "token", "auth", "key", "rsskey", "uid"}


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


def safe_url_identity(url: str) -> str:
    parts = urlsplit(url)
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


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
        normalized = value.strip().lower().replace(" ", "")
        aliases = {
            "free": Discount.FREE,
            "2xfree": Discount.TWO_X_FREE,
            "2x_free": Discount.TWO_X_FREE,
            "50%": Discount.HALF,
            "half": Discount.HALF,
            "2x50%": Discount.TWO_X_HALF,
            "normal": Discount.NORMAL,
            "none": Discount.NORMAL,
        }
        return aliases.get(normalized, Discount.NORMAL)

    @property
    def stable_id(self) -> str:
        return f"{self.site}:{safe_url_identity(self.source_url)}"


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
