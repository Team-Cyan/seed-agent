from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from seed_agent.models import Discount


class MTeamApiDiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["adult", "movie", "tvshow", "normal"] = "adult"
    only_free: bool = True
    sort_field: Literal["createdDate", "id", "downloads", "seeders", "size"] = "downloads"
    sort_order: Literal["asc", "desc"] = "desc"
    page_size: int = 50
    min_seeders: int = 0
    max_seeders: int | None = 200
    min_leechers: int = 0
    min_times_completed: int = 0

    @model_validator(mode="after")
    def validate_limits(self) -> MTeamApiDiscoveryConfig:
        if self.page_size < 1:
            raise ValueError("page_size must be >= 1")
        if self.min_seeders < 0:
            raise ValueError("min_seeders must be >= 0")
        if self.min_leechers < 0:
            raise ValueError("min_leechers must be >= 0")
        if self.min_times_completed < 0:
            raise ValueError("min_times_completed must be >= 0")
        if self.max_seeders is not None and self.max_seeders < self.min_seeders:
            raise ValueError("max_seeders must be >= min_seeders")
        return self


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    type: Literal["nexusphp", "mteam"]
    enabled: bool = True
    rss_url: str
    cookie_ref: str | None = None
    api_key_ref: str | None = None
    discovery_mode: Literal["rss", "api"] = "rss"
    api_discovery: MTeamApiDiscoveryConfig | None = None

    @model_validator(mode="after")
    def validate_discovery_mode(self) -> SiteConfig:
        if self.discovery_mode == "api":
            if self.type != "mteam":
                raise ValueError("discovery_mode=api is only supported for mteam")
            if self.api_discovery is None:
                raise ValueError("api_discovery must be set when discovery_mode=api")
            if not self.api_key_ref:
                raise ValueError("api_key_ref is required when discovery_mode=api")
        if self.type != "mteam" and self.api_discovery is not None:
            raise ValueError("api_discovery is only supported for mteam")
        return self


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

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
            raise ValueError("discounts must be a list")
        if not isinstance(value, list):
            raise ValueError("discounts must be a list")
        return [_normalize_discount(item) for item in value]


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

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
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["qbittorrent"]
    target: str
    category: str
    tags: list[str] = Field(default_factory=list)
    secret_ref: str | None = None


class CleanupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

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


class IntentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirmation_threshold: float = 0.82
    auto_enqueue_threshold: float = 0.94
    ambiguity_gap: float = 0.08
    default_resolution: str | None = "1080p"
    preferred_languages: list[str] = Field(default_factory=lambda: ["zh", "en"])
    inbox_ref: str = "local/inbox/intents.jsonl"

    @model_validator(mode="after")
    def validate_thresholds(self) -> IntentConfig:
        for field_name in ("confirmation_threshold", "auto_enqueue_threshold", "ambiguity_gap"):
            value = getattr(self, field_name)
            if not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be between 0 and 1")
        if self.auto_enqueue_threshold < self.confirmation_threshold:
            raise ValueError("auto_enqueue_threshold must be >= confirmation_threshold")
        return self


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    site_priority: dict[str, int] = Field(default_factory=dict)
    max_results_per_site: int = 20
    prefer_free: bool = True
    reject_hr_by_default: bool = True

    @model_validator(mode="after")
    def validate_limits(self) -> SearchConfig:
        if self.max_results_per_site < 1:
            raise ValueError("max_results_per_site must be >= 1")
        return self


class SecretSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    secret_ref: str | None = None


class DoubanWantedSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    export_ref: str | None = None


class SubscriptionSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    rules_ref: str | None = None


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    telegram: SecretSourceConfig = Field(default_factory=SecretSourceConfig)
    wechat_bridge: SecretSourceConfig = Field(default_factory=SecretSourceConfig)
    douban_wanted: DoubanWantedSourceConfig = Field(default_factory=DoubanWantedSourceConfig)
    subscription: SubscriptionSourceConfig = Field(default_factory=SubscriptionSourceConfig)


class SeedAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["balanced"]
    sites: list[SiteConfig]
    discovery: DiscoveryConfig
    scoring: ScoringConfig
    downloader: DownloaderConfig
    cleanup: CleanupConfig
    intent: IntentConfig = Field(default_factory=IntentConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    _config_dir: Path | None = PrivateAttr(default=None)

    @property
    def enabled_sites(self) -> list[SiteConfig]:
        return [site for site in self.sites if site.enabled]

    @property
    def config_dir(self) -> Path | None:
        return self._config_dir


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
    config = SeedAgentConfig.model_validate(data)
    config._config_dir = path.resolve().parent
    return config
