"""Single configuration authority with independent role validation and secret-free revisions."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from seed_agent import __version__
from seed_agent.media_import.config import MediaImportConfig
from seed_agent.models import safe_url_identity

CONFIG_SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 2_000_000


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    schema_version: Literal[1] = 1


class MediaRoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    deployment: DeploymentConfig | None = None
    media_import: MediaImportConfig


def public_structure(value: Any, *, depth=0, seen=None):
    """Never digest raw secret fields, URL credentials, or loaded credential files."""
    if depth > 32:
        return "<depth-limit>"
    seen = set() if seen is None else seen
    if isinstance(value, (dict, list)):
        if id(value) in seen:
            return "<cycle>"
        seen = seen | {id(value)}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key = str(key)
            lowered = key.casefold()
            secret = any(t in lowered for t in ["password", "token", "api_key", "cookie", "secret"])
            result[key] = (
                "<credential-value>"
                if secret and not lowered.endswith("_ref")
                else public_structure(item, depth=depth + 1, seen=seen)
            )
        return result
    if isinstance(value, list):
        return [public_structure(v, depth=depth + 1, seen=seen) for v in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return safe_url_identity(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(type(value).__name__)


def revision(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            public_structure(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ConfigView:
    role: str
    path: Path
    source_id: str
    full_revision: str
    effective_revision: str
    loaded_at: str
    config: Any
    media_configured: bool

    @property
    def workspace(self) -> Path:
        parent = self.path.parent
        return parent.parent if parent.name == "config" else parent

    def observation(self):
        return {
            "role": self.role,
            "config_source_id": self.source_id,
            "full_revision": self.full_revision,
            "effective_revision": self.effective_revision,
            "applied_revision": self.effective_revision,
            "applied_at": self.loaded_at,
            "application_version": __version__,
            "schema_version": CONFIG_SCHEMA_VERSION,
            "image_digest": os.environ.get("SEED_AGENT_IMAGE_DIGEST"),
            "validation_error": None,
        }


def load_view(path: Path, role: Literal["seed", "media"], *, require_identity=False) -> ConfigView:
    path = path.absolute()
    with path.open("rb") as stream:
        content = stream.read(MAX_CONFIG_BYTES + 1)
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError("configuration exceeds size limit")
    raw = yaml.safe_load(content) or {}
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")
    common = DeploymentConfig.model_validate(raw["deployment"]) if raw.get("deployment") else None
    if require_identity and common is None:
        raise ValueError("media worker requires an explicit deployment.source_id")
    source_id = (
        common.source_id if common else "legacy-" + revision(str(path.parent.resolve()))[:16]
    )
    media_configured = (
        isinstance(raw.get("media_import"), dict) and raw["media_import"].get("enabled") is True
    )
    if role == "media":
        config = MediaRoleConfig.model_validate(
            {"deployment": common, "media_import": raw.get("media_import", {})}
        )
        from seed_agent.config import validate_secret_ref

        for ref in [
            config.media_import.tmdb_secret_ref,
            config.media_import.opensubtitles_secret_ref,
            *(p.secret_ref for p in config.media_import.subtitle_providers),
        ]:
            if ref:
                validate_secret_ref(ref)
        effective = config.model_dump(mode="json")
    else:
        from seed_agent.config import SeedAgentConfig, _validate_config_secret_refs

        owned = {**raw, "media_import": {}}
        config = SeedAgentConfig.model_validate(owned)
        config._config_dir = path.resolve().parent
        config._media_configured = media_configured
        config._media_document = public_structure(raw.get("media_import", {}))
        _validate_config_secret_refs(config, path)
        effective = config.model_dump(mode="json", exclude={"media_import"})
    return ConfigView(
        role,
        path,
        source_id,
        revision(raw),
        revision(effective),
        datetime.now(UTC).isoformat(),
        config,
        media_configured,
    )


class MediaConfigGuard:
    """Revalidation never upgrades initial/command permission; invalid reloads fail closed."""

    def __init__(self, view: ConfigView, *, modes=None):
        self.view = view
        self.modes = modes or {
            kind: getattr(view.config.media_import, kind + "_policy")
            for kind in ["import", "subtitle", "reconcile"]
        }
        self.error = None

    def check(self, kind):
        try:
            current = load_view(self.view.path, "media")
            if (
                current.source_id != self.view.source_id
                or current.effective_revision != self.view.effective_revision
            ):
                raise ValueError("media configuration changed; re-plan required")
            if not current.config.media_import.enabled:
                raise ValueError("media disabled by current configuration")
            if (
                self.modes[kind] != "execute"
                or getattr(current.config.media_import, kind + "_policy") != "execute"
            ):
                raise ValueError("current/command media policy forbids execution")
            self.error = None
            return current
        except (OSError, ValueError) as exc:
            self.error = type(exc).__name__
            raise ValueError("media configuration validation/revision gate rejected write") from exc
