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

For most NAS or homelab deployments, the single-run job shape is safer and
easier to reason about. It gives the host scheduler ownership of timing, retry,
and restart behavior.

## Free-Window Safety

The main risk with freeleech torrents is not polling frequency by itself. The
risk is enqueueing a torrent when the remaining free window is too short or
unknown.

Recommended protections:

- set `discovery.min_left_time_minutes` to a conservative value for your own
  bandwidth and queueing behavior,
- use `--require-known-free-window` for unattended execute runs,
- optionally raise `--min-free-window-minutes` above the config default when you
  want stricter deployment-time policy.

If M-Team does not return a known remaining free window for a candidate,
`--require-known-free-window` rejects that candidate during execute-mode runs.

## Docker Image

Build locally:

```bash
docker build -t seed-agent:local .
```

Long-running scheduler example:

```bash
docker run --rm \
  -v "$PWD/config:/config:ro" \
  -v "$PWD/local:/app/local" \
  -v "$PWD/.seed-agent:/app/.seed-agent" \
  -e SEED_AGENT_MODE=schedule-run \
  -e SEED_AGENT_CONFIG=/config/config.yaml \
  -e SEED_AGENT_EXECUTE=true \
  -e SEED_AGENT_INTERVAL_MINUTES=30 \
  -e SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180 \
  -e SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true \
  seed-agent:local
```

Single-run job example:

```bash
docker run --rm \
  -v "$PWD/config:/config:ro" \
  -v "$PWD/local:/app/local" \
  -v "$PWD/.seed-agent:/app/.seed-agent" \
  -e SEED_AGENT_MODE=run-once \
  -e SEED_AGENT_CONFIG=/config/config.yaml \
  -e SEED_AGENT_EXECUTE=true \
  -e SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180 \
  -e SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true \
  seed-agent:local
```

## Environment Variables

- `SEED_AGENT_MODE`
  - `schedule-run`, `run-once`, `enqueue`, or any other CLI command
- `SEED_AGENT_CONFIG`
  - defaults to `/config/config.yaml`
- `SEED_AGENT_EXECUTE`
  - `true` or `false`
- `SEED_AGENT_INTERVAL_MINUTES`
  - used by `schedule-run`
- `SEED_AGENT_MIN_FREE_WINDOW_MINUTES`
  - optional execute-time free-window safety threshold
- `SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW`
  - `true` or `false`
- `SEED_AGENT_MAX_CYCLES`
  - useful for smoke tests or external supervisors

## DockerHub Shape

The current image is designed to be DockerHub-friendly:

- one image,
- one entrypoint script,
- environment-variable configuration for the common scheduling cases,
- no baked-in secrets,
- repo-mounted state and secret files.

When publishing to DockerHub later, keep the image generic and let the server
provide:

- the checked-in config file,
- gitignored secret files,
- persistent `.seed-agent/` state and audit storage.
