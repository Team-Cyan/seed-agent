"""Downloader-independent media configuration. All writer policies default to preview."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from seed_agent.media_import.routing import Destinations, Source, validate_sources


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    source_root: str
    target_root: str
    marker: str = ".media-volume"
    marker_value: str
    target_marker_value: str
    target_marker: str | None = None
    media_type: Literal["movie", "tv", "anime"] = "movie"
    readiness: Literal["completed_folder", "manual"] = "manual"
    completed_contract_acknowledged: bool = False
    min_age_seconds: int = Field(default=60, ge=0)
    exclude_dirs: list[str] = Field(default_factory=lambda: ["incomplete"])
    naming_backend: Literal["plex"] = "plex"
    title_policy: Literal["original", "localized", "english"] = "original"
    locale: str = "zh-CN"
    languages: list[list[str]] = Field(default_factory=lambda: [["zh-Hans", "zh-Hant"]])
    subtitle_kind: Literal["full", "forced", "sdh"] = "full"
    max_subtitles: int = Field(default=5, ge=1, le=10)
    missing_scans: int = Field(default=2, ge=2)
    grace_seconds: int = Field(default=86400, ge=0)
    max_cleanup_batch: int = Field(default=10, ge=1)
    max_missing_fraction: float = Field(default=0.5, gt=0, le=1)
    _mixed: bool = PrivateAttr(default=False)
    _source_only: bool = PrivateAttr(default=False)
    _route_id: str = PrivateAttr(default="legacy")
    _route_subdir: str = PrivateAttr(default="")
    _historical_descriptor: dict | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def safe_paths(self):
        roots = [Path(self.source_root), Path(self.target_root)]
        if not all(p.is_absolute() for p in roots):
            raise ValueError("media roots must be absolute")
        a, b = (p.resolve() for p in roots)
        if a == b or a in b.parents or b in a.parents:
            raise ValueError("media source and target roots must be disjoint")
        if Path(self.marker).name != self.marker or self.marker in {"", ".", ".."}:
            raise ValueError("marker must be a single filename")
        if self.target_marker is not None and (
            Path(self.target_marker).name != self.target_marker
            or self.target_marker in {"", ".", ".."}
        ):
            raise ValueError("target marker must be a single filename")
        if any(Path(x).name != x or x in {"", ".", ".."} for x in self.exclude_dirs):
            raise ValueError("exclude_dirs must contain directory names")
        if self.readiness == "completed_folder" and not self.completed_contract_acknowledged:
            raise ValueError("completed folder requires explicit contract acknowledgement")
        if not self.marker_value or not self.target_marker_value:
            raise ValueError("volume markers cannot be empty")
        if not self.languages or any(not x for x in self.languages):
            raise ValueError("language requirements cannot be empty")
        if any(x not in {"zh-Hans", "zh-Hant", "zh", "en"} for g in self.languages for x in g):
            raise ValueError("unsupported subtitle language")
        return self


class SubtitleProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["opensubtitlescom", "assrt", "subdl"]
    secret_ref: str | None = None
    enabled: bool = True


class MediaImportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    state_path: str = ".media-import/state.db"
    work_batch_size: int = Field(default=10, ge=1, le=50)
    max_inventory_files: int = Field(default=20000, ge=1, le=100000)
    inventory_timeout_seconds: int = Field(default=60, ge=1, le=300)
    profiles: list[Profile] = Field(default_factory=list, max_length=64)
    sources: list[Source] = Field(default_factory=list, max_length=64)
    destinations: Destinations | None = None
    interval_seconds: int = Field(default=1800, ge=1)
    import_policy: Literal["preview", "execute"] = "preview"
    subtitle_policy: Literal["preview", "execute"] = "preview"
    reconcile_policy: Literal["preview", "execute"] = "preview"
    tmdb_secret_ref: str | None = None
    opensubtitles_secret_ref: str | None = None
    subtitle_providers: list[SubtitleProviderConfig] = Field(default_factory=list, max_length=3)
    subtitle_refresh_seconds: int = Field(default=86400, ge=60)
    retry_horizon_seconds: int = Field(default=604800, ge=60)
    provider_interval_seconds: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def unique_profiles(self):
        if len({p.name for p in self.subtitle_providers}) != len(self.subtitle_providers):
            raise ValueError("duplicate subtitle provider")
        if self.sources:
            if self.profiles:
                raise ValueError("mixed sources and legacy profiles require explicit migration")
            if self.destinations is None:
                raise ValueError("mixed sources require separate destinations")
            validate_sources(self.sources, self.destinations)
        if len({p.name for p in self.profiles}) != len(self.profiles):
            raise ValueError("duplicate media profile")
        for i, p in enumerate(self.profiles):
            for q in self.profiles[i + 1 :]:
                a, b = Path(p.source_root).resolve(), Path(q.source_root).resolve()
                if a == b or a in b.parents or b in a.parents:
                    raise ValueError("source profiles must be disjoint")
                for source, target in [
                    (p.source_root, q.target_root),
                    (q.source_root, p.target_root),
                ]:
                    a, b = Path(source).resolve(), Path(target).resolve()
                    if a == b or a in b.parents or b in a.parents:
                        raise ValueError("cross-profile source/output overlap")
        return self
