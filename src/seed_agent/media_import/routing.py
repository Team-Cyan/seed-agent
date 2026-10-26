"""Mixed-source configuration and explicit metadata-to-destination resolution."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    root: str
    marker: str = ".media-volume"
    marker_value: str
    readiness: Literal["completed_folder", "manual"] = "manual"
    completed_contract_acknowledged: bool = False
    min_age_seconds: int = Field(default=60, ge=0)
    exclude_dirs: list[str] = Field(default_factory=lambda: ["incomplete"])
    legacy_output_roots: list[str] = Field(default_factory=list, max_length=64)
    languages: list[list[str]] = Field(default_factory=lambda: [["zh-Hans", "zh-Hant"]])
    subtitle_kind: Literal["full", "forced", "sdh"] = "full"
    max_subtitles: int = Field(default=5, ge=1, le=10)
    missing_scans: int = Field(default=2, ge=2)
    grace_seconds: int = Field(default=86400, ge=0)
    max_cleanup_batch: int = Field(default=10, ge=1)
    max_missing_fraction: float = Field(default=0.5, gt=0, le=1)

    @model_validator(mode="after")
    def validate_source(self):
        if not Path(self.root).is_absolute():
            raise ValueError("source root must be absolute")
        for value in [self.marker, *self.exclude_dirs]:
            if Path(value).name != value or value in {"", ".", ".."}:
                raise ValueError("marker/exclusions must be single names")
        normalized = []
        for value in self.legacy_output_roots:
            path = Path(value)
            if not path.is_absolute():
                raise ValueError("excluded output roots must be absolute")
            if (
                path.resolve() == Path(self.root).resolve()
                or path.resolve() in Path(self.root).resolve().parents
            ):
                raise ValueError("excluded output cannot contain source")
            normalized.append(os.path.normpath(value))
        self.legacy_output_roots = sorted(set(normalized))
        if not self.marker_value:
            raise ValueError("source marker cannot be empty")
        if self.readiness == "completed_folder" and not self.completed_contract_acknowledged:
            raise ValueError("completed folder requires explicit contract acknowledgement")
        if not self.languages or any(not r for r in self.languages):
            raise ValueError("empty subtitle language requirement")
        if any(v not in {"zh-Hans", "zh-Hant", "zh", "en"} for r in self.languages for v in r):
            raise ValueError("unsupported subtitle language")
        return self


class Destination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: str
    marker: str = ".media-volume"
    marker_value: str
    title_policy: Literal["original", "localized", "english"] = "original"
    locale: str = "zh-CN"

    @model_validator(mode="after")
    def validate_destination(self):
        if not Path(self.root).is_absolute():
            raise ValueError("destination root must be absolute")
        if (
            Path(self.marker).name != self.marker
            or self.marker in {"", ".", ".."}
            or not self.marker_value
        ):
            raise ValueError("invalid destination marker")
        return self


class Destinations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    library_root: str | None = None
    movies: Destination
    tv: Destination
    animation: Destination | None = None
    animated_movies: Destination | None = None
    animated_tv: Destination | None = None

    @model_validator(mode="after")
    def animation_routes(self):
        if self.animation and (self.animated_movies or self.animated_tv):
            raise ValueError("choose animation base or separate animated roots")
        if not self.animation and not self.animated_tv:
            raise ValueError("animated TV destination is required without animation base")
        if self.library_root:
            library = Path(self.library_root)
            if not library.is_absolute():
                raise ValueError("library root must be absolute")
            if any(
                not Path(root).resolve().is_relative_to(library.resolve())
                for root in self.physical_roots()
            ):
                raise ValueError("all destinations must be within the library output root")
        selected = [
            self.route(kind, animation) for kind in ["movie", "tv"] for animation in [False, True]
        ]
        for i, (route, root, subdir) in enumerate(selected):
            a = (Path(root.root) / subdir).resolve()
            for other_route, other, other_subdir in selected[i + 1 :]:
                b = (Path(other.root) / other_subdir).resolve()
                same_type = (route in {"movies", "animated_movies"}) == (
                    other_route in {"movies", "animated_movies"}
                )
                if (
                    a == b
                    and same_type
                    and root.model_dump(exclude={"root"}) == other.model_dump(exclude={"root"})
                ):
                    continue
                if a == b or a in b.parents or b in a.parents:
                    raise ValueError("effective destination roots must be disjoint")
        return self

    def exclusion_roots(self):
        return self.physical_roots() + ([self.library_root] if self.library_root else [])

    def physical_roots(self):
        return sorted(
            {
                getattr(self, key).root
                for key in ["movies", "tv", "animation", "animated_movies", "animated_tv"]
                if getattr(self, key) is not None
            }
        )

    def route(self, content_type, animation):
        if content_type not in {"movie", "tv"} or type(animation) is not bool:
            raise ValueError("confirmed content type and animation evidence required")
        if not animation:
            key = "movies" if content_type == "movie" else "tv"
            return key, getattr(self, key), ""
        key = "animated_movies" if content_type == "movie" else "animated_tv"
        if self.animation:
            return key, self.animation, "Movies" if content_type == "movie" else "TV"
        destination = (
            (self.animated_movies or self.movies) if content_type == "movie" else self.animated_tv
        )
        if destination is None:
            raise ValueError("animated TV destination is not configured")
        return key, destination, ""


def validate_sources(sources, targets):
    if len({s.id for s in sources}) != len(sources):
        raise ValueError("duplicate source ID")
    for i, source in enumerate(sources):
        a = Path(source.root).resolve()
        for other in sources[i + 1 :]:
            b = Path(other.root).resolve()
            if a == b or a in b.parents or b in a.parents:
                raise ValueError("source roots overlap")
        for root in [
            *targets.exclusion_roots(),
            *(p for s in sources for p in s.legacy_output_roots),
        ]:
            b = Path(root).resolve()
            if a == b or b in a.parents:
                raise ValueError("destination cannot equal or contain a source")


def source_adapter(source):
    from seed_agent.media_import.config import Profile

    fields = source.model_dump(exclude={"id", "root", "legacy_output_roots"})
    result = Profile.model_construct(
        name=source.id, source_root=source.root, target_root="", target_marker_value="", **fields
    )
    result._mixed = True
    result._source_only = True
    return result


def apply_descriptor(profile, descriptor):
    result = profile.model_copy(
        update={
            "target_root": descriptor["root"],
            "target_marker": descriptor["marker"],
            "target_marker_value": descriptor["marker_value"],
        }
    )
    result._source_only = False
    result._route_id = descriptor["route"]
    result._route_subdir = descriptor.get("subdir", "")
    result._historical_descriptor = descriptor
    return result


def effective_profile(profile, mapping, destinations):
    if not profile._mixed:
        return profile
    values = mapping.model_dump() if hasattr(mapping, "model_dump") else mapping
    route, destination, subdir = destinations.route(values["media_type"], values.get("animation"))
    result = profile.model_copy(
        update={
            "target_root": destination.root,
            "target_marker": destination.marker,
            "target_marker_value": destination.marker_value,
            "title_policy": destination.title_policy,
            "locale": destination.locale,
            "media_type": values["media_type"],
        }
    )
    result._source_only = False
    result._route_id = route
    result._route_subdir = subdir
    return result
