# seed-agent

`seed-agent` is a Docker-first self-hosted PT automation app for NAS and homelab deployments.

It is designed to run as a long-lived container, keep its state on mounted
storage, and manage PT discovery plus qBittorrent actions through versioned
config files and local secret files.

Current image:

- `ghcr.io/team-cyan/seed-agent:latest`
- versioned releases use tags such as `ghcr.io/team-cyan/seed-agent:0.2.0`

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

## Current Support Matrix

| Area | Status | Notes |
| --- | --- | --- |
| Docker deployment | Supported | Compose, Unraid template, Kubernetes CronJob example, heartbeat, and healthcheck are present. |
| qBittorrent downloader | Supported | The only implemented downloader; category policy is the cleanup authority boundary, and Want List media types can be routed to configured qB categories. |
| Transmission downloader | Planned | Candidate for the first second-downloader adapter. |
| NexusPHP-style RSS | Supported | RSS remains useful for fallback flows and non-M-Team sites. |
| M-Team RSS | Supported | Available as fallback and compatibility path. |
| M-Team API discovery/search | Supported | Preferred authenticated path when `api_key_ref` is configured, including intent search with Douban/IMDb ID lookup, broad keyword fallback, M-Team tag capture, and execute-time deferred download-token resolution. |
| Resource intent loop | Supported | Local intent add, inbox/Douban/IMDb Want List ingestion, search, ranking, confirmation, and enqueue are implemented. |
| Want List | Supported | Web UI page shows canonical Douban/IMDb wants with source/type filters, mobile cards, added time, merged source evidence, release/search status, and candidate review with explicit qB actions. |
| Web Settings UI | WIP | Local configuration UI exists for grouped safe settings edits with schema validation, diff previews, per-section YAML editing, visual downloader category/budget routing, sticky save actions, mobile navigation, read-only status, and Want List. |
| Read-only dashboard/API | Partial | State summary, heartbeat health, budget pools, and Want List are exposed; richer audit/cleanup dashboards remain planned. |

## Roadmap Snapshot

The immediate credibility pass is in place: license clarity, pull-request CI,
Docker smoke testing, README visibility, clear source-adapter status, and the
first Web UI Want List. The next product work stays grounded in qB live state,
conservative enqueue/prune decisions, and better reporting before wider
dashboard or multi-downloader expansion.

Medium-term work should validate extensibility with Transmission and a second
non-M-Team API provider, then turn tracker/account signals, downloader telemetry,
historical outcomes, and user confirmations into real scoring feedback.

## Source Adapter Status

| Source | Status | Current boundary |
| --- | --- | --- |
| file inbox | Wired | JSONL inbox ingestion is the supported local source path. |
| Telegram | Parser skeleton | Parses Telegram update payloads; no bot loop or hosted receiver is shipped. |
| WeChat bridge | Parser skeleton | Parses bridge payloads; no personal-account automation is shipped. |
| Douban wanted | Wired | Reads one or more public Douban wanted pages or local wanted-list export JSON files. |
| IMDb watchlist/list | Wired | Reads IMDb watchlist/list CSV exports and best-effort public page data when reachable. |
| subscription | Planned | Config shape exists for future rules, but no subscription runner is shipped. |

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
- Want List routing under `downloader.media_category_map:`
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
open http://127.0.0.1:8765
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
- `SEED_AGENT_WEB_ENABLED=true`
- `SEED_AGENT_WEB_HOST=0.0.0.0`
- `SEED_AGENT_WEB_PORT=8765`

The example publishes `8765:8765`, so the same container can run the scheduler
and the settings Web UI. Open `http://127.0.0.1:8765` for local
Compose installs, or the DockerMan WebUI button for Unraid installs.

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

For resource intents, `sources.want_lists` can hold multiple Douban users and
IMDb watchlists/lists. Douban source entries use `user_name`; IMDb entries use
`watchlist_url` or a CSV `export_ref`. The intent loop merges repeated wants by
Douban/IMDb IDs, then `search.required_keywords` / `search.preferred_keywords`
describe the desired release shape, such as Remux, 2160p, HDR, or Dolby Vision.
M-Team intent search fetches by Douban/IMDb IDs first and supplements with a
broad title/year keyword query; quality terms are applied during ranking so the
Web UI can show both matching candidates and lower-match fallback releases.
The same source/search boundary is intended to support later movie-list sites,
chat bridges, or API-triggered requests.

For TV or anime intents, `intent.series_search_mode` controls whether episode
requests search/rank full-season packs (`season`, the default) or individual
episodes (`episode`).

The local Web Settings UI keeps one physical config file for Docker/Unraid/CLI
compatibility. Each settings page also exposes the YAML block for its own
top-level section, so operators can edit `search:`, `intent:`, `downloader:`,
and similar blocks directly without splitting the runtime config into multiple
files.

On the downloader page, common qB settings are editable without hand-writing
YAML: category policies, budget pools, and the movie/TV/anime Want List routing
map. The YAML editor remains available for advanced edits and review.

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
- when a qB category is configured as mutable, every existing and future torrent
  in that category is considered managed, regardless of tags,
- add-only categories such as `movie` and `tv` may receive new torrents but are
  not auto-deleted,
- tags are metadata applied to new torrents for audit/search convenience; tags
  alone do not grant cleanup permission outside the configured category,
- shared budget pools can force paused enqueue behavior without widening cleanup.

## Documentation

- [Docs Index](docs/README.md)
- [Architecture And Supported Features](docs/architecture.md)
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
The template runs the scheduler and settings Web UI in one container, publishing
host port `8765` for DockerMan's WebUI button.

On `main`, GHCR receives `latest`, `main`, and `sha-<short-sha>` tags. On
release tags such as `v0.2.0`, GHCR also receives `v0.2.0`, `0.2.0`, and `0.2`.

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
uv run seed-agent web --config config/config.yaml --host 127.0.0.1 --port 8765
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
