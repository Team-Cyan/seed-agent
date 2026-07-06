# Unraid DockerMan Install

This guide is for operators who want `seed-agent` to look and behave like a
normal Unraid-managed Docker app instead of a standalone Compose project.

## Why This Path Exists

Docker Compose is enough to run `seed-agent`, but Unraid DockerMan gives you:

- template-backed edit and rebuild actions,
- container lifecycle controls in the main Docker page,
- remote image update checks when the image is published to GHCR,
- simpler operator ergonomics for a long-lived NAS service.

## Published Image

DockerMan should point to:

- `ghcr.io/team-cyan/seed-agent:latest`

That image is published from GitHub Actions on pushes to `main`.

## Single-Root Host Layout

The Unraid template mounts one host folder:

- `/mnt/user/appdata/seed-agent` -> `/workspace`

Inside that root, keep:

```text
/mnt/user/appdata/seed-agent/
└── runtime/
    ├── config/
    │   └── config.yaml
    ├── local/
    │   ├── inbox/
    │   └── secrets/
    ├── .seed-agent/
    └── state/
```

That keeps the Unraid mapping surface simple while preserving the repository's
expected config-relative secret paths.

## Secrets Stay On Disk

The DockerMan template intentionally does not expose M-Team or qBittorrent
credentials as template text fields.

Keep secrets as local files under:

- `/mnt/user/appdata/seed-agent/runtime/local/secrets/mteam-api-key.txt`
- `/mnt/user/appdata/seed-agent/runtime/local/secrets/qbittorrent.yaml`

That keeps credentials out of the template XML and still lets `schedule-run`
load them through the checked-in config file at:

- `/workspace/runtime/config/config.yaml`

In practice, DockerMan only needs to mount `/mnt/user/appdata/seed-agent` to
`/workspace`; the runtime config then resolves `local/secrets/...` relative to
that mounted root.

## Template

Copy or import:

- `deploy/unraid/seed-agent.xml`

Recommended user-visible defaults:

- `Network=bridge`
- restart policy `unless-stopped`
- `SEED_AGENT_MODE=schedule-run`
- `SEED_AGENT_CONFIG=/workspace/runtime/config/config.yaml`
- `SEED_AGENT_HEARTBEAT_FILE=/workspace/runtime/state/schedule-heartbeat.json`
- `SEED_AGENT_EXECUTE=true`
- `SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true`
- `SEED_AGENT_INTENT_EXECUTE=false`
- `SEED_AGENT_STARTUP_STATUS=true`
- `SEED_AGENT_WEB_ENABLED=true`
- `SEED_AGENT_WEB_HOST=0.0.0.0`
- `SEED_AGENT_WEB_PORT=8765`
- WebUI host port `8765` mapped to container port `8765/tcp`

## Runtime Visibility

Every non-healthcheck container start prints one redacted `runtime-status` JSON
line to Docker logs before the long-running command starts. Use that line to
confirm:

- the installed `seed-agent` version,
- the actual config path Docker passed to the container,
- whether the config file loaded successfully,
- whether the qB credential file path exists,
- state, audit, and heartbeat file paths.

You can also run the same check from the Unraid Docker console:

```sh
seed-agent runtime-status \
  --config /workspace/runtime/config/config.yaml \
  --heartbeat-file /workspace/runtime/state/schedule-heartbeat.json \
  --max-staleness-minutes 90
```

For heartbeat-only checks, run:

```sh
seed-agent healthcheck \
  --config /workspace/runtime/config/config.yaml \
  --heartbeat-file /workspace/runtime/state/schedule-heartbeat.json \
  --max-staleness-minutes 90
```

The heartbeat JSON now includes the package version and config path in addition
to cycle, interval, execution mode, accepted/enqueued counts, and the last error
field. If Unraid's log viewer looks empty, inspect the mounted file directly:

```sh
cat /workspace/runtime/state/schedule-heartbeat.json
```

## Updating The Container

After the container is installed through DockerMan, keep it managed by the
Unraid template system.

Use the Docker page's normal **Update** / **Apply Update** action when GHCR has
a new `latest` image. Do not update a template-managed install with manual
`docker rm && docker run` commands. Manual recreation can detach the running
container from DockerMan's template metadata, which makes the Unraid UI treat it
like a third-party container and can hide normal up-to-date status.

If a command-line repair is needed on the Unraid host, prefer DockerMan's own
template rebuild/update script so the recreated container keeps the managed
label:

```sh
/usr/local/emhttp/plugins/dynamix.docker.manager/scripts/update_container seed-agent
```

Afterward, confirm the container still has:

```text
net.unraid.docker.managed=dockerman
```

Also confirm Docker kept the scheduler restart policy:

```sh
docker inspect seed-agent --format '{{json .HostConfig.RestartPolicy}}'
```

Expected:

```json
{"Name":"unless-stopped","MaximumRetryCount":0}
```

If repeated `latest` pulls leave old `ghcr.io/team-cyan/seed-agent:<none>`
images behind, remove only unused seed-agent dangling images. Avoid broad
`docker system prune` operations on a NAS host.

## WebUI Button

`seed-agent` exposes the settings Web UI on container port `8765` when
`SEED_AGENT_WEB_ENABLED=true`.

The DockerMan template maps host port `8765` to container port `8765/tcp` and
sets:

```text
SEED_AGENT_WEB_ENABLED=true
SEED_AGENT_WEB_HOST=0.0.0.0
SEED_AGENT_WEB_PORT=8765
WebUI=http://[IP]:[PORT:8765]
```

If the Web UI is exposed beyond a trusted local network, add
`SEED_AGENT_WEB_TOKEN` to the DockerMan template. Non-empty values require
write/search/enqueue `POST` calls to include `X-Seed-Agent-Token` or
`Authorization: Bearer`.

If the Docker page shows the container as healthy but the WebUI button opens an
unavailable page, check these live facts before changing application config:

```sh
docker port seed-agent
docker inspect seed-agent --format '{{json .NetworkSettings.Ports}}'
docker inspect seed-agent --format '{{index .Config.Labels "net.unraid.docker.webui"}}'
docker exec seed-agent seed-agent --version
docker exec seed-agent seed-agent runtime-status \
  --config /workspace/runtime/config/config.yaml \
  --heartbeat-file /workspace/runtime/state/schedule-heartbeat.json \
  --max-staleness-minutes 90
```

A healthy scheduler with `ports={}` means the image updated, but the installed
DockerMan template did not publish the Web UI port. Update the template from
`deploy/unraid/seed-agent.xml`, then use Unraid's **Apply Update** action or:

```sh
/usr/local/emhttp/plugins/dynamix.docker.manager/scripts/update_container seed-agent
```

After the rebuild, `docker port seed-agent` should show a `8765/tcp` mapping.
