from __future__ import annotations

import re
from pathlib import Path

STATIC_ROOT = Path("src/seed_agent/web/static")


def test_static_assets_exist() -> None:
    assert (STATIC_ROOT / "index.html").exists()
    assert (STATIC_ROOT / "styles.css").exists()
    assert (STATIC_ROOT / "app.js").exists()


def test_web_brand_uses_the_canonical_runtime_icon() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert html.count("/static/icon.png") == 2
    assert "favicon.svg" not in html


def test_web_token_stays_in_memory_while_ui_preferences_are_persisted() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "data-web-token-button" in html
    assert "data-web-token-button hidden" in html
    assert "X-Seed-Agent-Token" in script
    assert "apiFetch" in script
    assert 'if (method === "POST")' in script
    assert 'headers.set("Content-Type", "application/json")' in script
    assert 'requestInit.body = "{}"' in script
    assert 'webTokenButton?.removeAttribute("hidden")' in script
    assert "seed-agent.ui-preferences.v1" in script
    preferences_block = script[
        script.index("function readUiPreferences") : script.index("function sectionFromLocation")
    ]
    assert "webToken" not in preferences_block
    assert "sessionStorage" not in script


def test_compose_keeps_read_only_root_but_mounts_web_config_paths_writable() -> None:
    compose = Path("deploy/docker-compose.example.yml").read_text(encoding="utf-8")

    assert "read_only: true" in compose
    assert "../config:/app/config:ro" not in compose
    assert "../local:/app/local:ro" not in compose
    assert "../config:/app/config" in compose
    assert "../local:/app/local" in compose


def test_index_contains_tracker_first_ui_anchors() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert "添加站点" in html
    assert "站点" in html
    assert 'aria-label="Language"' in html
    assert 'aria-label="Toggle theme"' in html
    assert "data-tracker-list" in html
    assert "data-language-menu" in html
    assert "data-config-path" in html
    assert 'data-section="overview"' in html
    assert 'data-section="logs"' in html
    assert 'data-section="download_client"' in html
    assert 'data-section="release_preferences"' in html
    assert 'data-section="want_sources"' not in html
    assert 'data-section="wants"' in html
    assert "想看决策" in html
    assert "资源匹配" in html
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
    assert "data-section-switcher" in html
    assert "data-section-group-label" in html
    assert "sectionGroupBySection" in script
    assert "switchSection" in script
    assert "syncNavigationLabels" in script
    assert ".mobile-section-select" in styles


def test_overview_cards_and_dark_neutral_controls_share_theme_tokens() -> None:
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));" in styles
    assert ".overview-summary-strip {\n  display: contents;" in styles
    assert "--nav-active-bg: #2b312d;" in styles
    assert "--neutral-bg: #2b312d;" in styles
    assert "background: var(--neutral-bg);" in styles


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
    assert "header.tabIndex = 0" in script
    assert 'event.key === "Enter"' in script
    assert "event.stopPropagation()" in script
    assert ".tracker-header" in styles
    assert "cursor: pointer" in styles


def test_collapsed_tracker_cards_do_not_render_status_body() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "summarizeTracker" not in script
    assert "summary.textContent = summarizeTracker(tracker)" not in script
    assert "if (!tracker.collapsed)" in script


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
    assert 'apiFetch("/api/config/sections"' in script
    assert "configSections" in script
    assert "newClientId" in script
    assert "globalThis.crypto?.randomUUID" in script
    assert "qBittorrent 目标" in script
    assert "资源匹配" in script
    assert "quality_tag_scores" in script
    assert "renderSearchTagScoreEditor" in script
    assert "readSearchTagScoreData" in script
    assert "Blu-ray" in script
    assert "同组别名只计一次" in script
    assert "want_lists" in script
    assert "watchlist_url" in script
    assert "series_search_mode" in script
    assert "select:season|episode" in script
    assert "renderDownloaderStructuredEditor" in script
    assert "data-media-category-map-field" in script
    assert "data-category-policy-row" in script
    assert "data-budget-pool-row" in script
    assert "removeprefix" not in script
    assert "renderWantsPanel" in script
    assert 'apiFetch("/api/wants"' in script
    assert 'apiFetch("/api/wants/sync"' in script
    assert "manual-add" not in script
    assert "手动添加" not in script
    assert "coerceSettingValue" in script
    assert "map" in script
    assert "配置文件" in script
    assert "Raw YAML preview" not in script


def test_strategy_pages_expose_operator_summary_and_release_presets() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderStrategySummary" in script
    assert "strategySummary" in script
    assert "策略概要" in script
    assert "Strategy summary" in script
    assert "releasePreferencePresets" in script
    assert "movie_remux_first" in script
    assert "tv_webdl_first" in script
    assert "anime_subtitle_friendly" in script
    assert "space_saving" in script
    assert '"1080p":' in script
    assert '"2160p":' in script
    assert "applyReleasePreferencePreset" in script
    assert "data-release-preset" in script
    assert ".strategy-summary" in styles
    assert ".preset-grid" in styles


def test_overview_reads_and_renders_ops_dashboard() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'apiFetch("/api/ops")' in script
    assert "renderOpsSummary" in script
    assert "opsDashboard" in script
    assert "trackerBackoff" in script
    assert "recentSchedulerRuns" in script
    assert "tracker_api_events" in script
    assert "want_search_runs" in script


def test_logs_page_reads_filters_and_refreshes_durable_timeline() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'data-section="logs"' in html
    assert '<option value="logs">' in html
    assert 'apiFetch("/api/logs")' in script
    assert "payload.unavailable_sources" in script
    assert "if (state.logs.unavailableSources.length)" in script
    assert 'uiText("logsPartial")' in script
    assert "section === \"logs\" && !state.logs.refreshedAt" in script
    assert "Promise.all([loadConfig(), loadOverview(), loadWants()])" in script
    assert "renderLogsPanel" in script
    assert 'data-log-filter="source"' in script
    assert 'data-log-filter="level"' in script
    assert "data-log-auto-refresh" in script
    assert "logSourceLabel" in script
    assert ".log-timeline" in styles
    assert ".log-entry-body" in styles


def test_mobile_header_and_want_empty_state_are_compact_and_actionable() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "mobile-section-select" in html
    assert "noWantsHelp" in script
    assert "action-empty-state" in script
    assert "empty-state-actions" in script
    assert 'data-want-action="sync"' in script
    assert 'data-want-action="config-open"' in script
    assert ".page-header p {\n    display: none;" in styles
    assert ".config-path {\n    font-size: 11px;" in styles
    assert ".empty-state-actions" in styles


def test_quality_tag_help_copy_is_device_neutral() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    forbidden_device_terms = [
        "Apple TV",
        "小米",
        "Xiaomi",
        "播放器友好",
        "友好资源",
        "player-friendly",
        "TV-friendly",
    ]
    for term in forbidden_device_terms:
        assert term not in script

    assert "source, player, and display" in script
    assert "Dolby lossless audio format" in script
    assert "Playback requires compatible audio support" in script


def test_want_list_toolbar_exposes_manual_refresh_and_seed_search() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-want-action="sync"' in script
    assert 'data-want-action="search"' in script
    assert 'data-want-action="search-one"' in script
    assert 'data-want-action="mark-viewed"' in script
    assert 'data-want-filter="status"' in script
    assert 'status: "not_downloaded"' in script
    assert "refreshWants" in script
    assert "searchTorrentsCurrentFilter" in script
    assert "searchOneWant" in script
    assert 'if (action === "sync")' in script
    assert 'if (action === "search-one")' in script
    assert 'if (action === "mark-viewed")' in script
    assert "/viewed`, {" in script
    assert "/search`, {" in script
    assert "await syncConfiguredWants(panel);" in script
    assert "await loadWants();" in script


def test_want_list_status_actions_have_a_consistent_layout_group() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'class="want-status-cell"' in script
    assert 'class="want-status-line"' in script
    assert 'class="want-row-actions"' in script
    assert "function wantStatusLabel(status, fallback)" in script
    assert 'downloaded: uiText("downloaded")' in script
    assert 'viewed: uiText("viewed")' in script
    assert "function wantCanSearch(item)" in script
    assert '!["downloaded", "viewed"].includes(item.status)' in script
    assert "function wantCanEnqueue(intent)" in script
    assert "payload.search_history || []" in script
    assert "function renderWantSearchHistory(rows)" in script
    assert ".want-status-line,\n.want-row-actions" in styles
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in styles


def test_want_list_actions_show_immediate_busy_feedback() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "syncingWants" in script
    assert "searchingWants" in script
    assert "setWantActionBusy(panel, button, true)" in script
    assert "setWantActionBusy(panel, button, false)" in script
    assert '[data-want-action="mark-viewed"]' in script
    assert 'item.setAttribute("aria-busy", busy ? "true" : "false")' in script
    assert (
        "`<div class=\"status-item info\">${escapeHtml(uiText(\"syncingWants\"))}</div>`"
        in script
    )
    assert (
        "`<div class=\"status-item info\">${escapeHtml(uiText(\"searchingWants\"))}</div>`"
        in script
    )


def test_want_list_added_at_displays_date_only() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "formatDate(item.added_at)" in script
    assert "function formatDate(value)" in script
    assert 'return String(value).split("T")[0].split(" ")[0];' in script


def test_downloader_page_exposes_visual_category_and_budget_editors() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "readDownloaderStructuredData" in script
    assert "handleDownloaderStructuredAction" in script
    assert 'data-structured-action="add-budget-pool"' in script
    assert 'data-structured-action="add-category-policy"' in script
    assert 'data-budget-pool-field="max_size_tib"' in script
    assert 'data-category-policy-field="budget_pool"' in script
    assert 'data-category-policy-field="delete_enabled"' in script
    assert "renderMediaCategoryMapField" in script
    assert 'renderMediaCategoryMapField("movie"' in script
    assert 'renderMediaCategoryMapField("tv"' in script
    assert 'renderMediaCategoryMapField("anime"' in script
    assert "Want type routing" in script
    assert "想看类型路由" in script
    assert ".structured-editor" in styles
    assert ".structured-row" in styles


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


def test_config_file_navigation_uses_existing_placeholder_key() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    match = re.search(
        r'if \(state\.currentSection === "config_file"\) \{\n(?P<body>.*?)\n  \}',
        script,
        re.DOTALL,
    )

    assert match is not None
    config_file_branch = match.group("body")
    assert "copy[state.language].placeholders.config_file" in config_file_branch
    assert "copy[state.language].placeholders.advanced" not in config_file_branch
    assert "renderConfigFilePanel()" in config_file_branch


def test_settings_pages_use_sticky_action_bar() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "settings-panel-header" in script
    assert "sticky-actions" in script
    assert ".sticky-actions" in styles
    assert "position: sticky" in styles


def test_mobile_settings_actions_are_not_sticky() -> None:
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 700px)" in styles
    assert ".sticky-actions {\n    position: static;" in styles
    assert "box-shadow: none;" in styles


def test_english_mode_covers_dynamic_config_and_tracker_copy() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "settingsPanelsByLanguage" in script
    assert "Default category" in script
    assert "Config file is not loaded" in script
    assert "Full config preview" in script
    assert "Edit common options with the form" in script
    assert "Save form" in script
    assert "This page YAML" in script
    assert "API key file exists" in script
    assert "Choose a type first" in script


def test_want_media_and_state_labels_are_translated() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'tv: "电视剧"' in script
    assert 'tv: "TV"' in script
    assert 'statusDeleted: "已删除"' in script
    assert 'statusDeleted: "Deleted"' in script
    assert 'deleted: uiText("statusDeleted")' in script
    assert 'downloading: uiText("statusDownloading")' in script
    assert 'seeding: uiText("statusSeeding")' in script


def test_mobile_help_controls_remain_tappable() -> None:
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".help {\n    height: 32px;\n    width: 32px;" in styles


def test_navigation_uses_user_facing_acquisition_and_torrent_filter_terms() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'pt_filters: "PT 入队规则"' in script
    assert 'seed_cleanup: "保种清理"' in script
    assert 'want_decision: "想看决策"' in script
    assert 'release_preferences: "资源匹配"' in script
    assert 'title: "PT 入队规则"' in script
    assert 'title: "资源匹配"' in script
    assert 'intent: "获取决策"' not in script
    assert 'search: "种子筛选"' not in script
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
    assert "formatBestCandidateScore" in script
    assert "best_candidate_score" in script
    assert "最高分" in script
    assert "want-table-desktop" in script
    assert "want-card-list" in script
    assert 'role="button" tabindex="0"' in script
    assert "查看候选" in script
    assert 'event.key !== "Enter" && event.key !== " "' in script
    assert ".want-card-list" in styles
    assert ".want-card" in styles
    assert ".want-score-pill" in styles
    assert ".inline-action" in styles


def test_want_list_exposes_candidate_review_drawer() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderWantCandidateModal" in script
    assert "openWantCandidates" in script
    assert "data-want-id" in script
    assert "data-want-candidate-modal" in script
    assert "/api/wants/${encodeURIComponent(intentId)}/candidates" in script
    assert "强制加入 qB" in script
    assert "预览强制入队" not in script
    assert "选择候选" not in script
    assert 'data-want-candidate-action="select"' not in script
    assert 'data-want-candidate-action="preview"' not in script
    assert 'data-want-candidate-action="enqueue"' in script
    assert "formatWantCandidateError" in script
    assert "低匹配" in script
    assert "closeOpenModal" in script
    assert "setModalBusy" in script
    assert ".candidate-card.dimmed" in styles
    assert ".candidate-score" in styles
    assert "candidateDisplayTags" in script
    assert "candidate-subtitle" in script
    assert "candidate-score-details" in script
    assert "candidate-media-info" in script
    assert "评分依据" in script
    assert "/^[a-z][a-z0-9_]*:\\d+$/i.test(tag)" in script
    assert ".candidate-card-footer" in styles
    assert ".candidate-media-info pre" in styles
    assert "opacity: 0.72" not in styles


def test_want_candidate_enqueue_is_single_click_execute() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "enqueueWantCandidate" in script
    assert 'data-want-candidate-action="enqueue"' in script
    assert "const body = { release_id: releaseId };" in script
    assert "renderWantCandidateStatus" in script
    assert "status.innerHTML = renderWantCandidateStatus(statusItem);" in script
    assert '["ok", "info", "warning"].includes(statusItem?.level)' in script
    assert "const resultStatus = payload.status?.[0]" in script
    assert 'status.innerHTML = message ? `<div class="status-item ok">' not in script
    assert "previewWantCandidateEnqueue" not in script
    assert "confirmWantCandidateEnqueue" not in script
    assert "renderWantCandidatePreview" not in script
    assert 'data-want-candidate-action="enqueue-confirm"' not in script
    assert "previewEnqueueQb" not in script
    assert "confirmEnqueueQb" not in script
    assert "enqueuePreviewReady" not in script
    assert "window.confirm" not in script
    assert ".candidate-preview" not in styles


def test_scheduler_controls_are_single_process_and_inline_confirmed() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'data-scheduler-action="trigger"' in script
    assert 'data-scheduler-action="clear-backoff"' in script
    assert '"/api/scheduler/trigger"' in script
    assert '"/api/scheduler/backoff/clear"' in script
    assert "schedulerConfirmClearBackoff" in script
    assert '"tracker_backfill_max_api_requests"' in script
    assert "window.confirm" not in script
    assert '.toggleAttribute("disabled", phase !== "waiting")' in script
    assert ".scheduler-controls" in styles
    assert "function renderSchedulerOperations(ops)" in script
    assert "${renderSchedulerOperations(ops)}" in script
    assert '${section === "scheduler" ? renderSchedulerControls() : ""}' not in script
    assert "data-scheduler-next-cycle" in script
    assert "formatSchedulerNextCycle" in script
    assert "formatRelativeTime" in script


def test_dashboard_attention_does_not_warn_for_review_required_items() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Candidate torrents include failed records." in script
    assert "Resource intents include failed records." in script
    assert "(candidateStates.confirmation_required || 0)" not in script
    assert "(intentStates.confirmation_required || 0)" not in script


def test_mobile_ui_uses_touch_sized_controls_and_modal_actions() -> None:
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "touch-action: manipulation" in styles
    assert "min-height: 44px" in styles
    assert "grid-template-columns: minmax(0, 1fr) 44px 44px" in styles
    assert ".section-eyebrow {\n    display: none;" in styles
    assert ".candidate-actions button:last-child" in styles
    assert "max-height: calc(100vh - 16px)" in styles
    assert "position: sticky" in styles


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

    assert 'apiFetch("/api/config/sections/preview"' in script
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
    assert "restoreUiPreferences" in script
    assert "updateSectionLocation" in script
    assert 'globalThis.addEventListener("hashchange"' in script
    assert "sectionFromLocation() || preferences.currentSection" in script
    assert "globalThis.location.hash = section" in script
    assert ".language-menu[hidden]" in styles
    assert ".config-path" in styles


def test_javascript_renders_readonly_overview_panel() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'apiFetch("/api/health")' in script
    assert 'apiFetch("/api/state/summary")' in script
    assert 'apiFetch("/api/pools")' in script
    assert "renderOverviewPanel" in script
    assert "renderStateChips" in script
    assert "renderBudgetPoolList" in script
    assert "renderAttentionList" in script
    assert "dashboardAttention" in script
    assert "metric-card" in script
    assert ".overview-dashboard" in styles
    assert ".overview-summary-strip" in styles
    assert ".overview-detail-grid" in styles
    assert ".overview-chip" in styles


def test_overview_surfaces_config_and_runtime_provenance() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "runtimeRoot" in script
    assert "renderRuntimeProvenance" in script
    assert "runtimeProvenance" in script
    assert "配置与运行来源" in script
    assert "Config and runtime provenance" in script
    assert "运行根目录" in script
    assert "Runtime root" in script
    assert "状态数据库" in script
    assert "State database" in script
    assert "心跳文件" in script
    assert "Heartbeat file" in script
    assert ".runtime-provenance" in styles
    assert ".runtime-path" in styles


def test_mobile_dashboard_uses_compact_single_column_layout() -> None:
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in styles
    assert ".overview-hero {\n    grid-template-columns: 1fr;" in styles
    assert ".overview-detail-grid {\n    grid-template-columns: 1fr;" in styles
    assert "@media (max-width: 700px)" in styles
    assert ".overview-dashboard {\n    gap: 10px;" in styles
    assert ".metric-card.primary .metric-value {\n    font-size: 28px;" in styles
