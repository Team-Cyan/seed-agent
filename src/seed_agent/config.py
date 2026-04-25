from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from seed_agent.models import Discount


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    type: Literal["nexusphp", "mteam"]
    enabled: bool = True
    rss_url: str
    cookie_ref: str | None = None
    api_key_ref: str | None = None


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
    default_category: str
    category_policies: list[CategoryPolicyConfig] = Field(default_factory=list)
    budget_pools: list[BudgetPoolConfig] = Field(default_factory=list)
    secret_ref: str | None = None

    @model_validator(mode="after")
    def validate_category_policy_links(self) -> DownloaderConfig:
        policy_names = [policy.name for policy in self.category_policies]
        if len(policy_names) != len(set(policy_names)):
            raise ValueError("category policy names must be unique")
        pool_names = [pool.name for pool in self.budget_pools]
        if len(pool_names) != len(set(pool_names)):
            raise ValueError("budget pool names must be unique")
        if self.default_category not in set(policy_names):
            raise ValueError("default_category must match a configured category policy")
        known_pools = set(pool_names)
        for policy in self.category_policies:
            if policy.budget_pool not in known_pools:
                raise ValueError(
                    f"category policy {policy.name} references unknown budget pool "
                    f"{policy.budget_pool}"
                )
            if policy.mode == "add_only" and policy.delete_enabled:
                raise ValueError("add_only category policies cannot enable delete")
        return self


class CategoryPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    mode: Literal["mutable", "add_only"]
    budget_pool: str
    delete_enabled: bool
    over_budget_behavior: Literal["add_paused"]
    tags: list[str] = Field(default_factory=list)


class BudgetPoolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    max_size_tib: float

    @model_validator(mode="after")
    def validate_positive_size(self) -> BudgetPoolConfig:
        if self.max_size_tib <= 0:
            raise ValueError("max_size_tib must be > 0")
        return self


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
