# Web UI Operator Guide

This guide explains how operators should use the local `seed-agent` Web UI and
when to switch back to the CLI. The Web UI is an operator console for safe
configuration editing, preview/search workflows, status inspection, and
deliberate Want List candidate enqueue. It is not the only control plane, and
the CLI remains the reference surface for scheduled, batch, and high-risk
operations.

## Surfaces

| Surface | Primary use | Risk level | Notes |
| --- | --- | --- | --- |
| Status and health | Read scheduler heartbeat, next-cycle timing, rate-limit history, state summary, budget-pool config, and Want List state. | Read-only plus explicit scheduler controls | The overview owns runtime status and the deliberate actions to trigger one cycle or clear the current M-Team backoff. Trigger requests are accepted only while the existing scheduler is waiting; clearing backoff uses an inline confirmation. |
| Run logs | Filter and search scheduler phase, tracker API, Want List search, audit, and runtime events. | Read-only | Persisted evidence survives process restarts; runtime events use bounded rotation. No Docker socket access is required. Container logs remain available through the host's log viewer. |
| Settings pages | Edit tracker, downloader, scheduler, discovery, cleanup, acquisition, and Want List source settings. | Preview-first config mutation | The Scheduler page is configuration-only. Non-tracker sections show a before/after diff preview and validate the full config before saving. Secret values stay in local secret files or secret refs. |
| Tracker actions | Validate a tracker draft, run site probe, or dry-run a tracker-local discovery preview. | Preview/read-only network access | These actions may call tracker APIs or RSS endpoints, but they must not enqueue to qBittorrent or clean up torrents. |
| Want List refresh | Sync configured Douban/IMDb sources into local intent state. | Local state mutation | It may read public/export source data and update `.seed-agent/state.db`, but it does not contact qBittorrent. |
| Want List search | Refresh configured sources, search/rank candidates for the current filters, and store release candidates. | Preview-first search | It may read runtime config, source state, and tracker/downloader-adjacent metadata needed for ranking. It does not add tasks to qBittorrent. |
| Want List candidate enqueue | Add exactly one selected release candidate through the shared intent enqueue path. | Explicit qB mutation | This is the only current Web UI qB enqueue surface. After reviewing the candidate card, clicking `加入 qB` or `强制加入 qB` immediately executes the add. |

## Optional API Token

By default the Web UI assumes a trusted local bind or LAN-only deployment. If
the Web UI is reachable outside a trusted local network, set
`SEED_AGENT_WEB_TOKEN` on the Web process. When this variable is non-empty,
every Web API `GET` and `POST` except the liveness-only `/api/health` endpoint
must include either:

- `X-Seed-Agent-Token: <token>`
- `Authorization: Bearer <token>`

`/api/health` is deliberately exempt so container health checks do not need to
read or forward the token.

The built-in UI keeps the token control hidden for unprotected deployments. If
the server returns `401 Unauthorized`, the UI reveals the control, asks for the
token, and keeps it in page memory only. It is not written to local storage.
External health checks must also send the token. Do not put it in committed
config files; keep it in local env or the host's secret manager.

`/api/health` is the Web-process health boundary: it verifies a short read-only
SQLite query before evaluating the scheduler heartbeat. A `200` response with
`status: ok` means both the Web process can read current state and the
scheduler heartbeat is fresh; unhealthy states return HTTP `503`.

## Config Concurrency And Secrets

- Config reads return a content revision. Saves must submit that revision; a
  stale browser draft receives `409 Conflict` instead of overwriting a newer
  CLI or Web edit.
- Config API responses redact credentials embedded in URLs and never return
  secret contents.
- Secret refs must resolve to regular files under the runtime
  `local/secrets/` directory. Absolute paths, parent traversal, and symlink
  escapes are rejected.
- Tracker probe and dry-run actions may only use credentials already assigned
  to that saved tracker. Changing a draft URL cannot reuse its cookie against a
  different origin, and the Web UI cannot bind an arbitrary existing secret
  file to another tracker.

## Web UI Vs CLI

Use the Web UI when the work is interactive and narrow:

- reviewing scheduler health, state counts, budget-pool setup, and Want List
  status,
- reviewing and filtering recent durable operational events in Run logs,
- using the overview to trigger one immediate scheduler cycle or clear a
  verified-stale M-Team backoff,
- editing routine config sections and checking the diff before save,
- adjusting Want List source configuration or media-type routing,
- refreshing/searching a small filtered Want List set,
- selecting one reviewed Want List release for qB enqueue.

Use the CLI when the work is batch-oriented, unattended, or high risk:

- starting/stopping the long-running `schedule-run` process or changing
  scheduler flags,
- running PT discovery/enqueue/prune loops,
- checking full JSON payloads for `run-once`, `review`, `daily-report`,
  `strategy-report`, `healthcheck`, or `runtime-status`,
- executing cleanup, especially delete-capable prune actions,
- performing broad operational verification on a Docker or Unraid host,
- diagnosing live downloader state when the Web UI summary is not enough.

When in doubt, start with the Web UI for read-only status and config previews,
then use the CLI for execution or deeper evidence.

## Runtime Logging

`SEED_AGENT_LOG_LEVEL` controls runtime verbosity (default `INFO`). Set it on
the Web and scheduler processes, then restart those processes to apply it.
`DEBUG` is intended for temporary diagnosis, not normal operation:

- `DEBUG`: successful HTTP reads, safe M-Team search payloads and page counts,
  provider steps, candidate filter/score reasons, subject classification, and
  downloader request status.
- `INFO`: lifecycle and phase boundaries, successful Web writes, search result
  summaries, and enqueue/cleanup decision counts (with an explicit `execute` flag).
- `WARNING`: rejected requests, configuration conflicts, partial source failure,
  tracker backoff/API rejection, or unavailable runtime log storage.
- `ERROR`: failed operations, search/persistence failures, server/database errors,
  and downloader mutation failures. A zero-result search alone is not an error.

Events are redacted JSON lines on stderr; CLI stdout remains machine-readable.
Web and scheduler also write `.seed-agent/runtime-events.jsonl`, capped at
2 MiB with three backups (about 8 MiB total). Files are owner-only and rotate
safely across both processes. This is a bounded diagnostic timeline, not a
replacement for durable SQLite history or the decision audit log.

Run logs merges runtime events with existing scheduler/tracker/Want/audit
evidence. Filter by `runtime` and level, search an intent ID or `request_id`,
and expand event details. `X-Request-ID` in a Web response identifies its nested
work. Successful reads log only at DEBUG to keep normal polling quiet.
`/api/logs?limit=500` is the maximum; each source uses bounded tail reads.
Historical events predating this release cannot be reconstructed.

For a missing Want candidate, open that Want's candidate dialog and expand
Search history (latest 50 per item, independent of the global timeline):

1. Check query paths and provider result counts.
2. Compare returned, ranked, and accepted counts plus `kind`, `media_type`, and
   `series_search_mode`. Returned > 0 but ranked = 0 points to eligibility
   filtering; ranked > 0 but accepted = 0 points to ranking thresholds.
3. Check Run logs for failures/backoff/rejected requests. Failed batches do not
   create successful search-history rows or partially replace candidates.

## Want List Workflow

The Want List page has separate refresh, search, review, and enqueue steps:

1. Refresh syncs configured Douban/IMDb sources into local intent state.
2. Search refreshes sources, searches configured providers for the filtered
   wants, ranks releases, and stores release candidates for review.
3. Opening a Want List row reads stored candidates and shows matching releases
   first, with lower-match releases still visible for operator override.
4. Clicking a candidate's enqueue button immediately performs the qB action.
   Matching candidates use `加入 qB`; lower-match candidates use
   `强制加入 qB`.

Refresh and search are preview-first, not qB mutation actions. They may still do
real work:

- read the active runtime config file,
- read and write `.seed-agent/state.db` intent and release-candidate rows,
- read configured Douban/IMDb public or export sources,
- call configured tracker search APIs such as M-Team API search,
- inspect enough runtime/downloader-derived context to rank candidates or apply
  enqueue planning constraints.

The boundary is qBittorrent mutation: refresh and search do not add torrents to
qBittorrent. Candidate-level enqueue is an explicit execute action; CLI
commands still require explicit execute mode.

## Runtime Provenance

If the Web UI looks wrong, first identify which runtime files it is reading. The
status and config APIs expose paths such as:

- `config_path`: the config file used by the Web UI process,
- `state_path`: the SQLite state database backing status and Want List rows,
- `heartbeat_file`: the scheduler heartbeat inspected by health status.

When the Web UI is enabled, the container health check also calls the
in-container `/api/health` endpoint. This catches a Web process whose open
SQLite/WAL descriptors have become stale even while the separate scheduler
process continues to update its heartbeat.

The CLI `runtime-status` command gives a fuller provenance snapshot:

```bash
uv run seed-agent runtime-status \
  --config config/config.yaml \
  --heartbeat-file state/schedule-heartbeat.json
```

On Unraid, run the same command inside the container with the deployed paths:

```bash
docker exec seed-agent seed-agent runtime-status \
  --config /workspace/runtime/config/config.yaml \
  --heartbeat-file /workspace/runtime/state/schedule-heartbeat.json \
  --max-staleness-minutes 90
```

Use this provenance before changing config. It helps distinguish these common
cases:

- the browser is connected to the right image but the wrong config file,
- the Web UI is reading an empty or cold `.seed-agent/state.db`,
- the scheduler heartbeat belongs to another mounted workspace,
- a Docker/Unraid template has not published the Web UI port even though the
  scheduler is healthy.

## Operational Rules

- Keep qBittorrent mutations deliberate. Web UI search does not approve enqueue
  or cleanup, while a candidate enqueue button is an immediate qB mutation.
- Use the overview's immediate-run action instead of restarting the container.
  It signals the current scheduler, rejects overlapping cycles, and resets the
  next interval from the manual cycle start.
- Clear backoff only after a bounded tracker probe confirms the service is
  responding again. The 5-second M-Team request pacer and scheduled backfill
  API budget remain active.
- Treat cleanup as CLI-owned until a dedicated Web UI cleanup surface exists.
- Check `runtime-status` when Web UI state disagrees with logs, qB, or expected
  mounted files.
- Keep secrets in `local/secrets/*`; do not paste raw tokens into shared docs or
  committed config.
- Set `SEED_AGENT_WEB_TOKEN` before exposing the Web UI through a reverse proxy
  or any non-trusted network.
- For unattended acquisition, prefer scheduler config plus CLI flags. The Web UI
  is best for inspection, config edits, and explicit single-candidate decisions.
