# Phase 2 Resource Intent Loop Plan

Date: 2026-04-22

## Review Of Phase 1

Phase 1 is ready to serve as the foundation for Phase 2.

Verified gates:

- `uv run pytest -q`: 104 tests passing.
- `uv run ruff check .`: passing.
- `uv run seed-agent --help`: CLI loads the Phase 1 command surface.
- `uv run seed-agent run-once --config config/example.yaml`: dry-run smoke works without downloader mutation.

Phase 1 strengths to preserve:

- Mutating downloader commands are dry-run by default and require `--execute`.
- qBittorrent operations are behind a downloader abstraction.
- Audit records redact private tracker tokens, cookies, passkeys, and password-like fields.
- Local lifecycle state is SQLite-backed and workspace-local.
- Cleanup decisions protect unmanaged torrents and only mutate clearly managed torrents.
- Batch mutation failures preserve decisions already made so audit/state can be written before the CLI exits non-zero.

Phase 1 follow-up fixed during this review:

- Same-rank lifecycle updates now preserve existing `score` and `torrent_hash` when an incoming write does not provide replacement values. This prevents repeated enqueue attempts or qB `Ok.` responses from erasing a known hash that later cleanup needs.

Known non-blocking issue:

- The local Python 3.14 toolchain emits `pytest_asyncio` deprecation warnings. These do not affect Phase 1 behavior, but should be cleaned up when the dependency/toolchain settles.

## Phase 2 Goal

Build the first resource-intent loop:

1. Accept a human or integration request for a movie/show/resource.
2. Normalize it into a structured `ResourceIntent`.
3. Search configured sources for matching releases.
4. Rank releases with explainable confidence and risk.
5. Require confirmation when ambiguity is meaningful.
6. Enqueue the selected release through the existing downloader abstraction.
7. Audit every external action and keep local intent state queryable.

Phase 2 should make Telegram, WeChat bridge, Douban wanted-list, and subscription workflows possible without making any one integration the core architecture.

## Product Boundary

In scope:

- CLI-first intent ingestion and review.
- Adapter interfaces for Telegram, WeChat bridge, Douban, and subscription sources.
- A local file/inbox source that can stand in for external integrations during development.
- Search abstraction and at least one working search path using existing RSS/site primitives.
- Ranking policy and confirmation queue.
- Reuse of qB enqueue, audit logging, redaction, config loading, and local state.

Out of scope for this phase:

- Full chat bot deployment.
- Personal WeChat reverse engineering.
- Full media-library organization, renaming, hardlinking, or Plex/Jellyfin import.
- Web dashboard.
- Auto-reseed.
- Broad plugin framework.
- LLM-dependent parsing as the only path. Optional LLM enrichment can be added later behind a deterministic interface.

## Design Decisions

- Keep the primary operator interface as CLI plus JSON output.
- Treat every source event as an `IntentEvent`, then normalize to `ResourceIntent`.
- Store intent state in the same `.seed-agent/state.db` database, using additive tables.
- Keep downloader mutations in existing qB action paths.
- Use confirmation as a state transition, not as an ad hoc prompt.
- Prefer deterministic matching first; add external metadata/LLM enrichment later only if the interface already works without it.
- Make source integrations shallow. They should ingest events; they should not own ranking or enqueue policy.

## Proposed Models

Add to `seed_agent.models` or a new `seed_agent.intent.models` module:

```python
class IntentSource(StrEnum):
    CLI = "cli"
    FILE_INBOX = "file_inbox"
    TELEGRAM = "telegram"
    WECHAT_BRIDGE = "wechat_bridge"
    DOUBAN_WANTED = "douban_wanted"
    SUBSCRIPTION = "subscription"


class IntentKind(StrEnum):
    MOVIE = "movie"
    SHOW = "show"
    EPISODE = "episode"
    UNKNOWN = "unknown"


class IntentState(StrEnum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    SEARCHED = "searched"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    ENQUEUED = "enqueued"
    FAILED = "failed"


class ResourceIntent(BaseModel):
    intent_id: str
    source: IntentSource
    raw_text: str
    kind: IntentKind
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    resolution: str | None = None
    quality: str | None = None
    language: str | None = None
    requested_at: datetime
    state: IntentState
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReleaseCandidate(BaseModel):
    release_id: str
    site: str
    title: str
    source_url: str
    download_url: str
    size_bytes: int
    seeders: int
    leechers: int
    discount: Discount = Discount.NORMAL
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RankedRelease(BaseModel):
    intent_id: str
    release: ReleaseCandidate
    score: int
    confidence: float
    accepted: bool
    confirmation_required: bool
    reasons: list[str]
    risks: list[str]
```

## Config Shape

Extend `config/example.yaml` with Phase 2 sections:

```yaml
want_decision:
  confirmation_threshold: 0.82
  auto_enqueue_threshold: 0.94
  ambiguity_gap: 0.08
  default_resolution: 1080p
  preferred_languages: ["zh", "en"]
  inbox_ref: local/inbox/intents.jsonl

release_preferences:
  site_priority:
    demo-free: 10
  max_results_per_site: 20
  prefer_free: true
  reject_hr_by_default: true

want_sources:
  telegram:
    enabled: false
    secret_ref: local/secrets/telegram.yaml
  wechat_bridge:
    enabled: false
    secret_ref: local/secrets/wechat-bridge.yaml
  douban_wanted:
    enabled: false
    export_ref: local/inbox/douban-wanted.json
  subscription:
    enabled: false
    rules_ref: config/subscriptions.yaml
```

Secrets stay under `local/secrets/`. Inbox files stay under `local/inbox/` and should be gitignored if they can contain private media preferences.

## State Schema Additions

Add tables through `StateStore` initialization or a small migration helper:

```sql
CREATE TABLE IF NOT EXISTS intents (
  intent_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  selected_release_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS release_candidates (
  release_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL,
  site TEXT NOT NULL,
  title TEXT NOT NULL,
  score INTEGER,
  confidence REAL,
  accepted INTEGER NOT NULL,
  confirmation_required INTEGER NOT NULL,
  release_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intents_state ON intents(state);
CREATE INDEX IF NOT EXISTS idx_release_candidates_intent ON release_candidates(intent_id);
```

Do not replace the Phase 1 `candidates` table. Phase 2 intent state is additive.

## Command Surface

Add commands without removing Phase 1 commands:

```bash
uv run seed-agent intent-add "download Inception 2010 1080p" --config config/example.yaml
uv run seed-agent intent-inbox --config config/example.yaml
uv run seed-agent intent-search <intent-id> --config config/example.yaml
uv run seed-agent intent-rank <intent-id> --config config/example.yaml
uv run seed-agent intent-review --config config/example.yaml
uv run seed-agent intent-confirm <intent-id> <release-id> --config config/example.yaml
uv run seed-agent intent-reject <intent-id> --config config/example.yaml
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml
uv run seed-agent intent-run-once --config config/example.yaml
uv run seed-agent intent-run-once --config config/example.yaml --execute
```

Mutating downloader behavior remains dry-run by default. `intent-confirm` changes local state only. `intent-enqueue --execute` is the first command that may touch qBittorrent.

## Implementation Tasks

### Task 1: Phase 2 Config And Models

Files:

- Modify `src/seed_agent/config.py`.
- Modify `src/seed_agent/models.py` or add `src/seed_agent/intent/models.py`.
- Modify `config/example.yaml`.
- Add `tests/test_intent_models.py`.
- Add `tests/test_phase2_config.py`.

Steps:

1. Add strict Pydantic config models for `intent`, `search`, and `sources`.
2. Add `ResourceIntent`, `ReleaseCandidate`, `RankedRelease`, and related enums.
3. Validate thresholds, ambiguity gap, source refs, and search limits.
4. Verify unknown config keys fail.

Gate:

```bash
uv run pytest tests/test_intent_models.py tests/test_phase2_config.py -q
uv run ruff check .
```

### Task 2: Intent State Store

Files:

- Modify `src/seed_agent/state.py`.
- Add `tests/test_intent_state.py`.

Steps:

1. Add additive `intents` and `release_candidates` tables.
2. Add methods to upsert/list intents by state.
3. Add methods to save ranked release candidates.
4. Preserve existing Phase 1 candidate state behavior.

Gate:

```bash
uv run pytest tests/test_state.py tests/test_intent_state.py -q
```

### Task 3: Deterministic Intent Normalization

Files:

- Add `src/seed_agent/intent/parse.py`.
- Add `tests/test_intent_parse.py`.

Steps:

1. Parse simple text like `Inception 2010 1080p`, `show S01E02 2160p`, and Chinese/English mixed titles without external services.
2. Extract title, year, season, episode, resolution, quality hints, and language hints where obvious.
3. Keep raw text and parser uncertainty in metadata.
4. Return `UNKNOWN` kind when classification is unclear.

Gate:

```bash
uv run pytest tests/test_intent_parse.py -q
```

### Task 4: Local Intent Ingestion

Files:

- Add `src/seed_agent/actions/intent.py`.
- Modify `src/seed_agent/cli.py`.
- Add `tests/test_intent_actions.py`.
- Add `tests/test_intent_cli.py`.

Steps:

1. Implement `intent-add` to normalize one CLI string and write an intent row.
2. Implement `intent-inbox` for JSONL inbox ingestion from `intent.inbox_ref`.
3. Make ingestion idempotent by stable source event id when present.
4. Print redacted JSON summaries.

Gate:

```bash
uv run pytest tests/test_intent_actions.py tests/test_intent_cli.py -q
```

### Task 5: Search Provider Interface

Files:

- Add `src/seed_agent/search/base.py`.
- Add `src/seed_agent/search/rss.py`.
- Add `tests/test_search_base.py`.
- Add `tests/test_search_rss.py`.

Steps:

1. Define a `SearchProvider` protocol returning `ReleaseCandidate` records.
2. Add an RSS-backed provider that reuses `fetch_rss_candidates` and filters by normalized title tokens.
3. Preserve source/download URL redaction behavior.
4. Keep live tracker calls mockable and opt-in.

Gate:

```bash
uv run pytest tests/test_search_base.py tests/test_search_rss.py -q
```

### Task 6: Ranking Policy

Files:

- Add `src/seed_agent/policies/intent_ranking.py`.
- Add `tests/test_intent_ranking.py`.

Steps:

1. Rank by title match, year/season/episode fit, resolution preference, site priority, discount, seeders/leechers, size, and H&R risk.
2. Produce reason and risk lists.
3. Mark confirmation required when confidence is below threshold or top candidates are too close.
4. Reject candidates that fail hard constraints.

Gate:

```bash
uv run pytest tests/test_intent_ranking.py -q
```

### Task 7: Intent Search And Review Commands

Files:

- Extend `src/seed_agent/actions/intent.py`.
- Extend `src/seed_agent/cli.py`.
- Add `tests/test_intent_search_cli.py`.

Steps:

1. Implement `intent-search <intent-id>`.
2. Implement `intent-rank <intent-id>`.
3. Implement `intent-review` to show pending confirmations and top candidates.
4. Store release candidates and ranked scores in SQLite.

Gate:

```bash
uv run pytest tests/test_intent_search_cli.py -q
```

### Task 8: Confirmation State

Files:

- Extend `src/seed_agent/actions/intent.py`.
- Extend `src/seed_agent/cli.py`.
- Add `tests/test_intent_confirmation.py`.

Steps:

1. Implement `intent-confirm <intent-id> <release-id>`.
2. Implement `intent-reject <intent-id>`.
3. Ensure confirmation changes only local state and never touches qBittorrent.
4. Audit confirmation decisions.

Gate:

```bash
uv run pytest tests/test_intent_confirmation.py -q
```

### Task 9: Intent Enqueue

Files:

- Extend `src/seed_agent/actions/intent.py`.
- Extend `src/seed_agent/cli.py`.
- Add `tests/test_intent_enqueue.py`.

Steps:

1. Convert a confirmed or high-confidence `RankedRelease` into the existing qB enqueue path.
2. Require `--execute` for qB mutation.
3. Preserve audit redaction and batch failure handling.
4. Link the intent row to the selected release and qB torrent hash when available.

Gate:

```bash
uv run pytest tests/test_intent_enqueue.py tests/test_run_once.py tests/test_cli.py -q
```

### Task 10: Integration Source Skeletons

Files:

- Add `src/seed_agent/sources/file_inbox.py`.
- Add `src/seed_agent/sources/telegram.py`.
- Add `src/seed_agent/sources/wechat_bridge.py`.
- Add `src/seed_agent/sources/douban.py`.
- Add `tests/test_intent_sources.py`.

Steps:

1. Implement file inbox fully.
2. Add Telegram and WeChat bridge payload parsers without live network loops.
3. Add Douban wanted-list import from a local JSON export shape.
4. Keep source secrets and tokens outside version control.

Gate:

```bash
uv run pytest tests/test_intent_sources.py -q
```

### Task 11: Combined Intent Run-Once

Files:

- Extend `src/seed_agent/actions/intent.py`.
- Extend `src/seed_agent/cli.py`.
- Add `tests/test_intent_run_once.py`.

Steps:

1. Implement `intent-run-once` as ingest -> search -> rank -> maybe enqueue.
2. Enqueue automatically only when confidence is above `auto_enqueue_threshold` and ambiguity is below the configured gap.
3. Otherwise move the intent to `CONFIRMATION_REQUIRED`.
4. Make the whole command dry-run by default.

Gate:

```bash
uv run pytest tests/test_intent_run_once.py -q
uv run seed-agent intent-run-once --config config/example.yaml
```

### Task 12: Docs And Handoff

Files:

- Modify `README.md`.
- Add `docs/operations/phase-2-usage.md`.
- Modify `docs/operations/session-handoff.md`.

Steps:

1. Document local inbox, intent commands, confirmation flow, and execute flow.
2. Document runtime state and audit inspection commands.
3. Keep integration setup as local/off-by-default.
4. Update handoff with Phase 2 status and next safe verification command.

Gate:

```bash
rg "intent-run-once|confirmation_required|local/inbox|phase-2" README.md docs/operations
uv run pytest -q
uv run ruff check .
```

## Final Verification

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run seed-agent --help
uv run seed-agent intent-add "Inception 2010 1080p" --config config/example.yaml
uv run seed-agent intent-run-once --config config/example.yaml
```

Expected:

- All tests pass.
- Ruff passes.
- Help lists the Phase 2 intent commands.
- Intent commands produce redacted JSON.
- Dry-run intent flow does not mutate qBittorrent.

## Review Checklist

Before considering Phase 2 done:

- No command touches qBittorrent without `--execute`.
- Confirmation state is explicit and test-covered.
- Ambiguous candidates never auto-enqueue.
- Secret refs, raw cookies, bot tokens, and tracker passkeys never appear in CLI output or audit logs.
- Failed partial batches write audit/state for completed work before returning non-zero.
- Phase 1 commands still pass their existing tests.
- Integration source code can parse local fixtures without requiring live external services.

## Suggested Branch

Use a new worktree/branch:

```bash
git worktree add /Users/lancer/.config/superpowers/worktrees/seed-agent/phase-2-resource-intent-loop -b feat/phase-2-resource-intent-loop
```

Keep Phase 2 commits task-sized and review each mutation boundary before moving to the next task.
