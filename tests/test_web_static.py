from __future__ import annotations

from pathlib import Path

STATIC_ROOT = Path("src/seed_agent/web/static")


def test_static_assets_exist() -> None:
    assert (STATIC_ROOT / "index.html").exists()
    assert (STATIC_ROOT / "styles.css").exists()
    assert (STATIC_ROOT / "app.js").exists()


def test_index_contains_tracker_first_ui_anchors() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert "添加站点" in html
    assert "站点" in html
    assert "aria-label=\"Language\"" in html
    assert "aria-label=\"Toggle theme\"" in html
    assert "data-tracker-list" in html
    assert "data-language-menu" in html
    assert "data-config-path" in html
    assert "data-section=\"overview\"" in html
    assert "data-section=\"downloader\"" in html
    assert "data-section=\"search\"" in html
    assert "data-section=\"sources\"" not in html
    assert "data-section=\"wants\"" in html
    assert "获取决策" in html
    assert "种子筛选" in html
    assert "配置文件" in html
    assert "资源意图" not in html
    assert "搜索策略" not in html
    assert "来源集成" not in html


def test_navigation_is_grouped_and_mobile_switchable() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'data-nav-group="operations"' in html
    assert 'data-nav-group="acquisition"' in html
    assert 'data-nav-group="automation"' in html
    assert 'data-nav-group-label="operations"' in html
    assert 'data-section-switcher' in html
    assert 'data-section-group-label' in html
    assert "sectionGroupBySection" in script
    assert "switchSection" in script
    assert "syncNavigationLabels" in script
    assert ".mobile-section-select" in styles


def test_tracker_actions_are_not_top_level_toolbar_items() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert "data-global-actions" not in html
    assert "验证此站点" not in html
    assert "站点探测" not in html
    assert "试运行预览" not in html


def test_javascript_renders_type_before_type_specific_fields() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "type" in script
    assert "站点名称" in script
    assert "renderTypeSpecificFields" in script
    assert "renderDiscoveryFields" in script
    assert "验证此站点" in script
    assert "站点探测" in script
    assert "试运行预览" in script


def test_javascript_gates_tracker_fields_by_discovery_mode() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'tracker.discovery_mode === "api"' in script
    assert 'tracker.discovery_mode === "rss"' in script
    assert "renderApiDiscoveryFields" in script
    assert "renderRssDiscoveryFields" in script


def test_tracker_header_row_toggles_collapse() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "toggleTrackerCard" in script
    assert 'setAttribute("data-tracker-toggle", "header")' in script
    assert 'header.tabIndex = 0' in script
    assert "event.key === \"Enter\"" in script
    assert "event.stopPropagation()" in script
    assert ".tracker-header" in styles
    assert "cursor: pointer" in styles


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
    assert "qBittorrent 目标" in script
    assert "种子筛选" in script
    assert "required_keywords" in script
    assert "want_lists" in script
    assert "watchlist_url" in script
    assert "series_search_mode" in script
    assert "select:season|episode" in script
    assert "removeprefix" not in script
    assert "renderWantsPanel" in script
    assert 'fetch("/api/wants"' in script
    assert "manual-add" not in script
    assert "手动添加" not in script
    assert "coerceSettingValue" in script
    assert "map" in script
    assert "配置文件" in script
    assert "Raw YAML preview" not in script


def test_each_config_page_exposes_section_yaml_editor() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderSectionYamlEditor" in script
    assert "本页 YAML" in script
    assert "data-section-yaml" in script
    assert '"/api/config/sections/yaml/preview"' in script
    assert '"/api/config/sections/yaml"' in script
    assert "renderConfigFilePanel" in script
    assert ".section-yaml-editor" in styles
    assert ".section-yaml-textarea" in styles


def test_settings_pages_use_sticky_action_bar() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "settings-panel-header" in script
    assert "sticky-actions" in script
    assert ".sticky-actions" in styles
    assert "position: sticky" in styles


def test_navigation_uses_user_facing_acquisition_and_torrent_filter_terms() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'intent: "获取决策"' in script
    assert 'search: "种子筛选"' in script
    assert 'title: "获取决策"' in script
    assert 'title: "种子筛选"' in script
    assert "资源意图" not in script
    assert "搜索策略" not in script


def test_want_source_config_gates_provider_specific_fields() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-provider-fields="douban"' in script
    assert 'data-provider-fields="imdb"' in script
    assert "syncWantSourceProviderFields" in script
    assert 'source.provider === "imdb"' in script
    assert '? "imdb" : "douban"' in script
    assert 'providerValue === "douban"' in script
    assert "providerFieldValue" in script


def test_want_list_has_mobile_card_layout() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderWantCard" in script
    assert "want-table-desktop" in script
    assert "want-card-list" in script
    assert ".want-card-list" in styles
    assert ".want-card" in styles


def test_general_sources_panel_is_not_exposed_in_frontend() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "来源集成" not in script
    assert "Telegram 密钥文件" not in script
    assert "WeChat bridge 密钥文件" not in script
    assert "订阅规则文件" not in script
    assert "telegram.secret_ref" not in script
    assert "Douban wanted enabled" not in script
    assert "Douban user name" not in script
    assert "Douban max pages" not in script
    assert "Douban export ref" not in script


def test_non_tracker_section_save_uses_diff_preview_confirmation() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'fetch("/api/config/sections/preview"' in script
    assert "confirmSettingsPanelSave" in script
    assert 'page.addEventListener("change"' in script
    assert "保存确认" in script
    assert "diff-preview" in script
    assert ".diff-preview" in styles


def test_map_setting_reports_invalid_entries_instead_of_dropping_them() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "无效映射项" in script
    assert "readSettingsPanelData(page, section)" in script
    assert "parseMapValue" in script
    assert "parts.length !== 2" in script
    assert 'rawValue.trim() === ""' in script


def test_javascript_handles_language_menu_and_section_navigation() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderSection" in script
    assert "currentSection" in script
    assert "languageOption" in script
    assert "setLanguage" in script
    assert "Downloader" in script
    assert "configPath" in script
    assert ".language-menu[hidden]" in styles
    assert ".config-path" in styles


def test_javascript_renders_readonly_overview_panel() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'fetch("/api/health")' in script
    assert 'fetch("/api/state/summary")' in script
    assert 'fetch("/api/pools")' in script
    assert "renderOverviewPanel" in script
    assert "metric-card" in script
    assert ".overview-grid" in styles
