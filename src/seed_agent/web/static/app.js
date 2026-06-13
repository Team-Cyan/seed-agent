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
    ui: {
      addedAt: "添加时间",
      addSource: "新增来源",
      all: "全部",
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
      confirmEnqueue: "确认把这个候选加入 qB 下载队列？这会向 qB 发送添加任务。",
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
      fullConfigPreview: "完整配置预览",
      fullConfigPreviewDescription: "这里是归一化后的只读预览。需要修改时，进入对应配置页编辑“本页 YAML”。",
      heartbeat: "心跳",
      heartbeatMissing: "心跳文件不存在",
      heartbeatStale: "过期",
      heartbeatMissingStatus: "缺失",
      heartbeatOk: "正常",
      imdbWatchlistUrl: "IMDb watchlist URL",
      invalidMapPrefix: "无效映射项",
      invalidMapSuffix: "请使用 site=priority，例如 demo=10。",
      leechers: "下载",
      loading: "加载中",
      loadingCandidates: "正在读取候选",
      localApiLoading: "正在读取本地只读 API。",
      lowerMatch: "低匹配，可强制",
      maxSizeTib: "容量上限 TiB",
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
      noPools: "未配置容量池",
      noStateRecords: "暂无状态记录",
      noTags: "无标签",
      noWants: "暂无想看资源",
      notChecked: "尚未检查",
      notSaved: "尚未保存",
      operationComplete: "操作完成",
      pages: "页数",
      preview: "预览",
      previewFormChanges: "预览表单改动",
      previewThisPageYaml: "预览本页 YAML",
      provider: "来源",
      readingStatus: "状态读取",
      remove: "移除",
      refreshWants: "刷新列表",
      requestFailedPrefix: "请求失败",
      resourceIntents: "获取意图",
      rssUrlHelp: "RSS 发现方式需要填写订阅地址。选择 API 时不会要求这个字段。",
      save: "保存",
      saveConfirmation: "保存确认",
      saveForm: "保存表单",
      saveThisPageYaml: "保存本页 YAML",
      search: "搜索",
      searchCompleted: "搜索已完成",
      searchCurrentFilter: "搜索当前筛选",
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
      status: "状态",
      dashboardAttention: "需要关注",
      tags: "标签",
      overBudgetBehavior: "超预算处理",
      overBudgetAddPaused: "暂停添加",
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
      wantResources: "想看资源",
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
    ui: {
      addedAt: "Added at",
      addSource: "Add source",
      all: "All",
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
      confirmEnqueue: "Add this candidate to the qB download queue? This sends an add request to qB.",
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
      fullConfigPreview: "Full config preview",
      fullConfigPreviewDescription: "This is the normalized read-only preview. To edit, open the matching settings page and update This page YAML.",
      heartbeat: "Heartbeat",
      heartbeatMissing: "Heartbeat file is missing",
      heartbeatStale: "Stale",
      heartbeatMissingStatus: "Missing",
      heartbeatOk: "OK",
      imdbWatchlistUrl: "IMDb watchlist URL",
      invalidMapPrefix: "Invalid map entry",
      invalidMapSuffix: "Use site=priority, for example demo=10.",
      leechers: "leechers",
      loading: "Loading",
      loadingCandidates: "Loading candidates",
      localApiLoading: "Reading the local read-only API.",
      lowerMatch: "Lower match, force allowed",
      maxSizeTib: "Size limit TiB",
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
      noPools: "No budget pools configured",
      noStateRecords: "No state records yet",
      noTags: "No tags",
      noWants: "No wants yet",
      notChecked: "Not checked",
      notSaved: "Not saved",
      operationComplete: "Operation completed",
      pages: "Pages",
      preview: "Preview",
      previewFormChanges: "Preview form changes",
      previewThisPageYaml: "Preview this page YAML",
      provider: "Source",
      readingStatus: "Status read",
      remove: "Remove",
      refreshWants: "Refresh list",
      requestFailedPrefix: "Request failed",
      resourceIntents: "Resource intents",
      rssUrlHelp: "RSS discovery needs a feed URL. This field is not required in API mode.",
      save: "Save",
      saveConfirmation: "Save confirmation",
      saveForm: "Save form",
      saveThisPageYaml: "Save this page YAML",
      search: "Search",
      searchCompleted: "Search completed",
      searchCurrentFilter: "Search current filters",
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
      status: "Status",
      dashboardAttention: "Needs attention",
      tags: "Tags",
      overBudgetBehavior: "Over budget",
      overBudgetAddPaused: "Add paused",
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
      wantResources: "Wanted resources",
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
      processing: "Processing",
      thisPageYamlSaved: "This page YAML saved",
      thisPageYamlPreviewReady: "This page YAML preview is ready",
    },
  },
};

const settingsPanelsByLanguage = {
  CN: {
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
      ["复核阈值", "confirmation_threshold", "number", "低于自动入队阈值或有风险时进入人工复核。"],
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
  },
  EN: {
    downloader: {
      title: "Downloader",
      fields: [
        ["qBittorrent target", "target", "text", "Select the downloader target. Writes downloader.target."],
        ["Default category", "default_category", "text", "Default qBittorrent category for new tasks."],
        ["Credential file", "secret_ref", "optional-text", "Local qB credential file path. Plain secrets are not saved here."],
      ],
    },
    discovery: {
      title: "Discovery",
      fields: [
        ["Discount labels", "discounts", "csv", "Candidate discount filters, for example free or 2xfree."],
        ["Minimum free minutes left", "min_left_time_minutes", "number", "Skip automatic enqueue when the free window is shorter than this."],
        ["Minimum seeders", "min_seeders", "optional-number", "Skip automatic enqueue below this seeder count; empty means no limit."],
        ["Minimum leechers", "min_leechers", "number", "Skip automatic enqueue below this demand count."],
        ["Target seeder/leecher ratio", "target_seed_leecher_ratio", "number", "Controls demand pressure; no absolute seeder cap is used."],
        ["Allow non-free", "allow_non_free", "boolean", "Allow normal candidates into scoring."],
        ["Maximum size GB", "max_size_gb", "optional-number", "Hard candidate size cap; empty means no limit."],
        ["Maximum active downloads", "max_active_downloads", "optional-number", "Above this, candidates are added paused."],
        ["Maximum remaining download GB", "max_total_amount_left_gb", "optional-number", "Above this remaining-download total, candidates are added paused."],
      ],
    },
    cleanup: {
      title: "Cleanup",
      fields: [
        ["Cold after days", "cold_after_days", "number", "Treat torrents as cold after this many days without useful upload."],
        ["Minimum upload delta GB", "min_upload_delta_gb", "number", "Only cleanup candidates below this upload delta."],
        ["Protect HR", "protect_hr", "boolean", "Protect HR-risk torrents by default."],
        ["Protect manual marks", "protect_manual", "boolean", "Protect manually marked torrents by default."],
        ["Protect media library", "protect_media_library", "boolean", "Protect media-library torrents by default."],
        ["Delete after no-upload hours", "delete_after_no_upload_hours", "number", "Zero-upload observation window."],
        ["Pause before delete hours", "pause_before_delete_hours", "number", "Hours to pause before delete observation."],
      ],
    },
    intent: {
      title: "Acquisition",
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
    search: {
      title: "Torrent Filters",
      fields: [
        ["Site priority", "site_priority", "map", "Use site=priority, for example mteam=10. Affects search ranking only and never saves secrets."],
        ["Max results per site", "max_results_per_site", "number", "Maximum retained search results per site."],
        ["Prefer free", "prefer_free", "boolean", "Prefer free/freeleech releases in search ranking."],
        ["Reject HR by default", "reject_hr_by_default", "boolean", "Reject HR-risk releases by default."],
        ["Required keywords", "required_keywords", "csv", "Keywords that must appear in result titles, for example Remux."],
        ["Preferred keywords", "preferred_keywords", "csv", "Scoring keywords, for example 2160p, HDR, or Dolby Vision."],
        ["Excluded keywords", "excluded_keywords", "csv", "Keywords to reject, for example CAM, TC, or Hardcoded."],
      ],
    },
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
      ? [{ level: "ok", message: uiText("apiKeyExists") }]
      : [{ level: "info", message: uiText("notChecked") }],
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
      throw new Error(uiText("readingStatus"));
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
  panel.className = "overview-dashboard";
  const { health, stateSummary, pools, error } = state.overview;
  if (error) {
    panel.append(renderMetricCard(uiText("readingStatus"), uiText("failed"), error, "warning"));
    return panel;
  }
  if (!health || !stateSummary || !pools) {
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
  return panel;
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
  const sources = state.configSections.sources || {};
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
    wrapper.innerHTML = `<div class="empty-state">${escapeHtml(uiText("noWants"))}</div>`;
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
    return sourceOk && typeOk;
  });
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
      <td>
        <span class="badge ${item.status === "queued" ? "ok" : ""}">${escapeHtml(item.status_label || item.state)}</span>
        ${bestScore ? `<span class="want-score-pill">${escapeHtml(bestScore)}</span>` : ""}
        <span class="inline-action">${escapeHtml(uiText("viewCandidates"))}</span>
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
          <span class="badge ${item.status === "queued" ? "ok" : ""}">${escapeHtml(item.status_label || item.state)}</span>
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

async function openWantCandidates(panel, intentId, message = "") {
  const modal = panel.querySelector("[data-want-candidate-modal]");
  const title = modal.querySelector("[data-want-candidate-title]");
  const list = modal.querySelector("[data-want-candidate-list]");
  const status = modal.querySelector("[data-want-candidate-status]");
  modal.dataset.intentId = intentId;
  modal.classList.remove("hidden");
  title.textContent = uiText("candidateTorrents");
  status.innerHTML = message ? `<div class="status-item ok">${escapeHtml(message)}</div>` : "";
  list.innerHTML = `<div class="empty-state">${escapeHtml(uiText("loadingCandidates"))}</div>`;
  try {
    const response = await fetch(`/api/wants/${encodeURIComponent(intentId)}/candidates`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `${uiText("requestFailedPrefix")}: ${response.status}`);
    }
    title.textContent = payload.intent?.title || uiText("candidateTorrents");
    list.innerHTML = renderWantCandidateList(payload.items || []);
  } catch (error) {
    list.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
  }
}

function renderWantCandidateList(items) {
  if (items.length === 0) {
    return `<div class="empty-state">${escapeHtml(uiText("noCandidates"))}</div>`;
  }
  const matching = items.filter((item) => item.matches_requirements);
  const lower = items.filter((item) => !item.matches_requirements);
  return `
    ${matching.length ? `<div class="candidate-group-title">${escapeHtml(uiText("matchingPreference"))}</div>` : ""}
    ${matching.map(renderWantCandidateCard).join("")}
    ${lower.length ? `<div class="candidate-group-title muted">${escapeHtml(uiText("lowerMatch"))}</div>` : ""}
    ${lower.map(renderWantCandidateCard).join("")}
  `;
}

function renderWantCandidateCard(item) {
  const tags = [...(item.official_tags || []), ...(item.inferred_tags || [])];
  const uniqueTags = Array.from(new Set(tags));
  const actionLabel = item.matches_requirements ? uiText("enqueueQb") : uiText("forceEnqueueQb");
  return `
    <article class="candidate-card ${item.matches_requirements ? "" : "dimmed"} ${item.selected ? "selected" : ""}">
      <div class="candidate-card-head">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <div class="muted-line">${escapeHtml(item.site)} · ${escapeHtml(formatCandidateSize(item))} · ${escapeHtml(item.seeders)} ${escapeHtml(uiText("seeders"))} / ${escapeHtml(item.leechers)} ${escapeHtml(uiText("leechers"))}</div>
        </div>
        <div class="candidate-score">
          <span>${escapeHtml(item.score)}</span>
          <small>${escapeHtml(item.status_label)}</small>
        </div>
      </div>
      <div class="candidate-tags">
        ${uniqueTags.map((tag) => `<span class="badge">${escapeHtml(tag)}</span>`).join("") || `<span class="badge">${escapeHtml(uiText("noTags"))}</span>`}
      </div>
      ${renderCandidateNotes(item)}
      <div class="tracker-actions-group candidate-actions">
        <button class="${item.matches_requirements ? "primary-button" : "secondary-button"}" type="button" data-want-candidate-action="enqueue" data-release-id="${escapeAttribute(item.release_id)}">${escapeHtml(actionLabel)}</button>
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
      ${risks.map((risk) => `<span class="status-item warning">${escapeHtml(risk)}</span>`).join("")}
      ${reasons.slice(0, 4).map((reason) => `<span class="status-item info">${escapeHtml(reason)}</span>`).join("")}
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
  const ok = window.confirm(uiText("confirmEnqueue"));
  if (!ok) {
    return;
  }
  const status = modal.querySelector("[data-want-candidate-status]");
  const endpoint = `/api/wants/${encodeURIComponent(intentId)}/enqueue`;
  const body = { release_id: releaseId, execute: true };
  try {
    setModalBusy(modal, true);
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("processing"))}</div>`;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(formatWantCandidateError(payload, response.status));
    }
    await loadWants();
    const message = payload.status?.[0]?.message || uiText("operationComplete");
    await openWantCandidates(panel, intentId, message);
  } catch (error) {
    status.innerHTML = `<div class="status-item warning">${escapeHtml(error.message)}</div>`;
  } finally {
    setModalBusy(modal, false);
  }
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
    const response = await fetch("/api/wants/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.wants.filters),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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

async function syncConfiguredWants(panel) {
  const status = panel.querySelector("[data-want-config-status]") || panel.querySelector("[data-want-status]");
  if (status) {
    status.innerHTML = `<div class="status-item info">${escapeHtml(uiText("syncingWants"))}</div>`;
  }
  try {
    const response = await fetch("/api/wants/sync", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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
  panel.querySelectorAll('[data-want-action="sync"], [data-want-action="search"]').forEach((item) => {
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
    const data = { ...(state.configSections.sources || {}) };
    data.want_lists = readWantSourceConfig(panel);
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section: "sources", data }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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
      tracker.status = [{ level: "warning", message: `${uiText("requestFailedPrefix")}: ${response.status}` }];
    }
    if (action === "save" && response.ok) {
      tracker.saved = true;
      tracker.api_key_value = "";
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
          <option value="add_paused" selected>${escapeHtml(uiText("overBudgetAddPaused"))}</option>
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
      <span class="badge">${escapeHtml(uiText("fromYaml"))}</span>
    </div>
    <div class="field-grid">${fields}</div>
    ${section === "downloader" ? renderDownloaderStructuredEditor(sectionData) : ""}
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
  if (section === "downloader") {
    readDownloaderStructuredData(page, data);
  }
  return data;
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
      over_budget_behavior: row.querySelector('[data-category-policy-field="over_budget_behavior"]')?.value || "add_paused",
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
      throw new Error(payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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
    const response = await fetch("/api/config/sections/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, data }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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
    const response = await fetch("/api/config/sections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, data }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.status?.[0]?.message || `${uiText("requestFailedPrefix")}: ${response.status}`);
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
