# qB Live-State Evidence And Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist enqueue-time candidate evidence, expose joined qB runtime reports, enrich cleanup previews, and put live-state enqueue planning v2 on the roadmap.

**Architecture:** Extend `StateStore` candidate rows with optional snapshot fields and SQLite migrations, then teach CLI report helpers to join candidate snapshot rows with qB runtime summaries. Cleanup behavior stays conservative; the first change is richer preview evidence rather than broader mutation authority.

**Tech Stack:** Python 3.14, SQLite, Pydantic models, Typer CLI JSON payloads, pytest, ruff.

---

## File Structure

- Modify `src/seed_agent/state.py`: add candidate snapshot columns, migrations, and read/write support.
- Modify `src/seed_agent/cli.py`: persist snapshot fields and expose joined evidence in `review`, `daily-report`, and `prune` preview.
- Modify `tests/test_state.py`: cover snapshot persistence and migration.
- Modify `tests/test_cli.py`: cover joined report evidence and prune preview evidence.
- Modify `docs/roadmap.md`: add live-state enqueue headroom planning v2 as a later follow-up.
- Modify `docs/ai/modules/state-audit.md`, `docs/ai/modules/downloader-qb.md`, and `docs/ai/modules/cleanup.md`: document the evidence/report contract.

### Task 1: Candidate Snapshot Persistence

**Files:**
- Modify: `src/seed_agent/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Add failing state tests**

Add tests that call `StateStore.upsert_candidate()` with `size_bytes`, `seeders`, `leechers`, `discount`, `left_time_minutes`, and `score_reasons`, then assert `get_candidate()` and `list_by_torrent_hash()` return those fields. Add a migration test by creating an old `candidates` table without those columns and constructing `StateStore`.

- [ ] **Step 2: Run state tests and observe failure**

Run:

```bash
uv run pytest -q tests/test_state.py -k "candidate_snapshot or migrates_candidate_snapshot"
```

Expected: FAIL because `upsert_candidate()` does not accept or persist the new fields.

- [ ] **Step 3: Implement candidate snapshot columns**

Update `StateStore.upsert_candidate()` with optional keyword-only arguments:

- `size_bytes: int | None | object = _UNSET`
- `seeders: int | None | object = _UNSET`
- `leechers: int | None | object = _UNSET`
- `discount: str | None | object = _UNSET`
- `left_time_minutes: int | None | object = _UNSET`
- `score_reasons: list[str] | None | object = _UNSET`

Persist `score_reasons` as JSON text and preserve existing values when a field is `_UNSET`.

- [ ] **Step 4: Add SQLite migration**

Extend candidate table initialization and migration to add:

- `size_bytes INTEGER`
- `seeders INTEGER`
- `leechers INTEGER`
- `discount TEXT`
- `left_time_minutes INTEGER`
- `score_reasons TEXT`

- [ ] **Step 5: Run state tests**

Run:

```bash
uv run pytest -q tests/test_state.py
```

Expected: PASS.

### Task 2: Persist Enqueue-Time Evidence

**Files:**
- Modify: `src/seed_agent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI test for stored candidate snapshots**

Add or extend a `run-once` test so discovered/scored candidates are persisted with seeders, leechers, discount, left-time, size, and score reasons. Use `StateStore(_state_path(config)).get_candidate(candidate_id)` after the command.

- [ ] **Step 2: Run targeted test and observe failure**

Run:

```bash
uv run pytest -q tests/test_cli.py -k "candidate_snapshot"
```

Expected: FAIL because CLI persistence does not pass snapshot fields to `StateStore`.

- [ ] **Step 3: Add CLI helper for candidate snapshot kwargs**

Implement `_candidate_snapshot_kwargs(candidate, score_reasons=None)` in `src/seed_agent/cli.py` and use it in discovered, scored, enqueue, and live qB backfill persistence paths where candidate data is available.

- [ ] **Step 4: Run targeted CLI test**

Run:

```bash
uv run pytest -q tests/test_cli.py -k "candidate_snapshot"
```

Expected: PASS.

### Task 3: Joined Evidence In Review And Daily Report

**Files:**
- Modify: `src/seed_agent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing report tests**

Add tests that seed candidate rows linked to a qB hash and assert `review` and `daily-report` managed torrent summaries contain a nested `candidate_evidence` object with candidate state, score, seeders, leechers, discount, left-time, free-window expiry, score reasons, first seen, and updated time.

- [ ] **Step 2: Run report tests and observe failure**

Run:

```bash
uv run pytest -q tests/test_cli.py -k "candidate_evidence"
```

Expected: FAIL because managed torrent summaries do not join candidate rows.

- [ ] **Step 3: Implement joined evidence helper**

Add `_candidate_evidence_summary(store, torrent_hash)` and pass `store` into `_managed_torrent_summary()` from `review` and `daily-report`. Include runtime `ratio`, `completed_at`, and `no_upload_since_at` in the managed torrent summary.

- [ ] **Step 4: Run report tests**

Run:

```bash
uv run pytest -q tests/test_cli.py -k "candidate_evidence"
```

Expected: PASS.

### Task 4: Cleanup Preview Evidence

**Files:**
- Modify: `src/seed_agent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing prune preview test**

Add a prune dry-run test that links a candidate row to a qB torrent and asserts each preview item includes `candidate_evidence`, qB runtime fields, `ratio`, `amount_left_gb`, `no_upload_since_at`, and `recent_upload_gb`.

- [ ] **Step 2: Run prune preview test and observe failure**

Run:

```bash
uv run pytest -q tests/test_cli.py -k "prune_preview_evidence"
```

Expected: FAIL because prune preview has only partial runtime and candidate fields.

- [ ] **Step 3: Enrich prune preview**

Reuse the joined evidence helper in `_prune_preview()` and include cleanup-specific runtime evidence without changing mutation authority.

- [ ] **Step 4: Run prune preview test**

Run:

```bash
uv run pytest -q tests/test_cli.py -k "prune_preview_evidence"
```

Expected: PASS.

### Task 5: Roadmap And Module Docs

**Files:**
- Modify: `docs/roadmap.md`
- Modify: `docs/ai/modules/state-audit.md`
- Modify: `docs/ai/modules/downloader-qb.md`
- Modify: `docs/ai/modules/cleanup.md`

- [ ] **Step 1: Update docs**

Document that C and B are now implemented through candidate snapshots, joined report evidence, and enriched prune previews. Add A as a later roadmap item: live-state enqueue headroom planning v2 depends on joined evidence proving which qB signals predict good enqueue outcomes.

- [ ] **Step 2: Review docs diff**

Run:

```bash
git diff -- docs/roadmap.md docs/ai/modules/state-audit.md docs/ai/modules/downloader-qb.md docs/ai/modules/cleanup.md
```

Expected: docs reflect implemented C/B and later A without claiming aggressive enqueue automation is complete.

### Task 6: Full Verification And Commit

**Files:**
- All changed files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_state.py tests/test_cli.py
```

Expected: PASS.

- [ ] **Step 2: Run full suite and lint**

Run:

```bash
uv run pytest -q
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Check version policy**

Run:

```bash
sed -n '1,120p' docs/operations/release-process.md
cat VERSION
```

Expected: decide whether this is a feature or codefix. Because it adds report evidence and conservative cleanup visibility, bump patch if it is intended for deployment.

- [ ] **Step 4: Commit**

Run:

```bash
git add src/seed_agent/state.py src/seed_agent/cli.py tests/test_state.py tests/test_cli.py docs/roadmap.md docs/ai/modules/state-audit.md docs/ai/modules/downloader-qb.md docs/ai/modules/cleanup.md
git commit -m "feat: add qb live-state evidence reports"
```

Expected: commit succeeds without staging unrelated `.agents` or agent-routing changes.
