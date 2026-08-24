# Intent Loop Module

## Purpose

Convert human requests into search/rank/reject/enqueue workflows.

## Primary Files

- `src/seed_agent/actions/intent.py`
- `src/seed_agent/intent/parse.py`
- `src/seed_agent/search/`
- `src/seed_agent/sources/`
- `tests/test_intent_*`

## Current Responsibilities

- ingest intents,
- ingest Douban wanted events from the personal-interest RSS as a recent-additions
  signal (currently newest 10 actions), retaining a local export as the full-list
  recovery source; enrich subject metadata only after the list event is persisted,
- ingest IMDb watchlist/list events from CSV exports or best-effort public page
  parsing,
- ingest Letterboxd watchlist events from CSV exports,
- ingest Telegram message updates through secret-backed polling with a required
  chat allowlist and a durable cursor committed only after successful intent
  processing,
- merge Douban and IMDb source events into canonical Want List works through
  `douban:<subject_id>` and `imdb:<tt_id>` aliases,
- normalize text,
- preserve trusted TV/anime source classification as structured `SHOW` intents
  and parse `S03`, `Season 3`, and `第三季` season notation,
- search sources,
- rank release candidates,
- reject unwanted options,
- enqueue an explicit release candidate when an ambiguous option is selected,
- enqueue through the shared downloader path.

## Expectations

- preserve deterministic local state transitions,
- keep source metadata on `ResourceIntent.metadata` when it is useful for UI or
  later search behavior,
- preserve source evidence separately from canonical intent rows so repeated
  wants from different configured lists do not duplicate searches or downloads,
- commit replay-sensitive source cursors only after the complete source batch
  and intent cycle succeed; a later source failure must leave earlier Telegram
  updates replayable,
- merge source aliases only from trusted source events; candidate release
  metadata is search evidence and must never establish canonical identity,
- treat `enqueued`, `rejected`, and operator-marked `viewed` intents as terminal for repeated source sync, and
  replace an intent's saved release snapshot on each successful search,
- keep search providers modular. M-Team remains the reference API provider;
  Torznab is available as the first non-M-Team provider to validate the
  `SearchProvider` boundary,
- keep Want List acquisition independent from the PT upload-farming
  `pt_filters.allow_non_free` switch. A requested work may use a paid release,
  while PT discovery remains free-only when that switch is false,
- keep PT upload-farming `max_active_downloads` scoped to the configured
  default `seed` category; movie, TV, and anime acquisition must not be blocked
  by seed-only active slots,
- apply the selected movie/TV/seed category policy, shared pool size,
  amount-left, and disk-reserve gates before enqueue, plus the active-slot gate
  for seed-category candidates. Reserve each
  accepted candidate in the same batch so later candidates cannot reuse its
  projected headroom,
- keep the operator-facing release score uncapped so strong candidates remain
  distinguishable above 100. Confidence and configured acceptance thresholds
  stay bounded to `0..1`, while ambiguity compares the uncapped score gap,
- keep candidate review focused on decision evidence: deduplicate equivalent
  quality aliases, hide raw tracker enum codes, keep risks visible, and collapse
  routine scoring reasons. Show tracker subtitle and MediaInfo/NFO only when the
  search provider already returned them,
- use the durable enqueue claim keyed by intent and release so concurrent Web,
  CLI, or scheduler workers cannot add the same release twice,
- require exact season/episode token boundaries so `S02E03` cannot match
  `S020E030`,
- when `series_search_mode=season`, exclude episode-labelled candidates from
  search results before persistence and candidate rendering; only an `Sxx`
  title without an explicit or compact numbered episode token (for example
  `S03E01-E06`, `S03.01-06`, or `S03.301-306`) is a provisional full-season
  match,
- redact credential-like assignments before persisting intent raw text while
  retaining stable source-event identity,
- keep source-only ingestion independent from downloader and search-provider
  availability,
- fetch configured Douban RSS, exports, and IMDb list events independently and
  persist their names before optional metadata enrichment; preserve a successfully read
  Douban list item when its mobile subject detail request fails, reuse
  persisted subject metadata on later refreshes, parse JSON-LD subject type/year
  when it is available, and use a strictly matched already-read IMDb Watch List
  item as a no-extra-request fallback (year match, or one unique exact title
  when RSS has no year),
- in season mode, reject explicit or compact episode-labelled releases even
  while a newly read RSS item remains untyped; require the `Sxx` full-season
  marker once the item is known to be TV/anime,
- keep one configured Want List source failure as a visible warning while
  allowing successfully read exports and other configured sources to ingest,
- evaluate enqueue runtime gates before resolving a deferred tracker download
  token, and preserve distinct already-enqueued/in-progress outcomes for
  idempotent callers.
- prepare Web and scheduled batch-search rankings in memory, then persist the
  complete batch through the StateStore atomic batch boundary rather than
  committing candidates, state, and history separately for every Want.
- let operators mark a Want as viewed without removing its source/candidate
  evidence; viewed Wants must not be searched or enqueued again.

## Verification

- `uv run pytest -q tests/test_intent_actions.py tests/test_intent_cli.py tests/test_intent_ranking.py tests/test_intent_run_once.py`
- `uv run pytest -q tests/test_search_contracts.py tests/test_search_torznab.py tests/test_intent_sources.py`
