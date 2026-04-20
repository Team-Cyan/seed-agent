from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seed_agent.models import Discount


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    enabled: bool = True
    rss_url: str
    cookie_ref: str | None = None


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discounts: list[Discount] = Field(default_factory=list)
    min_left_time_minutes: int
    min_leechers: int
    max_seeders: int
    allow_hr: bool = False
    min_seeders: int | None = None
    max_leechers: int | None = None
    preferred_size_min_gb: float | None = None
    preferred_size_max_gb: float | None = None

    @field_validator("discounts", mode="before")
    @classmethod
    def normalize_discounts(cls, value: Any) -> list[Discount]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("discounts must be a list")
        return [_normalize_discount(item) for item in value]


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    EXPECTED_WEIGHT_KEYS: ClassVar[tuple[str, ...]] = (
        "discount",
        "leechers",
        "seeders",
        "left_time",
        "size",
        "site_history",
    )

    min_score_to_enqueue: int
    weights: dict[str, int]

    @model_validator(mode="after")
    def validate_weights(self) -> ScoringConfig:
        weight_keys = set(self.weights)
        expected_keys = set(self.EXPECTED_WEIGHT_KEYS)
        if weight_keys != expected_keys:
            missing = sorted(expected_keys - weight_keys)
            unknown = sorted(weight_keys - expected_keys)
            details: list[str] = []
            if missing:
                details.append(f"missing keys: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown keys: {', '.join(unknown)}")
            raise ValueError(f"weights must use exact keys; {'; '.join(details)}")
        total = sum(self.weights.values())
        if total != 100:
            raise ValueError(f"weights must sum to 100, got {total}")
        return self


class DownloaderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    target: str
    category: str
    tags: list[str] = Field(default_factory=list)
    secret_ref: str | None = None


class CleanupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cold_after_days: int
    min_upload_delta_gb: float
    protect_hr: bool
    protect_manual: bool
    protect_media_library: bool
    pause_before_delete_hours: int

    @model_validator(mode="after")
    def validate_pause_before_delete_hours(self) -> CleanupConfig:
        if self.pause_before_delete_hours < 1:
            raise ValueError("pause_before_delete_hours must be >= 1")
        return self


class SeedAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    sites: list[SiteConfig]
    discovery: DiscoveryConfig
    scoring: ScoringConfig
    downloader: DownloaderConfig
    cleanup: CleanupConfig

    @property
    def enabled_sites(self) -> list[SiteConfig]:
        return [site for site in self.sites if site.enabled]


def _normalize_discount(value: Any) -> Discount:
    if isinstance(value, Discount):
        return value
    if not isinstance(value, str):
        raise ValueError("discounts entries must be strings or Discount values")
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
    if normalized not in aliases:
        raise ValueError(f"unknown discount label: {value}")
    return aliases[normalized]


def load_downloader_secret(path: Path) -> dict[str, str]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


def load_config(path: Path) -> SeedAgentConfig:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = loaded or {}
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a mapping")
    return SeedAgentConfig.model_validate(data)
