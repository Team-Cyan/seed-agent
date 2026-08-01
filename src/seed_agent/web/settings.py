from __future__ import annotations

import hashlib
import re
from difflib import unified_diff
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from seed_agent.config import (
    MTeamApiDiscoveryConfig,
    SeedAgentConfig,
    SiteConfig,
    atomic_write_text,
    load_config_mapping,
    model_dump_preserving_explicit_nulls,
    resolve_runtime_secret_path,
    validate_secret_ref,
    write_config_mapping,
)
from seed_agent.models import safe_url_identity

CONFIG_SECTION_NAMES = {
    "download_client",
    "pt_filters",
    "pt_scoring",
    "seed_cleanup",
    "want_decision",
    "release_preferences",
    "scheduler",
    "metrics",
    "want_sources",
}
ConfigSectionName = Literal[
    "download_client",
    "pt_filters",
    "pt_scoring",
    "seed_cleanup",
    "want_decision",
    "release_preferences",
    "scheduler",
    "metrics",
    "want_sources",
]
_CONFIG_WRITE_LOCK = RLock()


class ConfigRevisionConflict(ValueError):
    def __init__(self, expected: str, current: str) -> None:
        super().__init__("configuration changed since it was loaded; reload before saving")
        self.expected = expected
        self.current = current


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
    revision: str | None = None

    @field_validator("api_key_ref", "cookie_ref")
    @classmethod
    def validate_secret_refs(cls, value: str | None) -> str | None:
        return validate_secret_ref(value) if value else None


class ConfigSectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section: ConfigSectionName
    data: dict[str, Any]
    revision: str | None = None


class ConfigSectionYamlDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    section: ConfigSectionName
    yaml_text: str = Field(alias="yaml")
    revision: str | None = None


def config_sections_payload(config: SeedAgentConfig) -> dict[str, Any]:
    return {
        name: _redact_config_value(getattr(config, name).model_dump(mode="json"))
        for name in sorted(CONFIG_SECTION_NAMES)
    }


def config_section_yamls_payload(config: SeedAgentConfig) -> dict[str, str]:
    return {
        name: config_section_yaml_fragment(
            name,
            _redact_config_value(model_dump_preserving_explicit_nulls(getattr(config, name))),
        )
        for name in sorted(CONFIG_SECTION_NAMES)
    }


def normalized_config_yaml(config: SeedAgentConfig) -> str:
    return _normalized_config_yaml(config)


def config_revision(config_path: Path) -> str:
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


def config_section_yaml_fragment(section: str, data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        {section: data},
        sort_keys=False,
        allow_unicode=True,
    )


def save_config_section(config_path: Path, draft: ConfigSectionDraft) -> dict[str, Any]:
    with _CONFIG_WRITE_LOCK:
        _assert_config_revision(config_path, draft.revision)
        raw = load_config_mapping(config_path)
        raw[draft.section] = _restore_redacted_urls(
            draft.data,
            raw.get(draft.section),
        )
        config = write_config_mapping(config_path, raw)
        return _redact_config_value(
            model_dump_preserving_explicit_nulls(getattr(config, draft.section))
        )


def save_config_section_yaml(config_path: Path, draft: ConfigSectionYamlDraft) -> dict[str, Any]:
    data = _section_data_from_yaml(draft)
    saved = save_config_section(
        config_path,
        ConfigSectionDraft(section=draft.section, data=data, revision=draft.revision),
    )
    return {
        "section": draft.section,
        "data": saved,
        "yaml": config_section_yaml_fragment(draft.section, saved),
        "revision": config_revision(config_path),
    }


def preview_config_section(config_path: Path, draft: ConfigSectionDraft) -> dict[str, Any]:
    _assert_config_revision(config_path, draft.revision)
    before_raw = load_config_mapping(config_path)
    after_raw = dict(before_raw)
    after_raw[draft.section] = _restore_redacted_urls(
        draft.data,
        before_raw.get(draft.section),
    )

    before_config = SeedAgentConfig.model_validate(before_raw)
    after_config = SeedAgentConfig.model_validate(after_raw)
    normalized_section = _redact_config_value(
        model_dump_preserving_explicit_nulls(getattr(after_config, draft.section))
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
        "revision": config_revision(config_path),
    }


def preview_config_section_yaml(config_path: Path, draft: ConfigSectionYamlDraft) -> dict[str, Any]:
    data = _section_data_from_yaml(draft)
    return preview_config_section(
        config_path,
        ConfigSectionDraft(section=draft.section, data=data, revision=draft.revision),
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


def _merge_tracker_draft(
    draft: TrackerDraft,
    existing: dict[str, Any] | None,
) -> tuple[SiteConfig, dict[str, Any]]:
    if draft.type is None:
        raise ValueError("type is required")
    if not draft.name.strip():
        raise ValueError("tracker name is required")

    existing_data = dict(existing or {})
    _validate_tracker_secret_changes(draft, existing_data)
    rss_url = draft.rss_url
    existing_rss_url = existing_data.get("rss_url")
    if isinstance(existing_rss_url, str) and redact_url_credentials(existing_rss_url) == rss_url:
        rss_url = existing_rss_url

    api_key_ref = draft.api_key_ref or _generated_api_key_ref(draft)
    if not api_key_ref and draft.discovery_mode == "api":
        existing_ref = existing_data.get("api_key_ref")
        api_key_ref = str(existing_ref) if existing_ref else None

    site_data = existing_data
    site_data.update(
        {
            "name": draft.name.strip(),
            "type": draft.type,
            "enabled": draft.enabled,
            "rss_url": rss_url,
            "discovery_mode": draft.discovery_mode,
            "api_key_ref": api_key_ref,
        }
    )
    if "cookie_ref" in draft.model_fields_set:
        site_data["cookie_ref"] = draft.cookie_ref
    elif "cookie_ref" not in site_data:
        site_data["cookie_ref"] = None

    if draft.auth_header:
        site_data["auth_header"] = draft.auth_header
    elif not site_data.get("auth_header"):
        site_data["auth_header"] = "x-api-key"

    if draft.type != "mteam":
        site_data.pop("api_discovery", None)
    elif draft.discovery_mode == "api" and not site_data.get("api_discovery"):
        site_data["api_discovery"] = MTeamApiDiscoveryConfig().model_dump(mode="json")

    site = SiteConfig.model_validate(site_data)
    return site, model_dump_preserving_explicit_nulls(site)


def validate_tracker_network_draft(
    draft: TrackerDraft,
    config: SeedAgentConfig,
) -> None:
    existing = next(
        (site for site in config.tracker_sites if site.name == draft.name.strip()),
        None,
    )
    for field_name in ("api_key_ref", "cookie_ref"):
        requested_ref = getattr(draft, field_name)
        if not requested_ref:
            continue
        existing_ref = getattr(existing, field_name) if existing is not None else None
        if requested_ref != existing_ref:
            raise ValueError(
                "tracker network checks may only use credentials already assigned "
                "to the saved tracker"
            )
    if (
        draft.cookie_ref
        and existing is not None
        and _url_origin(draft.rss_url) != _url_origin(existing.rss_url)
    ):
        raise ValueError("tracker cookie cannot be sent to a different RSS origin")


def _validate_tracker_secret_changes(
    draft: TrackerDraft,
    existing: dict[str, Any],
) -> None:
    existing_cookie_ref = existing.get("cookie_ref")
    if draft.cookie_ref and draft.cookie_ref != existing_cookie_ref:
        raise ValueError(
            "Web UI cannot assign an existing cookie file to a tracker; "
            "configure new cookie refs in the local YAML"
        )
    if (
        draft.cookie_ref
        and isinstance(existing.get("rss_url"), str)
        and _url_origin(draft.rss_url) != _url_origin(str(existing["rss_url"]))
    ):
        raise ValueError("tracker cookie cannot be sent to a different RSS origin")

    existing_api_key_ref = existing.get("api_key_ref")
    if draft.api_key_ref and draft.api_key_ref != existing_api_key_ref:
        generated_ref = _generated_api_key_ref(draft)
        if draft.api_key_value is None or draft.api_key_ref != generated_ref:
            raise ValueError(
                "new tracker API keys must be supplied as a value and saved to the "
                "generated tracker-specific secret ref"
            )


def _url_origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    return parsed.scheme.casefold(), parsed.netloc.casefold()


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
    for label, secret_ref in (
        ("API key", draft.api_key_ref),
        ("Cookie", draft.cookie_ref),
    ):
        if not secret_ref:
            continue
        try:
            secret_path = _resolve_secret_write_path(secret_ref, root)
        except ValueError as exc:
            status.append({"level": "warning", "message": str(exc)})
        else:
            if secret_path.exists():
                status.append({"level": "ok", "message": f"{label} file exists"})
            else:
                status.append({"level": "warning", "message": f"{label} file is missing"})
    return status


def save_tracker_draft(config_path: Path, draft: TrackerDraft) -> SiteConfig:
    with _CONFIG_WRITE_LOCK:
        _assert_config_revision(config_path, draft.revision)
        raw = load_config_mapping(config_path)
        sites = raw.setdefault("tracker_sites", [])
        if not isinstance(sites, list):
            raise ValueError("sites must be a list")

        existing = next(
            (
                item
                for item in sites
                if isinstance(item, dict) and item.get("name") == draft.name.strip()
            ),
            None,
        )
        site, site_data = _merge_tracker_draft(draft, existing)
        replaced = False
        for index, item in enumerate(sites):
            if isinstance(item, dict) and item.get("name") == site.name:
                sites[index] = site_data
                replaced = True
                break
        if not replaced:
            sites.append(site_data)

        SeedAgentConfig.model_validate(raw)
        secret_backup = _secret_backup(
            config_path,
            site.api_key_ref,
            draft.api_key_value,
        )
        try:
            _write_secret_value(
                config_path,
                site.api_key_ref,
                draft.api_key_value,
            )
            write_config_mapping(config_path, raw)
        except Exception:
            _restore_secret_backup(secret_backup)
            raise
        return site


def preview_tracker_draft(config_path: Path, draft: TrackerDraft) -> dict[str, Any]:
    _assert_config_revision(config_path, draft.revision)
    before_raw = load_config_mapping(config_path)
    after_raw = dict(before_raw)
    sites = list(after_raw.get("tracker_sites") or [])
    existing = next(
        (
            item
            for item in sites
            if isinstance(item, dict) and item.get("name") == draft.name.strip()
        ),
        None,
    )
    site, site_data = _merge_tracker_draft(draft, existing)
    replaced = False
    for index, existing in enumerate(sites):
        if isinstance(existing, dict) and existing.get("name") == site.name:
            sites[index] = site_data
            replaced = True
            break
    if not replaced:
        sites.append(site_data)
    after_raw["tracker_sites"] = sites
    before_config = SeedAgentConfig.model_validate(before_raw)
    after_config = SeedAgentConfig.model_validate(after_raw)
    before_yaml = _normalized_config_yaml(before_config)
    after_yaml = _normalized_config_yaml(after_config)
    return {
        "tracker": _redact_config_value(site_data),
        "diff": "".join(
            unified_diff(
                before_yaml.splitlines(keepends=True),
                after_yaml.splitlines(keepends=True),
                fromfile="current",
                tofile="preview",
            )
        ),
        "revision": config_revision(config_path),
    }


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


def _secret_backup(
    config_path: Path,
    secret_ref: str | None,
    secret_value: str | None,
) -> tuple[Path, str | None, int | None] | None:
    if not secret_ref or secret_value is None:
        return None
    secret_path = _resolve_secret_write_path(secret_ref, _repo_root_for_config(config_path))
    if not secret_path.exists():
        return secret_path, None, None
    return (
        secret_path,
        secret_path.read_text(encoding="utf-8"),
        secret_path.stat().st_mode & 0o777,
    )


def _restore_secret_backup(backup: tuple[Path, str | None, int | None] | None) -> None:
    if backup is None:
        return
    path, content, mode = backup
    if content is None:
        path.unlink(missing_ok=True)
        return
    atomic_write_text(path, content, mode=mode)


def _repo_root_for_config(config_path: Path) -> Path:
    config_dir = config_path.resolve().parent
    if config_dir.name == "config":
        return config_dir.parent
    return config_dir


def _resolve_secret_write_path(path_value: str, root: Path) -> Path:
    return resolve_runtime_secret_path(path_value, root)


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
        _redact_config_value(model_dump_preserving_explicit_nulls(config)),
        sort_keys=False,
        allow_unicode=True,
    )


def _assert_config_revision(config_path: Path, expected: str | None) -> None:
    if expected is None:
        return
    current = config_revision(config_path)
    if expected != current:
        raise ConfigRevisionConflict(expected, current)


def _redact_config_value(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _redact_config_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_config_value(item, key=key) for item in value]
    if isinstance(value, str) and key is not None and (key == "url" or key.endswith("_url")):
        return redact_url_credentials(value)
    return value


def _restore_redacted_urls(incoming: Any, existing: Any) -> Any:
    if isinstance(incoming, dict):
        existing_mapping = existing if isinstance(existing, dict) else {}
        return {
            key: _restore_redacted_url_field(
                key,
                value,
                existing_mapping.get(key),
            )
            for key, value in incoming.items()
        }
    if isinstance(incoming, list):
        existing_items = existing if isinstance(existing, list) else []
        existing_by_id = {
            str(item.get("id")): item
            for item in existing_items
            if isinstance(item, dict) and item.get("id") is not None
        }
        restored: list[Any] = []
        for index, item in enumerate(incoming):
            previous = existing_items[index] if index < len(existing_items) else None
            if isinstance(item, dict) and item.get("id") is not None:
                previous = existing_by_id.get(str(item.get("id")), previous)
            restored.append(_restore_redacted_urls(item, previous))
        return restored
    return incoming


def _restore_redacted_url_field(key: str, incoming: Any, existing: Any) -> Any:
    if isinstance(incoming, str) and isinstance(existing, str):
        if (key == "url" or key.endswith("_url")) and redact_url_credentials(existing) == incoming:
            return existing
    return _restore_redacted_urls(incoming, existing)


def redact_url_credentials(value: str) -> str:
    safe_value = safe_url_identity(value)
    parts = urlsplit(safe_value)
    safe_query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if "credential" not in {token for token in re.split(r"[^a-z0-9]+", key.lower()) if token}
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(safe_query), parts.fragment)
    )
