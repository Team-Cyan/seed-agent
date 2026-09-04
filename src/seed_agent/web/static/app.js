const state = {
  trackers: [],
  overview: {
    health: null,
    stateSummary: null,
    pools: null,
    ops: null,
    error: null,
  },
  wants: {
    items: [],
    error: null,
    loading: true,
    filters: {
      source: "all",
      media_type: "all",
      status: "not_downloaded",
    },
  },
  logs: {
    entries: [],
    error: null,
    loading: true,
    autoRefresh: true,
    filters: {
      source: "all",
      level: "all",
      query: "",
    },
  },
  configSections: {},
  sectionYamls: {},
  configYaml: "",
  configPath: "",
  configRevision: "",
  runtimeRoot: "",
  schedulerEnvironmentOverrides: {},
  language: "CN",
  dark: false,
  currentSection: "overview",
  webToken: "",
};

const trackerList = document.querySelector("[data-tracker-list]");
const addTrackerButton = document.querySelector("[data-add-tracker]");
const themeButton = document.querySelector("[data-theme-button]");
const languageButton = document.querySelector("[data-language-button]");
const languageMenu = document.querySelector("[data-language-menu]");
const webTokenButton = document.querySelector("[data-web-token-button]");
const helpPopover = document.querySelector("[data-help-popover]");
const configPathLabel = document.querySelector("[data-config-path]");
const sectionSwitcher = document.querySelector("[data-section-switcher]");
const sectionGroupLabel = document.querySelector("[data-section-group-label]");
const navGroupLabels = document.querySelectorAll("[data-nav-group-label]");
const navItems = document.querySelectorAll("[data-section]");
let webTokenPrompt = null;

async function requestWebToken() {
  if (!webTokenPrompt) {
    webTokenPrompt = Promise.resolve()
      .then(() =>
        window.prompt(
          state.language === "CN" ? "输入 Web API token" : "Enter Web API token",
          state.webToken,
        ),
      )
      .then((value) => {
        if (value === null) {
          return false;
        }
        state.webToken = value.trim();
        webTokenButton?.classList.toggle("active", Boolean(state.webToken));
        return Boolean(state.webToken);
      })
      .finally(() => {
        webTokenPrompt = null;
      });
  }
  return webTokenPrompt;
}

async function apiFetch(input, init = {}, retryUnauthorized = true) {
  const requestInit = { ...init };
  const method = String(requestInit.method || "GET").toUpperCase();
  const headers = new Headers(init.headers || {});
  if (method === "POST") {
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (requestInit.body === undefined || requestInit.body === null) {
      requestInit.body = "{}";
    }
  }
  if (state.webToken) {
    headers.set("X-Seed-Agent-Token", state.webToken);
  }
  const response = await globalThis.fetch(input, { ...requestInit, headers });
  if (response.status !== 401 || !retryUnauthorized) {
    return response;
  }
  webTokenButton?.removeAttribute("hidden");
  if (!(await requestWebToken())) {
    return response;
  }
  return apiFetch(input, init, false);
}

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
      logs: "运行日志",
      tracker: "站点",
      download_client: "下载与分类",
      pt_filters: "PT 入队规则",
      seed_cleanup: "保种清理",
      scheduler: "定时任务",
      metrics: "监控指标",
      want_decision: "想看决策",
      wants: "想看列表",
      release_preferences: "资源匹配",
      config_file: "配置文件",
    },
    overviewTitle: "状态",
    overviewSubtitle: "本地只读状态：心跳、候选/意图数量和配置的容量池。",
    logsTitle: "运行日志",
    logsSubtitle: "查看持久化的调度、站点、想看搜索和审计事件。",
    trackerTitle: "站点",
    trackerSubtitle: "配置 PT 站点接入方式、认证文件和试运行检查。",
    addTracker: "添加站点",
    emptyTracker: "还没有站点。点击右上角添加站点开始配置。",
    placeholders: {
      download_client: {
        title: "下载与分类",
        description: "配置 qBittorrent 目标、默认分类、分类策略和容量池。",
      },
      pt_filters: {
        title: "PT 入队规则",
        description: "配置优惠标签、做种/下载数、体积上限和运行时限制。",
      },
      seed_cleanup: {
        title: "保种清理",
        description: "配置冷种判断、保护项和按目标容量直接删除。",
      },
      scheduler: {
        title: "定时任务",
        description: "统一配置扫描周期、清理、来源补全和想看搜索频率。",
      },
      metrics: {
        title: "监控指标",
        description: "配置可选的本地 Prometheus 指标端点。",
      },
      want_decision: {
        title: "想看决策",
        description: "配置自动找片/入队阈值、模糊确认、剧集搜索方式和收件箱。",
      },
      wants: {
        title: "想看列表",
        description: "集中查看 Douban 和 IMDb 想看资源，以及搜索/入队状态。",
      },
      release_preferences: {
        title: "资源匹配",
        description: "配置想看候选资源的站点优先级、结果数量、免费偏好和资源格式加减分。",
      },
      config_file: {
        title: "配置文件",
        description: "查看当前配置文件和各配置页对应的 YAML 区块。",
      },
      logs: {
        title: "运行日志",
        description: "查看持久化的调度、站点、想看搜索和审计事件；不需要 Docker socket。",
      },
    },
    ui: {
      addedAt: "添加时间",
      addSource: "新增来源",
      all: "全部",
      markViewed: "标记已看",
      markViewedCompleted: "已标记为已看",
      notFound: "未找到资源",
      notDownloaded: "未下载",
      downloaded: "已下载",
      viewed: "已看",
      apiKeyExists: "API key 文件已存在",
      apiKeyFile: "API key 文件",
      apiKeyFileHelp: "API 发现方式需要。这里只保存本地 secret 文件路径，例如 local/secrets/mt_api_key。",
      apiKeyValue: "API key 明文",
      apiKeyValueHelp: "可选填写。保存时写入 API key 文件指向的本地文件，保存后不回显明文。",
      anime: "动漫",
      authHeaderHelp: "API 请求使用的认证 header。M-Team 默认是 x-api-key。",
      basics: "基础",
      addBudgetPool: "新增容量池",
      addCategoryPolicy: "新增 qB 分类",
      budgetPools: "容量池",
      budgetPoolName: "容量池名称",
      candidateTorrents: "候选种子",
      candidateTorrentsCount: "候选种子",
      categoryPolicies: "qB 分类策略",
      categoryPolicyName: "qB 分类名称",
      cleanupNoConfigChanges: "没有实际配置变化。",
      configuredPools: "已配置容量池",
      close: "关闭",
      closeCandidates: "关闭候选种子",
      collapseTracker: "折叠站点",
      configFileDescription: "当前仍保持一个物理 YAML 文件，避免 CLI、Docker 和 Unraid 部署同时迁移。各配置页会显示并保存自己的 YAML 区块。",
      configFileTitle: "配置文件",
      configNotLoaded: "配置未加载",
      configPathLoadedPrefix: "配置文件: ",
      configPathMissing: "配置文件: 尚未加载",
      configSaved: "配置已保存",
      configYamlNotLoaded: "配置尚未加载。",
      confirmSaveForm: "确认保存表单",
      cookieFile: "Cookie 文件",
      cookieFileHelp: "可选。只保存本地 cookie secret 文件路径，不保存明文。",
      currentConfigFile: "当前配置文件",
      deleteEnabled: "允许自动清理",
      discoveryMode: "发现方式",
      discoveryModeHelp: "M-Team 支持 RSS 或 API。先选这里，再出现对应的认证和地址字段。",
      downloaders: "下载",
      enabled: "启用",
      enqueueQb: "加入 qB",
      expandTracker: "展开站点",
      exportFile: "导出文件",
      failed: "失败",
      fieldHelp: "字段说明",
      forceEnqueueQb: "强制加入 qB",
      formEditable: "表单可编辑，尚未写入 YAML。",
      formPreviewReady: "表单预览已准备。",
      formSavedPageState: "表单已保存在当前页面状态。",
      formValid: "表单格式通过。",
      fromYaml: "来自 YAML",
      runtimeOverrides: "运行时覆盖",
      fullConfigPreview: "完整配置预览",
      fullConfigPreviewDescription: "这里是归一化后的只读预览。需要修改时，进入对应配置页编辑“本页 YAML”。",
      heartbeat: "心跳",
      heartbeatFile: "心跳文件",
      heartbeatMissing: "心跳文件不存在",
      heartbeatStale: "过期",
      heartbeatMissingStatus: "缺失",
      heartbeatOk: "正常",
      imdbWatchlistUrl: "IMDb watchlist URL",
      invalidMapPrefix: "无效映射项",
      invalidMapSuffix: "请使用 site=priority，例如 demo=10。",
      leechers: "下载",
      loading: "加载中",
      logsAllLevels: "全部级别",
      logsAllSources: "全部来源",
      logsAutoRefresh: "自动刷新",
      logsEmpty: "当前筛选条件下没有日志。",
      logsFilter: "筛选日志",
      logDetails: "事件详情",
      logsRefresh: "刷新",
      logsRefreshed: "最近刷新",
      logsSearchPlaceholder: "搜索标题、消息、run ID…",
      logsSourceAudit: "审计",
      logsSourceScheduler: "调度",
      logsSourceTracker: "站点",
      logsSourceWant: "想看",
      loadingCandidates: "正在读取候选",
      localApiLoading: "正在读取本地只读 API。",
      lowerMatch: "低匹配，可强制",
      maxSizeTib: "容量上限 TiB",
      qualityTagScores: "常见标签加减分",
      qualityTagScoresHelp: "给常见资源标签设置整数加减分；同组别名只计一次，避免 BluRay 和 Blu-ray 重复加分或扣分。",
      scoreAdjustment: "加减分",
      bestCandidateScore: "最高分",
      mediaCategoryMap: "想看类型路由",
      mediaType: "类型",
      mode: "模式",
      modeAddOnly: "只新增",
      modeMutable: "可清理",
      minutesAgoCycle: "分钟前 · 第",
      movie: "电影",
      name: "名称",
      newSite: "新站点",
      noCandidates: "还没有候选。先点“搜索”。",
      noDashboardAttention: "当前没有需要特别处理的状态。",
      noData: "无数据",
      inactive: "未启用",
      noPools: "未配置容量池",
      noStateRecords: "暂无状态记录",
      noTags: "无标签",
      noWants: "暂无想看资源",
      noWantsHelp: "先刷新已配置来源，或打开来源配置接入豆瓣/IMDb；有条目后再搜索种子。",
      notChecked: "尚未检查",
      notSaved: "尚未保存",
      operationComplete: "操作完成",
      opsDashboard: "调度",
      pages: "页数",
      preview: "预览",
      previewFormChanges: "预览表单改动",
      previewThisPageYaml: "预览本页 YAML",
      provider: "来源",
      readingStatus: "状态读取",
      releasePresets: "资源偏好模板",
      remove: "移除",
      refreshWants: "刷新列表",
      requestFailedPrefix: "请求失败",
      resourceIntents: "获取意图",
      recentSchedulerRuns: "最近调度",
      runtimeProvenance: "配置与运行来源",
      runtimeManagedCount: "运行中任务",
      runtimeRoot: "运行根目录",
      rssUrlHelp: "RSS 发现方式需要填写订阅地址。选择 API 时不会要求这个字段。",
      presetAnimeSubtitleFriendly: "动漫字幕友好",
      presetApplied: "模板已应用，请预览后保存。",
      presetMovieRemuxFirst: "电影 Remux 优先",
      presetSpaceSaving: "空间节省",
      presetTvWebdlFirst: "剧集 WEB-DL 优先",
      save: "保存",
      saveConfirmation: "保存确认",
      saveForm: "保存表单",
      score: "分数",
      saveThisPageYaml: "保存本页 YAML",
      search: "搜索",
      searchCompleted: "搜索已完成",
      searchCurrentFilter: "搜索当前筛选",
      searchOneWant: "搜索这条",
      searchingWants: "正在搜索种子",
      searchTorrentsCurrentFilter: "搜索种子",
      sectionYamlDescription: "对应 {path} 中的 {section}: 区块。可以保留顶层区块名，也可以只填写区块内容。",
      sectionYamlTitle: "本页 YAML",
      seeders: "做种",
      selectType: "选择类型...",
      settingsDescription: "可以用表单编辑常用项，也可以直接编辑本页 YAML 区块。保存前会先做 schema 校验。",
      siteName: "站点名称",
      siteNameFilled: "站点名称已填写",
      siteNameHelp: "第二个必填项。用于配置引用、日志、站点优先级和搜索结果。",
      siteNameRequired: "站点名称必填",
      sourceConfig: "来源配置",
      sourceConfigTitle: "想看来源配置",
      stateDatabase: "状态数据库",
      status: "状态",
      strategySummary: "策略概要",
      summaryPreferFree: "优先免费",
      summaryRejectHr: "默认拒绝 HR",
      summarySitePriority: "站点优先级",
      summaryTaggedRules: "标签规则",
      dashboardAttention: "需要关注",
      tags: "标签",
      overBudgetBehavior: "超预算处理",
      overBudgetReject: "拒绝入队",
      statusAccepted: "已接受",
      statusConfirmationRequired: "待复核",
      statusDeleted: "已删除",
      statusDownloading: "下载中",
      statusEnqueued: "已入队",
      statusFailed: "失败",
      statusRejected: "已拒绝",
      statusScored: "已评分",
      statusSeeding: "做种中",
      syncWantsCompleted: "想看来源已同步",
      syncingWants: "正在刷新想看列表",
      title: "标题",
      trackerCancel: "取消",
      trackerApiEvents: "站点 API",
      trackerBackoff: "站点退避",
      schedulerPhase: "Scheduler 状态",
      schedulerRunning: "正在执行",
      schedulerWaiting: "等待下一轮",
      schedulerUnavailable: "状态不可用",
      schedulerNextCycle: "下一轮",
      schedulerDue: "已到计划时间，等待 scheduler 唤醒",
      schedulerQueuedImmediate: "已排队，将立即执行",
      schedulerTriggerNow: "立即执行一轮",
      schedulerTriggerRequest: "立即执行请求",
      schedulerTriggering: "正在触发",
      schedulerTriggerQueued: "已触发，后台将立即执行",
      schedulerClearBackoff: "清除限流",
      schedulerClearingBackoff: "正在清除限流",
      schedulerBackoffCleared: "限流状态已清除",
      schedulerConfirmClearBackoff: "确认清除限流",
      schedulerClearBackoffConfirm: "确认清除当前 M-Team backoff？真实限流保护仍会保留。",
      schedulerBackoffStatus: "限流状态",
      schedulerBackoffActive: "已限流",
      schedulerBackoffInactive: "未限流",
      schedulerBackoffStarted: "限流开始",
      schedulerBackoffEnds: "预计解除",
      trackerConfigMteam: "M-Team 配置",
      trackerConfigNexusphp: "NexusPHP 配置",
      trackerDryRun: "试运行预览",
      trackerProbe: "站点探测",
      trackerValidate: "验证此站点",
      tv: "电视剧",
      type: "类型",
      typeHelp: "第一个必填项。选择后，下方才显示该类型需要继续配置的字段。",
      typeRequired: "类型必填",
      typeSelected: "类型已选择",
      unknown: "未知",
      unknownSize: "未知体积",
      unsaved: "未保存",
      validateForm: "验证表单",
      viewCandidates: "查看候选",
      waitingType: "等待类型",
      wantRoutingHelp: "把想看列表里的电影、电视剧、动漫分别映射到 qB 分类。留空会使用后端默认回退。",
      wantCandidateSubtitle: "符合偏好的候选排在前面；低匹配候选会灰显，但仍可手动强制加入 qB。",
      wantSearchHistory: "搜索记录",
      wantSearchCounts: "返回 / 筛选后 / 接受",
      wantSearchNoHistory: "暂无搜索记录",
      wantSearchQueryPath: "查询路径",
      wantResources: "想看资源",
      wantSearchRuns: "想看搜索",
      wantsReadFailed: "想看列表读取失败",
      yes: "是",
      no: "否",
      attentionHeartbeat: "心跳不是正常状态，请检查 schedule-run 或容器状态。",
      attentionCandidateFailures: "候选种子里存在失败记录。",
      attentionIntentFailures: "获取意图里存在失败记录。",
      attentionNoPools: "还没有配置容量池，dashboard 无法展示容量边界。",
      doubanUser: "Douban 用户",
      chooseTypeFirst: "先选择类型。选完类型后，只显示这个类型需要继续配置的选项。",
      matchingPreference: "符合偏好",
      candidateNeedsReview: "需要确认",
      candidateScoreUnit: "分",
      scoreEvidence: "评分依据",
      mediaInfo: "媒体信息",
      processing: "正在处理",
      thisPageYamlSaved: "本页 YAML 已保存",
      thisPageYamlPreviewReady: "本页 YAML 预览已准备",
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
      logs: "Logs",
      tracker: "Tracker",
      download_client: "Download Client",
      pt_filters: "PT Intake Rules",
      seed_cleanup: "Seed Cleanup",
      scheduler: "Scheduler",
      metrics: "Metrics",
      want_decision: "Want Decisions",
      wants: "Want List",
      release_preferences: "Release Matching",
      config_file: "Config File",
    },
    overviewTitle: "Status",
    overviewSubtitle: "Local read-only status: heartbeat, candidate/intent counts, and configured budget pools.",
    logsTitle: "Logs",
    logsSubtitle: "Review durable scheduler, tracker, Want search, and audit events.",
    trackerTitle: "Tracker",
    trackerSubtitle: "New users start empty. Click Add Tracker to create a tracker card.",
    addTracker: "Add Tracker",
    emptyTracker: "No trackers yet. Click Add Tracker in the top right to start.",
    placeholders: {
      download_client: {
        title: "Download Client",
        description: "This section will configure the qBittorrent target, category policies, and budget pools.",
      },
      pt_filters: {
        title: "PT Intake Rules",
        description: "This section will configure freeleech filters, seed/leech limits, size bounds, and runtime gates.",
      },
      seed_cleanup: {
        title: "Seed Cleanup",
        description: "This section will configure cold torrent rules, protections, and target-limited capacity deletion.",
      },
      scheduler: {
        title: "Scheduler",
        description: "Configure cycle timing, pruning, tracker backfill, and scheduled Want List search frequency.",
      },
      metrics: {
        title: "Metrics",
        description: "Configure the optional local Prometheus metrics endpoint.",
      },
      want_decision: {
        title: "Want Decisions",
        description: "Configure score thresholds, ambiguity handling, series mode, and inbox settings for automated acquisition.",
      },
      wants: {
        title: "Want List",
        description: "Review Douban and IMDb wants with search and queue status.",
      },
      release_preferences: {
        title: "Release Matching",
        description: "Configure Want List candidate limits, site priority, freeleech preference, and release-format score adjustments.",
      },
      config_file: {
        title: "Config File",
        description: "Review the active config file and the YAML sections edited by each page.",
      },
      logs: {
        title: "Logs",
        description: "Review durable scheduler, tracker, Want search, and audit events without Docker socket access.",
      },
    },
    ui: {
      addedAt: "Added at",
      addSource: "Add source",
      all: "All",
      markViewed: "Mark viewed",
      markViewedCompleted: "Marked as viewed",
      notFound: "No resource found",
      notDownloaded: "Not downloaded",
      downloaded: "Downloaded",
      viewed: "Viewed",
      apiKeyExists: "API key file exists",
      apiKeyFile: "API key file",
      apiKeyFileHelp: "Required for API discovery. Stores only the local secret file path, for example local/secrets/mt_api_key.",
      apiKeyValue: "API key value",
      apiKeyValueHelp: "Optional. On save, writes the value into the configured API key file and does not echo it back.",
      anime: "Anime",
      authHeaderHelp: "Authentication header used by API requests. M-Team defaults to x-api-key.",
      basics: "Basics",
      addBudgetPool: "Add budget pool",
      addCategoryPolicy: "Add qB category",
      budgetPools: "Budget pools",
      budgetPoolName: "Budget pool name",
      candidateTorrents: "Candidate torrents",
      candidateTorrentsCount: "Candidate torrents",
      categoryPolicies: "qB category policies",
      categoryPolicyName: "qB category name",
      cleanupNoConfigChanges: "No actual config changes.",
      configuredPools: "Configured pools",
      close: "Close",
      closeCandidates: "Close candidate torrents",
      collapseTracker: "Collapse tracker",
      configFileDescription: "The runtime still uses one physical YAML file so CLI, Docker, and Unraid deployments migrate together. Each settings page can show and save its own YAML section.",
      configFileTitle: "Config file",
      configNotLoaded: "Config file is not loaded",
      configPathLoadedPrefix: "Config file: ",
      configPathMissing: "Config file: not loaded",
      configSaved: "Config saved",
      configYamlNotLoaded: "Config is not loaded.",
      confirmSaveForm: "Confirm save form",
      cookieFile: "Cookie file",
      cookieFileHelp: "Optional. Stores only the local cookie secret file path, not the cookie value.",
      currentConfigFile: "current config file",
      deleteEnabled: "Allow cleanup",
      discoveryMode: "Discovery mode",
      discoveryModeHelp: "M-Team supports RSS or API. Pick this first, then only the fields for that mode appear.",
      downloaders: "Downloads",
      enabled: "Enabled",
      enqueueQb: "Add to qB",
      expandTracker: "Expand tracker",
      exportFile: "Export file",
      failed: "Failed",
      fieldHelp: "Field help",
      forceEnqueueQb: "Force add to qB",
      formEditable: "Form is editable and has not been written to YAML.",
      formPreviewReady: "Form preview is ready.",
      formSavedPageState: "Form is saved in the current page state.",
      formValid: "Form format is valid.",
      fromYaml: "From YAML",
      runtimeOverrides: "Runtime overrides",
      fullConfigPreview: "Full config preview",
      fullConfigPreviewDescription: "This is the normalized read-only preview. To edit, open the matching settings page and update This page YAML.",
      heartbeat: "Heartbeat",
      heartbeatFile: "Heartbeat file",
      heartbeatMissing: "Heartbeat file is missing",
      heartbeatStale: "Stale",
      heartbeatMissingStatus: "Missing",
      heartbeatOk: "OK",
      imdbWatchlistUrl: "IMDb watchlist URL",
      invalidMapPrefix: "Invalid map entry",
      invalidMapSuffix: "Use site=priority, for example demo=10.",
      leechers: "leechers",
      loading: "Loading",
      logsAllLevels: "All levels",
      logsAllSources: "All sources",
      logsAutoRefresh: "Auto refresh",
      logsEmpty: "No logs match the current filters.",
      logsFilter: "Filter logs",
      logDetails: "Event details",
      logsRefresh: "Refresh",
      logsRefreshed: "Last refreshed",
      logsSearchPlaceholder: "Search title, message, or run ID…",
      logsSourceAudit: "Audit",
      logsSourceScheduler: "Scheduler",
      logsSourceTracker: "Tracker",
      logsSourceWant: "Want",
      loadingCandidates: "Loading candidates",
      localApiLoading: "Reading the local read-only API.",
      lowerMatch: "Lower match, force allowed",
      maxSizeTib: "Size limit TiB",
      qualityTagScores: "Common tag scores",
      qualityTagScoresHelp: "Set integer score adjustments for common release tags. Aliases in the same group count once, so BluRay and Blu-ray do not double-score.",
      scoreAdjustment: "Score",
      bestCandidateScore: "Best score",
      mediaCategoryMap: "Want type routing",
      mediaType: "Type",
      mode: "Mode",
      modeAddOnly: "Add only",
      modeMutable: "Mutable",
      minutesAgoCycle: "minutes ago · cycle",
      movie: "Movie",
      name: "Name",
      newSite: "New tracker",
      noCandidates: "No candidates yet. Run Search first.",
      noDashboardAttention: "No status needs attention right now.",
      noData: "No data",
      inactive: "Inactive",
      noPools: "No budget pools configured",
      noStateRecords: "No state records yet",
      noTags: "No tags",
      noWants: "No wants yet",
      noWantsHelp: "Refresh configured sources first, or open Source config to connect Douban/IMDb. Search torrents after wants appear.",
      notChecked: "Not checked",
      notSaved: "Not saved",
      operationComplete: "Operation completed",
      opsDashboard: "Scheduler",
      pages: "Pages",
      preview: "Preview",
      previewFormChanges: "Preview form changes",
      previewThisPageYaml: "Preview this page YAML",
      provider: "Source",
      readingStatus: "Status read",
      releasePresets: "Release presets",
      remove: "Remove",
      refreshWants: "Refresh list",
      requestFailedPrefix: "Request failed",
      resourceIntents: "Resource intents",
      recentSchedulerRuns: "Recent runs",
      runtimeProvenance: "Config and runtime provenance",
      runtimeManagedCount: "Runtime tasks",
      runtimeRoot: "Runtime root",
      rssUrlHelp: "RSS discovery needs a feed URL. This field is not required in API mode.",
      presetAnimeSubtitleFriendly: "Anime subtitle friendly",
      presetApplied: "Preset applied. Preview before saving.",
      presetMovieRemuxFirst: "Movie Remux first",
      presetSpaceSaving: "Space saving",
      presetTvWebdlFirst: "TV WEB-DL first",
      save: "Save",
      saveConfirmation: "Save confirmation",
      saveForm: "Save form",
      score: "Score",
      saveThisPageYaml: "Save this page YAML",
      search: "Search",
      searchCompleted: "Search completed",
      searchCurrentFilter: "Search current filters",
      searchOneWant: "Search this",
      searchingWants: "Searching torrents",
      searchTorrentsCurrentFilter: "Search torrents",
      sectionYamlDescription: "Maps to the {section}: block in {path}. You can keep the top-level section name or enter only the section body.",
      sectionYamlTitle: "This page YAML",
      seeders: "seeders",
      selectType: "Select type...",
      settingsDescription: "Edit common options with the form, or edit this page YAML directly. Saves run schema validation first.",
      siteName: "Site name",
      siteNameFilled: "Site name filled",
      siteNameHelp: "The second required field. Used by config references, logs, site priority, and search results.",
      siteNameRequired: "Site name is required",
      sourceConfig: "Source config",
      sourceConfigTitle: "Want source config",
      stateDatabase: "State database",
      status: "Status",
      strategySummary: "Strategy summary",
      summaryPreferFree: "Prefer free",
      summaryRejectHr: "Reject HR by default",
      summarySitePriority: "Site priority",
      summaryTaggedRules: "Tag rules",
      dashboardAttention: "Needs attention",
      tags: "Tags",
      overBudgetBehavior: "Over budget",
      overBudgetReject: "Reject enqueue",
      statusAccepted: "Accepted",
      statusConfirmationRequired: "Needs review",
      statusDeleted: "Deleted",
      statusDownloading: "Downloading",
      statusEnqueued: "Queued",
      statusFailed: "Failed",
      statusRejected: "Rejected",
      statusScored: "Scored",
      statusSeeding: "Seeding",
      syncWantsCompleted: "Want sources synced",
      syncingWants: "Refreshing Want List",
      title: "Title",
      trackerCancel: "Cancel",
      trackerApiEvents: "Tracker API",
      trackerBackoff: "Tracker backoff",
      schedulerPhase: "Scheduler state",
      schedulerRunning: "Running",
      schedulerWaiting: "Waiting",
      schedulerUnavailable: "Unavailable",
      schedulerNextCycle: "Next cycle",
      schedulerDue: "Due; waiting for the scheduler to wake",
      schedulerQueuedImmediate: "Queued to run immediately",
      schedulerTriggerNow: "Run one cycle now",
      schedulerTriggerRequest: "Immediate run request",
      schedulerTriggering: "Triggering",
      schedulerTriggerQueued: "Triggered; the scheduler will run immediately",
      schedulerClearBackoff: "Clear backoff",
      schedulerClearingBackoff: "Clearing backoff",
      schedulerBackoffCleared: "Backoff cleared",
      schedulerConfirmClearBackoff: "Confirm clear backoff",
      schedulerClearBackoffConfirm: "Clear the current M-Team backoff? Future rate-limit protection remains enabled.",
      schedulerBackoffStatus: "Rate-limit state",
      schedulerBackoffActive: "Rate limited",
      schedulerBackoffInactive: "Not rate limited",
      schedulerBackoffStarted: "Rate limit started",
      schedulerBackoffEnds: "Expected release",
      trackerConfigMteam: "M-Team config",
      trackerConfigNexusphp: "NexusPHP config",
      trackerDryRun: "Dry-run preview",
      trackerProbe: "Site probe",
      trackerValidate: "Validate tracker",
      tv: "TV",
      type: "Type",
      typeHelp: "The first required field. After selecting it, only fields for that tracker type are shown below.",
      typeRequired: "Type is required",
      typeSelected: "Type selected",
      unknown: "Unknown",
      unknownSize: "Unknown size",
      unsaved: "Unsaved",
      validateForm: "Validate form",
      viewCandidates: "View candidates",
      waitingType: "Waiting for type",
      wantRoutingHelp: "Map movie, TV, and anime wants to qB categories. Empty fields use the backend fallback.",
      wantCandidateSubtitle: "Preferred candidates stay first; lower-match candidates are dimmed but can still be forced into qB.",
      wantSearchHistory: "Search history",
      wantSearchCounts: "Returned / ranked / accepted",
      wantSearchNoHistory: "No search history",
      wantSearchQueryPath: "Query path",
      wantResources: "Wanted resources",
      wantSearchRuns: "Want searches",
      wantsReadFailed: "Failed to read Want List",
      yes: "Yes",
      no: "No",
      attentionHeartbeat: "Heartbeat is not OK. Check schedule-run or container status.",
      attentionCandidateFailures: "Candidate torrents include failed records.",
      attentionIntentFailures: "Resource intents include failed records.",
      attentionNoPools: "No budget pools are configured, so the dashboard cannot show capacity boundaries.",
      doubanUser: "Douban user",
      chooseTypeFirst: "Choose a type first. After that, only fields for the selected tracker type are shown.",
      matchingPreference: "Matches preferences",
      candidateNeedsReview: "Needs review",
      candidateScoreUnit: "pts",
      scoreEvidence: "Score details",
      mediaInfo: "Media info",
      processing: "Processing",
      thisPageYamlSaved: "This page YAML saved",
      thisPageYamlPreviewReady: "This page YAML preview is ready",
    },
  },
};

const settingsPanelsByLanguage = {
  CN: {
    download_client: {
      title: "下载与分类",
      fields: [
        ["qBittorrent 目标", "target", "text", "选择下载器目标。会写入 download_client.target。"],
        ["默认分类", "default_category", "text", "默认加入的 qBittorrent 分类。"],
        ["凭据文件", "secret_ref", "optional-text", "本地 qB 凭据文件路径，不保存明文。"],
      ],
    },
    pt_filters: {
      title: "PT 入队规则",
      fields: [
        ["优惠标签", "discounts", "csv", "候选折扣过滤，例如 free 或 2xfree。"],
        ["免费剩余时间下限", "min_left_time_minutes", "number", "免费窗口剩余分钟数低于此值时不自动加入。"],
        ["最小做种数", "min_seeders", "optional-number", "低于此做种数时不自动加入；留空表示不限制。"],
        ["最小下载数", "min_leechers", "number", "低于这个下载需求时不自动加入。"],
        ["下载数满分倍率", "leecher_score_full_at_multiplier", "number", "达到最小下载数乘以该倍率时拿满需求分；0 表示关闭渐进评分。"],
        ["目标做种/下载比", "target_seed_leecher_ratio", "number", "控制热门程度，不再使用绝对做种数上限。"],
        ["最大做种/下载比", "max_seed_leecher_ratio", "optional-number", "超过该竞争比时硬拒绝；0 或留空表示不限制。"],
        ["新鲜度满分小时", "freshness_full_score_hours", "number", "发布时间在该窗口内时拿满新鲜度分。"],
        ["新鲜度归零小时", "freshness_zero_score_hours", "number", "超过该窗口后新鲜度分归零；0 表示关闭年龄衰减。"],
        ["允许非免费", "allow_non_free", "boolean", "是否允许普通候选进入评分。"],
        ["最大体积 GB", "max_size_gb", "optional-number", "候选硬大小上限；0 或留空表示不限制。"],
        ["最大活动下载数", "max_active_downloads", "optional-number", "仅限 seed 刷上传队列；达到上限后拒绝新的 seed 入队，0 或留空表示不限制。"],
        ["最大剩余下载量 GB", "max_total_amount_left_gb", "optional-number", "预计剩余下载量超过上限时拒绝新的自动入队，0 或留空表示不限制。"],
        ["保留磁盘空间 GB", "min_free_disk_gb", "optional-number", "下载器真实剩余空间扣除既有未完成下载后低于此值时拒绝新的自动入队。"],
      ],
    },
    seed_cleanup: {
      title: "保种清理",
      fields: [
        ["冷种天数", "cold_after_days", "number", "多久没有有效上传后视为冷种。"],
        ["最小上传增量 GB", "min_upload_delta_gb", "number", "上传增量低于此值才进入清理候选。"],
        ["保护 HR", "protect_hr", "boolean", "HR 风险项默认保护。"],
        ["保护手动标记", "protect_manual", "boolean", "手动标记项默认保护。"],
        ["保护媒体库", "protect_media_library", "boolean", "媒体库相关种子默认保护。"],
        ["零上传删除小时数", "delete_after_no_upload_hours", "number", "零上传观察窗口。"],
        ["单轮软清理上限", "max_capacity_deletes_per_run", "number", "限制非硬上限场景的容量清理数量；池已超限和直接付费风险不受此限制。"],
      ],
    },
    scheduler: {
      title: "定时任务",
      fields: [
        ["扫描周期（分钟）", "interval_minutes", "number", "每轮 scheduled task 的间隔。"],
        ["容量守卫（秒）", "capacity_guard_interval_seconds", "number", "完整扫描之间仅检查 qB 硬容量和错误任务的频率。"],
        ["候选免费窗口下限", "min_free_window_minutes", "optional-number", "执行入队时要求的剩余免费分钟数；留空表示不限制。"],
        ["要求已知免费窗口", "require_known_free_window", "boolean", "自动入队前必须能确认免费窗口。"],
        ["启用清理", "prune_enabled", "boolean", "每轮运行 tracker backfill 后执行 seed 清理。"],
        ["启用来源补全", "tracker_backfill_enabled", "boolean", "扫描 qB-only 任务并补充 tracker 促销证据。"],
        ["单项补全 API 预算", "tracker_backfill_max_api_requests", "number", "限制批量列表未覆盖时使用 detail/search 降级补全的次数；批量分页不消耗此预算，已有新鲜证据的任务六小时内不重复降级查询。"],
        ["启用想看同步", "intent_enabled", "boolean", "每轮同步配置的想看来源。"],
        ["想看自动入队", "intent_execute", "boolean", "允许 scheduled Want List 结果自动写入下载器。"],
        ["想看搜索频率", "intent_search_mode", "select:daily|every_cycle", "每天在指定小时后执行一次，或每轮搜索。"],
        ["每日搜索小时", "intent_search_hour", "number", "daily 模式下使用本地时区的 0-23 小时；错过后会在下一轮补跑。"],
        ["Scheduler Lease 分钟", "lease_ttl_minutes", "number", "实例失联后允许其他 scheduler 接管前的等待时间。"],
      ],
    },
    metrics: {
      title: "监控指标",
      fields: [
        ["启用 Metrics", "enabled", "boolean", "从本地 SQLite 和 heartbeat 暴露 Prometheus 指标，不调用 tracker 或下载器。"],
        ["Metrics 路径", "path", "text", "Prometheus 拉取路径，例如 /metrics。"],
      ],
    },
    want_decision: {
      title: "想看决策",
      fields: [
        ["复核阈值", "confirmation_threshold", "number", "低于自动入队阈值或有风险时进入人工复核。"],
        ["自动入队阈值", "auto_enqueue_threshold", "number", "高于此阈值可自动入队。"],
        ["模糊分差", "ambiguity_gap", "number", "候选分差低于此值时视为模糊。"],
        ["默认清晰度", "default_resolution", "optional-text", "默认解析度偏好。"],
        ["剧集搜索方式", "series_search_mode", "select:season|episode", "电视剧/动漫按整季搜索或按单集搜索。"],
        ["偏好语言", "preferred_languages", "csv", "按逗号填写语言偏好。"],
        ["收件箱文件", "inbox_ref", "text", "本地意图收件箱 JSONL 路径。"],
      ],
    },
    release_preferences: {
      title: "资源匹配",
      fields: [
        ["站点优先级", "site_priority", "map", "按 site=priority 填写，例如 mteam=10。只影响搜索排序，不保存 secret。"],
        ["每站结果上限", "max_results_per_site", "number", "每个站点最多保留的搜索结果数量。"],
        ["每个意图 API 请求上限", "max_api_requests_per_intent", "number", "限制 ID 与标题回退查询的总次数。"],
        ["优先免费", "prefer_free", "boolean", "搜索排序中优先 free/freeleech 资源。"],
        ["默认排除 HR", "reject_hr_by_default", "boolean", "默认拒绝 HR 风险资源。"],
      ],
    },
  },
  EN: {
    download_client: {
      title: "Download Client",
      fields: [
        ["qBittorrent target", "target", "text", "Select the downloader target. Writes download_client.target."],
        ["Default category", "default_category", "text", "Default qBittorrent category for new tasks."],
        ["Credential file", "secret_ref", "optional-text", "Local qB credential file path. Plain secrets are not saved here."],
      ],
    },
    pt_filters: {
      title: "PT Intake Rules",
      fields: [
        ["Discount labels", "discounts", "csv", "Candidate discount filters, for example free or 2xfree."],
        ["Minimum free minutes left", "min_left_time_minutes", "number", "Skip automatic enqueue when the free window is shorter than this."],
        ["Minimum seeders", "min_seeders", "optional-number", "Skip automatic enqueue below this seeder count; empty means no limit."],
        ["Minimum leechers", "min_leechers", "number", "Skip automatic enqueue below this demand count."],
        ["Leecher full-score multiplier", "leecher_score_full_at_multiplier", "number", "Grant full demand credit at minimum leechers times this value; 0 disables the ramp."],
        ["Target seeder/leecher ratio", "target_seed_leecher_ratio", "number", "Controls demand pressure; no absolute seeder cap is used."],
        ["Maximum seeder/leecher ratio", "max_seed_leecher_ratio", "optional-number", "Hard-reject above this competition ratio; 0 or empty means no limit."],
        ["Freshness full-score hours", "freshness_full_score_hours", "number", "Grant full freshness credit inside this publication-age window."],
        ["Freshness zero-score hours", "freshness_zero_score_hours", "number", "Freshness tapers to zero at this age; 0 disables age decay."],
        ["Allow non-free", "allow_non_free", "boolean", "Allow normal candidates into scoring."],
        ["Maximum size GB", "max_size_gb", "optional-number", "Hard candidate size cap; 0 or empty means no limit."],
        ["Maximum active downloads", "max_active_downloads", "optional-number", "Seed upload-farming only. At the limit, reject new seed enqueue; 0 or empty means no limit."],
        ["Maximum remaining download GB", "max_total_amount_left_gb", "optional-number", "Reject new automatic enqueue above this limit; 0 or empty means no limit."],
        ["Minimum free disk GB", "min_free_disk_gb", "optional-number", "Reserve this much downloader-reported free disk after existing incomplete downloads."],
      ],
    },
    seed_cleanup: {
      title: "Seed Cleanup",
      fields: [
        ["Cold after days", "cold_after_days", "number", "Treat torrents as cold after this many days without useful upload."],
        ["Minimum upload delta GB", "min_upload_delta_gb", "number", "Only cleanup candidates below this upload delta."],
        ["Protect HR", "protect_hr", "boolean", "Protect HR-risk torrents by default."],
        ["Protect manual marks", "protect_manual", "boolean", "Protect manually marked torrents by default."],
        ["Protect media library", "protect_media_library", "boolean", "Protect media-library torrents by default."],
        ["Delete after no-upload hours", "delete_after_no_upload_hours", "number", "Zero-upload observation window."],
        ["Soft capacity deletes per run", "max_capacity_deletes_per_run", "number", "Caps non-hard-cap cleanup; an exceeded pool limit and direct paid-risk deletion bypass this value."],
      ],
    },
    scheduler: {
      title: "Scheduler",
      fields: [
        ["Interval minutes", "interval_minutes", "number", "Delay between scheduled cycles."],
        ["Capacity guard seconds", "capacity_guard_interval_seconds", "number", "qB-only hard-cap and error check frequency between full cycles."],
        ["Minimum free-window minutes", "min_free_window_minutes", "optional-number", "Required free-window headroom for execute-mode enqueue; empty disables it."],
        ["Require known free window", "require_known_free_window", "boolean", "Require verified free-window evidence before automatic enqueue."],
        ["Enable prune", "prune_enabled", "boolean", "Run seed cleanup after tracker backfill each cycle."],
        ["Enable tracker backfill", "tracker_backfill_enabled", "boolean", "Resolve tracker and promotion evidence for qB-only tasks."],
        ["Fallback API budget", "tracker_backfill_max_api_requests", "number", "Limit detail/search fallback calls when the batched user-torrent list does not cover a task; batch pagination does not consume this budget, and fresh evidence suppresses repeat fallback for six hours."],
        ["Enable Want sync", "intent_enabled", "boolean", "Sync configured Want List sources each cycle."],
        ["Execute Want enqueue", "intent_execute", "boolean", "Allow scheduled Want List matches to mutate the downloader."],
        ["Want search frequency", "intent_search_mode", "select:daily|every_cycle", "Search once daily after a local hour, or on every cycle."],
        ["Daily search hour", "intent_search_hour", "number", "Local hour from 0 through 23; a missed run is caught up on the next cycle."],
        ["Scheduler lease minutes", "lease_ttl_minutes", "number", "Time before another scheduler can take over an abandoned lease."],
      ],
    },
    metrics: {
      title: "Metrics",
      fields: [
        ["Enable metrics", "enabled", "boolean", "Expose Prometheus metrics from local SQLite and heartbeat state without tracker/downloader calls."],
        ["Metrics path", "path", "text", "Prometheus scrape path, for example /metrics."],
      ],
    },
    want_decision: {
      title: "Want Decisions",
      fields: [
        ["Review threshold", "confirmation_threshold", "number", "Below the auto-enqueue threshold or with risks, candidates require review."],
        ["Auto-enqueue threshold", "auto_enqueue_threshold", "number", "Above this threshold, candidates can auto-enqueue."],
        ["Ambiguity gap", "ambiguity_gap", "number", "Treat close-scored candidates as ambiguous below this score gap."],
        ["Default resolution", "default_resolution", "optional-text", "Default resolution preference."],
        ["Series search mode", "series_search_mode", "select:season|episode", "Search TV/anime by full season or by individual episode."],
        ["Preferred languages", "preferred_languages", "csv", "Comma-separated language preferences."],
        ["Inbox file", "inbox_ref", "text", "Local intent inbox JSONL path."],
      ],
    },
    release_preferences: {
      title: "Release Matching",
      fields: [
        ["Site priority", "site_priority", "map", "Use site=priority, for example mteam=10. Affects search ranking only and never saves secrets."],
        ["Max results per site", "max_results_per_site", "number", "Maximum retained search results per site."],
        ["API requests per intent", "max_api_requests_per_intent", "number", "Bounds identifier and title fallback queries."],
        ["Prefer free", "prefer_free", "boolean", "Prefer free/freeleech releases in search ranking."],
        ["Reject HR by default", "reject_hr_by_default", "boolean", "Reject HR-risk releases by default."],
      ],
    },
  },
};

const qualityTagGroups = [
  {
    key: "remux",
    label: "Remux",
    aliases: ["REMUX"],
    CN: "从蓝光盘抽取原始音视频并重新封装，通常不重新编码。常见于电影收藏，体积很大。",
    EN: "Original Blu-ray video and audio streams repackaged without re-encoding. Common for movie archives and usually very large.",
  },
  {
    key: "bluray",
    label: "Blu-ray",
    aliases: ["BluRay", "Blu-ray", "Bluray", "Blue-Ray", "蓝光", "BDRip"],
    CN: "来自蓝光盘源或蓝光压制。电影和完结动漫常见，通常比 WEB 来源体积更大。",
    EN: "Blu-ray-sourced or Blu-ray-encoded releases. Common for movies and finished anime, usually larger than WEB releases.",
  },
  {
    key: "uhd_bluray",
    label: "UHD Blu-ray",
    aliases: ["UHD BluRay", "4K UHD", "Ultra HD"],
    CN: "4K UHD 蓝光来源，常见于电影 Remux 或高质量压制。",
    EN: "4K UHD Blu-ray source, often used for movie Remuxes or high-quality encodes.",
  },
  {
    key: "webdl",
    label: "WEB-DL",
    aliases: ["WEB-DL", "WEBDL", "WEB DL"],
    CN: "流媒体平台原档下载，通常没有屏幕录制或二次压制痕迹。电视剧和新番动漫常见。",
    EN: "A direct file from a streaming platform, usually without screen capture or extra re-encoding artifacts. Common for TV and current anime.",
  },
  {
    key: "webrip",
    label: "WEBRip",
    aliases: ["WEBRip", "WEB-Rip"],
    CN: "流媒体录制或再处理版本，通常不如 WEB-DL 干净。",
    EN: "Captured or reprocessed streaming release, usually less clean than WEB-DL.",
  },
  {
    key: "hdtv",
    label: "HDTV",
    aliases: ["HDTV"],
    CN: "电视播出版来源，老剧或即时节目常见，画质通常低于 WEB-DL。",
    EN: "Broadcast TV source, common for older or quick-turnaround releases and usually lower quality than WEB-DL.",
  },
  {
    key: "dolby_vision",
    label: "Dolby Vision",
    aliases: ["DoVi", "DV", "Dolby Vision", "杜比视界"],
    CN: "杜比视界动态 HDR 格式，可按场景提供亮度和色彩元数据；播放效果取决于片源、播放器和显示设备支持。",
    EN: "Dolby Vision dynamic HDR, providing scene-aware brightness and color metadata. Playback depends on support from the source, player, and display.",
  },
  {
    key: "hdr10_plus",
    label: "HDR10+",
    aliases: ["HDR10+", "HDR 10+"],
    CN: "HDR10+ 动态 HDR 格式，可按场景提供元数据；需要片源、播放器和显示设备同时支持。",
    EN: "HDR10+ dynamic HDR with scene-aware metadata. It requires support from the source, player, and display.",
  },
  {
    key: "hdr10",
    label: "HDR10",
    aliases: ["HDR10", "HDR 10"],
    CN: "最常见的基础 HDR 格式，使用静态元数据，兼容范围通常很广。",
    EN: "The most common baseline HDR format, using static metadata and generally broad compatibility.",
  },
  {
    key: "hdr",
    label: "HDR",
    aliases: ["HDR"],
    CN: "泛 HDR 标记；不区分 HDR10、HDR10+ 或 Dolby Vision。",
    EN: "Generic HDR marker; does not distinguish HDR10, HDR10+, or Dolby Vision.",
  },
  {
    key: "sdr",
    label: "SDR",
    aliases: ["SDR"],
    CN: "普通动态范围。兼容性通常最好，但没有 HDR 的高光和暗部范围。",
    EN: "Standard dynamic range. Usually the most compatible, but without HDR highlight and shadow range.",
  },
  {
    key: "2160p",
    label: "2160p / 4K",
    aliases: ["2160p", "4K"],
    CN: "4K 分辨率。电影和高规格剧集常见，体积明显更大。",
    EN: "4K resolution. Common for movies and premium shows, with much larger files.",
  },
  {
    key: "1080p",
    label: "1080p",
    aliases: ["1080p", "FHD"],
    CN: "全高清。动漫和普通剧集常见，体积与兼容性更平衡。",
    EN: "Full HD. Common for anime and regular TV, with balanced size and compatibility.",
  },
  {
    key: "hevc",
    label: "HEVC / H.265",
    aliases: ["HEVC", "H.265", "H265", "x265"],
    CN: "H.265 视频编码。4K、HDR 和 10bit 动漫常见，压缩效率高。",
    EN: "H.265 video codec. Common for 4K, HDR, and 10-bit anime, with strong compression efficiency.",
  },
  {
    key: "avc",
    label: "AVC / H.264",
    aliases: ["AVC", "H.264", "H264", "x264"],
    CN: "H.264 视频编码。兼容性极好，1080p 资源常见。",
    EN: "H.264 video codec. Very compatible and common for 1080p releases.",
  },
  {
    key: "av1",
    label: "AV1",
    aliases: ["AV1"],
    CN: "新一代视频编码。压缩效率高，但老播放器或硬件兼容性需要确认。",
    EN: "Newer video codec with strong efficiency; older players or hardware may need compatibility checks.",
  },
  {
    key: "atmos",
    label: "Dolby Atmos",
    aliases: ["Atmos", "Dolby Atmos", "杜比全景声"],
    CN: "杜比全景声对象音频。WEB 资源常见于 DDP/E-AC3 Atmos，蓝光资源常见于 TrueHD Atmos。",
    EN: "Dolby Atmos object-based audio. WEB releases often carry it as DDP/E-AC3 Atmos, while Blu-ray releases often carry it as TrueHD Atmos.",
  },
  {
    key: "ddp",
    label: "DDP / E-AC3",
    aliases: ["DDP", "DD+", "EAC3", "E-AC3", "Dolby Digital Plus"],
    CN: "杜比数字 Plus / E-AC3，有损多声道音频。流媒体剧集和 Atmos 资源常见。",
    EN: "Dolby Digital Plus / E-AC3, a lossy multichannel audio format. Common in streaming TV and Atmos releases.",
  },
  {
    key: "truehd",
    label: "TrueHD",
    aliases: ["TrueHD", "Dolby TrueHD"],
    CN: "杜比无损音频格式，蓝光电影和 Remux 常见，通常体积较大。",
    EN: "Dolby lossless audio format, common on Blu-ray movies and Remux releases, and usually large.",
  },
  {
    key: "dts_hd_ma",
    label: "DTS-HD MA",
    aliases: ["DTS-HD MA", "DTS HD MA"],
    CN: "DTS 无损蓝光音轨，电影 Remux 常见，流媒体剧集较少见。",
    EN: "Lossless DTS Blu-ray audio, common on movie Remux releases and uncommon in streaming TV.",
  },
  {
    key: "dts_x",
    label: "DTS:X",
    aliases: ["DTS:X", "DTS X"],
    CN: "DTS 对象音频格式，常见于部分蓝光或 Remux 资源；播放需要对应音频链路支持。",
    EN: "DTS object-based audio, found on some Blu-ray or Remux releases. Playback requires compatible audio support.",
  },
  {
    key: "aac",
    label: "AAC",
    aliases: ["AAC"],
    CN: "常见有损音频。新番动漫和小体积资源常见。",
    EN: "Common lossy audio. Frequent in current anime and smaller releases.",
  },
  {
    key: "flac",
    label: "FLAC",
    aliases: ["FLAC"],
    CN: "无损音频格式。动漫 BDRip 常见，体积通常比 AAC 更大。",
    EN: "Lossless audio format. Common in anime BDRips and usually larger than AAC.",
  },
  {
    key: "ass",
    label: "ASS subtitles",
    aliases: ["ASS", "SSA", "特效字幕"],
    CN: "高级字幕格式，动漫字幕组常用。支持复杂样式和特效，但播放器兼容性要求更高。",
    EN: "Advanced subtitle format common in anime fansubs. Supports complex styling and effects, but requires better player compatibility.",
  },
];

const releasePreferencePresets = {
  movie_remux_first: {
    labelKey: "presetMovieRemuxFirst",
    scores: {
      remux: 20,
      uhd_bluray: 12,
      dolby_vision: 12,
      hdr10_plus: 8,
      truehd: 8,
      dts_hd_ma: 8,
      webdl: -8,
      hdtv: -16,
    },
  },
  tv_webdl_first: {
    labelKey: "presetTvWebdlFirst",
    scores: {
      webdl: 18,
      ddp: 8,
      atmos: 5,
      hevc: 4,
      hdtv: -12,
      remux: -10,
    },
  },
  anime_subtitle_friendly: {
    labelKey: "presetAnimeSubtitleFriendly",
    scores: {
      webdl: 12,
      "1080p": 8,
      hevc: 6,
      flac: 6,
      ass: 10,
      aac: 3,
      remux: -8,
    },
  },
  space_saving: {
    labelKey: "presetSpaceSaving",
    scores: {
      "1080p": 10,
      hevc: 8,
      webdl: 6,
      aac: 4,
      "2160p": -14,
      remux: -18,
      truehd: -8,
      dts_hd_ma: -8,
    },
  },
};

const navigationSections = [
  "overview",
  "logs",
  "wants",
  "tracker",
  "download_client",
  "pt_filters",
  "seed_cleanup",
  "scheduler",
  "metrics",
  "want_decision",
  "release_preferences",
  "config_file",
];

const uiPreferencesStorageKey = "seed-agent.ui-preferences.v1";

const sectionGroupBySection = {
  overview: "operations",
  logs: "operations",
  wants: "operations",
  tracker: "automation",
  download_client: "automation",
  pt_filters: "acquisition",
  seed_cleanup: "acquisition",
  scheduler: "automation",
  metrics: "advanced",
  want_decision: "acquisition",
  release_preferences: "acquisition",
  config_file: "advanced",
};

function activeCopy() {
  return copy[state.language] || copy.CN;
}

function uiText(key) {
  return activeCopy().ui?.[key] || copy.CN.ui?.[key] || key;
}

function currentSettingsPanels() {
  return settingsPanelsByLanguage[state.language] || settingsPanelsByLanguage.CN;
}

function settingsPanelSpec(section) {
  return currentSettingsPanels()[section] || settingsPanelsByLanguage.CN[section];
}

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
      { level: "warning", message: uiText("typeRequired") },
      { level: "warning", message: uiText("siteNameRequired") },
      { level: "info", message: uiText("notSaved") },
    ],
  });
  renderSection();
});

themeButton.addEventListener("click", () => {
  setTheme(!state.dark);
});

languageButton.addEventListener("click", () => {
  languageMenu.hidden = !languageMenu.hidden;
});

webTokenButton?.addEventListener("click", async () => {
  if (await requestWebToken()) {
    await loadInitialData();
  }
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
    closeOpenModal();
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
  saveUiPreferences();
  updateSectionLocation(section);
  navItems.forEach((navItem) => {
    navItem.classList.toggle("active", navItem.dataset.section === section);
  });
  sectionSwitcher.value = section;
  renderSection();
  if (section === "logs" && !state.logs.refreshedAt && !logsRefreshPending) {
    logsRefreshPending = true;
    loadLogs().finally(() => {
      logsRefreshPending = false;
      if (state.currentSection === "logs") {
        renderSection();
      }
    });
  }
}

function readUiPreferences() {
  try {
    const rawPreferences = globalThis.localStorage.getItem(uiPreferencesStorageKey);
    const preferences = rawPreferences ? JSON.parse(rawPreferences) : {};
    return {
      language: preferences.language === "EN" ? "EN" : "CN",
      dark: preferences.dark === true,
      currentSection: navigationSections.includes(preferences.currentSection)
        ? preferences.currentSection
        : "overview",
    };
  } catch {
    return { language: "CN", dark: false, currentSection: "overview" };
  }
}

function saveUiPreferences() {
  try {
    globalThis.localStorage.setItem(
      uiPreferencesStorageKey,
      JSON.stringify({
        language: state.language,
        dark: state.dark,
        currentSection: state.currentSection,
      }),
    );
  } catch {
    // Browser privacy mode or a restricted embedded browser can deny storage.
  }
}

function sectionFromLocation() {
  const section = globalThis.location.hash.replace(/^#/, "");
  return navigationSections.includes(section) ? section : null;
}

function updateSectionLocation(section) {
  if (globalThis.location.hash !== `#${section}`) {
    globalThis.location.hash = section;
  }
}

function applyTheme() {
  document.body.classList.toggle("dark", state.dark);
  themeButton.textContent = state.dark ? "☾" : "☀";
}

function setTheme(dark) {
  state.dark = dark;
  applyTheme();
  saveUiPreferences();
}

function restoreUiPreferences() {
  const preferences = readUiPreferences();
  state.language = preferences.language;
  state.dark = preferences.dark;
  state.currentSection = sectionFromLocation() || preferences.currentSection;
  document.documentElement.lang = state.language === "CN" ? "zh-CN" : "en";
  applyTheme();
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
  const response = await apiFetch("/api/config");
  if (!response.ok) {
    renderSection();
    return;
  }
  const payload = await response.json();
  state.configSections = payload.sections || {};
  state.sectionYamls = payload.section_yamls || {};
  state.configYaml = payload.config_yaml || "";
  state.configPath = payload.config_path || "";
  state.configRevision = payload.revision || "";
  state.runtimeRoot = payload.runtime_root || "";
  state.schedulerEnvironmentOverrides = payload.scheduler_environment_overrides || {};
  state.trackers = payload.trackers.map((tracker) => ({
    id: newClientId(),
    type: tracker.type,
    name: tracker.name,
    enabled: tracker.enabled,
    rss_url: tracker.rss_url,
    discovery_mode: tracker.discovery_mode,
    api_key_ref: tracker.api_key_ref || "",
    api_key_value: "",
    auth_header: tracker.auth_header || "x-api-key",
    cookie_ref: tracker.cookie_ref || "",
    saved: true,
    collapsed: true,
    status: tracker.has_api_key
      ? [{ level: "ok", message: uiText("apiKeyExists") }]
      : [{ level: "info", message: uiText("notChecked") }],
  }));
  renderSection();
}

async function loadOverview() {
  try {
    const [healthResponse, stateResponse, poolsResponse, opsResponse] = await Promise.all([
      apiFetch("/api/health"),
      apiFetch("/api/state/summary"),
      apiFetch("/api/pools"),
      apiFetch("/api/ops"),
    ]);
    if (!healthResponse.ok || !stateResponse.ok || !poolsResponse.ok || !opsResponse.ok) {
      throw new Error(uiText("readingStatus"));
    }
    state.overview = {
      health: await healthResponse.json(),
      stateSummary: await stateResponse.json(),
      pools: await poolsResponse.json(),
      ops: await opsResponse.json(),
      error: null,
    };
  } catch (error) {
    state.overview = {
      health: null,
      stateSummary: null,
      pools: null,
      ops: null,
      error: error.message,
    };
  }
}

async function loadWants() {
  try {
    const response = await apiFetch("/api/wants");
    if (!response.ok) {
      throw new Error(uiText("wantsReadFailed"));
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

async function loadLogs() {
  state.logs.loading = true;
  try {
    const response = await apiFetch("/api/logs");
    if (!response.ok) {
      throw new Error(`${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    const payload = await response.json();
    state.logs.entries = payload.entries || [];
    state.logs.error = null;
    state.logs.refreshedAt = new Date().toISOString();
  } catch (error) {
    state.logs.error = error.message;
  } finally {
    state.logs.loading = false;
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
  configPathLabel.textContent = state.configPath
    ? `${uiText("configPathLoadedPrefix")}${state.configPath}`
    : uiText("configPathMissing");
  if (state.currentSection === "overview") {
    title.textContent = copy[state.language].overviewTitle;
    subtitle.textContent = copy[state.language].overviewSubtitle;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderOverviewPanel());
    return;
  }
  if (state.currentSection === "logs") {
    title.textContent = copy[state.language].logsTitle;
    subtitle.textContent = copy[state.language].logsSubtitle;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderLogsPanel());
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
  if (state.currentSection === "config_file") {
    const placeholder = copy[state.language].placeholders.config_file;
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
  panel.className = "overview-dashboard";
  const { health, stateSummary, pools, ops, error } = state.overview;
  if (error) {
    panel.append(renderMetricCard(uiText("readingStatus"), uiText("failed"), error, "warning"));
    return panel;
  }
  if (!health || !stateSummary || !pools || !ops) {
    panel.append(renderMetricCard(uiText("readingStatus"), uiText("loading"), uiText("localApiLoading"), "info"));
    return panel;
  }

  const candidateStates = stateSummary.candidates?.by_state || {};
  const intentStates = stateSummary.intents?.by_state || {};
  const budgetPools = pools.budget_pools || [];

  const hero = document.createElement("div");
  hero.className = "overview-hero";
  const heartbeatCard = renderMetricCard(
    uiText("heartbeat"),
    formatHealthStatus(health.status),
    health.heartbeat_exists
      ? `${health.age_minutes ?? "?"} ${uiText("minutesAgoCycle")} ${health.heartbeat?.cycle ?? "?"}`
      : uiText("heartbeatMissing"),
    health.status === "ok" ? "ok" : "warning",
  );
  heartbeatCard.classList.add("primary");
  hero.append(heartbeatCard);

  const summaryStrip = document.createElement("div");
  summaryStrip.className = "overview-summary-strip";
  summaryStrip.append(
    renderMetricCard(uiText("candidateTorrentsCount"), stateSummary.candidates?.total ?? 0, formatStateCounts(candidateStates), "info"),
  );
  summaryStrip.append(renderMetricCard(uiText("resourceIntents"), stateSummary.intents?.total ?? 0, formatStateCounts(intentStates), "info"));
  summaryStrip.append(renderMetricCard(uiText("budgetPools"), budgetPools.length, uiText("configuredPools"), "info"));
  hero.append(summaryStrip);
  panel.append(hero);

  const detailGrid = document.createElement("div");
  detailGrid.className = "overview-detail-grid";
  detailGrid.innerHTML = `
    <article class="overview-detail-panel">
      <div class="section-title">${escapeHtml(uiText("budgetPools"))}</div>
      ${renderBudgetPoolList(budgetPools)}
    </article>
    <article class="overview-detail-panel">
      <div class="section-title">${escapeHtml(uiText("dashboardAttention"))}</div>
      ${renderAttentionList(health, candidateStates, intentStates, budgetPools)}
    </article>
    <article class="overview-detail-panel wide">
      <div class="section-title">${escapeHtml(uiText("opsDashboard"))}</div>
      ${renderSchedulerOperations(ops)}
    </article>
    <article class="overview-detail-panel wide">
      <div class="section-title">${escapeHtml(uiText("runtimeProvenance"))}</div>
      ${renderRuntimeProvenance(health, stateSummary)}
    </article>
    <article class="overview-detail-panel wide">
      <div class="section-title">${escapeHtml(uiText("status"))}</div>
      <div class="overview-state-groups">
        <div>
          <div class="metric-label">${escapeHtml(uiText("candidateTorrentsCount"))}</div>
          ${renderStateChips(candidateStates)}
        </div>
        <div>
          <div class="metric-label">${escapeHtml(uiText("resourceIntents"))}</div>
          ${renderStateChips(intentStates)}
        </div>
      </div>
    </article>
  `;
  panel.append(detailGrid);
  panel.addEventListener("click", (event) => {
    const schedulerButton = event.target?.closest?.("[data-scheduler-action]");
    const schedulerAction = schedulerButton?.dataset?.schedulerAction;
    if (schedulerAction) {
      handleSchedulerAction(panel, schedulerAction, schedulerButton);
    }
  });
  return panel;
}

function renderSchedulerOperations(ops) {
  const backoff = ops.schedule_backoff || {};
  const phase = ops.scheduler_control?.phase || "unavailable";
  const phaseLabel = phase === "running" ? uiText("schedulerRunning") : phase === "waiting" ? uiText("schedulerWaiting") : uiText("schedulerUnavailable");
  return `
    <div class="scheduler-operations">
      <div class="scheduler-controls">
        <div class="tracker-actions-group">
          <button class="primary-button" type="button" data-scheduler-action="trigger" ${phase === "waiting" ? "" : "disabled"}>${escapeHtml(uiText("schedulerTriggerNow"))}</button>
          <button class="secondary-button" type="button" data-scheduler-action="clear-backoff" ${backoff.active ? "" : "disabled"}>${escapeHtml(uiText("schedulerClearBackoff"))}</button>
        </div>
        <div class="status-list scheduler-state-list">
          <div class="status-item info">${escapeHtml(uiText("schedulerPhase"))}: ${escapeHtml(phaseLabel)}</div>
          <div class="status-item info">${escapeHtml(uiText("schedulerNextCycle"))}: <span data-scheduler-next-cycle>${escapeHtml(formatSchedulerNextCycle(ops))}</span></div>
          <div data-scheduler-status></div>
        </div>
      </div>
      ${renderOpsSummary(ops)}
    </div>
  `;
}

function renderOpsSummary(ops) {
  const runs = ops.scheduler_runs || [];
  const events = ops.tracker_api_events || [];
  const wantRuns = ops.want_search_runs || [];
  const backoff = ops.schedule_backoff || {};
  const pendingTrigger = ops.scheduler_trigger || null;
  const rows = [
    [uiText("schedulerBackoffStatus"), backoff.active ? `${uiText("schedulerBackoffActive")} · ${backoff.endpoint || "mteam"}` : uiText("schedulerBackoffInactive")],
    [uiText("schedulerBackoffStarted"), backoff.active && backoff.created_at ? `${formatRelativeTime(backoff.created_at)} · ${formatDateTime(backoff.created_at)}` : uiText("noData")],
    [uiText("schedulerBackoffEnds"), backoff.active && backoff.until ? `${formatRemainingMinutes(backoff.remaining_minutes)} · ${formatDateTime(backoff.until)}` : uiText("noData")],
    [uiText("schedulerTriggerRequest"), pendingTrigger ? formatDateTime(pendingTrigger.requested_at) : uiText("inactive")],
    [uiText("recentSchedulerRuns"), runs.length ? `${runs[0].status || "unknown"} · ${runs[0].run_id || ""}` : uiText("noData")],
    [uiText("trackerApiEvents"), events.length],
    [uiText("wantSearchRuns"), wantRuns.length ? `${wantRuns[0].status || "unknown"} · ${wantRuns[0].source || ""}` : uiText("noData")],
  ];
  return `
    <div class="overview-list">
      ${rows
        .map(
          ([label, value]) => `
            <div class="overview-pool-row">
              <strong>${escapeHtml(label)}</strong>
              <span>${escapeHtml(value)}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function formatSchedulerNextCycle(ops) {
  if (ops.scheduler_trigger) {
    return uiText("schedulerQueuedImmediate");
  }
  if (ops.scheduler_control?.phase === "running") {
    return uiText("schedulerRunning");
  }
  const latestRun = (ops.scheduler_runs || [])[0];
  const startedAt = Date.parse(latestRun?.started_at || "");
  const intervalMinutes = Number(latestRun?.interval_minutes);
  if (!Number.isFinite(startedAt) || !Number.isFinite(intervalMinutes) || intervalMinutes <= 0) {
    return uiText("schedulerUnavailable");
  }
  const nextRunAt = startedAt + intervalMinutes * 60_000;
  const remainingMinutes = Math.ceil((nextRunAt - Date.now()) / 60_000);
  if (remainingMinutes <= 0) {
    return uiText("schedulerDue");
  }
  return `${formatRemainingMinutes(remainingMinutes)} · ${formatDateTime(new Date(nextRunAt).toISOString())}`;
}

function formatRemainingMinutes(value) {
  const minutes = Math.max(Math.ceil(Number(value) || 0), 0);
  if (minutes < 60) {
    return state.language === "CN" ? `${minutes} 分钟后` : `in ${minutes} min`;
  }
  const hours = Math.ceil(minutes / 60);
  if (hours < 48) {
    return state.language === "CN" ? `${hours} 小时后` : `in ${hours} hr`;
  }
  const days = Math.ceil(hours / 24);
  return state.language === "CN" ? `${days} 天后` : `in ${days} days`;
}

function formatRelativeTime(value) {
  const elapsedMinutes = Math.max(Math.floor((Date.now() - Date.parse(value)) / 60_000), 0);
  if (!Number.isFinite(elapsedMinutes) || elapsedMinutes < 1) {
    return state.language === "CN" ? "刚刚" : "just now";
  }
  if (elapsedMinutes < 60) {
    return state.language === "CN" ? `${elapsedMinutes} 分钟前` : `${elapsedMinutes} min ago`;
  }
  const hours = Math.floor(elapsedMinutes / 60);
  if (hours < 48) {
    return state.language === "CN" ? `${hours} 小时前` : `${hours} hr ago`;
  }
  const days = Math.floor(hours / 24);
  return state.language === "CN" ? `${days} 天前` : `${days} days ago`;
}

function renderRuntimeProvenance(health, stateSummary) {
  const rows = [
    [uiText("currentConfigFile"), stateSummary.config_path || state.configPath],
    [uiText("runtimeRoot"), stateSummary.runtime_root || health.runtime_root || state.runtimeRoot],
    [uiText("stateDatabase"), stateSummary.state_path],
    [uiText("heartbeatFile"), health.heartbeat_file],
  ].filter(([, value]) => value);
  if (rows.length === 0) {
    return `<div class="status-item info">${escapeHtml(uiText("noData"))}</div>`;
  }
  return `
    <div class="runtime-provenance">
      ${rows
        .map(
          ([label, value]) => `
            <div class="runtime-row">
              <span class="metric-label">${escapeHtml(label)}</span>
              <code class="runtime-path">${escapeHtml(value)}</code>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderBudgetPoolList(budgetPools) {
  if (budgetPools.length === 0) {
    return `<div class="status-item info">${escapeHtml(uiText("noPools"))}</div>`;
  }
  return `
    <div class="overview-list">
      ${budgetPools
        .map(
          (pool) => `
            <div class="overview-pool-row">
              <strong>${escapeHtml(pool.name || uiText("unknown"))}</strong>
              <span>${escapeHtml(pool.max_size_tib ?? "?")} TiB</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderAttentionList(health, candidateStates, intentStates, budgetPools) {
  const items = [];
  if (health.status !== "ok") {
    items.push(uiText("attentionHeartbeat"));
  }
  if ((candidateStates.failed || 0) > 0) {
    items.push(uiText("attentionCandidateFailures"));
  }
  if ((intentStates.failed || 0) > 0) {
    items.push(uiText("attentionIntentFailures"));
  }
  if (budgetPools.length === 0) {
    items.push(uiText("attentionNoPools"));
  }
  if (items.length === 0) {
    return `<div class="status-item ok">${escapeHtml(uiText("noDashboardAttention"))}</div>`;
  }
  return `
    <div class="attention-list">
      ${items.map((item) => `<div class="status-item warning">${escapeHtml(item)}</div>`).join("")}
    </div>
  `;
}

function renderStateChips(counts) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return `<div class="status-item info">${escapeHtml(uiText("noStateRecords"))}</div>`;
  }
  const labels = stateCountLabels();
  return `
    <div class="overview-chip-list">
      ${entries
        .map(
          ([name, count]) => `
            <span class="overview-chip">
              <span>${escapeHtml(labels[name] || name)}</span>
              <strong>${escapeHtml(count)}</strong>
            </span>
          `,
        )
        .join("")}
    </div>
  `;
}

function stateCountLabels() {
  return {
    accepted: uiText("statusAccepted"),
    scored: uiText("statusScored"),
    enqueued: uiText("statusEnqueued"),
    confirmation_required: uiText("statusConfirmationRequired"),
    rejected: uiText("statusRejected"),
    failed: uiText("statusFailed"),
    deleted: uiText("statusDeleted"),
    downloading: uiText("statusDownloading"),
    seeding: uiText("statusSeeding"),
  };
}

function renderMetricCard(label, value, detail, level) {
  const card = document.createElement("article");
  card.className = `metric-card ${level}`;
  card.innerHTML = `
    <div class="metric-label">${escapeHtml(label)}</div>
    <div class="metric-value">${escapeHtml(value)}</div>
    <div class="status-item ${escapeAttribute(level)}">${escapeHtml(detail || uiText("noData"))}</div>
  `;
  return card;
}

function formatHealthStatus(status) {
  const labels = {
    ok: uiText("heartbeatOk"),
    stale: uiText("heartbeatStale"),
    missing_heartbeat: uiText("heartbeatMissingStatus"),
  };
  return labels[status] || status || uiText("unknown");
}

function renderLogsPanel() {
  const panel = document.createElement("section");
  panel.className = "logs-panel";
  panel.innerHTML = `
    <div class="logs-toolbar" aria-label="${escapeAttribute(uiText("logsFilter"))}">
      <label class="field compact-field">
        <span>${escapeHtml(uiText("provider"))}</span>
        <select data-log-filter="source">
          <option value="all">${escapeHtml(uiText("logsAllSources"))}</option>
          ${["scheduler", "tracker", "want", "audit", "runtime"].map((source) => `<option value="${source}" ${state.logs.filters.source === source ? "selected" : ""}>${escapeHtml(logSourceLabel(source))}</option>`).join("")}
        </select>
      </label>
      <label class="field compact-field">
        <span>${escapeHtml(uiText("status"))}</span>
        <select data-log-filter="level">
          <option value="all">${escapeHtml(uiText("logsAllLevels"))}</option>
          ${["debug", "info", "warning", "error", "critical"].map((level) => `<option value="${level}" ${state.logs.filters.level === level ? "selected" : ""}>${escapeHtml(level)}</option>`).join("")}
        </select>
      </label>
      <label class="field logs-search-field">
        <span>${escapeHtml(uiText("search"))}</span>
        <input type="search" data-log-filter="query" value="${escapeAttribute(state.logs.filters.query)}" placeholder="${escapeAttribute(uiText("logsSearchPlaceholder"))}" />
      </label>
      <div class="logs-toolbar-actions">
        <label class="logs-auto-refresh">
          <input type="checkbox" data-log-auto-refresh ${state.logs.autoRefresh ? "checked" : ""} />
          <span>${escapeHtml(uiText("logsAutoRefresh"))}</span>
        </label>
        <button class="secondary-button" type="button" data-log-refresh>${escapeHtml(uiText("logsRefresh"))}</button>
      </div>
    </div>
    <div class="logs-meta" data-logs-meta></div>
    <div class="log-timeline" data-log-timeline></div>
  `;
  panel.addEventListener("change", (event) => {
    const filter = event.target?.dataset?.logFilter;
    if (filter) {
      state.logs.filters[filter] = event.target.value;
      updateLogEntries(panel);
    }
    if (event.target?.matches?.("[data-log-auto-refresh]")) {
      state.logs.autoRefresh = event.target.checked;
    }
  });
  panel.addEventListener("input", (event) => {
    if (event.target?.dataset?.logFilter === "query") {
      state.logs.filters.query = event.target.value;
      updateLogEntries(panel);
    }
  });
  panel.addEventListener("click", async (event) => {
    const refreshButton = event.target?.closest?.("[data-log-refresh]");
    if (!refreshButton) {
      return;
    }
    if (logsRefreshPending) {
      return;
    }
    refreshButton.disabled = true;
    logsRefreshPending = true;
    await loadLogs();
    logsRefreshPending = false;
    if (state.currentSection === "logs") {
      renderSection();
    }
  });
  updateLogEntries(panel);
  return panel;
}

function updateLogEntries(panel) {
  const timeline = panel.querySelector("[data-log-timeline]");
  const meta = panel.querySelector("[data-logs-meta]");
  if (state.logs.loading) {
    timeline.innerHTML = `<div class="status-item info">${escapeHtml(uiText("loading"))}</div>`;
    return;
  }
  if (state.logs.error) {
    timeline.innerHTML = `<div class="status-item warning">${escapeHtml(state.logs.error)}</div>`;
    return;
  }
  const query = state.logs.filters.query.trim().toLocaleLowerCase();
  const entries = state.logs.entries.filter((entry) => {
    if (state.logs.filters.source !== "all" && entry.source !== state.logs.filters.source) {
      return false;
    }
    if (state.logs.filters.level !== "all" && entry.level !== state.logs.filters.level) {
      return false;
    }
    if (!query) {
      return true;
    }
    return [entry.title, entry.message, entry.run_id, entry.intent_id, entry.target_id, entry.request_id, JSON.stringify(entry.details || {})]
      .filter(Boolean)
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
  meta.textContent = `${entries.length} / ${state.logs.entries.length} · ${uiText("logsRefreshed")}: ${formatLogDateTime(state.logs.refreshedAt)}`;
  if (!entries.length) {
    timeline.innerHTML = `<div class="empty-state">${escapeHtml(uiText("logsEmpty"))}</div>`;
    return;
  }
  timeline.innerHTML = entries.map(renderLogEntry).join("");
}

function renderLogEntry(entry) {
  const identifiers = [entry.run_id, entry.intent_id, entry.target_id, entry.request_id].filter(Boolean);
  const status = entry.status_code ? `HTTP ${entry.status_code}` : "";
  return `
    <article class="log-entry ${escapeAttribute(entry.level || "info")}">
      <div class="log-entry-marker" aria-hidden="true"></div>
      <div class="log-entry-body">
        <div class="log-entry-head">
          <div class="log-entry-title">
            <span class="badge">${escapeHtml(logSourceLabel(entry.source))}</span>
            <strong>${escapeHtml(entry.title || uiText("noData"))}</strong>
          </div>
          <time datetime="${escapeAttribute(entry.timestamp || "")}">${escapeHtml(formatLogDateTime(entry.timestamp))}</time>
        </div>
        ${entry.message ? `<div class="log-entry-message">${escapeHtml(entry.message)}</div>` : ""}
        ${entry.details && Object.keys(entry.details).length ? `<details class="candidate-media-info"><summary>${escapeHtml(uiText("logDetails"))}</summary><pre>${escapeHtml(JSON.stringify(entry.details, null, 2))}</pre></details>` : ""}
        ${identifiers.length || status ? `<div class="log-entry-context">${escapeHtml([status, ...identifiers].filter(Boolean).join(" · "))}</div>` : ""}
      </div>
    </article>
  `;
}

function logSourceLabel(source) {
  const labels = {
    scheduler: uiText("logsSourceScheduler"),
    tracker: uiText("logsSourceTracker"),
    want: uiText("logsSourceWant"),
    audit: uiText("logsSourceAudit"),
    runtime: state.language === "CN" ? "运行事件" : "Runtime",
  };
  return labels[source] || source || uiText("unknown");
}

function formatLogDateTime(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) {
    return value || "";
  }
  return date.toLocaleString(state.language === "CN" ? "zh-CN" : "en-GB", {
    dateStyle: "short",
    timeStyle: "medium",
    hour12: false,
  });
}

function formatStateCounts(counts) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return uiText("noStateRecords");
  }
  const labels = {
    accepted: uiText("statusAccepted"),
    scored: uiText("statusScored"),
    enqueued: uiText("statusEnqueued"),
    confirmation_required: uiText("statusConfirmationRequired"),
    rejected: uiText("statusRejected"),
    failed: uiText("statusFailed"),
    deleted: uiText("statusDeleted"),
    downloading: uiText("statusDownloading"),
    seeding: uiText("statusSeeding"),
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
          <span>${escapeHtml(uiText("provider"))}</span>
          <select data-want-filter="source">
            ${renderWantSourceOptions()}
          </select>
        </label>
        <label class="field compact-field">
          <span>${escapeHtml(uiText("mediaType"))}</span>
          <select data-want-filter="media_type">
            <option value="all">${escapeHtml(uiText("all"))}</option>
            <option value="movie">${escapeHtml(uiText("movie"))}</option>
            <option value="tv">${escapeHtml(uiText("tv"))}</option>
            <option value="anime">${escapeHtml(uiText("anime"))}</option>
          </select>
        </label>
        <label class="field compact-field">
          <span>${escapeHtml(uiText("status"))}</span>
          <select data-want-filter="status">
            <option value="all">${escapeHtml(uiText("all"))}</option>
            <option value="not_found">${escapeHtml(uiText("notFound"))}</option>
            <option value="not_downloaded">${escapeHtml(uiText("notDownloaded"))}</option>
            <option value="downloaded">${escapeHtml(uiText("downloaded"))}</option>
            <option value="viewed">${escapeHtml(uiText("viewed"))}</option>
          </select>
        </label>
      </div>
      <div class="tracker-actions-group">
        <button class="secondary-button" type="button" data-want-action="sync" aria-label="${escapeAttribute(uiText("refreshWants"))}">${escapeHtml(uiText("refreshWants"))}</button>
        <button class="secondary-button" type="button" data-want-action="search" aria-label="${escapeAttribute(uiText("searchTorrentsCurrentFilter"))}">${escapeHtml(uiText("searchTorrentsCurrentFilter"))}</button>
        <button class="primary-button" type="button" data-want-action="config-open" aria-label="${escapeAttribute(uiText("sourceConfigTitle"))}">${escapeHtml(uiText("sourceConfig"))}</button>
      </div>
    </div>
    <div class="status-list" data-want-status></div>
    ${renderWantConfigModal()}
    ${renderWantCandidateModal()}
    <div class="section-title">${escapeHtml(uiText("wantResources"))}</div>
  `;
  panel.querySelector('[data-want-filter="source"]').value = state.wants.filters.source;
  panel.querySelector('[data-want-filter="media_type"]').value = state.wants.filters.media_type;
  panel.querySelector('[data-want-filter="status"]').value = state.wants.filters.status;
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
    if (event.target?.matches?.("[data-want-config-modal]")) {
      panel.querySelector("[data-want-config-modal]")?.classList.add("hidden");
      return;
    }
    if (event.target?.matches?.("[data-want-candidate-modal]")) {
      closeWantCandidateModal(panel);
      return;
    }
    const candidateButton = event.target?.closest?.("[data-want-candidate-action]");
    const candidateAction = candidateButton?.dataset?.wantCandidateAction;
    if (candidateAction) {
      handleWantCandidateAction(panel, candidateAction, candidateButton);
      return;
    }
    const actionButton = event.target?.closest?.("[data-want-action]");
    const action = actionButton?.dataset?.wantAction;
    if (action) {
      handleWantAction(panel, action, actionButton);
      return;
    }
    const wantTarget = event.target?.closest?.("[data-want-id]");
    if (wantTarget?.dataset?.wantId) {
      openWantCandidates(panel, wantTarget.dataset.wantId);
    }
  });
  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    const wantTarget = event.target?.closest?.("[data-want-id]");
    if (!wantTarget?.dataset?.wantId) {
      return;
    }
    event.preventDefault();
    openWantCandidates(panel, wantTarget.dataset.wantId);
  });
  return panel;
}

function renderWantSourceOptions() {
  const options = [`<option value="all">${escapeHtml(uiText("all"))}</option>`];
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
  const sources = state.configSections.want_sources || {};
  const wantLists = configuredWantLists(sources);
  return `
    <div class="modal-backdrop hidden" data-want-config-modal>
      <div class="modal-panel">
        <div class="modal-header">
          <div class="section-title">${escapeHtml(uiText("sourceConfigTitle"))}</div>
          <button class="icon-button" type="button" data-want-action="config-close" aria-label="${escapeAttribute(uiText("close"))}">×</button>
        </div>
        <div class="want-source-list" data-want-source-list>
          ${wantLists.map((source, index) => renderWantSourceConfigRow(source, index)).join("")}
        </div>
        <div class="tracker-actions-group">
          <button class="secondary-button" type="button" data-want-action="config-add">${escapeHtml(uiText("addSource"))}</button>
          <button class="secondary-button" type="button" data-want-action="config-preview">${escapeHtml(uiText("preview"))}</button>
          <button class="primary-button" type="button" data-want-action="config-save">${escapeHtml(uiText("save"))}</button>
        </div>
        <div class="status-list" data-want-config-status></div>
      </div>
    </div>
  `;
}

function renderWantCandidateModal() {
  return `
    <div class="modal-backdrop hidden" data-want-candidate-modal>
      <div class="modal-panel candidate-modal">
        <div class="modal-header">
            <div>
            <div class="section-title" data-want-candidate-title>${escapeHtml(uiText("candidateTorrents"))}</div>
            <div class="muted-line">${escapeHtml(uiText("wantCandidateSubtitle"))}</div>
          </div>
          <button class="icon-button" type="button" data-want-candidate-action="close" aria-label="${escapeAttribute(uiText("closeCandidates"))}">×</button>
        </div>
        <div class="status-list" data-want-candidate-status></div>
        <div class="candidate-list" data-want-candidate-list></div>
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
        <span>${escapeHtml(uiText("provider"))}</span>
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
        <span>${escapeHtml(uiText("name"))}</span>
        <input data-want-source-field="label" value="${escapeHtml(source.label || "")}" />
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("enabled"))}</span>
        <select data-want-source-field="enabled">
          <option value="true" ${source.enabled !== false ? "selected" : ""}>${escapeHtml(uiText("yes"))}</option>
          <option value="false" ${source.enabled === false ? "selected" : ""}>${escapeHtml(uiText("no"))}</option>
        </select>
      </label>
      <div class="provider-fields ${provider === "douban" ? "" : "hidden"}" data-provider-fields="douban">
        <label class="field">
          <span>${escapeHtml(uiText("doubanUser"))}</span>
          <input data-want-source-field="user_name" value="${escapeHtml(source.user_name || "")}" />
        </label>
        <label class="field">
          <span>${escapeHtml(uiText("exportFile"))}</span>
          <input data-want-source-field="export_ref" value="${escapeHtml(provider === "douban" ? source.export_ref || "" : "")}" />
        </label>
        <label class="field">
          <span>${escapeHtml(uiText("pages"))}</span>
          <input data-want-source-field="max_pages" type="number" min="1" value="${escapeHtml(provider === "douban" ? source.max_pages || 1 : 1)}" />
        </label>
      </div>
      <div class="provider-fields ${provider === "imdb" ? "" : "hidden"}" data-provider-fields="imdb">
        <label class="field wide">
          <span>${escapeHtml(uiText("imdbWatchlistUrl"))}</span>
          <input data-want-source-field="watchlist_url" value="${escapeHtml(source.watchlist_url || "")}" />
        </label>
        <label class="field">
          <span>${escapeHtml(uiText("exportFile"))}</span>
          <input data-want-source-field="export_ref" value="${escapeHtml(provider === "imdb" ? source.export_ref || "" : "")}" />
        </label>
        <label class="field">
          <span>${escapeHtml(uiText("pages"))}</span>
          <input data-want-source-field="max_pages" type="number" min="1" value="${escapeHtml(provider === "imdb" ? source.max_pages || 1 : 1)}" />
        </label>
      </div>
      <button class="secondary-button" type="button" data-want-action="config-remove" data-row-index="${index}">${escapeHtml(uiText("remove"))}</button>
    </div>
  `;
}

function renderWantTable() {
  const wrapper = document.createElement("div");
  wrapper.className = "want-table-wrap";
  const items = filteredWantItems();
  if (state.wants.loading) {
    wrapper.innerHTML = `<div class="empty-state">${escapeHtml(uiText("loading"))}</div>`;
    return wrapper;
  }
  if (state.wants.error) {
    wrapper.innerHTML = `<div class="status-item warning">${escapeHtml(state.wants.error)}</div>`;
    return wrapper;
  }
  if (items.length === 0) {
    wrapper.innerHTML = `
      <div class="empty-state action-empty-state">
        <h3>${escapeHtml(uiText("noWants"))}</h3>
        <p>${escapeHtml(uiText("noWantsHelp"))}</p>
        <div class="empty-state-actions">
          <button class="secondary-button" type="button" data-want-action="sync">${escapeHtml(uiText("refreshWants"))}</button>
          <button class="primary-button" type="button" data-want-action="config-open">${escapeHtml(uiText("sourceConfig"))}</button>
        </div>
      </div>
    `;
    return wrapper;
  }
  wrapper.innerHTML = `
    <div class="want-table-desktop">
      <table class="want-table">
        <thead>
          <tr>
            <th>${escapeHtml(uiText("title"))}</th>
            <th>${escapeHtml(uiText("mediaType"))}</th>
            <th>${escapeHtml(uiText("provider"))}</th>
            <th>${escapeHtml(uiText("addedAt"))}</th>
            <th>${escapeHtml(uiText("status"))}</th>
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
    const statusOk =
      state.wants.filters.status === "all" ||
      item.status === state.wants.filters.status;
    return sourceOk && typeOk && statusOk;
  });
}

function wantStatusBadgeClass(status) {
  return ["downloaded", "viewed"].includes(status) ? "ok" : "";
}

function wantStatusLabel(status, fallback) {
  const labels = {
    not_found: uiText("notFound"),
    not_downloaded: uiText("notDownloaded"),
    downloaded: uiText("downloaded"),
    viewed: uiText("viewed"),
  };
  return labels[status] || fallback || status;
}

function wantCanSearch(item) {
  return !["downloaded", "viewed"].includes(item.status);
}

function wantCanEnqueue(intent) {
  return !["downloaded", "viewed"].includes(intent?.status);
}

function renderWantRow(item) {
  const bestScore = formatBestCandidateScore(item);
  return `
    <tr class="want-row" data-want-id="${escapeAttribute(item.intent_id)}" role="button" tabindex="0" aria-label="${escapeAttribute(uiText("viewCandidates"))} ${escapeAttribute(item.title || item.raw_text)}">
      <td>
        <strong>${escapeHtml(item.title || item.raw_text)}</strong>
        <div class="muted-line">${escapeHtml(item.raw_text || "")}</div>
      </td>
      <td>${escapeHtml(formatMediaType(item.media_type))}</td>
      <td>${escapeHtml(item.source_label || item.source)}</td>
      <td>${escapeHtml(formatDate(item.added_at))}</td>
      <td class="want-status-cell">
        <div class="want-status-line">
          <span class="badge ${wantStatusBadgeClass(item.status)}">${escapeHtml(wantStatusLabel(item.status, item.status_label || item.state))}</span>
          ${bestScore ? `<span class="want-score-pill">${escapeHtml(bestScore)}</span>` : ""}
        </div>
        <div class="want-row-actions">
          ${wantCanSearch(item) ? `<button class="secondary-button compact-button" type="button" data-want-action="search-one" data-want-id="${escapeAttribute(item.intent_id)}">${escapeHtml(uiText("searchOneWant"))}</button>` : ""}
          ${item.status !== "viewed" ? `<button class="secondary-button compact-button" type="button" data-want-action="mark-viewed" data-want-id="${escapeAttribute(item.intent_id)}">${escapeHtml(uiText("markViewed"))}</button>` : ""}
          <span class="inline-action">${escapeHtml(uiText("viewCandidates"))}</span>
        </div>
      </td>
    </tr>
  `;
}

function renderWantCard(item) {
  const bestScore = formatBestCandidateScore(item);
  return `
    <article class="want-card" data-want-id="${escapeAttribute(item.intent_id)}" role="button" tabindex="0" aria-label="${escapeAttribute(uiText("viewCandidates"))} ${escapeAttribute(item.title || item.raw_text)}">
      <div class="want-card-header">
        <strong>${escapeHtml(item.title || item.raw_text)}</strong>
        <div class="want-card-status">
          <span class="badge ${wantStatusBadgeClass(item.status)}">${escapeHtml(wantStatusLabel(item.status, item.status_label || item.state))}</span>
          ${bestScore ? `<span class="want-score-pill">${escapeHtml(bestScore)}</span>` : ""}
        </div>
      </div>
      <div class="muted-line">${escapeHtml(item.raw_text || "")}</div>
      <div class="want-card-meta">
        <span>${escapeHtml(formatMediaType(item.media_type))}</span>
        <span>${escapeHtml(item.source_label || item.source)}</span>
        <span>${escapeHtml(formatDate(item.added_at))}</span>
      </div>
      <div class="want-card-footer">
        ${wantCanSearch(item) ? `<button class="secondary-button compact-button" type="button" data-want-action="search-one" data-want-id="${escapeAttribute(item.intent_id)}">${escapeHtml(uiText("searchOneWant"))}</button>` : ""}
        ${item.status !== "viewed" ? `<button class="secondary-button compact-button" type="button" data-want-action="mark-viewed" data-want-id="${escapeAttribute(item.intent_id)}">${escapeHtml(uiText("markViewed"))}</button>` : ""}
        <span class="inline-action">${escapeHtml(uiText("viewCandidates"))}</span>
      </div>
    </article>
  `;
}

function formatBestCandidateScore(item) {
  if (item.best_candidate_score === null || item.best_candidate_score === undefined) {
    return "";
  }
  return `${uiText("bestCandidateScore")} ${item.best_candidate_score}`;
}

async function openWantCandidates(panel, intentId, statusItem = null) {
  const modal = panel.querySelector("[data-want-candidate-modal]");
  const title = modal.querySelector("[data-want-candidate-title]");
  const list = modal.querySelector("[data-want-candidate-list]");
  const status = modal.querySelector("[data-want-candidate-status]");
  modal.dataset.intentId = intentId;
  modal.classList.remove("hidden");
  title.textContent = uiText("candidateTorrents");
  status.innerHTML = renderWantCandidateStatus(statusItem);
  list.innerHTML = `<div class="empty-state">${escapeHtml(uiText("loadingCandidates"))}</div>`;
  try {
    const response = await apiFetch(`/api/wants/${encodeURIComponent(intentId)}/candidates`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    title.textContent = payload.intent?.title || uiText("candidateTorrents");
    list.innerHTML = renderWantCandidateList(
      payload.items || [],
      payload.intent || {},
      payload.search_history || [],
    );
  } catch (error) {
    list.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
  }
}

function renderWantCandidateStatus(statusItem) {
  const message = String(statusItem?.message || "").trim();
  if (!message) {
    return "";
  }
  const level = ["ok", "info", "warning"].includes(statusItem?.level)
    ? statusItem.level
    : "info";
  return `<div class="status-item ${escapeAttribute(level)}">${escapeHtml(message)}</div>`;
}

function renderWantCandidateList(items, intent = {}, searchHistory = []) {
  const history = renderWantSearchHistory(searchHistory);
  if (items.length === 0) {
    return `${history}<div class="empty-state">${escapeHtml(uiText("noCandidates"))}</div>`;
  }
  const matching = items.filter((item) => item.matches_requirements);
  const lower = items.filter((item) => !item.matches_requirements);
  return `
    ${history}
    ${matching.length ? `<div class="candidate-group-title">${escapeHtml(uiText("matchingPreference"))}</div>` : ""}
    ${matching.map((item) => renderWantCandidateCard(item, intent)).join("")}
    ${lower.length ? `<div class="candidate-group-title muted">${escapeHtml(uiText("lowerMatch"))}</div>` : ""}
    ${lower.map((item) => renderWantCandidateCard(item, intent)).join("")}
  `;
}

function renderWantSearchHistory(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return `<div class="muted-line">${escapeHtml(uiText("wantSearchNoHistory"))}</div>`;
  }
  const entries = rows.map((row) => {
    const providers = Array.isArray(row.provider_diagnostics) ? row.provider_diagnostics : [];
    const paths = providers.flatMap((provider) => Array.isArray(provider.attempts)
      ? provider.attempts.map((attempt) => attempt.query_path).filter(Boolean)
      : []);
    const resultCount = Number.isFinite(Number(row.results_count)) ? row.results_count : 0;
    const query = paths.length
      ? ` · ${escapeHtml(uiText("wantSearchQueryPath"))}: ${escapeHtml([...new Set(paths)].join(", "))}`
      : "";
    const message = row.message ? ` · ${escapeHtml(row.message)}` : "";
    const summary = row.search_summary || {};
    const counts = summary.release_count !== undefined
      ? `${escapeHtml(uiText("wantSearchCounts"))}: ${escapeHtml([summary.release_count, summary.ranked_count, summary.accepted_count].join(" / "))} · ${escapeHtml([summary.kind, summary.media_type, summary.series_search_mode].filter(Boolean).join(" / "))}`
      : escapeHtml(String(resultCount));
    return `<li>${escapeHtml(formatDateTime(row.searched_at))} · ${escapeHtml(row.source || "unknown")} · ${escapeHtml(row.status || "unknown")} · ${counts}${query}${message}</li>`;
  }).join("");
  return `
    <details class="candidate-media-info">
      <summary>${escapeHtml(uiText("wantSearchHistory"))} (${rows.length})</summary>
      <ul class="candidate-reasons">${entries}</ul>
    </details>
  `;
}

const candidateTagPriority = [
  "2160p",
  "1080p",
  "webdl",
  "webrip",
  "uhd_bluray",
  "bluray",
  "remux",
  "dolby_vision",
  "hdr10_plus",
  "hdr10",
  "hdr",
  "sdr",
  "hevc",
  "avc",
  "av1",
  "atmos",
  "ddp",
  "truehd",
  "dts_hd_ma",
  "dts_x",
  "aac",
  "flac",
  "ass",
];

function normalizeCandidateTag(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/([a-z])(\d)|(\d)([a-z])/g, "$1$3 $2$4")
    .replace(/[^a-z0-9+\u4e00-\u9fff]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function candidateTagGroupKey(value) {
  const normalizedValue = normalizeCandidateTag(value);
  for (const group of qualityTagGroups) {
    if (normalizeCandidateTag(group.label) === normalizedValue) {
      return group.key;
    }
  }
  const normalized = ` ${normalizedValue} `;
  for (const group of qualityTagGroups) {
    for (const label of group.aliases || []) {
      const alias = normalizeCandidateTag(label);
      if (alias && normalized.includes(` ${alias} `)) {
        return group.key;
      }
    }
  }
  return null;
}

function candidateDisplayTags(item) {
  const grouped = new Map();
  const extra = [];
  const extraSeen = new Set();
  for (const rawTag of [...(item.official_tags || []), ...(item.inferred_tags || [])]) {
    const tag = String(rawTag || "").trim();
    if (!tag || /^[a-z][a-z0-9_]*:\d+$/i.test(tag)) {
      continue;
    }
    const groupKey = candidateTagGroupKey(tag);
    if (groupKey) {
      grouped.set(groupKey, qualityTagGroups.find((group) => group.key === groupKey)?.label || tag);
      continue;
    }
    const key = tag.toLowerCase();
    if (!extraSeen.has(key)) {
      extraSeen.add(key);
      extra.push(tag);
    }
  }
  if (
    grouped.has("dolby_vision")
    || grouped.has("hdr10_plus")
    || grouped.has("hdr10")
  ) {
    grouped.delete("hdr");
  }
  if (grouped.has("uhd_bluray")) {
    grouped.delete("bluray");
  }
  return [
    ...candidateTagPriority
      .filter((key) => grouped.has(key))
      .map((key) => grouped.get(key)),
    ...extra,
  ];
}

const candidateNoteTranslations = {
  "close to top candidate": "与最高分接近",
  "ambiguous top candidates": "最高分候选接近",
  "title tokens matched": "标题匹配",
  "weak title match": "标题匹配较弱",
  "year matched": "年份匹配",
  "year missing": "缺少年份",
  "resolution matched": "分辨率匹配",
  "resolution missing": "分辨率与偏好不符",
  "season matched": "季度匹配",
  "season missing": "缺少季度",
  "episode matched": "集数匹配",
  "episode missing": "缺少集数",
  "healthy seeders": "做种健康",
  "active leechers": "下载活跃",
  "free discount preferred": "免费资源优先",
  "H&R risk": "存在 H&R 风险",
};

function formatCandidateNote(note) {
  const text = String(note || "");
  if (state.language !== "CN") {
    return text;
  }
  if (candidateNoteTranslations[text]) {
    return candidateNoteTranslations[text];
  }
  const qualityScore = text.match(/^quality tag score ([+-]\d+): (.+)$/);
  if (qualityScore) {
    return `${qualityScore[2]} ${qualityScore[1]}`;
  }
  const sitePriority = text.match(/^site priority \+(\d+)$/);
  if (sitePriority) {
    return `站点优先级 +${sitePriority[1]}`;
  }
  return text;
}

function renderWantCandidateCard(item, intent = {}) {
  const tags = candidateDisplayTags(item);
  const actionLabel = item.matches_requirements ? uiText("enqueueQb") : uiText("forceEnqueueQb");
  const subtitle = item.subtitle && item.subtitle.trim() !== String(item.title || "").trim()
    ? `<div class="candidate-subtitle">${escapeHtml(item.subtitle)}</div>`
    : "";
  const mediaInfo = item.media_info
    ? `
      <details class="candidate-media-info">
        <summary>${escapeHtml(uiText("mediaInfo"))}</summary>
        <pre>${escapeHtml(item.media_info)}</pre>
      </details>
    `
    : "";
  const enqueueAction = wantCanEnqueue(intent)
    ? `<button class="${item.matches_requirements ? "primary-button" : "secondary-button"}" type="button" data-want-candidate-action="enqueue" data-release-id="${escapeAttribute(item.release_id)}">${escapeHtml(actionLabel)}</button>`
    : "";
  return `
    <article class="candidate-card ${item.matches_requirements ? "" : "dimmed"} ${item.selected ? "selected" : ""}" data-release-id="${escapeAttribute(item.release_id)}">
      <div class="candidate-card-head">
        <div class="candidate-title-block">
          <strong>${escapeHtml(item.title)}</strong>
          ${subtitle}
          <div class="candidate-meta">
            <span>${escapeHtml(item.site)}</span>
            <span>${escapeHtml(formatCandidateSize(item))}</span>
            <span>${escapeHtml(item.seeders)} ${escapeHtml(uiText("seeders"))}</span>
            <span>${escapeHtml(item.leechers)} ${escapeHtml(uiText("leechers"))}</span>
          </div>
        </div>
        <div class="candidate-score">
          <span>${escapeHtml(item.score)}</span>
          <small>${escapeHtml(uiText("candidateScoreUnit"))} · ${escapeHtml(item.matches_requirements ? uiText("matchingPreference") : uiText("candidateNeedsReview"))}</small>
        </div>
      </div>
      <div class="candidate-tags">
        ${tags.map((tag) => `<span class="badge">${escapeHtml(tag)}</span>`).join("") || `<span class="badge">${escapeHtml(uiText("noTags"))}</span>`}
      </div>
      ${renderCandidateNotes(item)}
      ${mediaInfo}
      <div class="candidate-card-footer">
        <div class="candidate-confidence">${escapeHtml(item.matches_requirements ? uiText("matchingPreference") : uiText("candidateNeedsReview"))}</div>
        <div class="tracker-actions-group candidate-actions">
          ${enqueueAction}
        </div>
      </div>
    </article>
  `;
}

function renderCandidateNotes(item) {
  const risks = item.risks || [];
  const reasons = item.reasons || [];
  if (risks.length === 0 && reasons.length === 0) {
    return "";
  }
  return `
    <div class="candidate-notes">
      ${risks.length ? `<div class="candidate-risks">${risks.map((risk) => `<span class="candidate-risk">${escapeHtml(formatCandidateNote(risk))}</span>`).join("")}</div>` : ""}
      ${reasons.length ? `
        <details class="candidate-score-details">
          <summary>${escapeHtml(uiText("scoreEvidence"))} · ${escapeHtml(reasons.length)}</summary>
          <div class="candidate-reasons">
            ${reasons.map((reason) => `<span>${escapeHtml(formatCandidateNote(reason))}</span>`).join("")}
          </div>
        </details>
      ` : ""}
    </div>
  `;
}

function formatCandidateSize(item) {
  if (typeof item.size_gb === "number") {
    return `${item.size_gb.toFixed(item.size_gb >= 10 ? 1 : 2)} GB`;
  }
  return uiText("unknownSize");
}

async function handleWantCandidateAction(panel, action, button) {
  const modal = panel.querySelector("[data-want-candidate-modal]");
  if (action === "close") {
    closeWantCandidateModal(panel);
    return;
  }
  const intentId = modal.dataset.intentId;
  const releaseId = button?.dataset?.releaseId;
  if (!intentId || !releaseId) {
    return;
  }
  if (action === "enqueue") {
    await enqueueWantCandidate(panel, intentId, releaseId);
  }
}

async function enqueueWantCandidate(panel, intentId, releaseId) {
  const modal = panel.querySelector("[data-want-candidate-modal]");
  const status = modal.querySelector("[data-want-candidate-status]");
  try {
    setModalBusy(modal, true);
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("processing"))}</div>`;
    const payload = await submitWantCandidateEnqueue(intentId, releaseId);
    await loadWants();
    const resultStatus = payload.status?.[0] || {
      level: payload.outcome === "enqueued" ? "ok" : "info",
      message: uiText("operationComplete"),
    };
    await openWantCandidates(panel, intentId, resultStatus);
  } catch (error) {
    status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
  } finally {
    setModalBusy(modal, false);
  }
}

async function submitWantCandidateEnqueue(intentId, releaseId) {
  const endpoint = `/api/wants/${encodeURIComponent(intentId)}/enqueue`;
  const body = { release_id: releaseId };
  const response = await apiFetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(formatWantCandidateError(payload, response.status));
  }
  return payload;
}

function formatWantCandidateError(payload, statusCode) {
  const statusMessage = payload?.status?.find?.((item) => item?.message)?.message;
  const failedDecision = payload?.decisions?.find?.((item) => item?.action?.endsWith?.(".failed"));
  if (statusMessage) {
    return statusMessage;
  }
  if (failedDecision?.reason) {
    return failedDecision.reason;
  }
  return payload?.error || `${uiText("requestFailedPrefix")}: ${statusCode}`;
}

async function handleWantAction(panel, action, event) {
  if (action === "sync") {
    await refreshWants(panel, event);
    return;
  }
  if (action === "search") {
    await searchFilteredWants(panel, event);
    return;
  }
  if (action === "search-one") {
    await searchSingleWant(panel, event);
    return;
  }
  if (action === "mark-viewed") {
    await markWantViewed(panel, event);
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
    const row = event?.closest?.("[data-want-source-row]");
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
      state.configSections.want_sources = payload.data;
      if (payload.section_yamls) {
        state.sectionYamls = payload.section_yamls;
      }
      if (payload.config_yaml) {
        state.configYaml = payload.config_yaml;
      }
      if (payload.revision) {
        state.configRevision = payload.revision;
      }
      await syncConfiguredWants(panel);
      await loadWants();
      renderSection();
    }
  }
}

async function refreshWants(panel, button) {
  const status = panel.querySelector("[data-want-status]");
  setWantActionBusy(panel, button, true);
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("syncingWants"))}</div>`;
  }
  try {
    const payload = await syncConfiguredWants(panel);
    if (!payload) {
      return;
    }
    await loadWants();
    renderSection();
    const refreshedStatus = document.querySelector("[data-want-status]");
    if (refreshedStatus) {
      refreshedStatus.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || uiText("syncWantsCompleted"))}</div>`;
    }
  } finally {
    setWantActionBusy(panel, button, false);
  }
}

async function searchFilteredWants(panel, button) {
  const status = panel.querySelector("[data-want-status]");
  setWantActionBusy(panel, button, true);
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("searchingWants"))}</div>`;
  }
  try {
    const response = await apiFetch("/api/wants/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.wants.filters),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    await loadWants();
    renderSection();
    const refreshedStatus = document.querySelector("[data-want-status]");
    if (refreshedStatus) {
      refreshedStatus.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || uiText("searchCompleted"))}</div>`;
    }
  } catch (error) {
    status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
  } finally {
    setWantActionBusy(panel, button, false);
  }
}

async function searchSingleWant(panel, button) {
  const intentId = button?.dataset?.wantId;
  const status = panel.querySelector("[data-want-status]");
  if (!intentId) {
    return;
  }
  setWantActionBusy(panel, button, true);
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("searchingWants"))}</div>`;
  }
  try {
    const response = await apiFetch(`/api/wants/${encodeURIComponent(intentId)}/search`, {
      method: "POST",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    await loadWants();
    renderSection();
    const refreshedStatus = document.querySelector("[data-want-status]");
    if (refreshedStatus) {
      refreshedStatus.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || uiText("searchCompleted"))}</div>`;
    }
  } catch (error) {
    if (status) {
      status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
    }
  } finally {
    setWantActionBusy(panel, button, false);
  }
}

async function markWantViewed(panel, button) {
  const intentId = button?.dataset?.wantId;
  const status = panel.querySelector("[data-want-status]");
  if (!intentId) {
    return;
  }
  setWantActionBusy(panel, button, true);
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("processing"))}</div>`;
  }
  try {
    const response = await apiFetch(`/api/wants/${encodeURIComponent(intentId)}/viewed`, {
      method: "POST",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    await loadWants();
    renderSection();
    const refreshedStatus = document.querySelector("[data-want-status]");
    if (refreshedStatus) {
      refreshedStatus.innerHTML = `<div class="status-item ok">${escapeHtml(uiText("markViewedCompleted"))}</div>`;
    }
  } catch (error) {
    if (status) {
      status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
    }
  } finally {
    setWantActionBusy(panel, button, false);
  }
}

async function syncConfiguredWants(panel) {
  const status = panel.querySelector("[data-want-config-status]") || panel.querySelector("[data-want-status]");
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("syncingWants"))}</div>`;
  }
  try {
    const response = await apiFetch("/api/wants/sync", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    if (status) {
      status.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || uiText("syncWantsCompleted"))}</div>`;
    }
    return payload;
  } catch (error) {
    if (status) {
      status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
    }
    return null;
  }
}

function setWantActionBusy(panel, button, busy) {
  panel.querySelectorAll('[data-want-action="sync"], [data-want-action="search"], [data-want-action="search-one"], [data-want-action="mark-viewed"]').forEach((item) => {
    item.disabled = busy;
    item.setAttribute("aria-busy", busy ? "true" : "false");
  });
  if (button) {
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
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
        label: `${uiText("provider")}${index + 1}`,
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
    const data = { ...(state.configSections.want_sources || {}) };
    data.want_lists = readWantSourceConfig(panel);
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section: "want_sources", data, revision: state.configRevision || null }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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
    movie: uiText("movie"),
    tv: uiText("tv"),
    anime: uiText("anime"),
    unknown: uiText("unknown"),
  };
  return labels[value] || value || uiText("unknown");
}

function formatDateTime(value, precision = "datetime") {
  if (!value) {
    return "";
  }
  const text = String(value);
  if (precision === "date") {
    return text.split("T")[0].split(" ")[0];
  }
  return text.replace("T", " ").replace("+00:00", " UTC");
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  return String(value).split("T")[0].split(" ")[0];
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
      <strong>${escapeHtml(tracker.name || uiText("newSite"))}</strong>
      ${tracker.saved ? "" : `<span class="badge warn">${escapeHtml(uiText("unsaved"))}</span>`}
      ${tracker.type ? `<span class="badge">${escapeHtml(tracker.type)}</span>` : `<span class="badge">${escapeHtml(uiText("waitingType"))}</span>`}
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
  collapse.setAttribute("aria-label", tracker.collapsed ? uiText("expandTracker") : uiText("collapseTracker"));
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
      placeholder.textContent = uiText("chooseTypeFirst");
      body.append(placeholder);
    }
    body.append(renderTrackerDetailFooter(tracker));
    card.append(body);
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
    <div class="section-title">${escapeHtml(uiText("basics"))}</div>
    <div class="field-grid">
      <label class="field">
        <span>${escapeHtml(uiText("type"))} ${help(uiText("typeHelp"))}</span>
        <select data-field="type">
          <option value="">${escapeHtml(uiText("selectType"))}</option>
          <option value="mteam">M-Team</option>
          <option value="nexusphp">NexusPHP</option>
        </select>
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("siteName"))} ${help(uiText("siteNameHelp"))}</span>
        <input data-field="name" placeholder="mt" value="${escapeAttribute(tracker.name)}" />
      </label>
    </div>
  `;
  bindFields(wrapper, tracker);
  return wrapper;
}

function renderTypeSpecificFields(tracker) {
  const configTitle = tracker.type === "mteam" ? uiText("trackerConfigMteam") : uiText("trackerConfigNexusphp");
  const wrapper = document.createElement("div");
  wrapper.innerHTML = `
    <div class="tracker-detail-grid">
      <div>
        <div class="section-title">${escapeHtml(configTitle)}</div>
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
          <span>${escapeHtml(uiText("discoveryMode"))} ${help(uiText("discoveryModeHelp"))}</span>
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
      <span>RSS URL ${help(uiText("rssUrlHelp"))}</span>
      <input data-field="rss_url" value="${escapeAttribute(tracker.rss_url)}" />
    </label>
    <label class="field">
      <span>${escapeHtml(uiText("cookieFile"))} ${help(uiText("cookieFileHelp"))}</span>
      <input data-field="cookie_ref" value="${escapeAttribute(tracker.cookie_ref)}" />
    </label>
  `;
}

function renderApiDiscoveryFields(tracker) {
  return `
    <label class="field">
      <span>${escapeHtml(uiText("apiKeyFile"))} ${help(uiText("apiKeyFileHelp"))}</span>
      <input data-field="api_key_ref" value="${escapeAttribute(tracker.api_key_ref)}" />
    </label>
    <label class="field">
      <span>${escapeHtml(uiText("apiKeyValue"))} ${help(uiText("apiKeyValueHelp"))}</span>
      <input data-field="api_key_value" value="${escapeAttribute(tracker.api_key_value)}" />
    </label>
    <label class="field">
      <span>Auth header ${help(uiText("authHeaderHelp"))}</span>
      <input data-field="auth_header" value="${escapeAttribute(tracker.auth_header)}" />
    </label>
  `;
}

function renderTrackerDetailFooter(tracker) {
  const footer = document.createElement("div");
  footer.className = "tracker-actions";
  footer.innerHTML = `
    <div class="tracker-actions-group">
      <button class="secondary-button" type="button" data-action="validate" aria-label="${escapeAttribute(uiText("trackerValidate"))}">${escapeHtml(uiText("trackerValidate"))}</button>
      <button class="secondary-button" type="button" data-action="site-probe" aria-label="${escapeAttribute(uiText("trackerProbe"))}">${escapeHtml(uiText("trackerProbe"))}</button>
      <button class="secondary-button" type="button" data-action="dry-run" aria-label="${escapeAttribute(uiText("trackerDryRun"))}">${escapeHtml(uiText("trackerDryRun"))}</button>
      <button class="secondary-button" type="button" data-action="preview" aria-label="${escapeAttribute(uiText("preview"))}">${escapeHtml(uiText("preview"))}</button>
    </div>
    <div class="tracker-actions-group">
      <button class="secondary-button" type="button" data-action="cancel">${escapeHtml(uiText("trackerCancel"))}</button>
      <button class="primary-button" type="button" data-action="save">${escapeHtml(uiText("save"))}</button>
    </div>
  `;
  footer.addEventListener("click", (event) => {
    const action = event.target?.closest?.("[data-action]")?.dataset?.action;
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
    preview: "/api/trackers/preview",
    save: "/api/trackers",
  };
  try {
    const response = await apiFetch(endpoints[action], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toDraftPayload(tracker)),
    });
    const payload = await response.json();
    tracker.status = payload.status || tracker.status;
    tracker.diff = payload.diff || "";
    if (!response.ok && !payload.status) {
      tracker.status = [
        {
          level: "warning",
          message: payload.message || `${uiText("requestFailedPrefix")}: ${response.status}`,
        },
      ];
    }
    if (action === "save" && response.ok) {
      tracker.saved = true;
      tracker.api_key_value = "";
      state.configRevision = payload.revision || state.configRevision;
    }
  } catch (error) {
    tracker.status = [{ level: "warning", message: `${uiText("requestFailedPrefix")}: ${error.message}` }];
  }
  renderSection();
}

function renderStatusPanel(tracker) {
  return `
    <div class="status-panel">
      <h3>${escapeHtml(uiText("status"))}</h3>
      <div class="status-list">
        ${tracker.status
          .map(
            (item) =>
              `<div class="status-item ${escapeAttribute(item.level)}">${escapeHtml(formatStatusMessage(item.message))}</div>`,
          )
          .join("")}
      </div>
      ${tracker.diff ? `<pre class="diff-preview">${escapeHtml(tracker.diff)}</pre>` : ""}
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
          { level: field.value ? "info" : "warning", message: field.value ? uiText("typeSelected") : uiText("typeRequired") },
          { level: tracker.name ? "info" : "warning", message: tracker.name ? uiText("siteNameFilled") : uiText("siteNameRequired") },
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
    revision: state.configRevision || null,
  };
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
  return `<button class="help" type="button" data-help="${escapeAttribute(text)}" aria-label="${escapeAttribute(uiText("fieldHelp"))}">?</button>`;
}

function formatStatusMessage(message) {
  const translations = {
    "API key 文件已存在": "apiKeyExists",
    "API key file exists": "apiKeyExists",
    "尚未检查": "notChecked",
    "Not checked": "notChecked",
    "类型已选择": "typeSelected",
    "Type selected": "typeSelected",
    "类型必填": "typeRequired",
    "Type is required": "typeRequired",
    "站点名称已填写": "siteNameFilled",
    "Site name filled": "siteNameFilled",
    "站点名称必填": "siteNameRequired",
    "Site name is required": "siteNameRequired",
    "尚未保存": "notSaved",
    "Not saved": "notSaved",
  };
  return translations[message] ? uiText(translations[message]) : message;
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

function closeOpenModal() {
  const wantsPanel = document.querySelector(".wants-panel");
  if (!wantsPanel) {
    return;
  }
  wantsPanel.querySelector("[data-want-config-modal]")?.classList.add("hidden");
  closeWantCandidateModal(wantsPanel, false);
}

function closeWantCandidateModal(panel, rerender = true) {
  panel.querySelector("[data-want-candidate-modal]")?.classList.add("hidden");
  if (rerender) {
    renderSection();
  }
}

function setModalBusy(modal, busy) {
  modal.querySelectorAll("button").forEach((button) => {
    button.disabled = busy;
  });
}

restoreUiPreferences();
syncNavigationLabels();
switchSection(state.currentSection);
loadInitialData();

globalThis.addEventListener("hashchange", () => {
  const section = sectionFromLocation();
  if (section && section !== state.currentSection) {
    switchSection(section);
  }
});

globalThis.setInterval(() => {
  const nextCycle = document.querySelector("[data-scheduler-next-cycle]");
  if (nextCycle && state.overview.ops) {
    nextCycle.textContent = formatSchedulerNextCycle(state.overview.ops);
  }
}, 30_000);

let logsRefreshPending = false;
globalThis.setInterval(async () => {
  if (state.currentSection !== "logs" || !state.logs.autoRefresh || logsRefreshPending) {
    return;
  }
  logsRefreshPending = true;
  await loadLogs();
  logsRefreshPending = false;
  if (state.currentSection === "logs") {
    renderSection();
  }
}, 30_000);

function setLanguage(language) {
  state.language = language === "EN" ? "EN" : "CN";
  document.documentElement.lang = state.language === "CN" ? "zh-CN" : "en";
  languageMenu.hidden = true;
  addTrackerButton.textContent = copy[state.language].addTracker;
  syncNavigationLabels();
  saveUiPreferences();
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
    .filter((section) => settingsPanelSpec(section))
    .map(
      (section) =>
        `<button class="secondary-button" type="button" data-config-jump="${escapeAttribute(section)}">${escapeHtml(copy[state.language].nav[section])}</button>`,
    )
    .join("");
  page.innerHTML = `
    <div class="settings-panel-header">
      <div>
        <div class="section-title">${escapeHtml(uiText("configFileTitle"))}</div>
        <p>${escapeHtml(uiText("configFileDescription"))}</p>
      </div>
      <span class="badge">${escapeHtml(state.configPath || uiText("configNotLoaded"))}</span>
    </div>
    <div class="config-section-jumps">${sectionButtons}</div>
    <div class="section-yaml-editor">
      <div class="section-title">${escapeHtml(uiText("fullConfigPreview"))}</div>
      <p>${escapeHtml(uiText("fullConfigPreviewDescription"))}</p>
      <pre class="diff-preview">${escapeHtml(state.configYaml || uiText("configYamlNotLoaded"))}</pre>
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
  const description = uiText("sectionYamlDescription")
    .replace("{path}", state.configPath || uiText("currentConfigFile"))
    .replace("{section}", section);
  return `
    <div class="section-yaml-editor">
      <div class="section-title">${escapeHtml(uiText("sectionYamlTitle"))}</div>
      <p>${escapeHtml(description)}</p>
      <textarea class="section-yaml-textarea" data-section-yaml spellcheck="false">${escapeHtml(yamlText)}</textarea>
    </div>
  `;
}

function renderDownloaderStructuredEditor(sectionData) {
  const budgetPools = Array.isArray(sectionData.budget_pools) ? sectionData.budget_pools : [];
  const categoryPolicies = Array.isArray(sectionData.category_policies) ? sectionData.category_policies : [];
  const policyNames = categoryPolicies.map((policy) => policy.name).filter(Boolean);
  const poolNames = budgetPools.map((pool) => pool.name).filter(Boolean);
  return `
    <div class="structured-editor" data-downloader-structured-editor>
      <div class="structured-section">
        <div class="structured-section-head">
          <div>
            <div class="section-title">${escapeHtml(uiText("mediaCategoryMap"))}</div>
            <p>${escapeHtml(uiText("wantRoutingHelp"))}</p>
          </div>
        </div>
        <datalist id="downloader-category-policy-options">
          ${policyNames.map((name) => `<option value="${escapeAttribute(name)}"></option>`).join("")}
        </datalist>
        <div class="field-grid compact">
          ${renderMediaCategoryMapField("movie", sectionData.media_category_map?.movie)}
          ${renderMediaCategoryMapField("tv", sectionData.media_category_map?.tv)}
          ${renderMediaCategoryMapField("anime", sectionData.media_category_map?.anime)}
        </div>
      </div>
      <div class="structured-section">
        <div class="structured-section-head">
          <div class="section-title">${escapeHtml(uiText("budgetPools"))}</div>
          <button class="secondary-button" type="button" data-structured-action="add-budget-pool">${escapeHtml(uiText("addBudgetPool"))}</button>
        </div>
        <div class="structured-list" data-budget-pool-list>
          ${budgetPools.map((pool, index) => renderBudgetPoolRow(pool, index)).join("")}
        </div>
      </div>
      <div class="structured-section">
        <div class="structured-section-head">
          <div class="section-title">${escapeHtml(uiText("categoryPolicies"))}</div>
          <button class="secondary-button" type="button" data-structured-action="add-category-policy">${escapeHtml(uiText("addCategoryPolicy"))}</button>
        </div>
        <datalist id="downloader-budget-pool-options">
          ${poolNames.map((name) => `<option value="${escapeAttribute(name)}"></option>`).join("")}
        </datalist>
        <div class="structured-list" data-category-policy-list>
          ${categoryPolicies.map((policy, index) => renderCategoryPolicyRow(policy, index)).join("")}
        </div>
      </div>
    </div>
  `;
}

function renderSearchTagScoreEditor(sectionData) {
  const scores = sectionData.quality_tag_scores || {};
  return `
    <div class="structured-editor quality-tag-score-editor" data-search-tag-score-editor>
      ${renderStrategySummary(sectionData)}
      ${renderReleasePreferencePresets()}
      <div class="structured-section">
        <div class="structured-section-head">
          <div>
            <div class="section-title">${escapeHtml(uiText("qualityTagScores"))}</div>
            <p>${escapeHtml(uiText("qualityTagScoresHelp"))}</p>
          </div>
        </div>
        <div class="structured-list quality-tag-score-list">
          ${qualityTagGroups.map((group) => renderSearchTagScoreRow(group, scores[group.key] || 0)).join("")}
        </div>
      </div>
    </div>
  `;
}

function renderStrategySummary(sectionData) {
  const scores = sectionData.quality_tag_scores || {};
  const sitePriorityCount = Object.keys(sectionData.site_priority || {}).length;
  const taggedRuleCount = Object.values(scores).filter((score) => Number(score) !== 0).length;
  const chips = [
    [uiText("summaryPreferFree"), sectionData.prefer_free === false ? uiText("no") : uiText("yes")],
    [uiText("summaryRejectHr"), sectionData.reject_hr_by_default === false ? uiText("no") : uiText("yes")],
    [uiText("summarySitePriority"), String(sitePriorityCount)],
    [uiText("summaryTaggedRules"), String(taggedRuleCount)],
  ];
  return `
    <div class="structured-section strategy-summary">
      <div class="section-title">${escapeHtml(uiText("strategySummary"))}</div>
      <div class="strategy-summary-chips">
        ${chips
          .map(
            ([label, value]) => `
              <span class="strategy-chip">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value)}</strong>
              </span>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderReleasePreferencePresets() {
  return `
    <div class="structured-section release-presets">
      <div class="structured-section-head">
        <div class="section-title">${escapeHtml(uiText("releasePresets"))}</div>
      </div>
      <div class="preset-grid">
        ${Object.entries(releasePreferencePresets)
          .map(
            ([key, preset]) => `
              <button class="secondary-button" type="button" data-release-preset="${escapeAttribute(key)}">${escapeHtml(uiText(preset.labelKey))}</button>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function applyReleasePreferencePreset(page, presetKey) {
  const preset = releasePreferencePresets[presetKey];
  if (!preset) {
    return false;
  }
  page.querySelectorAll("[data-quality-tag-score]").forEach((field) => {
    field.value = preset.scores[field.dataset.qualityTagScore] ?? 0;
  });
  resetSettingsPanelPreview(page);
  page.querySelector("[data-setting-status] .status-list").innerHTML = `
    <div class="status-item info">${escapeHtml(uiText("presetApplied"))}</div>
  `;
  return true;
}

function renderSearchTagScoreRow(group, score) {
  const description = group[state.language] || group.EN;
  const helpText = `${description}\n\n${uiText("tags")}: ${group.aliases.join(", ")}\n${uiText("qualityTagScoresHelp")}`;
  return `
    <div class="structured-row quality-tag-score-row" data-quality-tag-score-row>
      <div class="quality-tag-label">
        <span>${escapeHtml(group.label)} ${help(helpText)}</span>
        <small>${escapeHtml(group.aliases.slice(0, 4).join(" / "))}</small>
      </div>
      <label class="field">
        <span>${escapeHtml(uiText("scoreAdjustment"))}</span>
        <input data-quality-tag-score="${escapeAttribute(group.key)}" type="number" step="1" value="${escapeAttribute(score)}" />
      </label>
    </div>
  `;
}

function renderMediaCategoryMapField(mediaType, value) {
  return `
    <label class="field">
      <span>${escapeHtml(uiText(mediaType))}</span>
      <input
        data-media-category-map-field="${escapeAttribute(mediaType)}"
        list="downloader-category-policy-options"
        value="${escapeAttribute(value || "")}"
      />
    </label>
  `;
}

function renderBudgetPoolRow(pool = {}, index = 0) {
  return `
    <div class="structured-row" data-budget-pool-row data-row-index="${index}">
      <label class="field">
        <span>${escapeHtml(uiText("budgetPoolName"))}</span>
        <input data-budget-pool-field="name" value="${escapeAttribute(pool.name || "")}" />
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("maxSizeTib"))}</span>
        <input data-budget-pool-field="max_size_tib" type="number" step="0.1" min="0" value="${escapeAttribute(pool.max_size_tib ?? "")}" />
      </label>
      <button class="secondary-button row-remove-button" type="button" data-structured-action="remove-budget-pool">${escapeHtml(uiText("remove"))}</button>
    </div>
  `;
}

function renderCategoryPolicyRow(policy = {}, index = 0) {
  const mode = policy.mode || "add_only";
  const deleteEnabled = policy.delete_enabled === true;
  return `
    <div class="structured-row category-policy-row" data-category-policy-row data-row-index="${index}">
      <label class="field">
        <span>${escapeHtml(uiText("categoryPolicyName"))}</span>
        <input data-category-policy-field="name" value="${escapeAttribute(policy.name || "")}" />
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("mode"))}</span>
        <select data-category-policy-field="mode">
          <option value="add_only" ${mode === "add_only" ? "selected" : ""}>${escapeHtml(uiText("modeAddOnly"))}</option>
          <option value="mutable" ${mode === "mutable" ? "selected" : ""}>${escapeHtml(uiText("modeMutable"))}</option>
        </select>
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("budgetPools"))}</span>
        <input data-category-policy-field="budget_pool" list="downloader-budget-pool-options" value="${escapeAttribute(policy.budget_pool || "")}" />
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("deleteEnabled"))}</span>
        <select data-category-policy-field="delete_enabled">
          <option value="false" ${deleteEnabled ? "" : "selected"}>${escapeHtml(uiText("no"))}</option>
          <option value="true" ${deleteEnabled ? "selected" : ""}>${escapeHtml(uiText("yes"))}</option>
        </select>
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("overBudgetBehavior"))}</span>
        <select data-category-policy-field="over_budget_behavior">
          <option value="reject" selected>${escapeHtml(uiText("overBudgetReject"))}</option>
        </select>
      </label>
      <label class="field">
        <span>${escapeHtml(uiText("tags"))}</span>
        <input data-category-policy-field="tags" value="${escapeAttribute((policy.tags || []).join(", "))}" />
      </label>
      <button class="secondary-button row-remove-button" type="button" data-structured-action="remove-category-policy">${escapeHtml(uiText("remove"))}</button>
    </div>
  `;
}

function renderSettingsPanel(section) {
  const spec = settingsPanelSpec(section);
  const page = document.createElement("div");
  page.className = "settings-panel";
  const sectionData = state.configSections[section] || {};
  const schedulerOverrides = section === "scheduler" ? state.schedulerEnvironmentOverrides : {};
  const schedulerOverrideEntries = Object.entries(schedulerOverrides);
  const configSourceLabel = schedulerOverrideEntries.length
    ? `${uiText("fromYaml")} + ${uiText("runtimeOverrides")}`
    : uiText("fromYaml");
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
        <p>${escapeHtml(uiText("settingsDescription"))}</p>
      </div>
      <span class="badge">${escapeHtml(configSourceLabel)}</span>
    </div>
    ${schedulerOverrideEntries.length ? `<div class="status-item warning">${escapeHtml(uiText("runtimeOverrides"))}: ${escapeHtml(schedulerOverrideEntries.map(([key, value]) => `${key}=${value}`).join(", "))}</div>` : ""}
    <div class="field-grid">${fields}</div>
    ${section === "download_client" ? renderDownloaderStructuredEditor(sectionData) : ""}
    ${section === "release_preferences" ? renderSearchTagScoreEditor(sectionData) : ""}
    ${renderSectionYamlEditor(section)}
    <div class="tracker-actions sticky-actions">
      <div class="tracker-actions-group">
        <button class="secondary-button" type="button" data-setting-action="validate">${escapeHtml(uiText("validateForm"))}</button>
        <button class="secondary-button" type="button" data-setting-action="preview">${escapeHtml(uiText("previewFormChanges"))}</button>
        <button class="secondary-button" type="button" data-setting-action="yaml-preview">${escapeHtml(uiText("previewThisPageYaml"))}</button>
        <button class="secondary-button" type="button" data-setting-action="yaml-save">${escapeHtml(uiText("saveThisPageYaml"))}</button>
      </div>
      <button class="primary-button" type="button" data-setting-action="save">${escapeHtml(uiText("saveForm"))}</button>
    </div>
    <div class="status-panel settings-status" data-setting-status>
      <h3>${escapeHtml(uiText("status"))}</h3>
      <div class="status-list">
        <div class="status-item info">${escapeHtml(uiText("formEditable"))}</div>
      </div>
    </div>
  `;
  page.addEventListener("click", (event) => {
    const preset = event.target?.closest?.("[data-release-preset]")?.dataset?.releasePreset;
    if (preset && applyReleasePreferencePreset(page, preset)) {
      return;
    }
    const structuredAction = event.target?.closest?.("[data-structured-action]")?.dataset?.structuredAction;
    if (structuredAction && handleDownloaderStructuredAction(page, structuredAction, event.target)) {
      return;
    }
    const action = event.target?.closest?.("[data-setting-action]")?.dataset?.settingAction;
    if (action) {
      updateSettingsPanelStatus(page, section, action);
    }
  });
  page.addEventListener("input", () => resetSettingsPanelPreview(page));
  page.addEventListener("change", () => resetSettingsPanelPreview(page));
  return page;
}

async function handleSchedulerAction(page, action, actionButton) {
  const status = page.querySelector("[data-scheduler-status]");
  const buttons = page.querySelectorAll("[data-scheduler-action]");
  if (action === "clear-backoff" && actionButton.dataset.confirmed !== "true") {
    actionButton.dataset.confirmed = "true";
    actionButton.textContent = uiText("schedulerConfirmClearBackoff");
    if (status) {
      status.innerHTML = `<div class="status-item warning">${escapeHtml(uiText("schedulerClearBackoffConfirm"))}</div>`;
    }
    return;
  }
  buttons.forEach((button) => { button.disabled = true; });
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(action === "trigger" ? uiText("schedulerTriggering") : uiText("schedulerClearingBackoff"))}</div>`;
  }
  try {
    const endpoint = action === "trigger" ? "/api/scheduler/trigger" : "/api/scheduler/backoff/clear";
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    if (status) {
      status.innerHTML = `<div class="status-item ok">${escapeHtml(action === "trigger" ? uiText("schedulerTriggerQueued") : uiText("schedulerBackoffCleared"))}</div>`;
    }
    await loadOverview();
    renderSection();
  } catch (error) {
    if (status) {
      status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
    }
  } finally {
    if (action === "clear-backoff") {
      delete actionButton.dataset.confirmed;
      actionButton.textContent = uiText("schedulerClearBackoff");
    }
    const phase = state.overview.ops?.scheduler_control?.phase;
    page.querySelector('[data-scheduler-action="trigger"]')?.toggleAttribute("disabled", phase !== "waiting");
    page.querySelector('[data-scheduler-action="clear-backoff"]')?.toggleAttribute("disabled", !state.overview.ops?.schedule_backoff?.active);
  }
}

function handleDownloaderStructuredAction(page, action, target) {
  if (!page.querySelector("[data-downloader-structured-editor]")) {
    return false;
  }
  if (action === "add-budget-pool") {
    const list = page.querySelector("[data-budget-pool-list]");
    list?.insertAdjacentHTML("beforeend", renderBudgetPoolRow({}, list.children.length));
    resetSettingsPanelPreview(page);
    return true;
  }
  if (action === "remove-budget-pool") {
    target.closest("[data-budget-pool-row]")?.remove();
    resetSettingsPanelPreview(page);
    return true;
  }
  if (action === "add-category-policy") {
    const list = page.querySelector("[data-category-policy-list]");
    list?.insertAdjacentHTML("beforeend", renderCategoryPolicyRow({ tags: ["seed-agent"] }, list.children.length));
    resetSettingsPanelPreview(page);
    return true;
  }
  if (action === "remove-category-policy") {
    target.closest("[data-category-policy-row]")?.remove();
    resetSettingsPanelPreview(page);
    return true;
  }
  return false;
}

function updateSettingsPanelStatus(page, section, action) {
  if (section !== "config_file" && action === "yaml-preview") {
    previewSettingsPanelYaml(page, section);
    return;
  }
  if (section !== "config_file" && action === "yaml-save") {
    saveSettingsPanelYaml(page, section);
    return;
  }
  if (section !== "config_file" && action === "save") {
    if (page.dataset.previewConfirmed === "true") {
      confirmSettingsPanelSave(page, section);
      return;
    }
    previewSettingsPanelSave(page, section);
    return;
  }
  if (action === "preview" && section !== "config_file") {
    previewSettingsPanelSave(page, section);
    return;
  }
  const messages = {
    validate: `${settingsPanelSpec(section).title}: ${uiText("formValid")}`,
    preview: `${settingsPanelSpec(section).title}: ${uiText("formPreviewReady")}`,
    save: `${settingsPanelSpec(section).title}: ${uiText("formSavedPageState")}`,
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
  if (section === "download_client") {
    readDownloaderStructuredData(page, data);
  }
  if (section === "release_preferences") {
    readSearchTagScoreData(page, data);
  }
  return data;
}

function readSearchTagScoreData(page, data) {
  const scores = {};
  page.querySelectorAll("[data-quality-tag-score]").forEach((field) => {
    const score = Number.parseInt(field.value || "0", 10);
    if (Number.isNaN(score) || score === 0) {
      return;
    }
    scores[field.dataset.qualityTagScore] = score;
  });
  data.quality_tag_scores = scores;
}

function readDownloaderStructuredData(page, data) {
  const mediaCategoryMap = {};
  page.querySelectorAll("[data-media-category-map-field]").forEach((field) => {
    const value = field.value.trim();
    if (value) {
      mediaCategoryMap[field.dataset.mediaCategoryMapField] = value;
    }
  });
  data.media_category_map = mediaCategoryMap;

  const budgetPools = [];
  page.querySelectorAll("[data-budget-pool-row]").forEach((row) => {
    const name = row.querySelector('[data-budget-pool-field="name"]')?.value.trim() || "";
    const maxSize = row.querySelector('[data-budget-pool-field="max_size_tib"]')?.value.trim() || "";
    if (!name && !maxSize) {
      return;
    }
    budgetPools.push({
      name,
      max_size_tib: Number(maxSize),
    });
  });
  data.budget_pools = budgetPools;

  const categoryPolicies = [];
  page.querySelectorAll("[data-category-policy-row]").forEach((row) => {
    const name = row.querySelector('[data-category-policy-field="name"]')?.value.trim() || "";
    const budgetPool = row.querySelector('[data-category-policy-field="budget_pool"]')?.value.trim() || "";
    const mode = row.querySelector('[data-category-policy-field="mode"]')?.value || "add_only";
    const tags = row.querySelector('[data-category-policy-field="tags"]')?.value || "";
    if (!name && !budgetPool) {
      return;
    }
    categoryPolicies.push({
      name,
      mode,
      budget_pool: budgetPool,
      delete_enabled: row.querySelector('[data-category-policy-field="delete_enabled"]')?.value === "true",
      over_budget_behavior: row.querySelector('[data-category-policy-field="over_budget_behavior"]')?.value || "reject",
      tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
    });
  });
  data.category_policies = categoryPolicies;
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
        throw new Error(`${uiText("invalidMapPrefix")}: ${item}. ${uiText("invalidMapSuffix")}`);
      }
      result[key] = numericValue;
    });
  return result;
}

function resetSettingsPanelPreview(page) {
  page.dataset.previewConfirmed = "false";
  const saveButton = page.querySelector('[data-setting-action="save"]');
  if (saveButton) {
    saveButton.textContent = uiText("saveForm");
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
  if (payload.revision) {
    state.configRevision = payload.revision;
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
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, yaml: yamlText, revision: state.configRevision || null }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    if (persist) {
      applyReturnedConfigState(payload, section, page);
    }
    page.dataset.previewConfirmed = "false";
    const saveButton = page.querySelector('[data-setting-action="save"]');
    if (saveButton) {
      saveButton.textContent = uiText("saveForm");
    }
    const message = persist ? uiText("thisPageYamlSaved") : uiText("thisPageYamlPreviewReady");
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
    const response = await apiFetch("/api/config/sections/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, data, revision: state.configRevision || null }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    page.dataset.previewConfirmed = "true";
    const saveButton = page.querySelector('[data-setting-action="save"]');
    if (saveButton) {
      saveButton.textContent = uiText("confirmSaveForm");
    }
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item ok">${escapeHtml(uiText("saveConfirmation"))}</div>
      <pre class="diff-preview">${escapeHtml(payload.diff || uiText("cleanupNoConfigChanges"))}</pre>
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
    const response = await apiFetch("/api/config/sections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, data, revision: state.configRevision || null }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    applyReturnedConfigState(payload, section, page);
    page.dataset.previewConfirmed = "false";
    const saveButton = page.querySelector('[data-setting-action="save"]');
    if (saveButton) {
      saveButton.textContent = uiText("saveForm");
    }
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item ok">${escapeHtml(uiText("configSaved"))}</div>
    `;
  } catch (error) {
    page.querySelector("[data-setting-status] .status-list").innerHTML = `
      <div class="status-item warning">${escapeHtml(error.message)}</div>
    `;
  }
}
