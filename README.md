# seed-agent

`seed-agent` is a Docker-first self-hosted PT automation app for NAS and homelab deployments.

It is designed to run as a long-lived container, keep its state on mounted
storage, and manage PT discovery plus qBittorrent actions through versioned
config files and local secret files.

Current image:

- `ghcr.io/team-cyan/seed-agent:latest`
- versioned releases use tags such as `ghcr.io/team-cyan/seed-agent:0.1.2`

The primary operator experience is:

- prepare `config.yaml`,
- prepare local secrets,
- launch with Docker Compose,
- inspect logs, heartbeat, and audit output,
- adjust strategy without rebuilding the image.

This project is not a dashboard, a media server, or a general Python utility
that happens to ship a container. Docker deployment is the main product shape.

## What It Does

Today `seed-agent` focuses on two loops:

1. PT upload strategy loop
   - discover candidate torrents,
   - score them,
   - enqueue accepted candidates to qBittorrent,
   - review managed torrents,
   - prune cold managed torrents,
   - keep an audit trail for downloader mutations.

2. Resource intent loop
   - ingest user intents,
   - search releases,
   - rank and confirm choices,
   - enqueue through the same downloader path.

The default deployment shape for self-hosted use is a Docker container running
`schedule-run`.

## Quick Start

1. Copy the example config:

```bash
cp config/example.yaml config/config.yaml
```

2. Create local secret files:

- `local/secrets/qbittorrent.yaml`
- `local/secrets/mt.api-key` if you use M-Team API discovery

3. Review and adjust:

- tracker/site config under `sites:`
- strategy thresholds under `discovery:` and `scoring:`
- qB category ownership under `downloader.category_policies:`
- cleanup thresholds under `cleanup:`

4. Start the container:

```bash
cp deploy/seed-agent.env.example deploy/seed-agent.env
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml up -d
```

5. Verify:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml logs -f seed-agent
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml ps
```

State and audit files are written under `.seed-agent/` in the mounted workspace.

## Recommended Docker Layout

Mount these paths into the container:

- `./config:/app/config:ro`
- `./local:/app/local:ro`
- `./.seed-agent:/app/.seed-agent`
- `./state:/state`

That layout gives you:

- checked-in config under `config/`,
- gitignored secrets under `local/secrets/`,
- durable runtime state in `.seed-agent/`,
- scheduler heartbeat under `state/`.

## Docker Compose Install

The included Compose example runs the app as a long-lived scheduler container.

Key environment variables:

- `SEED_AGENT_MODE=schedule-run`
- `SEED_AGENT_CONFIG=/app/config/config.yaml`
- `SEED_AGENT_EXECUTE=true`
- `SEED_AGENT_INTERVAL_MINUTES=30`
- `SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180`
- `SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true`
- `SEED_AGENT_HEARTBEAT_FILE=/state/schedule-heartbeat.json`
- `SEED_AGENT_MAX_STALENESS_MINUTES=90`
- `SEED_AGENT_PRUNE=true`

See:

- [Docker Compose User Guide](docs/operations/docker-compose-user-guide.md)
- [Docker Scheduling](docs/operations/docker-scheduling.md)
- [Compose Example](deploy/docker-compose.example.yml)
- [Unraid Template](deploy/unraid/seed-agent.xml)
- [Unraid DockerMan Install](docs/operations/unraid-dockerman.md)

If you want to switch from GHCR to Docker Hub later, set `SEED_AGENT_IMAGE` in
`deploy/seed-agent.env` instead of editing the Compose file.

## Configuration And Secrets

Keep strategy config and secrets separate:

- safe to version:
  - `config/config.yaml`
  - `config/example.yaml`
- local only:
  - `local/secrets/qbittorrent.yaml`
  - `local/secrets/mt.api-key`
  - optional site cookies

For M-Team, the preferred authenticated path is API-driven discovery with
`api_key_ref`. RSS remains in the repo as a fallback path for other sites and
compatibility flows.

## Runtime Safety Defaults

Recommended unattended protections:

- conservative `discovery.min_left_time_minutes`
- `SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180`
- `SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true`
- `discovery.max_active_downloads`
- `discovery.max_total_amount_left_gb`

These guards help avoid:

- enqueueing candidates with too little remaining free time,
- enqueueing when the downloader is already congested,
- starting new work while a shared budget pool is already saturated.

## qB Category Model

`seed-agent` treats category policy as a safety boundary:

- mutable categories such as `seed` may be paused or deleted by policy,
- add-only categories such as `movie` and `tv` may receive new torrents but are
  not auto-deleted,
- shared budget pools can force paused enqueue behavior without widening cleanup.

## Documentation

- [Docs Index](docs/README.md)
- [Roadmap](docs/roadmap.md)
- [Docker Compose User Guide](docs/operations/docker-compose-user-guide.md)
- [Docker Scheduling](docs/operations/docker-scheduling.md)
- [Docker Image Publishing](docs/operations/docker-image-publishing.md)
- [Release Process](docs/operations/release-process.md)
- [Unraid DockerMan Install](docs/operations/unraid-dockerman.md)
- [Phase 1 Usage](docs/operations/phase-1-usage.md)
- [Phase 2 Usage](docs/operations/phase-2-usage.md)
- [Compose Example](deploy/docker-compose.example.yml)
- [Kubernetes CronJob Example](deploy/kubernetes/cronjob.example.yaml)

## Image Sources

The project is structured to work with:

- local image builds,
- GitHub Container Registry,
- Docker Hub style publishing.

For Unraid users who want native DockerMan actions such as edit, update checks,
and template-driven rebuilds, the repository now includes a first-party Unraid
template and a GitHub Actions workflow that publishes `ghcr.io/team-cyan/seed-agent`.

On `main`, GHCR receives `latest`, `main`, and `sha-<short-sha>` tags. On
release tags such as `v0.1.2`, GHCR also receives `v0.1.2`, `0.1.2`, and `0.1`.

The image is intentionally generic:

- no baked-in config,
- no baked-in secrets,
- runtime behavior comes from env vars, mounted config, and mounted state.

See [Docker Image Publishing](docs/operations/docker-image-publishing.md).

## Local Development

Local Python development still exists for contributors and debugging:

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
```

But that is a contributor workflow, not the primary operator installation path.

## CLI Reference

Mutating commands are dry-run first unless `--execute` is set.

Examples:

```bash
uv run seed-agent run-once --config config/config.yaml
uv run seed-agent run-once --config config/config.yaml --execute
uv run seed-agent schedule-run --config config/config.yaml --execute --interval-minutes 30
uv run seed-agent healthcheck --config config/config.yaml
```

## Runtime Files

Mounted runtime files:

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`
- `state/schedule-heartbeat.json`

Local inbox files live under `local/inbox/`.

## References

This project has learned from several open-source projects and public
references, but it does not aim to copy their full product shape.

- [`pt-tools`](https://github.com/sunerpy/pt-tools)
- [`PT-Plugin-Plus`](https://github.com/pt-plugins/PT-Plugin-Plus)
- [`MoviePilot`](https://github.com/jxxghp/MoviePilot)
- [`nas-tools`](https://github.com/NAStool/nas-tools)
- [`vertex`](https://github.com/vertex-app/vertex)
- [`Auto_Bangumi`](https://github.com/EstrellaXD/Auto_Bangumi)
- [`ani-rss`](https://github.com/walse0/ani-rss)
- [`bgmi`](https://github.com/BGmi/BGmi)
- [`mteam-active-top-rss`](https://hub.docker.com/r/xiaohaigreen/mteam-active-top-rss)
