# Apple Container Local Debugging

Use this workflow on the Mac mini when a change needs container-level validation
before live Unraid checks.

## Runtime Layout

The local mirror should stay under gitignored paths:

- `local/runtime/container-unraid/runtime/config/config.yaml`
- `local/runtime/container-unraid/runtime/local/secrets/`
- `local/runtime/container-unraid/runtime/.seed-agent/`
- `local/runtime/container-unraid/runtime/state/`

Keep secret files mode `600` and the secrets directory mode `700`.

## Build

```sh
container build -t seed-agent:local .
```

## Web-Only Smoke

Use Web mode first. It validates config, mounts, static assets, state access, and
ops endpoints without starting the scheduler loop.

```sh
container run --name seed-agent-web --detach --rm \
  --publish 8876:8765/tcp \
  --env TZ=Asia/Shanghai \
  --env SEED_AGENT_MODE=web \
  --env SEED_AGENT_CONFIG=/workspace/runtime/config/config.yaml \
  --env SEED_AGENT_WEB_HOST=0.0.0.0 \
  --env SEED_AGENT_WEB_PORT=8765 \
  --volume "$PWD/local/runtime/container-unraid:/workspace" \
  seed-agent:local
```

If `http://127.0.0.1:8876` resets connections, use the container IP from
`container list --all`:

```sh
curl -fsS "http://<container-ip>:8765/api/health"
curl -fsS "http://<container-ip>:8765/api/ops"
```

## Dry-Run Scheduler Smoke

Run this only when a scheduler, provider, downloader, or runtime evidence change
needs full-cycle validation. It may contact configured qBittorrent and trackers
even when `SEED_AGENT_EXECUTE=false`.

```sh
container run --name seed-agent-local --detach --rm \
  --env TZ=Asia/Shanghai \
  --env SEED_AGENT_MODE=schedule-run \
  --env SEED_AGENT_CONFIG=/workspace/runtime/config/config.yaml \
  --env SEED_AGENT_EXECUTE=false \
  --env SEED_AGENT_INTENT_EXECUTE=false \
  --env SEED_AGENT_WEB_ENABLED=true \
  --env SEED_AGENT_WEB_HOST=0.0.0.0 \
  --env SEED_AGENT_WEB_PORT=8765 \
  --env SEED_AGENT_HEARTBEAT_FILE=/workspace/runtime/state/schedule-heartbeat.json \
  --volume "$PWD/local/runtime/container-unraid:/workspace" \
  seed-agent:local
```

Stop the scheduler smoke after the first cycle unless intentionally testing
daemon behavior:

```sh
container stop seed-agent-local
```
