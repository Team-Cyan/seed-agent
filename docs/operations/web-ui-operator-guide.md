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
| Status and health | Read scheduler heartbeat, state summary, budget-pool config, and Want List state. | Read-only | Safe for routine checks. It reads mounted runtime files and may show stale or missing state when the container is pointed at the wrong workspace. |
| Settings pages | Edit tracker, downloader, discovery, cleanup, acquisition, and Want List source settings. | Preview-first config mutation | Non-tracker sections show a before/after diff preview and validate the full config before saving. Secret values stay in local secret files or secret refs. |
| Tracker actions | Validate a tracker draft, run site probe, or dry-run a tracker-local discovery preview. | Preview/read-only network access | These actions may call tracker APIs or RSS endpoints, but they must not enqueue to qBittorrent or clean up torrents. |
| Want List refresh | Sync configured Douban/IMDb sources into local intent state. | Local state mutation | It may read public/export source data and update `.seed-agent/state.db`, but it does not contact qBittorrent. |
| Want List search | Refresh configured sources, search/rank candidates for the current filters, and store release candidates. | Preview-first search | It may read runtime config, source state, and tracker/downloader-adjacent metadata needed for ranking. It does not add tasks to qBittorrent. |
| Want List candidate enqueue | Add exactly one selected release candidate through the shared intent enqueue path. | Explicit qB mutation | This is the only current Web UI qB enqueue surface. Use it only after reviewing the candidate modal preview and in-modal confirmation. |

## Optional API Token

By default the Web UI assumes a trusted local bind or LAN-only deployment. If
the Web UI is reachable outside a trusted local network, set
`SEED_AGENT_WEB_TOKEN` on the Web process. When this variable is non-empty,
every Web API `GET` and `POST` must include either:

- `X-Seed-Agent-Token: <token>`
- `Authorization: Bearer <token>`

The built-in UI asks for the token and keeps it in page memory only. It is not
written to local storage. External health checks must also send the token. Do
not put it in committed config files; keep it in local env or the host's secret
manager.

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
- editing routine config sections and checking the diff before save,
- adjusting Want List source configuration or media-type routing,
- refreshing/searching a small filtered Want List set,
- selecting one reviewed Want List release for qB enqueue.

Use the CLI when the work is batch-oriented, unattended, or high risk:

- running `schedule-run` or changing scheduler flags,
- running PT discovery/enqueue/prune loops,
- checking full JSON payloads for `run-once`, `review`, `daily-report`,
  `strategy-report`, `healthcheck`, or `runtime-status`,
- executing cleanup, especially delete-capable prune actions,
- performing broad operational verification on a Docker or Unraid host,
- diagnosing live downloader state when the Web UI summary is not enough.

When in doubt, start with the Web UI for read-only status and config previews,
then use the CLI for execution or deeper evidence.

## Preview-First Want List Workflow

The Want List page has separate refresh, search, review, and enqueue steps:

1. Refresh syncs configured Douban/IMDb sources into local intent state.
2. Search refreshes sources, searches configured providers for the filtered
   wants, ranks releases, and stores release candidates for review.
3. Opening a Want List row reads stored candidates and shows matching releases
   first, with lower-match releases still visible for operator override.
4. Candidate enqueue first builds an in-modal preview for one release. The
   preview does not contact qBittorrent runtime, update intent state, or write
   audit rows. The in-modal confirmation performs the qB action.

Refresh and search are preview-first, not qB mutation actions. They may still do
real work:

- read the active runtime config file,
- read and write `.seed-agent/state.db` intent and release-candidate rows,
- read configured Douban/IMDb public or export sources,
- call configured tracker search APIs such as M-Team API search,
- inspect enough runtime/downloader-derived context to rank candidates or apply
  enqueue planning constraints.

The boundary is qBittorrent mutation: refresh and search do not add torrents to
qBittorrent. Candidate preview is narrower and remains side-effect-free for qB,
intent state, and audit. qB enqueue only happens through the candidate-level
confirmation action or a CLI command with explicit execute mode.

## Runtime Provenance

If the Web UI looks wrong, first identify which runtime files it is reading. The
status and config APIs expose paths such as:

- `config_path`: the config file used by the Web UI process,
- `state_path`: the SQLite state database backing status and Want List rows,
- `heartbeat_file`: the scheduler heartbeat inspected by health status.

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

- Keep qBittorrent mutations deliberate. Web UI search and candidate preview
  actions are not approval to enqueue or clean up.
- Treat cleanup as CLI-owned until a dedicated Web UI cleanup surface exists.
- Check `runtime-status` when Web UI state disagrees with logs, qB, or expected
  mounted files.
- Keep secrets in `local/secrets/*`; do not paste raw tokens into shared docs or
  committed config.
- Set `SEED_AGENT_WEB_TOKEN` before exposing the Web UI through a reverse proxy
  or any non-trusted network.
- For unattended acquisition, prefer scheduler config plus CLI flags. The Web UI
  is best for inspection, config edits, and explicit single-candidate decisions.
