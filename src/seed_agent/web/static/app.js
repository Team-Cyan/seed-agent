const state = {
  trackers: [],
  overview: {
    health: null,
    stateSummary: null,
    pools: null,
    error: null,
  },
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
const navItems = document.querySelectorAll("[data-section]");

const copy = {
  CN: {
    nav: {
      overview: "状态",
      tracker: "Tracker",
      downloader: "下载器",
      discovery: "发现策略",
      cleanup: "清理策略",
      intent: "资源意图",
      advanced: "高级 YAML",
    },
    overviewTitle: "状态",
    overviewSubtitle: "本地只读状态：heartbeat、候选/意图计数和配置的 budget pool。",
    trackerTitle: "Tracker",
    trackerSubtitle: "新用户初始为空。点击添加后出现一个 Tracker 配置卡。",
    addTracker: "添加 Tracker",
    emptyTracker: "还没有 Tracker。点击右上角添加 Tracker 开始配置。",
    placeholders: {
      downloader: {
        title: "下载器",
        description: "下一步会在这里配置 qBittorrent target、category policy 和 budget pool。",
      },
      discovery: {
        title: "发现策略",
        description: "下一步会在这里配置 free、seed/leech、size 和运行时 gate。",
      },
      cleanup: {
        title: "清理策略",
        description: "下一步会在这里配置冷种、保护项和 pause-before-delete。",
      },
      intent: {
        title: "资源意图",
        description: "下一步会在这里配置 intent 阈值、语言偏好和 inbox。",
      },
      advanced: {
        title: "高级 YAML",
        description: "这里会提供 raw YAML 预览、diff 和保存前验证。",
      },
    },
  },
  EN: {
    nav: {
      overview: "Status",
      tracker: "Tracker",
      downloader: "Downloader",
      discovery: "Discovery",
      cleanup: "Cleanup",
      intent: "Intent",
      advanced: "Advanced YAML",
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
        title: "Intent",
        description: "This section will configure intent thresholds, language preferences, and inbox settings.",
      },
      advanced: {
        title: "Advanced YAML",
        description: "This section will provide raw YAML preview, diffs, and validation before save.",
      },
    },
  },
};

const settingsPanels = {
  downloader: {
    title: "下载器",
    fields: [
      ["qBittorrent target", "local", "选择 downloader target。后续会映射到 downloader.target。"],
      ["Default category", "seed", "默认加入的 qB category。"],
      ["Secret ref", "local/secrets/qbittorrent.json", "本地 qB 凭据文件路径，不保存明文。"],
      ["Over budget", "add_paused", "预算超限时默认暂停添加，避免直接撑爆容量。"],
    ],
  },
  discovery: {
    title: "发现策略",
    fields: [
      ["Discounts", "free", "候选折扣过滤，例如 free 或 2xfree。"],
      ["Min leechers", "1", "低于这个做种需求时不自动加入。"],
      ["Target seed/leecher ratio", "16", "控制热门程度，不再用绝对 seed cap。"],
      ["Allow non-free", "false", "是否允许 NORMAL 候选进入评分。"],
    ],
  },
  cleanup: {
    title: "清理策略",
    fields: [
      ["Cold after days", "7", "多久没有有效上传后视为冷种。"],
      ["Min upload delta GB", "1", "上传增量低于此值才进入清理候选。"],
      ["Protect media library", "true", "媒体库相关种子默认保护。"],
      ["Pause before delete hours", "24", "删除前先暂停观察的小时数。"],
    ],
  },
  intent: {
    title: "资源意图",
    fields: [
      ["Min score", "70", "自动入队的最低评分。"],
      ["Preferred language", "any", "未来用于按语言或地区偏好过滤。"],
      ["Inbox category", "seed", "待处理资源默认进入的 category。"],
      ["Manual review below", "70", "低于自动阈值时进入人工 review。"],
    ],
  },
  advanced: {
    title: "高级 YAML",
    fields: [
      ["Raw YAML preview", "sites:\\n  - name: mt\\n    discovery_mode: api", "预览即将写入的 YAML 片段。"],
      ["Diff mode", "before / after", "保存前展示配置差异。"],
      ["Validation", "strict", "保存前按 seed-agent config schema 校验。"],
      ["Secret boundary", "local/secrets/*", "明文 secret 只写入本地 gitignored 路径。"],
    ],
  },
};

addTrackerButton.addEventListener("click", () => {
  state.trackers.unshift({
    id: crypto.randomUUID(),
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
      { level: "warning", message: "type is required" },
      { level: "warning", message: "tracker name is required" },
      { level: "info", message: "not saved yet" },
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
    state.currentSection = item.dataset.section;
    navItems.forEach((navItem) => {
      navItem.classList.toggle("active", navItem === item);
    });
    renderSection();
  });
});

async function loadConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) {
    renderSection();
    return;
  }
  const payload = await response.json();
  state.trackers = payload.trackers.map((tracker) => ({
    id: crypto.randomUUID(),
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
      ? [{ level: "ok", message: "API key file exists" }]
      : [{ level: "info", message: "not checked yet" }],
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
      throw new Error("status request failed");
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

async function loadInitialData() {
  await Promise.all([loadConfig(), loadOverview()]);
  renderSection();
}

function renderSection() {
  const title = document.querySelector(".page-header h1");
  const subtitle = document.querySelector(".page-header p");
  if (state.currentSection === "overview") {
    title.textContent = copy[state.language].overviewTitle;
    subtitle.textContent = copy[state.language].overviewSubtitle;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderOverviewPanel());
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
      "Heartbeat",
      health.status,
      health.heartbeat_exists
        ? `${health.age_minutes ?? "?"} min old · cycle ${health.heartbeat?.cycle ?? "?"}`
        : "heartbeat file missing",
      health.status === "ok" ? "ok" : "warning",
    ),
  );
  panel.append(
    renderMetricCard("Candidates", stateSummary.candidates?.total ?? 0, formatStateCounts(candidateStates), "info"),
  );
  panel.append(renderMetricCard("Intents", stateSummary.intents?.total ?? 0, formatStateCounts(intentStates), "info"));
  panel.append(
    renderMetricCard(
      "Budget pools",
      budgetPools.length,
      budgetPools.map((pool) => `${pool.name}: ${pool.max_size_tib} TiB`).join(" · ") || "no pools configured",
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
    <div class="status-item ${escapeAttribute(level)}">${escapeHtml(detail || "no data")}</div>
  `;
  return card;
}

function formatStateCounts(counts) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return "no state rows";
  }
  return entries.map(([name, count]) => `${name}: ${count}`).join(" · ");
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
  header.innerHTML = `
    <div class="tracker-title">
      <strong>${escapeHtml(tracker.name || "新 Tracker")}</strong>
      ${tracker.saved ? "" : '<span class="badge warn">未保存</span>'}
      ${tracker.type ? `<span class="badge">${escapeHtml(tracker.type)}</span>` : '<span class="badge">等待类型</span>'}
    </div>
  `;
  const collapse = document.createElement("button");
  collapse.className = "icon-button";
  collapse.type = "button";
  collapse.textContent = tracker.collapsed ? "⌄" : "⌃";
  collapse.addEventListener("click", () => {
    tracker.collapsed = !tracker.collapsed;
    renderSection();
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
        <span>Tracker name ${help("第二个必填项。用于配置引用、日志、站点优先级和搜索结果。")}</span>
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
      <span>Cookie ref ${help("可选。只保存本地 cookie secret 文件路径，不保存明文。")}</span>
      <input data-field="cookie_ref" value="${escapeAttribute(tracker.cookie_ref)}" />
    </label>
  `;
}

function renderApiDiscoveryFields(tracker) {
  return `
    <label class="field">
      <span>API key ref ${help("API 发现方式需要。这里只保存本地 secret 文件路径，例如 local/secrets/mt_api_key。")}</span>
      <input data-field="api_key_ref" value="${escapeAttribute(tracker.api_key_ref)}" />
    </label>
    <label class="field">
      <span>API key ${help("可选填写。保存时写入 API key ref 指向的本地文件，保存后不回显明文。")}</span>
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
      <button class="secondary-button" type="button" data-action="validate" aria-label="Validate This Tracker">验证此 Tracker</button>
      <button class="secondary-button" type="button" data-action="site-probe" aria-label="Site Probe">站点探测</button>
      <button class="secondary-button" type="button" data-action="dry-run" aria-label="Dry-run Preview">Dry-run 预览</button>
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
      tracker.status = [{ level: "warning", message: `request failed: ${response.status}` }];
    }
    if (action === "save" && response.ok) {
      tracker.saved = true;
      tracker.api_key_value = "";
    }
  } catch (error) {
    tracker.status = [{ level: "warning", message: `request failed: ${error.message}` }];
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
          { level: field.value ? "info" : "warning", message: field.value ? "type selected" : "type is required" },
          { level: tracker.name ? "info" : "warning", message: tracker.name ? "tracker name set" : "tracker name is required" },
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

loadInitialData();

function setLanguage(language) {
  state.language = language;
  document.documentElement.lang = language === "CN" ? "zh-CN" : "en";
  languageMenu.hidden = true;
  addTrackerButton.textContent = copy[language].addTracker;
  navItems.forEach((item) => {
    item.textContent = copy[language].nav[item.dataset.section];
  });
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

function renderSettingsPanel(section) {
  const spec = settingsPanels[section];
  const page = document.createElement("div");
  page.className = "settings-panel";
  const fields = spec.fields
    .map(
      ([label, value, description]) => `
        <label class="field">
          <span>${escapeHtml(label)} ${help(description)}</span>
          <input data-setting-field="${escapeAttribute(label)}" value="${escapeAttribute(value)}" />
        </label>
      `,
    )
    .join("");
  page.innerHTML = `
    <div class="section-title">${escapeHtml(spec.title)}</div>
    <div class="field-grid">${fields}</div>
    <div class="tracker-actions">
      <div class="tracker-actions-group">
        <button class="secondary-button" type="button" data-setting-action="validate">验证配置</button>
        <button class="secondary-button" type="button" data-setting-action="preview">预览 YAML</button>
      </div>
      <button class="primary-button" type="button" data-setting-action="save">保存草稿</button>
    </div>
    <div class="status-panel settings-status" data-setting-status>
      <h3>状态</h3>
      <div class="status-list">
        <div class="status-item info">草稿可编辑，尚未写入 YAML。</div>
      </div>
    </div>
  `;
  page.addEventListener("click", (event) => {
    const action = event.target?.dataset?.settingAction;
    if (action) {
      updateSettingsPanelStatus(page, section, action);
    }
  });
  return page;
}

function updateSettingsPanelStatus(page, section, action) {
  const messages = {
    validate: `${settingsPanels[section].title}：配置草稿格式通过。`,
    preview: `${settingsPanels[section].title}：YAML 预览已准备。`,
    save: `${settingsPanels[section].title}：草稿已保存在当前页面状态。`,
  };
  page.querySelector("[data-setting-status] .status-list").innerHTML = `
    <div class="status-item ok">${escapeHtml(messages[action])}</div>
  `;
}
