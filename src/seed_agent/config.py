from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from seed_agent.models import Discount
from seed_agent.quality_tags import quality_tag_group_keys

MTeamDiscoveryMode = Literal[
    "normal",
    "adult",
    "movie",
    "music",
    "tvshow",
    "waterfall",
    "rss",
    "rankings",
]


class MTeamApiDiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: MTeamDiscoveryMode | None = "adult"
    modes: list[MTeamDiscoveryMode] = Field(default_factory=list)
    page_number: int = 1
    only_free: bool = True
    discount: (
        Literal[
            "NORMAL",
            "PERCENT_70",
            "PERCENT_50",
            "FREE",
            "_2X_FREE",
            "_2X",
            "_2X_PERCENT_50",
        ]
        | None
    ) = None
    sort_field: Literal[
        "created_date",
        "createdDate",
        "downloads",
        "times_completed",
        "seeders",
        "leechers",
        "size",
        "name",
        "CREATED_DATE",
        "SIZE",
        "SEEDERS",
        "LEECHERS",
        "TIMES_COMPLETED",
        "NAME",
    ] = "downloads"
    sort_order: Literal["asc", "desc"] = "desc"
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
    dmm_field: Literal["kid", "director", "series", "maker", "label", "product_number"] | None = (
        None
    )
    dmm_keyword: str | None = None
    min_seeders: int | None = 0
    max_seeders: int | None = 200
    min_leechers: int | None = 0
    min_times_completed: int = 0

    @field_validator(
        "categories",
        "sources",
        "mediums",
        "standards",
        "video_codecs",
        "audio_codecs",
        "teams",
        "processings",
        "countries",
    )
    @classmethod
    def validate_non_negative_id_list(cls, value: list[int]) -> list[int]:
        if any(item < 0 for item in value):
            raise ValueError("M-Team filter ids must be >= 0")
        return value

    @model_validator(mode="after")
    def validate_limits(self) -> MTeamApiDiscoveryConfig:
        if self.page_number < 1 or self.page_number > 1000:
            raise ValueError("page_number must be between 1 and 1000")
        if self.page_size < 1:
            raise ValueError("page_size must be >= 1")
        if self.page_size > 200:
            raise ValueError("page_size must be <= 200")
        if self.max_pages < 1 or self.max_pages > 20:
            raise ValueError("max_pages must be between 1 and 20")
        if self.last_id is not None and self.last_id < 0:
            raise ValueError("last_id must be >= 0")
        if self.author is not None and self.author < 0:
            raise ValueError("author must be >= 0")
        if self.labels is not None and self.labels < 0:
            raise ValueError("labels must be >= 0")
        if self.visible < 0:
            raise ValueError("visible must be >= 0")
        if self.min_seeders is not None and self.min_seeders < 0:
            raise ValueError("min_seeders must be >= 0")
        if self.min_leechers is not None and self.min_leechers < 0:
            raise ValueError("min_leechers must be >= 0")
        if self.min_times_completed < 0:
            raise ValueError("min_times_completed must be >= 0")
        if len(set(self.modes)) != len(self.modes):
            raise ValueError("modes must not contain duplicates")
        min_seeders = self.min_seeders or 0
        if self.max_seeders not in {None, 0} and self.max_seeders < min_seeders:
            raise ValueError("max_seeders must be >= min_seeders")
        return self


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    type: Literal["nexusphp", "mteam", "torznab"]
    enabled: bool = True
    rss_url: str
    cookie_ref: str | None = None
    api_key_ref: str | None = None
    auth_header: str = "x-api-key"
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
    target_seed_leecher_ratio: float = 16.0
    max_seed_leecher_ratio: float | None = None
    freshness_full_score_hours: float = 6.0
    freshness_zero_score_hours: float = 72.0
    allow_non_free: bool = False
    allow_hr: bool = False
    min_seeders: int | None = None
    max_leechers: int | None = None
    leecher_score_full_at_multiplier: float = 1.0
    min_size_gb: float | None = None
    max_size_gb: float | None = None
    preferred_size_min_gb: float | None = None
    preferred_size_max_gb: float | None = None
    size_partial_max_gb: float = 150.0
    max_active_downloads: int | None = None
    max_total_amount_left_gb: float | None = None
    min_free_disk_gb: float | None = None

    @field_validator("discounts", mode="before")
    @classmethod
    def normalize_discounts(cls, value: Any) -> list[Discount]:
        if value is None:
            raise ValueError("discounts must be a list")
        if not isinstance(value, list):
            raise ValueError("discounts must be a list")
        return [_normalize_discount(item) for item in value]

    @model_validator(mode="after")
    def validate_optional_limits(self) -> DiscoveryConfig:
        for field_name in (
            "min_seeders",
            "max_leechers",
            "min_size_gb",
            "max_size_gb",
            "preferred_size_min_gb",
            "preferred_size_max_gb",
            "size_partial_max_gb",
            "target_seed_leecher_ratio",
            "max_seed_leecher_ratio",
            "freshness_full_score_hours",
            "freshness_zero_score_hours",
            "max_active_downloads",
            "max_total_amount_left_gb",
            "min_free_disk_gb",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be >= 0")
        if (
            self.min_size_gb is not None
            and self.max_size_gb not in {None, 0}
            and self.max_size_gb < self.min_size_gb
        ):
            raise ValueError("max_size_gb must be >= min_size_gb")
        if (
            self.preferred_size_min_gb is not None
            and self.preferred_size_max_gb is not None
            and self.preferred_size_max_gb < self.preferred_size_min_gb
        ):
            raise ValueError("preferred_size_max_gb must be >= preferred_size_min_gb")
        if 0 < self.leecher_score_full_at_multiplier < 1:
            raise ValueError("leecher_score_full_at_multiplier must be 0 or >= 1")
        if (
            self.freshness_zero_score_hours > 0
            and self.freshness_zero_score_hours <= self.freshness_full_score_hours
        ):
            raise ValueError(
                "freshness_zero_score_hours must be 0 or > freshness_full_score_hours"
            )
        return self


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    EXPECTED_WEIGHT_KEYS: ClassVar[tuple[str, ...]] = (
        "discount",
        "leechers",
        "seeders",
        "freshness",
        "left_time",
        "size",
        "site_history",
    )

    min_score_to_enqueue: int
    weights: dict[str, int]

    @model_validator(mode="before")
    @classmethod
    def default_legacy_freshness_weight(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        weights = value.get("weights")
        if not isinstance(weights, dict) or "freshness" in weights:
            return value
        return {**value, "weights": {**weights, "freshness": 0}}

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
        invalid = {key: value for key, value in self.weights.items() if not 0 <= value <= 100}
        if invalid:
            details = ", ".join(f"{key}={value}" for key, value in sorted(invalid.items()))
            raise ValueError(f"weights must each be between 0 and 100; got {details}")
        total = sum(self.weights.values())
        if total != 100:
            raise ValueError(f"weights must sum to 100, got {total}")
        return self


class DownloaderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    VALID_MEDIA_CATEGORY_KEYS: ClassVar[set[str]] = {"movie", "tv", "anime"}

    type: Literal["qbittorrent", "transmission"]
    target: str
    default_category: str
    category_policies: list[CategoryPolicyConfig] = Field(default_factory=list)
    budget_pools: list[BudgetPoolConfig] = Field(default_factory=list)
    media_category_map: dict[str, str] = Field(default_factory=dict)
    secret_ref: str | None = None

    @field_validator("media_category_map", mode="before")
    @classmethod
    def normalize_media_category_map(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("media_category_map must be a mapping")
        normalized: dict[str, str] = {}
        for raw_key, raw_category in value.items():
            key = str(raw_key).strip().lower()
            if key not in cls.VALID_MEDIA_CATEGORY_KEYS:
                allowed = ", ".join(sorted(cls.VALID_MEDIA_CATEGORY_KEYS))
                raise ValueError(f"media_category_map key must be one of: {allowed}")
            if raw_category in {None, ""}:
                continue
            normalized[key] = str(raw_category).strip()
        return normalized

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
        known_policies = set(policy_names)
        for media_type, category in self.media_category_map.items():
            if category not in known_policies:
                raise ValueError(
                    f"media_category_map {media_type} references unknown category {category}"
                )
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
    over_budget_behavior: Literal["reject"]
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_over_budget_behavior(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("over_budget_behavior") == "add_paused":
            return {**value, "over_budget_behavior": "reject"}
        return value


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
    delete_after_no_upload_hours: int = 2
    delete_completed_low_upload_after_hours: int | None = None
    completed_low_upload_min_ratio: float = 0.0
    completed_low_upload_min_gb: float = 0.0
    max_capacity_deletes_per_run: int = 50

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_pause_delay(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "pause_before_delete_hours" not in value:
            return value
        cleaned = dict(value)
        cleaned.pop("pause_before_delete_hours", None)
        return cleaned

    @model_validator(mode="after")
    def validate_cleanup_delays(self) -> CleanupConfig:
        if self.delete_after_no_upload_hours < 1:
            raise ValueError("delete_after_no_upload_hours must be >= 1")
        if (
            self.delete_completed_low_upload_after_hours is not None
            and self.delete_completed_low_upload_after_hours < 1
        ):
            raise ValueError("delete_completed_low_upload_after_hours must be >= 1")
        if self.completed_low_upload_min_ratio < 0:
            raise ValueError("completed_low_upload_min_ratio must be >= 0")
        if self.completed_low_upload_min_gb < 0:
            raise ValueError("completed_low_upload_min_gb must be >= 0")
        if self.max_capacity_deletes_per_run < 1:
            raise ValueError("max_capacity_deletes_per_run must be >= 1")
        return self


class IntentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirmation_threshold: float = 0.82
    auto_enqueue_threshold: float = 0.94
    ambiguity_gap: float = 0.08
    default_resolution: str | None = None
    series_search_mode: Literal["season", "episode"] = "season"
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
    max_api_requests_per_intent: int = 3
    prefer_free: bool = True
    reject_hr_by_default: bool = True
    quality_tag_scores: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_limits(self) -> SearchConfig:
        if self.max_results_per_site < 1:
            raise ValueError("max_results_per_site must be >= 1")
        if self.max_api_requests_per_intent < 1:
            raise ValueError("max_api_requests_per_intent must be >= 1")
        unknown_keys = set(self.quality_tag_scores) - quality_tag_group_keys()
        if unknown_keys:
            raise ValueError(
                "unknown quality tag score keys: " + ", ".join(sorted(unknown_keys))
            )
        return self


class ReleaseProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    default_resolution: str | None = None
    series_search_mode: Literal["season", "episode"] | None = None
    quality_tag_scores: dict[str, int] = Field(default_factory=dict)
    site_priority: dict[str, int] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile(self) -> ReleaseProfileConfig:
        unknown_keys = set(self.quality_tag_scores) - quality_tag_group_keys()
        if unknown_keys:
            raise ValueError(
                "unknown quality tag score keys: " + ", ".join(sorted(unknown_keys))
            )
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("source_ids must not contain duplicates")
        return self


class SecretSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    secret_ref: str | None = None


class DoubanWantedSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    export_ref: str | None = None
    user_name: str | None = None
    max_pages: int = 1

    @model_validator(mode="after")
    def validate_max_pages(self) -> DoubanWantedSourceConfig:
        if self.max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        return self


class WantListSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: Literal["douban", "imdb", "letterboxd"]
    id: str
    label: str
    enabled: bool = True
    user_name: str | None = None
    watchlist_url: str | None = None
    export_ref: str | None = None
    max_pages: int = 1

    @model_validator(mode="after")
    def validate_want_list_source(self) -> WantListSourceConfig:
        if not self.id.strip():
            raise ValueError("want list id must not be empty")
        if not self.label.strip():
            raise ValueError("want list label must not be empty")
        if self.max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        if self.enabled and self.provider == "douban" and not (self.user_name or self.export_ref):
            raise ValueError("douban want list requires user_name or export_ref")
        if self.enabled and self.provider == "imdb" and not (self.watchlist_url or self.export_ref):
            raise ValueError("imdb want list requires watchlist_url or export_ref")
        if self.enabled and self.provider == "letterboxd" and not self.export_ref:
            raise ValueError("letterboxd want list requires export_ref")
        return self


class SubscriptionSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    rules_ref: str | None = None


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    telegram: SecretSourceConfig = Field(default_factory=SecretSourceConfig)
    wechat_bridge: SecretSourceConfig = Field(default_factory=SecretSourceConfig)
    douban_wanted: DoubanWantedSourceConfig = Field(default_factory=DoubanWantedSourceConfig)
    want_lists: list[WantListSourceConfig] = Field(default_factory=list)
    subscription: SubscriptionSourceConfig = Field(default_factory=SubscriptionSourceConfig)


class StateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_retention_days: int = 30
    backup_retention_count: int = 10
    audit_archive_retention_count: int = 20
    audit_archive_max_mb: int = 100

    @model_validator(mode="after")
    def validate_retention(self) -> StateConfig:
        if self.candidate_retention_days < 1:
            raise ValueError("candidate_retention_days must be >= 1")
        if self.backup_retention_count < 1:
            raise ValueError("backup_retention_count must be >= 1")
        if self.audit_archive_retention_count < 1:
            raise ValueError("audit_archive_retention_count must be >= 1")
        if self.audit_archive_max_mb < 1:
            raise ValueError("audit_archive_max_mb must be >= 1")
        return self


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    interval_minutes: int = 60
    capacity_guard_interval_seconds: int = 60
    min_free_window_minutes: int | None = None
    require_known_free_window: bool = True
    prune_enabled: bool = False
    tracker_backfill_enabled: bool = True
    # The task limit remains for compatibility; scheduled work rotates by risk
    # and oldest evidence until the request budget is exhausted.
    tracker_backfill_limit: int | None = None
    tracker_backfill_category: str | None = None
    tracker_backfill_max_api_requests: int = 20
    intent_enabled: bool = True
    intent_execute: bool = False
    intent_search_mode: Literal["daily", "every_cycle"] = "daily"
    intent_search_hour: int = 0
    lease_ttl_minutes: int = 120

    @model_validator(mode="after")
    def validate_scheduler(self) -> SchedulerConfig:
        if self.interval_minutes < 1:
            raise ValueError("scheduler.interval_minutes must be >= 1")
        if self.capacity_guard_interval_seconds < 10:
            raise ValueError("scheduler.capacity_guard_interval_seconds must be >= 10")
        if self.min_free_window_minutes is not None and self.min_free_window_minutes < 0:
            raise ValueError("scheduler.min_free_window_minutes must be >= 0")
        if self.tracker_backfill_limit is not None and self.tracker_backfill_limit < 1:
            raise ValueError("scheduler.tracker_backfill_limit must be >= 1")
        if self.tracker_backfill_max_api_requests < 1:
            raise ValueError("scheduler.tracker_backfill_max_api_requests must be >= 1")
        if not 0 <= self.intent_search_hour <= 23:
            raise ValueError("scheduler.intent_search_hour must be between 0 and 23")
        if self.lease_ttl_minutes < 5:
            raise ValueError("scheduler.lease_ttl_minutes must be >= 5")
        if self.lease_ttl_minutes <= self.interval_minutes:
            raise ValueError("scheduler.lease_ttl_minutes must exceed interval_minutes")
        return self

    def with_overrides(self, overrides: dict[str, Any]) -> SchedulerConfig:
        updates = {key: value for key, value in overrides.items() if value is not None}
        if updates.get("min_free_window_minutes") == 0:
            updates["min_free_window_minutes"] = None
        return SchedulerConfig.model_validate({**self.model_dump(), **updates})


class MetricsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = False
    path: str = "/metrics"

    @model_validator(mode="after")
    def validate_path(self) -> MetricsConfig:
        if not self.path.startswith("/") or self.path == "/":
            raise ValueError("metrics.path must be an absolute non-root HTTP path")
        return self


class SeedAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["balanced"]
    tracker_sites: list[SiteConfig]
    pt_filters: DiscoveryConfig
    pt_scoring: ScoringConfig
    download_client: DownloaderConfig
    seed_cleanup: CleanupConfig
    want_decision: IntentConfig = Field(default_factory=IntentConfig)
    release_preferences: SearchConfig = Field(default_factory=SearchConfig)
    release_profiles: dict[str, ReleaseProfileConfig] = Field(default_factory=dict)
    want_sources: SourcesConfig = Field(default_factory=SourcesConfig)
    local_state: StateConfig = Field(default_factory=StateConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    _config_dir: Path | None = PrivateAttr(default=None)

    @property
    def enabled_sites(self) -> list[SiteConfig]:
        return [site for site in self.tracker_sites if site.enabled]

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


def validate_secret_ref(secret_ref: str) -> str:
    value = secret_ref.strip()
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or len(path.parts) < 3
        or path.parts[:2] != ("local", "secrets")
        or ".." in path.parts
    ):
        raise ValueError("secret refs must be relative files under local/secrets")
    return value


def resolve_runtime_secret_path(secret_ref: str, runtime_root: Path) -> Path:
    value = validate_secret_ref(secret_ref)
    root = runtime_root.resolve()
    secrets_root = (root / "local" / "secrets").resolve()
    resolved = (root / Path(value)).resolve()
    if (
        not secrets_root.is_relative_to(root)
        or resolved == secrets_root
        or not resolved.is_relative_to(secrets_root)
    ):
        raise ValueError("secret refs must resolve to files under runtime local/secrets")
    return resolved


def model_dump_preserving_explicit_nulls(model: BaseModel) -> dict[str, Any]:
    dumped = model.model_dump(mode="json", exclude_none=True)
    _restore_explicit_nulls(dumped, model)
    return dumped


def _restore_explicit_nulls(dumped: Any, source: Any) -> None:
    if isinstance(source, BaseModel) and isinstance(dumped, dict):
        for field_name in type(source).model_fields:
            value = getattr(source, field_name)
            if value is None:
                if field_name in source.model_fields_set:
                    dumped[field_name] = None
                continue
            if field_name in dumped:
                _restore_explicit_nulls(dumped[field_name], value)
        return
    if isinstance(source, list) and isinstance(dumped, list):
        for dumped_item, source_item in zip(dumped, source, strict=False):
            _restore_explicit_nulls(dumped_item, source_item)
        return
    if isinstance(source, dict) and isinstance(dumped, dict):
        for key, source_value in source.items():
            if key in dumped:
                _restore_explicit_nulls(dumped[key], source_value)


def _runtime_root_for_config(path: Path) -> Path:
    config_dir = path.resolve().parent
    return config_dir.parent if config_dir.name == "config" else config_dir


def _validate_config_secret_refs(config: SeedAgentConfig, config_path: Path) -> None:
    runtime_root = _runtime_root_for_config(config_path)
    refs = [config.download_client.secret_ref]
    refs.extend(site.cookie_ref for site in config.tracker_sites)
    refs.extend(site.api_key_ref for site in config.tracker_sites)
    refs.extend(
        (
            config.want_sources.telegram.secret_ref,
            config.want_sources.wechat_bridge.secret_ref,
        )
    )
    for secret_ref in refs:
        if secret_ref:
            resolve_runtime_secret_path(secret_ref, runtime_root)


def load_config_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = loaded or {}
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a mapping")
    return dict(data)


def atomic_write_text(path: Path, content: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def write_config_mapping(path: Path, data: dict[str, Any]) -> SeedAgentConfig:
    config = SeedAgentConfig.model_validate(data)
    _validate_config_secret_refs(config, path)
    normalized = model_dump_preserving_explicit_nulls(config)
    atomic_write_text(
        path,
        yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True),
    )
    config._config_dir = path.resolve().parent
    return config


def load_config(path: Path) -> SeedAgentConfig:
    data = load_config_mapping(path)
    config = SeedAgentConfig.model_validate(data)
    _validate_config_secret_refs(config, path)
    config._config_dir = path.resolve().parent
    return config
