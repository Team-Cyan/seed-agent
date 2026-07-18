# Docker Scheduling

This guide covers the recommended server deployment shape for the Phase 1 PT
strategy loop.

## Deployment Modes

`seed-agent` supports two Docker-friendly modes:

1. Long-running scheduler container
   - runs `schedule-run`
   - sleeps between cycles inside the container
   - useful when you want one always-on service

2. Single-run job container
   - runs `run-once --execute`
   - best when your host already has a scheduler such as cron, Unraid User
     Scripts, systemd timers, or Kubernetes CronJobs

For this repository's Docker-first app shape, the normal installation path is
the long-running scheduler container. External schedulers remain supported, but
they are now an alternative deployment mode rather than the main one.

Current project recommendation:

- default to a long-running `schedule-run` container for Docker Compose users,
- use the single-run job shape when your host already has stronger scheduling
  primitives and you want one-shot container execution,
- use a heartbeat file plus `healthcheck` for the long-running shape.

The entrypoint drops root privileges before startup status, Web, scheduler, or
one-off CLI commands run. Set numeric `PUID` and `PGID` to match the owner of
mounted config and state paths. The Compose example also uses a read-only root
filesystem with a dedicated `/tmp` tmpfs; durable writes must stay in mounted
runtime paths. The same privilege transition clears inheritable, ambient, and
bounding Linux capabilities; do not pre-drop `SETUID`/`SETGID`, which are needed
only for that transition. The entrypoint does not recursively change mounted
ownership.

On the reference Unraid deployment, qBittorrent and Plex use `PUID=1000` and
`PGID=100`; the seed-agent DockerMan template uses the same values so mounted
appdata remains writable without running the application as root.

M-Team search, detail, and token requests share a per-process minimum request
interval. `SEED_AGENT_MTEAM_MIN_REQUEST_INTERVAL_SECONDS` defaults to `1.25`;
do not reduce it on unattended deployments without a bounded live probe. The
default adds headroom after production rejected the 51st continuous request at
one-second spacing. Web and scheduler processes use independent limiters.

Scheduled source backfill first pages through M-Team's
`member/getUserTorrentList` endpoint for the account's seeding, leeching, and
stopped incomplete torrents. One batch row refreshes promotion evidence without
a per-torrent detail call. `scheduler.tracker_backfill_max_api_requests`
defaults to `20` and only limits detail/search fallback for qB tasks absent from
that batch snapshot; normal batch pagination does not consume the fallback
budget. A batch miss with tracker evidence refreshed in the previous six hours
also skips fallback, while batch matches continue to refresh every cycle.
Incomplete tasks missing from the batch remain unknown-free cleanup risks during
that cooldown; cached evidence does not make them safe to keep downloading.

Both variables must be configured together. Existing DockerMan installations
that predate these template fields and provide neither variable retain their
legacy container user until the operator adds matching IDs; this avoids making
mounted SQLite and secret files unreadable during an image-only update.

## Free-Window Safety

The main risk with freeleech torrents is not polling frequency by itself. The
risk is enqueueing a torrent when the remaining free window is too short or
unknown.

Recommended protections:

- set `pt_filters.min_left_time_minutes` to a conservative value for your own
  bandwidth and queueing behavior,
- use `--require-known-free-window` for unattended execute runs,
- optionally raise `--min-free-window-minutes` above the config default when you
  want stricter deployment-time policy.

If M-Team does not return a known remaining free window for a candidate,
`--require-known-free-window` rejects that candidate during execute-mode runs.
One important exception now exists: some M-Team API rows represent effectively
permanent FREE torrents by returning `discount=FREE` with an explicit
`discountEndTime=null`. `seed-agent` treats that shape as a known unlimited
free window, so those candidates remain eligible during execute-mode runs.
If you pass these flags during dry-run, the CLI will also preview that same
safety decision in the printed candidate output.

## Docker Image

Build locally:

```bash
docker build -t seed-agent:local .
```

The Dockerfile now installs application dependencies through `uv.lock`, so
source builds no longer rely on an unconstrained `pip install .` path.

Long-running scheduler example:

```bash
docker run --rm \
  -v "$PWD/config:/app/config:ro" \
  -v "$PWD/local:/app/local" \
  -v "$PWD/.seed-agent:/app/.seed-agent" \
  -v "$PWD/state:/state" \
  -e SEED_AGENT_MODE=schedule-run \
  -e SEED_AGENT_CONFIG=/app/config/config.yaml \
  -e SEED_AGENT_EXECUTE=true \
  -e SEED_AGENT_INTERVAL_MINUTES=60 \
  -e SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180 \
  -e SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true \
  -e SEED_AGENT_HEARTBEAT_FILE=/state/schedule-heartbeat.json \
  seed-agent:local
```

Single-run job example:

```bash
docker run --rm \
  -v "$PWD/config:/app/config:ro" \
  -v "$PWD/local:/app/local" \
  -v "$PWD/.seed-agent:/app/.seed-agent" \
  -e SEED_AGENT_MODE=run-once \
  -e SEED_AGENT_CONFIG=/app/config/config.yaml \
  -e SEED_AGENT_EXECUTE=true \
  -e SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180 \
  -e SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true \
  seed-agent:local
```

## Environment Variables

- `SEED_AGENT_MODE`
  - `schedule-run`, `run-once`, `enqueue`, or any other CLI command
- `SEED_AGENT_CONFIG`
  - defaults to `/app/config/config.yaml`
- `SEED_AGENT_EXECUTE`
  - `true` or `false`
- `SEED_AGENT_HEARTBEAT_FILE`
  - optional heartbeat JSON file written by `schedule-run`
- `SEED_AGENT_MAX_STALENESS_MINUTES`
  - used by `healthcheck`
- `SEED_AGENT_MAX_CYCLES`
  - useful for smoke tests or external supervisors
The YAML `scheduler` section is the canonical source for cycle behavior. The
DockerMan template and Compose example do not define scheduler policy
overrides. Legacy explicit environment variables remain compatible, but should
be removed so Web UI saves are authoritative. `SEED_AGENT_EXECUTE` remains an
explicit deployment safety control and is not stored in YAML.

## Healthcheck And Logging

For long-running scheduler containers:

- set `SEED_AGENT_HEARTBEAT_FILE` to a writable persistent path,
- expect the first scheduler cycle to take longer than a healthcheck probe when
  site discovery is slow, so give Compose or your supervisor a few minutes of
  `start_period`,
- run `seed-agent healthcheck --config /app/config/config.yaml --heartbeat-file ...`
  from Docker Compose, Kubernetes, or another supervisor,
- treat JSON stdout as the primary log stream,
- persist `.seed-agent/audit.jsonl` and the heartbeat file if you want postmortem
  visibility after container restarts.

Example manual probe:

```bash
docker run --rm \
  -v "$PWD/config:/app/config:ro" \
  -v "$PWD/state:/state" \
  -e SEED_AGENT_MODE=healthcheck \
  -e SEED_AGENT_CONFIG=/app/config/config.yaml \
  -e SEED_AGENT_HEARTBEAT_FILE=/state/schedule-heartbeat.json \
  -e SEED_AGENT_MAX_STALENESS_MINUTES=90 \
  -e SEED_AGENT_PRUNE=true \
  seed-agent:local
```

First-class examples live in:

- `deploy/docker-compose.example.yml`
- `deploy/kubernetes/cronjob.example.yaml`

## DockerHub Shape

The current image is designed to be DockerHub-friendly:

- one image,
- one entrypoint script,
- environment-variable configuration for the common scheduling cases,
- no baked-in secrets,
- repo-mounted state and secret files.

When publishing to DockerHub, keep the image generic and let the server provide:

- the checked-in config file,
- gitignored secret files,
- persistent `.seed-agent/` state and audit storage.

See also:

- `docs/operations/docker-compose-user-guide.md`
- `docs/operations/docker-image-publishing.md`
