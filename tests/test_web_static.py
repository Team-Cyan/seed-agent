from __future__ import annotations

from pathlib import Path

STATIC_ROOT = Path("src/seed_agent/web/static")


def test_static_assets_exist() -> None:
    assert (STATIC_ROOT / "index.html").exists()
    assert (STATIC_ROOT / "styles.css").exists()
    assert (STATIC_ROOT / "app.js").exists()


def test_index_contains_tracker_first_ui_anchors() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert "Add Tracker" in html
    assert "Tracker" in html
    assert "aria-label=\"Language\"" in html
    assert "aria-label=\"Toggle theme\"" in html
    assert "data-tracker-list" in html
    assert "data-language-menu" in html
    assert "data-section=\"overview\"" in html
    assert "data-section=\"downloader\"" in html


def test_tracker_actions_are_not_top_level_toolbar_items() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert "data-global-actions" not in html
    assert "Validate This Tracker" not in html
    assert "Site Probe" not in html
    assert "Dry-run Preview" not in html


def test_javascript_renders_type_before_type_specific_fields() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "type" in script
    assert "tracker name" in script.lower()
    assert "renderTypeSpecificFields" in script
    assert "renderDiscoveryFields" in script
    assert "Validate This Tracker" in script
    assert "Site Probe" in script
    assert "Dry-run Preview" in script


def test_javascript_gates_tracker_fields_by_discovery_mode() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'tracker.discovery_mode === "api"' in script
    assert 'tracker.discovery_mode === "rss"' in script
    assert "renderApiDiscoveryFields" in script
    assert "renderRssDiscoveryFields" in script


def test_api_key_input_is_plain_text_for_visibility() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-field="api_key_value" type="password"' not in script
    assert 'data-field="api_key_value"' in script


def test_help_icons_use_visible_popover() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "data-help-popover" in html
    assert "data-help" in script
    assert "showHelpPopover" in script
    assert ".help-popover[hidden]" in styles


def test_non_tracker_sections_render_config_panels() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "renderSettingsPanel" in script
    assert "updateSettingsPanelStatus" in script
    assert "data-setting-field" in script
    assert "data-setting-action" in script
    assert 'fetch("/api/config/sections"' in script
    assert "configSections" in script
    assert "qBittorrent target" in script
    assert "Raw YAML preview" in script


def test_javascript_handles_language_menu_and_section_navigation() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderSection" in script
    assert "currentSection" in script
    assert "languageOption" in script
    assert "setLanguage" in script
    assert "Downloader" in script
    assert ".language-menu[hidden]" in styles


def test_javascript_renders_readonly_overview_panel() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'fetch("/api/health")' in script
    assert 'fetch("/api/state/summary")' in script
    assert 'fetch("/api/pools")' in script
    assert "renderOverviewPanel" in script
    assert "metric-card" in script
    assert ".overview-grid" in styles
