# Want List Search Workflow Review And Repair Plan

Status: implemented and reviewed locally; the user authorized commit and push
on 2026-10-08. Live deployment remains pending separate authorization.

## Scope And Evidence

Review source ingestion, scheduled/Web/CLI search, M-Team identity queries,
ranking, atomic candidate persistence, and explicit/scheduled enqueue. PT upload
discovery and cleanup policy remain separate.

Reviewed checkout: version `0.24.1`. Existing unrelated documentation changes
were preserved. Read-only application API evidence on 2026-10-07 shows:

- Dear You / 给阿嬷的情书 had zero saved results from the Web search on August 31.
- The October 7 Web search returned 48 releases via `douban_id`, including
  M-Team torrent `1266040`; none was accepted and all had `weak title match`.
- Recent scheduler cycles continued running. Short network backoffs exist, but
  cannot establish the cause of the entire historical search gap.
- Earlier search rows lack provider diagnostics; they cannot establish why the
  August search returned zero. The current queue defect was reproduced locally.

All review reproductions used disposable SQLite databases, fixture providers,
and, for enqueue, a fake downloader. No real downloader mutations occurred.
The focused existing test selection passed: 46 tests, 152 deselected. These
tests do not cover the defects below.

## Findings

| ID | Priority | Finding | Evidence and impact |
| --- | --- | --- | --- |
| F1 | P1 | Previously searched Wants leave the scheduled queue permanently | `actions/intent.py:469,710` selects only `normalized`; `state.py:3092` turns zero results into `confirmation_required`. Repeated source ingestion preserves that state. This also excludes Wants with existing candidates, and automatic enqueue consideration is limited to the current search batch. |
| F2 | P1 | Failed or unavailable search can become successful zero results | `search/mteam.py:105` swallows non-retriable identifier errors; `actions/intent.py:518` accepts an empty provider list. Both paths can replace existing candidates with an empty snapshot and write `status=searched`. Reproduced with a stored candidate, no providers, and all identifier queries rejected. |
| F3 | P1 | Enqueue and search do not consistently protect an active enqueue claim | `state.py:1800` permits a claim on a rejected Want; `actions/intent.py:317` rejects without coordinating with a claim; claim completion overwrites rejection. Rejecting during deferred URL resolution still produced one fake add and final `enqueued` state. `save_want_search_batch` also replaced candidates while an enqueue claim was active. |
| F4 | P2 | Exact work identity is ignored during ranking | `policies/intent_ranking.py:90` scores only the main release title. Matching external IDs and a Chinese tracker subtitle did not remove `weak title match` from an English release title in the reproduction. Native Douban-first search itself already works. |
| F5 | P2 | Review state cannot reflect improved results | `state.py:2307,3054` applies monotonic lifecycle ordering to search decisions. After zero results, a new accepted candidate requiring no confirmation still left the Want in `confirmation_required`. |
| F6 | P2 | Search entry points have different terminal and history behavior | Web eligibility in `web/app.py:1566` permits rejected/failed Wants, although atomic persistence skips them. Standalone CLI `search_intent` can clear a rejected Want's candidates without adding search history. It also returns a searched state inconsistent with the persisted terminal state. |
| F7 | P2 | UI cannot explain search freshness or absence | `web/app.py:1920` maps every zero-candidate nonterminal Want to `not_found`, including never searched or previously failed cases. The list lacks last search outcome, successful search time, and next eligible search time. |

## Intended Contract

### Lifecycle And Search Progress

- Keep source identity/evidence, lifecycle state, search progress, candidate
  preferences, and downloader safety decisions distinct.
- Search eligible Wants in `normalized`, `searched`, and
  `confirmation_required`. Exclude `enqueued`, `rejected`, `viewed`, selected
  releases, and active enqueue claims at selection and commit time.
- Retain the existing treatment of legacy `failed` as protected until an
  explicit recovery transition is defined. New transient search failures must
  be recorded as search outcomes, not permanent lifecycle failures.
- Initial Wants are eligible immediately. Previously searched active Wants
  become due at the next configured daily boundary; `every_cycle` refreshes
  them once per cycle. Manual search bypasses cadence, but respects terminal
  guards and tracker backoff.
- Source refresh must not reset search progress or terminal decisions.
- Successful new results can transition `confirmation_required` back to
  `searched`. Terminal lifecycle protection remains binding.
- A locally ready Want blocked by runtime capacity must be reconsidered when
  capacity becomes available, without requiring a new source event. Keep this
  decision separate from whether tracker search is due.

### Search Outcomes And Identity

- Only a fully successful, authoritative search replaces the candidate
  snapshot. A genuine successful empty result may clear it.
- Missing providers, rejected requests, partial provider/query failure,
  rate limits, and network errors are distinct outcomes. Preserve the last
  successful snapshot and persist redacted failure/skip evidence.
- Preserve atomic batch writes. On batch abort, write failure evidence
  separately without claiming successful candidate replacement.
- Keep Douban URL first, IMDb URL supplementation within the existing budget,
  and title/year search only when external IDs are absent. Keep `mode` omitted
  for identifier queries. No frontend JWT or browser-login dependency.
- Normalize compact IDs and canonical URLs at a shared comparison boundary.
  Use a matching candidate ID as identity evidence; conflicting IDs remain a
  risk. Keep per-release query provenance when rows omit IDs, without inventing
  an ID match or changing canonical Want aliases from release metadata.
- A subtitle can provide title corroboration. Year, season/episode, H&R,
  ambiguity, and capacity checks remain independent.
- Identity evidence replaces weak title evidence; it must not simply stack
  extra points on top of a full title match or automatically approve enqueue.

## Implementation Sequence

### 1. Protect State And Unify Search Outcomes

Owners: `actions/intent.py`, `state.py`, `web/app.py`, `search/mteam.py`, and
relevant provider contracts/tests.

1. Define one terminal/selected/active-claim eligibility policy for search and
   state transitions, shared by Web, CLI, scheduler, and final persistence.
2. Guard claim acquisition against rejection and other protected states.
   Give reject the same active-claim conflict semantics as mark-viewed:
   rejection must not report success while enqueue owns the Want.
3. Protect candidate replacement while enqueue is in flight. Preserve claim
   ownership checks and deliberate handling of expiry before external add.
4. Make all identifier queries failing propagate a structured search failure.
   A partially failed supplement cannot be represented as complete success.
5. Reject missing-provider searches before candidate persistence. Record safe
   diagnostics and preserve old candidates on failed/partial searches.
6. Route standalone CLI search/rank persistence through the same protected
   transaction/history boundary, while retaining its supported command shape.
7. Recompute nonterminal review state from the latest successful ranking;
   avoid global removal of terminal monotonic protections.

Acceptance: failed/no-provider searches retain old evidence; rejected Wants
cannot acquire enqueue ownership; active-claim rejection returns a conflict;
search cannot remove in-flight candidates; all entry points protect terminals.

### 2. Implement Durable, Fair Re-search Scheduling

Owners: `state.py`, `actions/intent.py`, `cli.py`, and state/schema documentation.

1. Persist per-Want search progress: latest attempt/outcome, last successful
   search time, and the scheduling information needed to compute next due time.
   Do not use `intents.updated_at`, which source refresh also changes.
2. Derive historical last-success information from `want_search_runs`. Missing
   history means due; do not rewrite lifecycle states to restart the backlog.
3. Replace the normalized-only selector and pending check with the same due
   query across all eligible nonterminal states.
4. Preserve the current limit of 10 Wants per scheduled batch and the five
   second M-Team pacer. Order by due time/oldest search progress with a stable
   tie breaker so no Want is starved by repeated queue-head searches.
5. Continue draining due Wants on later scheduler cycles after the first batch
   succeeds. A successful first batch must not mark the whole daily backlog
   finished. Persist progress so restarts and backoff resume safely.
6. Reconsider locally ready, capacity-blocked acquisition candidates when intent
   execution is enabled, with fresh gates and the existing enqueue claim. Do
   not broaden automatic execution for operators using dry-run intents.

Acceptance: a zero-result Want is searched on later configured days; more than
10 due Wants all receive a turn; restart/backoff cannot strand the tail; a Want
is not repeatedly searched within the same daily window.

### 3. Carry Identity Evidence Into Ranking

Owners: `search/mteam.py`, `policies/intent_ranking.py`, models/provider metadata,
and ranking/search tests.

1. Preserve safe per-release query provenance and returned external IDs across
   provider deduplication and candidate persistence.
2. Compare normalized external IDs before main-title similarity. Treat explicit
   conflict as a risk and missing evidence as unknown.
3. Use tracker subtitle and trusted title aliases as corroborating fallback
   evidence without additional per-release detail calls.
4. Keep quality preference scoring independent and show the identity reason in
   candidate review. Preserve review for close competing releases.

Acceptance: an English release with the same Douban ID as a Chinese Want is
not labelled a weak title match; a mismatched ID is not accepted because of
title similarity; identity alone does not bypass other requirements.

### 4. Expose Progress And Verify Recovery

Owners: `web/app.py`, Web static UI, operational/module docs, and tests.

1. Expose last successful search, latest attempt outcome, next search eligibility,
   due backlog count, and actionable skip reasons.
2. Distinguish never searched, successfully searched with zero results, failed,
   deferred by backoff, found but requiring review, and downloaded/viewed.
   Preserve existing source/candidate evidence and API compatibility where possible.
3. Update discovery, intent-loop, M-Team, state/audit contracts, schema inventory,
   scheduling/operator guidance, and tracked roadmap status during implementation.
4. After local validation and separately authorized deployment, verify legacy
   zero-result Wants re-enter scheduling naturally. Do not manually reset all
   states or mass enqueue the backlog.

## Verification Plan

- Add regressions for all eight local reproductions: zero-result exclusion,
  sticky review state, no-provider snapshot deletion, rejected identifier
  requests recorded as empty success, CLI terminal snapshot replacement,
  rejected enqueue claims, candidate replacement during enqueue, and ignored
  identity evidence. Add the fake-downloader reject-during-resolution scenario.
- Exercise >10 due Wants over several cycles, manual searches, daily boundary
  changes, continuous source refresh, restart, and rate-limit/network recovery.
- Test selection/commit races, batch rollback, unchanged source aliases,
  terminal lifecycle protection, and local capacity-blocked retry.
- Check compact ID/URL equivalence, missing/conflicting IDs, multiple providers,
  duplicate releases, Chinese/English aliases, and season/episode safety.
- Focused suites: `test_intent_actions.py`, `test_intent_run_once.py`,
  `test_intent_search_cli.py`, `test_intent_ranking.py`, `test_search_mteam.py`,
  `test_search_contracts.py`, `test_state.py`, `test_cli.py`,
  `test_web_settings.py`, and `test_web_static.py`.
- Shared behavior requires `uv run pytest -q`, `uv run ruff check .`,
  `git diff --check`, and `uv run python scripts/check_public_repository.py`.
- Read `docs/operations/release-process.md` before commit/push/release; code
  fixes require a patch bump. Image publication and live deployment remain
  separately authorized steps with backup and migration verification.

## Preserved Boundaries

Keep RSS/Torznab support, M-Team ID-first search, atomic state/audit evidence,
deferred execute-only download tokens, deliberate Web enqueue, scheduler lease,
tracker backoff, category/budget/reserve gates, and current terminal protections.
Do not delete the state database or audit trail, add candidate-derived canonical
aliases, weaken matching thresholds globally, or use private credentials in
fixtures or documentation.

## Implementation Record

- Search progress is derived from existing `want_search_runs`; no schema
  migration or lifecycle-reset script is required. Failed attempts use a
  30-minute local retry floor, while manual requests bypass local cadence.
- Active source-normalized Wants are fairly selected from all three search
  lifecycle states. Explicit CLI search also accepts a structured received
  intent for compatibility; unnormalized received rows are not scheduled.
- Standalone CLI search now ranks through the same atomic history boundary.
  Reranking and local capacity retry do not change tracker-search freshness.
- Search failures retain prior snapshots. Rejection refuses active claims;
  claim acquisition/renewal and candidate replacement protect terminal state.
- Final review reproduced a work-metadata update during provider execution.
  Candidate commits now compare the current matching inputs with the searched
  inputs, and only committed results can reach automatic acquisition. Six
  regressions cover changed kind/year/resolution/IDs, harmless source refresh,
  equivalent canonical IDs, and skipped-commit enqueue protection.
- Query provenance survives M-Team deduplication and supplies retrieval evidence
  when a search row omits external IDs; explicit returned-ID conflicts remain
  risks. Source aliases are not changed by candidate metadata.
- Version metadata is synchronized to `0.24.2`. Regression coverage includes
  multi-day/backlog/restart scheduling, failure preservation, terminal/race
  guards, identity evidence, and local capacity retry. Live acceptance has not
  been performed; the original production history remains intact.

Final local verification on 2026-10-08: `uv run pytest -q` passed all 843 tests;
`uv run ruff check .`, `git diff --check`, public repository hygiene, and
Node syntax validation passed. Seven fixture assertions additionally verified
Want UI status selection, protected actions, progress rendering, and escaping.
