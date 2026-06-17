# Docker Compose User Guide

This guide is the normal installation path for `seed-agent`.

It assumes:

- you want a long-lived Docker container,
- the container runs `schedule-run`,
- config and state live on mounted storage,
- qBittorrent and tracker secrets stay in local files.

## 1. Prepare The Workspace

Recommended host layout:

```text
seed-agent/
├── config/
│   ├── config.yaml
│   └── example.yaml
├── local/
│   ├── inbox/
│   └── secrets/
│       ├── qbittorrent.yaml
│       └── mt.api-key
├── .seed-agent/
└── state/
```

Create missing directories:

```bash
mkdir -p config local/secrets local/inbox .seed-agent state
```

## 2. Prepare `config/config.yaml`

Start from the example:

```bash
cp config/example.yaml config/config.yaml
```

Then update at least:

- `tracker_sites:`
- `pt_filters:`
- `download_client:`
- `seed_cleanup:`

For unattended NAS use, strongly consider:

- `pt_filters.min_left_time_minutes`
- `pt_filters.max_active_downloads`
- `pt_filters.max_total_amount_left_gb`
- `download_client.category_policies`
- `download_client.budget_pools`
- `seed_cleanup.delete_after_no_upload_hours`

`pt_filters.max_total_amount_left_gb` is an active download liability cap. The
agent ignores zero-progress stopped download placeholders for that cap and uses
score order when deciding which accepted candidates should start versus be added
paused.

## 3. Prepare Local Secrets

### qBittorrent

Create `local/secrets/qbittorrent.yaml`:

```yaml
base_url: http://qb.local:8080
username: your-user
password: your-password
```

### M-Team API Key

If your config uses `api_key_ref: local/secrets/mt.api-key`, create:

```text
your-mteam-api-key
```

Do not commit either secret file.

## 4. Review Compose Settings

Use [deploy/docker-compose.example.yml](../../deploy/docker-compose.example.yml)
as the starting point.

If you want an explicit image override file, start with:

```bash
cp deploy/seed-agent.env.example deploy/seed-agent.env
```

Default model:

- one container,
- `schedule-run`,
- execute mode enabled,
- heartbeat file enabled,
- Docker healthcheck enabled.

Main env vars:

- `SEED_AGENT_MODE=schedule-run`
- `SEED_AGENT_CONFIG=/app/config/config.yaml`
- `SEED_AGENT_EXECUTE=true`
- `SEED_AGENT_INTERVAL_MINUTES=30`
- `SEED_AGENT_MIN_FREE_WINDOW_MINUTES=180`
- `SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true`
- `SEED_AGENT_HEARTBEAT_FILE=/state/schedule-heartbeat.json`
- `SEED_AGENT_MAX_STALENESS_MINUTES=90`
- `SEED_AGENT_PRUNE=true`
- `SEED_AGENT_INTENT_EXECUTE=false`
- `SEED_AGENT_STARTUP_STATUS=true`
- `SEED_AGENT_WEB_ENABLED=true`
- `SEED_AGENT_WEB_HOST=0.0.0.0`
- `SEED_AGENT_WEB_PORT=8765`

The example publishes host port `8765` to the container's Web UI port. That lets
one long-running container serve the settings UI while `schedule-run` remains
the foreground process.

The Compose file reads `SEED_AGENT_IMAGE` from `deploy/seed-agent.env`, so you can switch
between GHCR, Docker Hub, and a private registry without editing YAML.

## 5. Start The App

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml up -d
```

If you want to build from local source:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml up -d --build
```

That source build uses `uv.lock` inside the Docker image, so the container path
matches the repository's pinned Python dependency set.

## 6. Verify The Deployment

Check container status:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml ps
```

Watch logs:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml logs -f seed-agent
```

The first log line should be a redacted `runtime-status` JSON payload. It shows
the installed version, config path, state/audit paths, heartbeat path, and
whether configured credential files are present.

You can print the same status on demand:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml exec seed-agent \
  seed-agent runtime-status \
    --config /app/config/config.yaml \
    --heartbeat-file /state/schedule-heartbeat.json
```

Check runtime files:

```bash
ls -lah .seed-agent
ls -lah state
```

Expected files:

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`
- `state/schedule-heartbeat.json`

It is normal for the very first scheduler cycle to take a couple of minutes
before the first heartbeat appears. The example Compose file leaves a four-minute
`start_period` for that reason.

Check the Web UI:

```bash
open http://127.0.0.1:8765
```

If the page does not load, first confirm that the container has a published port:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml port seed-agent 8765
```

## 7. Common Operations

Restart:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml restart seed-agent
```

Stop:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml down
```

Rebuild after local changes:

```bash
docker compose --env-file deploy/seed-agent.env -f deploy/docker-compose.example.yml up -d --build
```

## 8. Safety Notes

- Keep `seed` as the mutable category unless you intentionally widen the policy.
- Keep `movie` and `tv` add-only if they represent library content.
- Do not place secrets inside `config/config.yaml`.
- Treat cleanup thresholds as high-risk changes.
- Prefer making the app more conservative before making it more aggressive.

## 9. Troubleshooting

If the container is unhealthy:

1. check Compose logs,
2. run `seed-agent runtime-status` inside the container,
3. inspect `state/schedule-heartbeat.json`,
4. confirm `config/config.yaml` is mounted where `SEED_AGENT_CONFIG` expects,
5. confirm `local/secrets/` paths match the refs used in YAML,
6. confirm qB Web API credentials work outside the container.

If the app starts but discovers nothing:

1. verify the site is enabled,
2. verify API key or cookie paths,
3. check free-window filters and discovery bounds,
4. review the JSON output from logs before loosening thresholds.
