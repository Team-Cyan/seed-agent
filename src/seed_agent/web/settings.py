from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from seed_agent.config import MTeamApiDiscoveryConfig, SeedAgentConfig, SiteConfig, load_config

CONFIG_SECTION_NAMES = {
    "downloader",
    "discovery",
    "cleanup",
    "intent",
    "search",
    "sources",
}


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

    section: Literal["downloader", "discovery", "cleanup", "intent", "search", "sources"]
    data: dict[str, Any]


def config_sections_payload(config: SeedAgentConfig) -> dict[str, Any]:
    return {
        name: getattr(config, name).model_dump(mode="json")
        for name in sorted(CONFIG_SECTION_NAMES)
    }


def save_config_section(config_path: Path, draft: ConfigSectionDraft) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")
    raw[draft.section] = draft.data
    config = SeedAgentConfig.model_validate(raw)
    raw[draft.section] = getattr(config, draft.section).model_dump(
        mode="json",
        exclude_none=True,
    )
    config_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return raw[draft.section]


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
        secret_path = _resolve_repo_path(draft.api_key_ref, root)
        if secret_path.exists():
            status.append({"level": "ok", "message": "API key file exists"})
        else:
            status.append({"level": "warning", "message": "API key file is missing"})
    return status


def save_tracker_draft(config_path: Path, draft: TrackerDraft) -> SiteConfig:
    site = tracker_draft_to_config(draft)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")

    sites = raw.setdefault("sites", [])
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

    config_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    load_config(config_path)
    return site


def _write_secret_value(
    config_path: Path,
    secret_ref: str | None,
    secret_value: str | None,
) -> None:
    if not secret_ref or secret_value is None:
        return
    root = _repo_root_for_config(config_path)
    secret_path = _resolve_repo_path(secret_ref, root)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(secret_value, encoding="utf-8")


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


def _generated_api_key_ref(draft: TrackerDraft) -> str | None:
    if draft.type != "mteam" or draft.discovery_mode != "api" or not draft.api_key_value:
        return None
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", draft.name.strip().lower()).strip("-")
    if not slug:
        slug = "tracker"
    return f"local/secrets/{slug}.api-key"
