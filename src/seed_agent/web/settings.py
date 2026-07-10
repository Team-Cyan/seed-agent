from __future__ import annotations

import re
from difflib import unified_diff
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from seed_agent.config import (
    MTeamApiDiscoveryConfig,
    SeedAgentConfig,
    SiteConfig,
    atomic_write_text,
    load_config_mapping,
    write_config_mapping,
)

CONFIG_SECTION_NAMES = {
    "download_client",
    "pt_filters",
    "seed_cleanup",
    "want_decision",
    "release_preferences",
    "scheduler",
    "want_sources",
}
ConfigSectionName = Literal[
    "download_client",
    "pt_filters",
    "seed_cleanup",
    "want_decision",
    "release_preferences",
    "scheduler",
    "want_sources",
]
LOCAL_SECRETS_DIR = Path("local/secrets")


class TrackerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["nexusphp", "mteam"] | None = None
    name: str = ""
    enabled: bool = True
    rss_url: str = ""
    discovery_mode: Literal["rss", "api"] = "rss"
    api_key_ref: str | None = None
    api_key_value: str | None = None
    auth_header: str | None = None
    cookie_ref: str | None = None


class ConfigSectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section: ConfigSectionName
    data: dict[str, Any]


class ConfigSectionYamlDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    section: ConfigSectionName
    yaml_text: str = Field(alias="yaml")


def config_sections_payload(config: SeedAgentConfig) -> dict[str, Any]:
    return {
        name: getattr(config, name).model_dump(mode="json")
        for name in sorted(CONFIG_SECTION_NAMES)
    }


def config_section_yamls_payload(config: SeedAgentConfig) -> dict[str, str]:
    return {
        name: config_section_yaml_fragment(
            name,
            getattr(config, name).model_dump(mode="json", exclude_none=True),
        )
        for name in sorted(CONFIG_SECTION_NAMES)
    }


def normalized_config_yaml(config: SeedAgentConfig) -> str:
    return _normalized_config_yaml(config)


def config_section_yaml_fragment(section: str, data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        {section: data},
        sort_keys=False,
        allow_unicode=True,
    )


def save_config_section(config_path: Path, draft: ConfigSectionDraft) -> dict[str, Any]:
    raw = load_config_mapping(config_path)
    raw[draft.section] = draft.data
    config = SeedAgentConfig.model_validate(raw)
    raw[draft.section] = getattr(config, draft.section).model_dump(
        mode="json",
        exclude_none=True,
    )
    write_config_mapping(config_path, raw)
    return raw[draft.section]


def save_config_section_yaml(config_path: Path, draft: ConfigSectionYamlDraft) -> dict[str, Any]:
    data = _section_data_from_yaml(draft)
    saved = save_config_section(
        config_path,
        ConfigSectionDraft(section=draft.section, data=data),
    )
    return {
        "section": draft.section,
        "data": saved,
        "yaml": config_section_yaml_fragment(draft.section, saved),
    }


def preview_config_section(config_path: Path, draft: ConfigSectionDraft) -> dict[str, Any]:
    before_raw = load_config_mapping(config_path)
    after_raw = dict(before_raw)
    after_raw[draft.section] = draft.data

    before_config = SeedAgentConfig.model_validate(before_raw)
    after_config = SeedAgentConfig.model_validate(after_raw)
    normalized_section = getattr(after_config, draft.section).model_dump(
        mode="json",
        exclude_none=True,
    )
    before_yaml = _normalized_config_yaml(before_config)
    after_yaml = _normalized_config_yaml(after_config)
    diff = "".join(
        unified_diff(
            before_yaml.splitlines(keepends=True),
            after_yaml.splitlines(keepends=True),
            fromfile="current",
            tofile="preview",
        )
    )
    return {
        "section": draft.section,
        "data": normalized_section,
        "diff": diff,
        "yaml": config_section_yaml_fragment(draft.section, normalized_section),
    }


def preview_config_section_yaml(config_path: Path, draft: ConfigSectionYamlDraft) -> dict[str, Any]:
    data = _section_data_from_yaml(draft)
    return preview_config_section(
        config_path,
        ConfigSectionDraft(section=draft.section, data=data),
    )


def tracker_draft_to_config(draft: TrackerDraft) -> SiteConfig:
    if draft.type is None:
        raise ValueError("type is required")
    if not draft.name.strip():
        raise ValueError("tracker name is required")

    api_key_ref = draft.api_key_ref or _generated_api_key_ref(draft)
    api_discovery = None
    if draft.type == "mteam" and draft.discovery_mode == "api":
        api_discovery = MTeamApiDiscoveryConfig()

    return SiteConfig(
        name=draft.name.strip(),
        type=draft.type,
        enabled=draft.enabled,
        rss_url=draft.rss_url,
        cookie_ref=draft.cookie_ref,
        api_key_ref=api_key_ref,
        auth_header=draft.auth_header or "x-api-key",
        discovery_mode=draft.discovery_mode,
        api_discovery=api_discovery,
    )


def build_tracker_status(draft: TrackerDraft, root: Path) -> list[dict[str, str]]:
    status: list[dict[str, str]] = []
    if draft.type is None:
        status.append({"level": "warning", "message": "type is required"})
    if not draft.name.strip():
        status.append({"level": "warning", "message": "tracker name is required"})
    if (
        draft.discovery_mode == "api"
        and draft.type == "mteam"
        and not draft.api_key_ref
        and not draft.api_key_value
    ):
        status.append(
            {
                "level": "warning",
                "message": "api_key_ref is required when discovery_mode=api",
            }
        )
    if draft.discovery_mode == "api" and draft.type == "mteam" and _generated_api_key_ref(draft):
        status.append(
            {
                "level": "info",
                "message": f"API key will be saved to {_generated_api_key_ref(draft)}",
            }
        )
    if draft.discovery_mode == "rss" and not draft.rss_url.strip():
        status.append({"level": "warning", "message": "rss_url is recommended for rss discovery"})
    if draft.api_key_ref:
        try:
            secret_path = (
                _resolve_secret_write_path(draft.api_key_ref, root)
                if draft.api_key_value is not None
                else _resolve_repo_path(draft.api_key_ref, root)
            )
        except ValueError as exc:
            status.append({"level": "warning", "message": str(exc)})
        else:
            if secret_path.exists():
                status.append({"level": "ok", "message": "API key file exists"})
            else:
                status.append({"level": "warning", "message": "API key file is missing"})
    return status


def save_tracker_draft(config_path: Path, draft: TrackerDraft) -> SiteConfig:
    site = tracker_draft_to_config(draft)
    raw = load_config_mapping(config_path)

    sites = raw.setdefault("tracker_sites", [])
    if not isinstance(sites, list):
        raise ValueError("sites must be a list")

    site_data = site.model_dump(mode="json", exclude_none=True)
    replaced = False
    for index, existing in enumerate(sites):
        if isinstance(existing, dict) and existing.get("name") == site.name:
            sites[index] = site_data
            replaced = True
            break
    if not replaced:
        sites.append(site_data)

    _write_secret_value(
        config_path,
        draft.api_key_ref or _generated_api_key_ref(draft),
        draft.api_key_value,
    )

    write_config_mapping(config_path, raw)
    return site


def _write_secret_value(
    config_path: Path,
    secret_ref: str | None,
    secret_value: str | None,
) -> None:
    if not secret_ref or secret_value is None:
        return
    root = _repo_root_for_config(config_path)
    secret_path = _resolve_secret_write_path(secret_ref, root)
    atomic_write_text(secret_path, secret_value, mode=0o600)


def _repo_root_for_config(config_path: Path) -> Path:
    config_dir = config_path.resolve().parent
    if config_dir.name == "config":
        return config_dir.parent
    return config_dir


def _resolve_repo_path(path_value: str, root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return root / path


def _resolve_secret_write_path(path_value: str, root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        raise ValueError("API key file must be saved under local/secrets")
    resolved = (root / path).resolve()
    secrets_root = (root / LOCAL_SECRETS_DIR).resolve()
    if resolved == secrets_root or not resolved.is_relative_to(secrets_root):
        raise ValueError("API key file must be saved under local/secrets")
    return resolved


def _generated_api_key_ref(draft: TrackerDraft) -> str | None:
    if draft.type != "mteam" or draft.discovery_mode != "api" or not draft.api_key_value:
        return None
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", draft.name.strip().lower()).strip("-")
    if not slug:
        slug = "tracker"
    return f"local/secrets/{slug}.api-key"


def _section_data_from_yaml(draft: ConfigSectionYamlDraft) -> dict[str, Any]:
    loaded = yaml.safe_load(draft.yaml_text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("section YAML must be a mapping")

    if draft.section in loaded:
        section_data = loaded[draft.section] or {}
        if not isinstance(section_data, dict):
            raise ValueError(f"{draft.section} must be a mapping")
        extra_keys = set(loaded) - {draft.section}
        if extra_keys:
            raise ValueError(
                f"section YAML should only contain {draft.section}, got extra keys: "
                f"{', '.join(sorted(extra_keys))}"
            )
        return section_data
    return loaded


def _normalized_config_yaml(config: SeedAgentConfig) -> str:
    return yaml.safe_dump(
        config.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
    )
