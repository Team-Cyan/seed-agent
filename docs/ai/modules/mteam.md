# M-Team Module

## Purpose

Handle M-Team-specific discovery, detail enrichment, and download-token generation concerns.

## Primary Files

- `src/seed_agent/sites/mteam.py`
- `src/seed_agent/search/mteam.py`
- `src/seed_agent/sites/rss.py`
- `tests/test_mteam_site.py`
- `tests/test_search_mteam.py`
- `docs/specs/2026-04-24-mteam-api-driven-discovery.md`

## Current Status

Implemented today:

- RSS candidate parsing for M-Team feed shape
- `x-api-key` detail enrichment
- API-driven discovery with native M-Team filters, FREE/discount filtering, and
  activity-based sorting
- deferred `genDlToken` download URL generation for accepted API-discovered
  candidates during execute-mode enqueue
- non-zero M-Team responses are structured errors rather than empty results;
  HTTP 429 and service/network failures stop later tracker calls in the cycle
  and feed scheduler protection,
- M-Team API-backed resource intent search, using the same search endpoint while
  keeping download-token resolution deferred until execute-mode intent enqueue
- ID-first intent search through native M-Team `douban` and `imdb` filters when
  the source event provides external IDs, with Douban tried first, IMDb used as
  a supplement, and a broad title/year keyword fallback added to catch rows that
  lack external-ID metadata
- search result metadata captures M-Team API tag fields such as medium,
  standard, video codec, audio codec, and labels for Web UI candidate review
- intent search supports generic Remux/quality preferences through
  `release_preferences.quality_tag_scores` and TV/anime pack behavior through
  `want_decision.series_search_mode`
- `site-probe` visibility for authenticated M-Team access and discovery mode

Current preferred auth:

- `api_key_ref`

Current fallback still present in code:

- cookie-based enrichment compatibility

## Important Constraints

- Do not delete the RSS path. It remains useful for fallback and for other sites.
- Do not reintroduce browser-login assumptions into the main flow.
- Treat M-Team API key as the long-term preferred authenticated path.
- All M-Team API clients within one process share a request-start interval. The
  default is 1.25 seconds after production rejected the 51st continuous request
  at one-second spacing, and can be tuned with
  `SEED_AGENT_MTEAM_MIN_REQUEST_INTERVAL_SECONDS`; keep it conservative. Web
  and scheduler processes intentionally maintain separate limiters.
- Scheduler source backfill also has a per-cycle API budget, defaulting to 20.
  Pacing controls bursts; the budget limits longer-window cumulative usage.
- Pagination stops when the API page itself is exhausted, not when local
  filtering leaves a short result list.
- Treat timezone-naive M-Team API date strings as `Asia/Shanghai`; convert them
  to UTC before calculating or persisting free-window time.
- Keep API discovery cheap: search/detail calls may run during discovery and
  scoring, but `genDlToken` should only run for accepted candidates when
  enqueue is executing.
- Treat `discount=FREE` plus an explicit `discountEndTime=null` from the M-Team
  API as a known unlimited free window rather than an unknown expiry.
- When refreshed tracker evidence no longer contains a promotion expiry, clear
  the previously persisted finite left-time value instead of extending stale
  free-window evidence.
- Keep upload discovery knobs in `api_discovery`; credentials stay in
  `api_key_ref` / ignored local secret files. Intent search uses conservative
  search-specific defaults and should not inherit adult/freeleech upload
  discovery filters.
- For upload discovery, `api_discovery.min_seeders` and `min_leechers` can be
  `null` to inherit global `pt_filters` thresholds. Explicit `0` keeps the
  native M-Team API lower-bound filter open.
- For intent search, keep user quality preferences generic in
  `release_preferences.quality_tag_scores` rather than inventing M-Team-only Remux/Profile
  switches. Use `want_decision.series_search_mode` for season-pack vs episode behavior.
- ID-first intent search should not put quality terms such as Remux into the
  API keyword field. Fetch by Douban/IMDb ID first, supplement with a broad
  title/year keyword query, then apply generic quality preferences during
  ranking so lower-match candidates remain visible for operator override.
- Want List search may return NORMAL/non-free releases because it represents a
  requested acquisition. This does not weaken the separate PT upload-farming
  free-only gate.

## Desired Future State

- keep API discovery as the preferred M-Team path,
- retain RSS as a tested fallback and reusable adapter.

## Verification

- `uv run pytest -q tests/test_mteam_site.py tests/test_search_mteam.py tests/test_rss_site.py`
- `uv run seed-agent site-probe --config <mteam-config>`

## If You Get Stuck

Read:

- `docs/ai/reference-repos.md`
- `docs/specs/2026-04-24-mteam-api-driven-discovery.md`
