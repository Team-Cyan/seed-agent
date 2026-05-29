const state = {
  trackers: [],
  overview: {
    health: null,
    stateSummary: null,
    pools: null,
    error: null,
  },
  wants: {
    items: [],
    error: null,
    loading: true,
    filters: {
      source: "all",
      media_type: "all",
    },
  },
  configSections: {},
  sectionYamls: {},
  configYaml: "",
  configPath: "",
  language: "CN",
  dark: false,
  currentSection: "overview",
};

const trackerList = document.querySelector("[data-tracker-list]");
const addTrackerButton = document.querySelector("[data-add-tracker]");
const themeButton = document.querySelector("[data-theme-button]");
const languageButton = document.querySelector("[data-language-button]");
const languageMenu = document.querySelector("[data-language-menu]");
const helpPopover = document.querySelector("[data-help-popover]");
const configPathLabel = document.querySelector("[data-config-path]");
const sectionSwitcher = document.querySelector("[data-section-switcher]");
const sectionGroupLabel = document.querySelector("[data-section-group-label]");
const navGroupLabels = document.querySelectorAll("[data-nav-group-label]");
const navItems = document.querySelectorAll("[data-section]");

const copy = {
  CN: {
    groups: {
      operations: "运行",
      automation: "连接",
      acquisition: "策略",
      advanced: "配置",
    },
    nav: {
      overview: "状态",
      tracker: "站点",
      downloader: "下载器",
      discovery: "发现策略",
      cleanup: "清理策略",
      intent: "获取决策",
      wants: "想看列表",
      search: "种子筛选",
      advanced: "配置文件",
    },
    overviewTitle: "状态",
    overviewSubtitle: "本地只读状态：心跳、候选/意图数量和配置的容量池。",
    trackerTitle: "站点",
    trackerSubtitle: "配置 PT 站点接入方式、认证文件和试运行检查。",
    addTracker: "添加站点",
    emptyTracker: "还没有站点。点击右上角添加站点开始配置。",
    placeholders: {
      downloader: {
        title: "下载器",
        description: "配置 qBittorrent 目标、默认分类、分类策略和容量池。",
      },
      discovery: {
        title: "发现策略",
        description: "配置优惠标签、做种/下载数、体积上限和运行时限制。",
      },
      cleanup: {
        title: "清理策略",
        description: "配置冷种判断、保护项和删除前暂停观察。",
      },
      intent: {
        title: "获取决策",
        description: "配置自动找片/入队阈值、模糊确认、剧集搜索方式和收件箱。",
      },
      wants: {
        title: "想看列表",
        description: "集中查看 Douban 和 IMDb 想看资源，以及搜索/入队状态。",
      },
      search: {
        title: "种子筛选",
        description: "配置候选种子的站点优先级、结果数量和 Remux/4K/HDR 关键词过滤。",
      },
      advanced: {
        title: "配置文件",
        description: "查看当前配置文件和各配置页对应的 YAML 区块。",
      },
    },
  },
  EN: {
    groups: {
      operations: "Run",
      automation: "Connections",
      acquisition: "Rules",
      advanced: "Config",
    },
    nav: {
      overview: "Status",
      tracker: "Tracker",
      downloader: "Downloader",
      discovery: "Discovery",
      cleanup: "Cleanup",
      intent: "Acquisition",
      wants: "Want List",
      search: "Torrent Filters",
      advanced: "Config File",
    },
    overviewTitle: "Status",
    overviewSubtitle: "Local read-only status: heartbeat, candidate/intent counts, and configured budget pools.",
    trackerTitle: "Tracker",
    trackerSubtitle: "New users start empty. Click Add Tracker to create a tracker card.",
    addTracker: "Add Tracker",
    emptyTracker: "No trackers yet. Click Add Tracker in the top right to start.",
    placeholders: {
      downloader: {
        title: "Downloader",
        description: "This section will configure the qBittorrent target, category policies, and budget pools.",
      },
      discovery: {
        title: "Discovery",
        description: "This section will configure freeleech filters, seed/leech limits, size bounds, and runtime gates.",
      },
      cleanup: {
        title: "Cleanup",
        description: "This section will configure cold torrent rules, protections, and pause-before-delete behavior.",
      },
      intent: {
        title: "Acquisition Rules",
        description: "Configure score thresholds, ambiguity handling, series mode, and inbox settings for automated acquisition.",
      },
      wants: {
        title: "Want List",
        description: "Review Douban and IMDb wants with search and queue status.",
      },
      search: {
        title: "Torrent Filters",
        description: "Configure candidate torrent limits, site priority, and Remux/4K/HDR keyword filters.",
      },
      advanced: {
        title: "Config File",
        description: "Review the active config file and the YAML sections edited by each page.",
      },
    },
  },
};

const settingsPanels = {
  downloader: {
    title: "下载器",
    fields: [
      ["qBittorrent 目标", "target", "text", "选择下载器目标。会写入 downloader.target。"],
      ["默认分类", "default_category", "text", "默认加入的 qBittorrent 分类。"],
      ["凭据文件", "secret_ref", "optional-text", "本地 qB 凭据文件路径，不保存明文。"],
    ],
  },
  discovery: {
    title: "发现策略",
    fields: [
      ["优惠标签", "discounts", "csv", "候选折扣过滤，例如 free 或 2xfree。"],
      ["免费剩余时间下限", "min_left_time_minutes", "number", "免费窗口剩余分钟数低于此值时不自动加入。"],
      ["最小做种数", "min_seeders", "optional-number", "低于此做种数时不自动加入；留空表示不限制。"],
      ["最小下载数", "min_leechers", "number", "低于这个下载需求时不自动加入。"],
      ["目标做种/下载比", "target_seed_leecher_ratio", "number", "控制热门程度，不再使用绝对做种数上限。"],
      ["允许非免费", "allow_non_free", "boolean", "是否允许普通候选进入评分。"],
      ["最大体积 GB", "max_size_gb", "optional-number", "候选硬大小上限；留空表示不限制。"],
      ["最大活动下载数", "max_active_downloads", "optional-number", "超过后将候选转为暂停添加。"],
      ["最大剩余下载量 GB", "max_total_amount_left_gb", "optional-number", "剩余下载总量超过后暂停添加。"],
    ],
  },
  cleanup: {
    title: "清理策略",
    fields: [
      ["冷种天数", "cold_after_days", "number", "多久没有有效上传后视为冷种。"],
      ["最小上传增量 GB", "min_upload_delta_gb", "number", "上传增量低于此值才进入清理候选。"],
      ["保护 HR", "protect_hr", "boolean", "HR 风险项默认保护。"],
      ["保护手动标记", "protect_manual", "boolean", "手动标记项默认保护。"],
      ["保护媒体库", "protect_media_library", "boolean", "媒体库相关种子默认保护。"],
      ["零上传删除小时数", "delete_after_no_upload_hours", "number", "零上传观察窗口。"],
      ["删除前暂停小时数", "pause_before_delete_hours", "number", "删除前先暂停观察的小时数。"],
    ],
  },
  intent: {
    title: "获取决策",
    fields: [
      ["确认阈值", "confirmation_threshold", "number", "高于此阈值可进入确认流程。"],
      ["自动入队阈值", "auto_enqueue_threshold", "number", "高于此阈值可自动入队。"],
      ["模糊分差", "ambiguity_gap", "number", "候选分差低于此值时视为模糊。"],
      ["默认清晰度", "default_resolution", "optional-text", "默认解析度偏好。"],
      ["剧集搜索方式", "series_search_mode", "select:season|episode", "电视剧/动漫按整季搜索或按单集搜索。"],
      ["偏好语言", "preferred_languages", "csv", "按逗号填写语言偏好。"],
      ["收件箱文件", "inbox_ref", "text", "本地意图收件箱 JSONL 路径。"],
    ],
  },
  search: {
    title: "种子筛选",
    fields: [
      ["站点优先级", "site_priority", "map", "按 site=priority 填写，例如 mteam=10。只影响搜索排序，不保存 secret。"],
      ["每站结果上限", "max_results_per_site", "number", "每个站点最多保留的搜索结果数量。"],
      ["优先免费", "prefer_free", "boolean", "搜索排序中优先 free/freeleech 资源。"],
      ["默认排除 HR", "reject_hr_by_default", "boolean", "默认拒绝 HR 风险资源。"],
      ["必须包含关键词", "required_keywords", "csv", "必须出现在搜索结果标题中的关键词，例如 Remux。"],
      ["偏好关键词", "preferred_keywords", "csv", "加分关键词，例如 2160p、HDR 或 Dolby Vision。"],
      ["排除关键词", "excluded_keywords", "csv", "排除关键词，例如 CAM、TC 或 Hardcoded。"],
    ],
  },
};

const navigationSections = [
  "overview",
  "wants",
  "tracker",
  "downloader",
  "discovery",
  "cleanup",
  "intent",
  "search",
  "advanced",
];

const sectionGroupBySection = {
  overview: "operations",
  wants: "operations",
  tracker: "automation",
  downloader: "automation",
  discovery: "acquisition",
  cleanup: "acquisition",
  intent: "acquisition",
  search: "acquisition",
  advanced: "advanced",
};

addTrackerButton.addEventListener("click", () => {
  state.trackers.unshift({
    id: newClientId(),
    type: "",
    name: "",
    enabled: true,
    rss_url: "",
    discovery_mode: "rss",
    api_key_ref: "",
    api_key_value: "",
    auth_header: "x-api-key",
    cookie_ref: "",
    saved: false,
    collapsed: false,
    status: [
      { level: "warning", message: "类型必填" },
      { level: "warning", message: "站点名称必填" },
      { level: "info", message: "尚未保存" },
    ],
  });
  renderSection();
});

themeButton.addEventListener("click", () => {
  state.dark = !state.dark;
  document.body.classList.toggle("dark", state.dark);
  themeButton.textContent = state.dark ? "☾" : "☀";
});

languageButton.addEventListener("click", () => {
  languageMenu.hidden = !languageMenu.hidden;
});

languageMenu.addEventListener("click", (event) => {
  const language = event.target?.dataset?.languageOption;
  if (language) {
    setLanguage(language);
  }
});

document.addEventListener("click", (event) => {
  const helpTarget = event.target.closest?.("[data-help]");
  if (helpTarget) {
    event.preventDefault();
    showHelpPopover(helpTarget);
    return;
  }
  if (!event.target.closest?.("[data-help-popover]")) {
    hideHelpPopover();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    hideHelpPopover();
  }
});

navItems.forEach((item) => {
  item.addEventListener("click", () => {
    switchSection(item.dataset.section);
  });
});

sectionSwitcher.addEventListener("change", () => {
  switchSection(sectionSwitcher.value);
});

function switchSection(section) {
  if (!navigationSections.includes(section)) {
    return;
  }
  state.currentSection = section;
  navItems.forEach((navItem) => {
    navItem.classList.toggle("active", navItem.dataset.section === section);
  });
  sectionSwitcher.value = section;
  renderSection();
}

function syncNavigationLabels() {
  navItems.forEach((item) => {
    item.textContent = copy[state.language].nav[item.dataset.section];
  });
  Array.from(sectionSwitcher.options).forEach((option) => {
    option.textContent = copy[state.language].nav[option.value];
  });
  navGroupLabels.forEach((label) => {
    label.textContent = copy[state.language].groups[label.dataset.navGroupLabel];
  });
}

async function loadConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) {
    renderSection();
    return;
  }
  const payload = await response.json();
  state.configSections = payload.sections || {};
  state.sectionYamls = payload.section_yamls || {};
  state.configYaml = payload.config_yaml || "";
  state.configPath = payload.config_path || "";
  state.trackers = payload.trackers.map((tracker) => ({
    id: newClientId(),
    type: tracker.type,
    name: tracker.name,
    enabled: tracker.enabled,
    rss_url: tracker.rss_url,
    discovery_mode: tracker.discovery_mode,
    api_key_ref: tracker.api_key_ref || "",
    api_key_value: "",
    auth_header: "x-api-key",
    cookie_ref: tracker.cookie_ref || "",
    saved: true,
    collapsed: true,
    status: tracker.has_api_key
      ? [{ level: "ok", message: "API key 文件已存在" }]
      : [{ level: "info", message: "尚未检查" }],
  }));
  renderSection();
}

async function loadOverview() {
  try {
    const [healthResponse, stateResponse, poolsResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/state/summary"),
      fetch("/api/pools"),
    ]);
    if (!healthResponse.ok || !stateResponse.ok || !poolsResponse.ok) {
      throw new Error("状态读取失败");
    }
    state.overview = {
      health: await healthResponse.json(),
      stateSummary: await stateResponse.json(),
      pools: await poolsResponse.json(),
      error: null,
    };
  } catch (error) {
    state.overview = {
      health: null,
      stateSummary: null,
      pools: null,
      error: error.message,
    };
  }
}

async function loadWants() {
  try {
    const response = await fetch("/api/wants");
    if (!response.ok) {
      throw new Error("想看列表读取失败");
    }
    const payload = await response.json();
    state.wants = {
      items: payload.items || [],
      error: null,
      loading: false,
      filters: state.wants.filters,
    };
  } catch (error) {
    state.wants = {
      items: [],
      error: error.message,
      loading: false,
      filters: state.wants.filters,
    };
  }
}

async function loadInitialData() {
  await Promise.all([loadConfig(), loadOverview(), loadWants()]);
  renderSection();
}

function renderSection() {
  const title = document.querySelector(".page-header h1");
  const subtitle = document.querySelector(".page-header p");
  const groupKey = sectionGroupBySection[state.currentSection] || "operations";
  sectionGroupLabel.textContent = copy[state.language].groups[groupKey];
  trackerList.setAttribute("aria-label", copy[state.language].nav[state.currentSection] || "Content");
  configPathLabel.textContent = state.configPath ? `配置文件: ${state.configPath}` : "配置文件: 尚未加载";
  if (state.currentSection === "overview") {
    title.textContent = copy[state.language].overviewTitle;
    subtitle.textContent = copy[state.language].overviewSubtitle;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderOverviewPanel());
    return;
  }
  if (state.currentSection === "wants") {
    const placeholder = copy[state.language].placeholders.wants;
    title.textContent = placeholder.title;
    subtitle.textContent = placeholder.description;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderWantsPanel());
    return;
  }
  if (state.currentSection === "advanced") {
    const placeholder = copy[state.language].placeholders.advanced;
    title.textContent = placeholder.title;
    subtitle.textContent = placeholder.description;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderConfigFilePanel());
    return;
  }
  if (state.currentSection !== "tracker") {
    const placeholder = copy[state.language].placeholders[state.currentSection];
    title.textContent = placeholder.title;
    subtitle.textContent = placeholder.description;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderSettingsPanel(state.currentSection));
    return;
  }
  title.textContent = copy[state.language].trackerTitle;
  subtitle.textContent = copy[state.language].trackerSubtitle;
  addTrackerButton.hidden = false;
  renderTrackerSection();
}

function renderOverviewPanel() {
  const panel = document.createElement("section");
  panel.className = "overview-grid";
  const { health, stateSummary, pools, error } = state.overview;
  if (error) {
    panel.append(renderMetricCard("状态读取", "失败", error, "warning"));
    return panel;
  }
  if (!health || !stateSummary || !pools) {
    panel.append(renderMetricCard("状态读取", "加载中", "正在读取本地只读 API。", "info"));
    return panel;
  }

  const candidateStates = stateSummary.candidates?.by_state || {};
  const intentStates = stateSummary.intents?.by_state || {};
  const budgetPools = pools.budget_pools || [];
  panel.append(
    renderMetricCard(
      "心跳",
      formatHealthStatus(health.status),
      health.heartbeat_exists
        ? `${health.age_minutes ?? "?"} 分钟前 · 第 ${health.heartbeat?.cycle ?? "?"} 轮`
        : "心跳文件不存在",
      health.status === "ok" ? "ok" : "warning",
    ),
  );
  panel.append(
    renderMetricCard("候选种子", stateSummary.candidates?.total ?? 0, formatStateCounts(candidateStates), "info"),
  );
  panel.append(renderMetricCard("获取意图", stateSummary.intents?.total ?? 0, formatStateCounts(intentStates), "info"));
  panel.append(
    renderMetricCard(
      "容量池",
      budgetPools.length,
      budgetPools.map((pool) => `${pool.name}: ${pool.max_size_tib} TiB`).join(" · ") || "未配置容量池",
      "info",
    ),
  );
  return panel;
}

function renderMetricCard(label, value, detail, level) {
  const card = document.createElement("article");
  card.className = `metric-card ${level}`;
  card.innerHTML = `
    <div class="metric-label">${escapeHtml(label)}</div>
    <div class="metric-value">${escapeHtml(value)}</div>
    <div class="status-item ${escapeAttribute(level)}">${escapeHtml(detail || "无数据")}</div>
  `;
  return card;
}

function formatHealthStatus(status) {
  const labels = {
    ok: "正常",
    stale: "过期",
    missing_heartbeat: "缺失",
  };
  return labels[status] || status || "未知";
}

function formatStateCounts(counts) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return "暂无状态记录";
  }
  const labels = {
    accepted: "已接受",
    scored: "已评分",
    enqueued: "已入队",
    confirmation_required: "待确认",
    rejected: "已拒绝",
    failed: "失败",
  };
  return entries.map(([name, count]) => `${labels[name] || name}: ${count}`).join(" · ");
}

function renderWantsPanel() {
  const panel = document.createElement("section");
  panel.className = "wants-panel";
  panel.innerHTML = `
    <div class="wants-toolbar">
      <div class="want-filters">
        <label class="field compact-field">
          <span>来源</span>
          <select data-want-filter="source">
            ${renderWantSourceOptions()}
          </select>
        </label>
        <label class="field compact-field">
          <span>类型</span>
          <select data-want-filter="media_type">
            <option value="all">全部</option>
            <option value="movie">电影</option>
            <option value="tv">电视剧</option>
            <option value="anime">动漫</option>
          </select>
        </label>
      </div>
      <div class="tracker-actions-group">
        <button class="secondary-button" type="button" data-want-action="search">搜索</button>
        <button class="primary-button" type="button" data-want-action="config-open">配置</button>
      </div>
    </div>
    <div class="status-list" data-want-status></div>
    ${renderWantConfigModal()}
    <div class="section-title">想看资源</div>
  `;
  panel.querySelector('[data-want-filter="source"]').value = state.wants.filters.source;
  panel.querySelector('[data-want-filter="media_type"]').value = state.wants.filters.media_type;
  panel.append(renderWantTable());
  panel.addEventListener("change", (event) => {
    const filter = event.target?.dataset?.wantFilter;
    if (filter) {
      state.wants.filters[filter] = event.target.value;
      renderSection();
      return;
    }
    if (event.target?.dataset?.wantSourceField === "provider") {
      syncWantSourceProviderFields(event.target.closest("[data-want-source-row]"));
    }
  });
  panel.addEventListener("click", (event) => {
    const action = event.target?.dataset?.wantAction;
    if (action) {
      handleWantAction(panel, action, event);
    }
  });
  return panel;
}

function renderWantSourceOptions() {
  const options = ['<option value="all">全部</option>'];
  const seen = new Set();
  state.wants.items.forEach((item) => {
    const keys = item.source_keys || [item.source];
    keys.forEach((key) => {
      if (!key || seen.has(key)) {
        return;
      }
      seen.add(key);
      const label = sourceLabelForKey(key);
      options.push(`<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`);
    });
  });
  return options.join("");
}

function sourceLabelForKey(key) {
  const match = state.wants.items.find((item) => (item.source_keys || []).includes(key));
  if (!match) {
    return key;
  }
  const label = match.source_label || key;
  return label.replace(/\s\+\d+$/, "");
}

function renderWantConfigModal() {
  const sources = state.configSections.sources || {};
  const wantLists = configuredWantLists(sources);
  return `
    <div class="modal-backdrop hidden" data-want-config-modal>
      <div class="modal-panel">
        <div class="modal-header">
          <div class="section-title">想看来源配置</div>
          <button class="icon-button" type="button" data-want-action="config-close" aria-label="关闭">×</button>
        </div>
        <div class="want-source-list" data-want-source-list>
          ${wantLists.map((source, index) => renderWantSourceConfigRow(source, index)).join("")}
        </div>
        <div class="tracker-actions-group">
          <button class="secondary-button" type="button" data-want-action="config-add">新增来源</button>
          <button class="secondary-button" type="button" data-want-action="config-preview">预览</button>
          <button class="primary-button" type="button" data-want-action="config-save">保存</button>
        </div>
        <div class="status-list" data-want-config-status></div>
      </div>
    </div>
  `;
}

function configuredWantLists(sources) {
  const configured = Array.isArray(sources.want_lists) ? [...sources.want_lists] : [];
  if (configured.length > 0) {
    return configured;
  }
  const legacyDouban = sources.douban_wanted || {};
  if (legacyDouban.user_name || legacyDouban.export_ref || legacyDouban.enabled) {
    return [
      {
        provider: "douban",
        id: "douban-wanted",
        label: legacyDouban.user_name || "Douban",
        enabled: legacyDouban.enabled === true,
        user_name: legacyDouban.user_name || "",
        export_ref: legacyDouban.export_ref || "",
        max_pages: legacyDouban.max_pages || 1,
      },
    ];
  }
  return configured;
}

function renderWantSourceConfigRow(source, index) {
  const provider = source.provider === "imdb" ? "imdb" : "douban";
  return `
    <div class="want-source-row" data-want-source-row="${index}">
      <label class="field">
        <span>来源</span>
        <select data-want-source-field="provider">
          <option value="douban" ${provider === "douban" ? "selected" : ""}>Douban</option>
          <option value="imdb" ${provider === "imdb" ? "selected" : ""}>IMDb</option>
        </select>
      </label>
      <label class="field">
        <span>ID</span>
        <input data-want-source-field="id" value="${escapeHtml(source.id || "")}" />
      </label>
      <label class="field">
        <span>名称</span>
        <input data-want-source-field="label" value="${escapeHtml(source.label || "")}" />
      </label>
      <label class="field">
        <span>启用</span>
        <select data-want-source-field="enabled">
          <option value="true" ${source.enabled !== false ? "selected" : ""}>是</option>
          <option value="false" ${source.enabled === false ? "selected" : ""}>否</option>
        </select>
      </label>
      <div class="provider-fields ${provider === "douban" ? "" : "hidden"}" data-provider-fields="douban">
        <label class="field">
          <span>Douban 用户</span>
          <input data-want-source-field="user_name" value="${escapeHtml(source.user_name || "")}" />
        </label>
        <label class="field">
          <span>导出文件</span>
          <input data-want-source-field="export_ref" value="${escapeHtml(provider === "douban" ? source.export_ref || "" : "")}" />
        </label>
        <label class="field">
          <span>页数</span>
          <input data-want-source-field="max_pages" type="number" min="1" value="${escapeHtml(provider === "douban" ? source.max_pages || 1 : 1)}" />
        </label>
      </div>
      <div class="provider-fields ${provider === "imdb" ? "" : "hidden"}" data-provider-fields="imdb">
        <label class="field wide">
          <span>IMDb watchlist URL</span>
          <input data-want-source-field="watchlist_url" value="${escapeHtml(source.watchlist_url || "")}" />
        </label>
        <label class="field">
          <span>导出文件</span>
          <input data-want-source-field="export_ref" value="${escapeHtml(provider === "imdb" ? source.export_ref || "" : "")}" />
        </label>
        <label class="field">
          <span>页数</span>
          <input data-want-source-field="max_pages" type="number" min="1" value="${escapeHtml(provider === "imdb" ? source.max_pages || 1 : 1)}" />
        </label>
      </div>
      <button class="secondary-button" type="button" data-want-action="config-remove" data-row-index="${index}">移除</button>
    </div>
  `;
}

function renderWantTable() {
  const wrapper = document.createElement("div");
  wrapper.className = "want-table-wrap";
  const items = filteredWantItems();
  if (state.wants.loading) {
    wrapper.innerHTML = '<div class="empty-state">加载中</div>';
    return wrapper;
  }
  if (state.wants.error) {
    wrapper.innerHTML = `<div class="status-item warning">${escapeHtml(state.wants.error)}</div>`;
    return wrapper;
  }
  if (items.length === 0) {
    wrapper.innerHTML = '<div class="empty-state">暂无想看资源</div>';
    return wrapper;
  }
  wrapper.innerHTML = `
    <div class="want-table-desktop">
      <table class="want-table">
        <thead>
          <tr>
            <th>标题</th>
            <th>类型</th>
            <th>来源</th>
            <th>添加时间</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(renderWantRow).join("")}
        </tbody>
      </table>
    </div>
    <div class="want-card-list">
      ${items.map(renderWantCard).join("")}
    </div>
  `;
  return wrapper;
}

function filteredWantItems() {
  return state.wants.items.filter((item) => {
    const sourceOk =
      state.wants.filters.source === "all" ||
      (item.source_keys || []).includes(state.wants.filters.source);
    const typeOk =
      state.wants.filters.media_type === "all" ||
      item.media_type === state.wants.filters.media_type;
    return sourceOk && typeOk;
  });
}

function renderWantRow(item) {
  return `
    <tr>
      <td>
        <strong>${escapeHtml(item.title || item.raw_text)}</strong>
        <div class="muted-line">${escapeHtml(item.raw_text || "")}</div>
      </td>
      <td>${escapeHtml(formatMediaType(item.media_type))}</td>
      <td>${escapeHtml(item.source_label || item.source)}</td>
      <td>${escapeHtml(formatDateTime(item.added_at))}</td>
      <td><span class="badge ${item.status === "queued" ? "ok" : ""}">${escapeHtml(item.status_label || item.state)}</span></td>
    </tr>
  `;
}

function renderWantCard(item) {
  return `
    <article class="want-card">
      <div class="want-card-header">
        <strong>${escapeHtml(item.title || item.raw_text)}</strong>
        <span class="badge ${item.status === "queued" ? "ok" : ""}">${escapeHtml(item.status_label || item.state)}</span>
      </div>
      <div class="muted-line">${escapeHtml(item.raw_text || "")}</div>
      <div class="want-card-meta">
        <span>${escapeHtml(formatMediaType(item.media_type))}</span>
        <span>${escapeHtml(item.source_label || item.source)}</span>
        <span>${escapeHtml(formatDateTime(item.added_at))}</span>
      </div>
    </article>
  `;
}

async function handleWantAction(panel, action, event) {
  if (action === "search") {
    await searchFilteredWants(panel);
    return;
  }
  if (action === "config-open") {
    panel.querySelector("[data-want-config-modal]")?.classList.remove("hidden");
    return;
  }
  if (action === "config-close") {
    panel.querySelector("[data-want-config-modal]")?.classList.add("hidden");
    return;
  }
  if (action === "config-add") {
    addWantSourceConfigRow(panel);
    return;
  }
  if (action === "config-remove") {
    const row = event?.target?.closest("[data-want-source-row]");
    row?.remove();
    return;
  }
  if (action === "config-preview") {
    await submitWantSourceConfig(panel, "/api/config/sections/preview");
    return;
  }
  if (action === "config-save") {
    const payload = await submitWantSourceConfig(panel, "/api/config/sections");
    if (payload?.data) {
      state.configSections.sources = payload.data;
      if (payload.section_yamls) {
        state.sectionYamls = payload.section_yamls;
      }
      if (payload.config_yaml) {
        state.configYaml = payload.config_yaml;
      }
      await syncConfiguredWants(panel);
      await loadWants();
      renderSection();
    }
  }
}

async function searchFilteredWants(panel) {
  const status = panel.querySelector("[data-want-status]");
  try {
    const response = await fetch("/api/wants/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.wants.filters),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `请求失败：${response.status}`);
    }
    await loadWants();
    renderSection();
    const refreshedStatus = document.querySelector("[data-want-status]");
    if (refreshedStatus) {
      refreshedStatus.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || "搜索已完成")}</div>`;
    }
  } catch (error) {
    status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
  }
}

async function syncConfiguredWants(panel) {
  const status = panel.querySelector("[data-want-config-status]") || panel.querySelector("[data-want-status]");
  try {
    const response = await fetch("/api/wants/sync", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `请求失败：${response.status}`);
    }
    if (status) {
      status.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || "想看来源已同步")}</div>`;
    }
    return payload;
  } catch (error) {
    if (status) {
      status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
    }
    return null;
  }
}

function addWantSourceConfigRow(panel) {
  const list = panel.querySelector("[data-want-source-list]");
  const index = list.querySelectorAll("[data-want-source-row]").length;
  list.insertAdjacentHTML(
    "beforeend",
    renderWantSourceConfigRow(
      {
        provider: "douban",
        id: `douban-${index + 1}`,
        label: `来源${index + 1}`,
        enabled: true,
        max_pages: 1,
      },
      index,
    ),
  );
}

function syncWantSourceProviderFields(row) {
  if (!row) {
    return;
  }
  const provider = row.querySelector('[data-want-source-field="provider"]')?.value || "douban";
  row.querySelectorAll("[data-provider-fields]").forEach((group) => {
    group.classList.toggle("hidden", group.dataset.providerFields !== provider);
  });
}

function readWantSourceConfig(panel) {
  return Array.from(panel.querySelectorAll("[data-want-source-row]")).map((row) => {
    const value = (name) => row.querySelector(`[data-want-source-field="${name}"]`)?.value?.trim() || "";
    const providerValue = value("provider") || "douban";
    const providerFieldValue = (name) =>
      row
        .querySelector(`[data-provider-fields="${providerValue}"] [data-want-source-field="${name}"]`)
        ?.value?.trim() || "";
    const source = {
      provider: providerValue,
      id: value("id"),
      label: value("label"),
      enabled: value("enabled") !== "false",
      max_pages: Number.parseInt(providerFieldValue("max_pages") || "1", 10),
    };
    if (providerValue === "douban" && providerFieldValue("user_name")) {
      source.user_name = providerFieldValue("user_name");
    }
    if (providerValue === "imdb" && providerFieldValue("watchlist_url")) {
      source.watchlist_url = providerFieldValue("watchlist_url");
    }
    if (providerFieldValue("export_ref")) {
      source.export_ref = providerFieldValue("export_ref");
    }
    return source;
  });
}

async function submitWantSourceConfig(panel, endpoint) {
  const status = panel.querySelector("[data-want-config-status]");
  try {
    const data = { ...(state.configSections.sources || {}) };
    data.want_lists = readWantSourceConfig(panel);
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section: "sources", data }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `请求失败：${response.status}`);
    }
    status.innerHTML = `
      <div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || "ok")}</div>
      ${payload.diff ? `<pre class="diff-preview">${escapeHtml(payload.diff)}</pre>` : ""}
    `;
    return payload;
  } catch (error) {
    status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
    return null;
  }
}

function formatMediaType(value) {
  const labels = {
    movie: "电影",
    tv: "电视剧",
    anime: "动漫",
    unknown: "未知",
  };
  return labels[value] || value || "未知";
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  return String(value).replace("T", " ").replace("+00:00", " UTC");
}

function renderTrackerSection() {
  trackerList.replaceChildren();
  if (state.trackers.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = copy[state.language].emptyTracker;
    trackerList.append(empty);
    return;
  }
  state.trackers.forEach((tracker) => {
    trackerList.append(renderTrackerCard(tracker));
  });
}

function renderTrackerCard(tracker) {
  const card = document.createElement("section");
  card.className = `tracker-card ${tracker.saved ? "" : "draft"}`;

  const header = document.createElement("div");
  header.className = "tracker-header";
  header.setAttribute("data-tracker-toggle", "header");
  header.role = "button";
  header.tabIndex = 0;
  header.setAttribute("aria-expanded", String(!tracker.collapsed));
  header.innerHTML = `
    <div class="tracker-title">
      <strong>${escapeHtml(tracker.name || "新站点")}</strong>
      ${tracker.saved ? "" : '<span class="badge warn">未保存</span>'}
      ${tracker.type ? `<span class="badge">${escapeHtml(tracker.type)}</span>` : '<span class="badge">等待类型</span>'}
    </div>
  `;
  header.addEventListener("click", () => {
    toggleTrackerCard(tracker);
  });
  header.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleTrackerCard(tracker);
    }
  });
  const collapse = document.createElement("button");
  collapse.className = "icon-button";
  collapse.type = "button";
  collapse.setAttribute("aria-label", tracker.collapsed ? "展开站点" : "折叠站点");
  collapse.textContent = tracker.collapsed ? "⌄" : "⌃";
  collapse.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleTrackerCard(tracker);
  });
  header.append(collapse);
  card.append(header);

  if (!tracker.collapsed) {
    const body = document.createElement("div");
    body.className = "tracker-body";
    body.append(renderBaseFields(tracker));
    if (tracker.type) {
      body.append(renderTypeSpecificFields(tracker));
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "placeholder";
      placeholder.textContent = "先选择类型。选完类型后，只显示这个类型需要继续配置的选项。";
      body.append(placeholder);
    }
    body.append(renderTrackerDetailFooter(tracker));
    card.append(body);
  } else {
    const summary = document.createElement("div");
    summary.className = "tracker-body";
    summary.textContent = summarizeTracker(tracker);
    card.append(summary);
  }

  return card;
}

function toggleTrackerCard(tracker) {
  tracker.collapsed = !tracker.collapsed;
  renderSection();
}

function renderBaseFields(tracker) {
  const wrapper = document.createElement("div");
  wrapper.innerHTML = `
    <div class="section-title">基础</div>
    <div class="field-grid">
      <label class="field">
        <span>类型 ${help("第一个必填项。选择后，下方才显示该类型需要继续配置的字段。")}</span>
        <select data-field="type">
          <option value="">选择类型...</option>
          <option value="mteam">M-Team</option>
          <option value="nexusphp">NexusPHP</option>
        </select>
      </label>
      <label class="field">
        <span>站点名称 ${help("第二个必填项。用于配置引用、日志、站点优先级和搜索结果。")}</span>
        <input data-field="name" placeholder="mt" value="${escapeAttribute(tracker.name)}" />
      </label>
    </div>
  `;
  bindFields(wrapper, tracker);
  return wrapper;
}

function renderTypeSpecificFields(tracker) {
  const configTitle = tracker.type === "mteam" ? "M-Team 配置" : "NexusPHP 配置";
  const wrapper = document.createElement("div");
  wrapper.innerHTML = `
    <div class="tracker-detail-grid">
      <div>
        <div class="section-title">${configTitle}</div>
        ${renderDiscoveryFields(tracker)}
      </div>
      ${renderStatusPanel(tracker)}
    </div>
  `;
  bindFields(wrapper, tracker);
  return wrapper;
}

function renderDiscoveryFields(tracker) {
  if (tracker.type === "mteam") {
    return `
      <div class="field-grid">
        <label class="field">
          <span>发现方式 ${help("M-Team 支持 RSS 或 API。先选这里，再出现对应的认证和地址字段。")}</span>
          <select data-field="discovery_mode">
            <option value="rss">rss</option>
            <option value="api">api</option>
          </select>
        </label>
        ${tracker.discovery_mode === "rss" ? renderRssDiscoveryFields(tracker) : ""}
        ${tracker.discovery_mode === "api" ? renderApiDiscoveryFields(tracker) : ""}
      </div>
    `;
  }
  return `
    <div class="field-grid">
      ${renderRssDiscoveryFields(tracker)}
    </div>
  `;
}

function renderRssDiscoveryFields(tracker) {
  return `
    <label class="field wide">
      <span>RSS URL ${help("RSS 发现方式需要填写订阅地址。选择 API 时不会要求这个字段。")}</span>
      <input data-field="rss_url" value="${escapeAttribute(tracker.rss_url)}" />
    </label>
    <label class="field">
      <span>Cookie 文件 ${help("可选。只保存本地 cookie secret 文件路径，不保存明文。")}</span>
      <input data-field="cookie_ref" value="${escapeAttribute(tracker.cookie_ref)}" />
    </label>
  `;
}

function renderApiDiscoveryFields(tracker) {
  return `
    <label class="field">
      <span>API key 文件 ${help("API 发现方式需要。这里只保存本地 secret 文件路径，例如 local/secrets/mt_api_key。")}</span>
      <input data-field="api_key_ref" value="${escapeAttribute(tracker.api_key_ref)}" />
    </label>
    <label class="field">
      <span>API key 明文 ${help("可选填写。保存时写入 API key 文件指向的本地文件，保存后不回显明文。")}</span>
      <input data-field="api_key_value" value="${escapeAttribute(tracker.api_key_value)}" />
    </label>
    <label class="field">
      <span>Auth header ${help("API 请求使用的认证 header。M-Team 默认是 x-api-key。")}</span>
      <input data-field="auth_header" value="${escapeAttribute(tracker.auth_header)}" />
    </label>
  `;
}

function renderTrackerDetailFooter(tracker) {
  const footer = document.createElement("div");
  footer.className = "tracker-actions";
  footer.innerHTML = `
    <div class="tracker-actions-group">
      <button class="secondary-button" type="button" data-action="validate" aria-label="验证此站点">验证此站点</button>
      <button class="secondary-button" type="button" data-action="site-probe" aria-label="站点探测">站点探测</button>
      <button class="secondary-button" type="button" data-action="dry-run" aria-label="试运行预览">试运行预览</button>
    </div>
    <div class="tracker-actions-group">
      <button class="secondary-button" type="button" data-action="cancel">取消</button>
      <button class="primary-button" type="button" data-action="save">保存</button>
    </div>
  `;
  footer.addEventListener("click", (event) => {
    const action = event.target?.dataset?.action;
    if (action) {
      handleTrackerAction(tracker, action);
    }
  });
  return footer;
}

async function handleTrackerAction(tracker, action) {
  if (action === "cancel") {
    state.trackers = state.trackers.filter((item) => item.id !== tracker.id);
    renderSection();
    return;
  }
  const endpoints = {
    validate: "/api/trackers/validate",
    "site-probe": "/api/trackers/site-probe",
    "dry-run": "/api/trackers/dry-run",
    save: "/api/trackers",
  };
  try {
    const response = await fetch(endpoints[action], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toDraftPayload(tracker)),
    });
    const payload = await response.json();
    tracker.status = payload.status || tracker.status;
    if (!response.ok && !payload.status) {
      tracker.status = [{ level: "warning", message: `请求失败：${response.status}` }];
    }
    if (action === "save" && response.ok) {
      tracker.saved = true;
      tracker.api_key_value = "";
    }
  } catch (error) {
    tracker.status = [{ level: "warning", message: `请求失败：${error.message}` }];
  }
  renderSection();
}

function renderStatusPanel(tracker) {
  return `
    <div class="status-panel">
      <h3>状态</h3>
      <div class="status-list">
        ${tracker.status
          .map(
            (item) =>
              `<div class="status-item ${escapeAttribute(item.level)}">${escapeHtml(item.message)}</div>`,
          )
          .join("")}
      </div>
    </div>
  `;
}

function bindFields(root, tracker) {
  root.querySelectorAll("[data-field]").forEach((field) => {
    field.value = tracker[field.dataset.field] || "";
    const eventName = field.tagName === "SELECT" ? "change" : "input";
    field.addEventListener(eventName, () => {
      tracker[field.dataset.field] = field.value;
      if (field.dataset.field === "type" || field.dataset.field === "discovery_mode") {
        tracker.status = [
          { level: field.value ? "info" : "warning", message: field.value ? "类型已选择" : "类型必填" },
          { level: tracker.name ? "info" : "warning", message: tracker.name ? "站点名称已填写" : "站点名称必填" },
        ];
        renderSection();
      }
    });
  });
}

function toDraftPayload(tracker) {
  return {
    type: tracker.type || null,
    name: tracker.name,
    enabled: tracker.enabled,
    rss_url: tracker.rss_url,
    discovery_mode: tracker.discovery_mode,
    api_key_ref: tracker.api_key_ref || null,
    api_key_value: tracker.api_key_value || null,
    auth_header: tracker.auth_header || null,
    cookie_ref: tracker.cookie_ref || null,
  };
}

function summarizeTracker(tracker) {
  const status = tracker.status.map((item) => item.message).join(" · ");
  return status || "尚未检查";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

function help(text) {
  return `<button class="help" type="button" data-help="${escapeAttribute(text)}" aria-label="字段说明">?</button>`;
}

function newClientId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  const randomPart = Math.random().toString(36).slice(2, 10);
  return `client-${Date.now().toString(36)}-${randomPart}`;
}

function showHelpPopover(target) {
  helpPopover.textContent = target.dataset.help;
  const box = target.getBoundingClientRect();
  helpPopover.hidden = false;
  const left = Math.min(box.left, window.innerWidth - helpPopover.offsetWidth - 12);
  const top = Math.min(box.bottom + 8, window.innerHeight - helpPopover.offsetHeight - 12);
  helpPopover.style.left = `${Math.max(12, left)}px`;
  helpPopover.style.top = `${Math.max(12, top)}px`;
}

function hideHelpPopover() {
  helpPopover.hidden = true;
}

syncNavigationLabels();
loadInitialData();

function setLanguage(language) {
  state.language = language;
  document.documentElement.lang = language === "CN" ? "zh-CN" : "en";
  languageMenu.hidden = true;
  addTrackerButton.textContent = copy[language].addTracker;
  syncNavigationLabels();
  renderSection();
}

function renderPlaceholderPage(placeholder) {
  const page = document.createElement("div");
  page.className = "placeholder-page";
  page.innerHTML = `
    <h2>${escapeHtml(placeholder.title)}</h2>
    <p>${escapeHtml(placeholder.description)}</p>
  `;
  return page;
}

function renderConfigFilePanel() {
  const page = document.createElement("div");
  page.className = "settings-panel config-file-panel";
  const sectionButtons = navigationSections
    .filter((section) => settingsPanels[section])
    .map(
      (section) =>
        `<button class="secondary-button" type="button" data-config-jump="${escapeAttribute(section)}">${escapeHtml(copy[state.language].nav[section])}</button>`,
    )
    .join("");
  page.innerHTML = `
    <div class="settings-panel-header">
      <div>
        <div class="section-title">配置文件</div>
        <p>当前仍保持一个物理 YAML 文件，避免 CLI、Docker 和 Unraid 部署同时迁移。各配置页会显示并保存自己的 YAML 区块。</p>
      </div>
      <span class="badge">${escapeHtml(state.configPath || "配置未加载")}</span>
    </div>
    <div class="config-section-jumps">${sectionButtons}</div>
    <div class="section-yaml-editor">
      <div class="section-title">完整配置预览</div>
      <p>这里是归一化后的只读预览。需要修改时，进入对应配置页编辑“本页 YAML”。</p>
      <pre class="diff-preview">${escapeHtml(state.configYaml || "配置尚未加载。")}</pre>
    </div>
  `;
  page.addEventListener("click", (event) => {
    const section = event.target?.dataset?.configJump;
    if (section) {
      switchSection(section);
    }
  });
  return page;
}

function renderSectionYamlEditor(section) {
  const yamlText = state.sectionYamls[section] || `${section}: {}\n`;
  return `
    <div class="section-yaml-editor">
      <div class="section-title">本页 YAML</div>
      <p>对应 ${escapeHtml(state.configPath || "当前配置文件")} 中的 <code>${escapeHtml(section)}:</code> 区块。可以保留顶层区块名，也可以只填写区块内容。</p>
      <textarea class="section-yaml-textarea" data-section-yaml spellcheck="false">${escapeHtml(yamlText)}</textarea>
    </div>
  `;
}

function renderSettingsPanel(section) {
  const spec = settingsPanels[section];
  const page = document.createElement("div");
  page.className = "settings-panel";
  const sectionData = state.configSections[section] || {};
  const fields = spec.fields
    .map(
      ([label, key, type, description]) => `
        <label class="field">
          <span>${escapeHtml(label)} ${help(description)}</span>
          ${renderSettingInput(key, type, getSettingValue(sectionData, key))}
        </label>
      `,
    )
    .join("");
  page.innerHTML = `
    <div class="settings-panel-header">
      <div>
        <div class="section-title">${escapeHtml(spec.title)}</div>
        <p>可以用表单编辑常用项，也可以直接编辑本页 YAML 区块。保存前会先做 schema 校验。</p>
      </div>
      <span class="badge">来自 YAML</span>
    </div>
    <div class="field-grid">${fields}</div>
    ${renderSectionYamlEditor(section)}
    <div class="tracker-actions sticky-actions">
      <div class="tracker-actions-group">
        <button class="secondary-button" type="button" data-setting-action="validate">验证表单</button>
        <button class="secondary-button" type="button" data-setting-action="preview">预览表单改动</button>
        <button class="secondary-button" type="button" data-setting-action="yaml-preview">预览本页 YAML</button>
        <button class="secondary-button" type="button" data-setting-action="yaml-save">保存本页 YAML</button>
      </div>
      <button class="primary-button" type="button" data-setting-action="save">保存表单</button>
    </div>
    <div class="status-panel settings-status" data-setting-status>
      <h3>状态</h3>
      <div class="status-list">
        <div class="status-item info">表单可编辑，尚未写入 YAML。</div>
      </div>
    </div>
  `;
  page.addEventListener("click", (event) => {
    const action = event.target?.dataset?.settingAction;
    if (action) {
      updateSettingsPanelStatus(page, section, action);
    }
  });
  page.addEventListener("input", () => resetSettingsPanelPreview(page));
  page.addEventListener("change", () => resetSettingsPanelPreview(page));
  return page;
}

function updateSettingsPanelStatus(page, section, action) {
  if (section !== "advanced" && action === "yaml-preview") {
    previewSettingsPanelYaml(page, section);
    return;
  }
  if (section !== "advanced" && action === "yaml-save") {
    saveSettingsPanelYaml(page, section);
    return;
  }
  if (section !== "advanced" && action === "save") {
    if (page.dataset.previewConfirmed === "true") {
      confirmSettingsPanelSave(page, section);
      return;
    }
    previewSettingsPanelSave(page, section);
    return;
  }
  if (action === "preview" && section !== "advanced") {
    previewSettingsPanelSave(page, section);
    return;
  }
  const messages = {
    validate: `${settingsPanels[section].title}：表单格式通过。`,
    preview: `${settingsPanels[section].title}：表单预览已准备。`,
    save: `${settingsPanels[section].title}：表单已保存在当前页面状态。`,
  };
  page.querySelector("[data-setting-status] .status-list").innerHTML = `
    <div class="status-item ok">${escapeHtml(messages[action])}</div>
  `;
}

function renderSettingInput(key, type, value) {
  if (type.startsWith("select:")) {
    const options = type
      .slice("select:".length)
      .split("|")
      .map(
        (option) =>
          `<option value="${escapeAttribute(option)}" ${value === option ? "selected" : ""}>${escapeHtml(option)}</option>`,
      )
      .join("");
    return `<select data-setting-field="${escapeAttribute(key)}" data-setting-type="${escapeAttribute(type)}">${options}</select>`;
  }
  if (type === "boolean") {
    return `
      <select data-setting-field="${escapeAttribute(key)}" data-setting-type="${escapeAttribute(type)}">
        <option value="true" ${value === true ? "selected" : ""}>true</option>
        <option value="false" ${value === false ? "selected" : ""}>false</option>
      </select>
    `;
  }
  const displayValue = formatSettingDisplayValue(value, type);
  return `
    <input data-setting-field="${escapeAttribute(key)}" data-setting-type="${escapeAttribute(type)}" value="${escapeAttribute(displayValue)}" />
  `;
}

function formatSettingDisplayValue(value, type) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (type === "map" && value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, priority]) => `${key}=${priority}`)
      .join(", ");
  }
  return value ?? "";
}

function readSettingsPanelData(page, section) {
  const data = { ...(state.configSections[section] || {}) };
  page.querySelectorAll("[data-setting-field]").forEach((field) => {
    setSettingValue(
      data,
      field.dataset.settingField,
      coerceSettingValue(field.value, field.dataset.settingType),
    );
  });
  return data;
}

function coerceSettingValue(value, type) {
  if (type === "boolean") {
    return value === "true";
  }
  if (type === "number") {
    return Number(value);
  }
  if (type === "optional-number") {
    return value.trim() === "" ? null : Number(value);
  }
  if (type === "csv") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (type === "map") {
    return parseMapValue(value);
  }
  if (type === "optional-text") {
    return value.trim() === "" ? null : value.trim();
  }
  if (type.startsWith("select:")) {
    return value;
  }
  return value;
}

function getSettingValue(data, key) {
  return key.split(".").reduce((value, part) => value?.[part], data);
}

function setSettingValue(data, key, value) {
  const parts = key.split(".");
  let cursor = data;
  parts.slice(0, -1).forEach((part) => {
    cursor[part] = { ...(cursor[part] || {}) };
    cursor = cursor[part];
  });
  cursor[parts[parts.length - 1]] = value;
}

function parseMapValue(value) {
  const result = {};
  value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((item) => {
      const parts = item.split(/[=:]/);
      const [rawKey, rawValue] = parts;
      const key = rawKey?.trim();
      const numericValue = Number(rawValue?.trim());
      if (
        parts.length !== 2 ||
        !key ||
        rawValue.trim() === "" ||
        !Number.isFinite(numericValue)
      ) {
        throw new Error(`无效映射项：${item}。请使用 site=priority，例如 demo=10。`);
      }
      result[key] = numericValue;
    });
  return result;
}

function resetSettingsPanelPreview(page) {
  page.dataset.previewConfirmed = "false";
  const saveButton = page.querySelector('[data-setting-action="save"]');
  if (saveButton) {
    saveButton.textContent = "保存表单";
  }
}

function applyReturnedConfigState(payload, section, page) {
  if (payload.data) {
    state.configSections[section] = payload.data;
  }
  if (payload.section_yamls) {
    state.sectionYamls = payload.section_yamls;
  } else if (payload.yaml) {
    state.sectionYamls[section] = payload.yaml;
  }
  if (payload.config_yaml) {
    state.configYaml = payload.config_yaml;
  }
  const yamlTextarea = page.querySelector("[data-section-yaml]");
  if (yamlTextarea && state.sectionYamls[section]) {
    yamlTextarea.value = state.sectionYamls[section];
  }
}

function readSectionYamlText(page) {
  return page.querySelector("[data-section-yaml]")?.value || "";
}

async function previewSettingsPanelYaml(page, section) {
  await submitSettingsPanelYaml(page, section, "/api/config/sections/yaml/preview", false);
}

async function saveSettingsPanelYaml(page, section) {
  await submitSettingsPanelYaml(page, section, "/api/config/sections/yaml", true);
}

async function submitSettingsPanelYaml(page, section, endpoint, persist) {
  try {
    const yamlText = readSectionYamlText(page);
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, yaml: yamlText }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `请求失败：${response.status}`);
    }
    if (persist) {
      applyReturnedConfigState(payload, section, page);
    }
    page.dataset.previewConfirmed = "false";
    const saveButton = page.querySelector('[data-setting-action="save"]');
    if (saveButton) {
      saveButton.textContent = "保存表单";
    }
    const message = persist ? "本页 YAML 已保存" : "本页 YAML 预览已准备";
    const diff = payload.diff ? `<pre class="diff-preview">${escapeHtml(payload.diff)}</pre>` : "";
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item ok">${escapeHtml(message)}</div>
      ${diff}
    `;
  } catch (error) {
    page.dataset.previewConfirmed = "false";
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item warning">${escapeHtml(error.message)}</div>
    `;
  }
}

async function previewSettingsPanelSave(page, section) {
  try {
    const data = readSettingsPanelData(page, section);
    const response = await fetch("/api/config/sections/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, data }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `请求失败：${response.status}`);
    }
    page.dataset.previewConfirmed = "true";
    const saveButton = page.querySelector('[data-setting-action="save"]');
    if (saveButton) {
      saveButton.textContent = "确认保存表单";
    }
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item ok">保存确认</div>
      <pre class="diff-preview">${escapeHtml(payload.diff || "没有实际配置变化。")}</pre>
    `;
  } catch (error) {
    page.dataset.previewConfirmed = "false";
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item warning">${escapeHtml(error.message)}</div>
    `;
  }
}

async function confirmSettingsPanelSave(page, section) {
  await saveSettingsPanel(page, section);
}

async function saveSettingsPanel(page, section) {
  try {
    const data = readSettingsPanelData(page, section);
    const response = await fetch("/api/config/sections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, data }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `请求失败：${response.status}`);
    }
    applyReturnedConfigState(payload, section, page);
    page.dataset.previewConfirmed = "false";
    const saveButton = page.querySelector('[data-setting-action="save"]');
    if (saveButton) {
      saveButton.textContent = "保存表单";
    }
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item ok">配置已保存</div>
    `;
  } catch (error) {
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item warning">${escapeHtml(error.message)}</div>
    `;
  }
}
