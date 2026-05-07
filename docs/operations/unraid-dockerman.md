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

## Template

Copy or import:

- `deploy/unraid/seed-agent.xml`

Recommended user-visible defaults:

- `Network=bridge`
- `SEED_AGENT_MODE=schedule-run`
- `SEED_AGENT_CONFIG=/workspace/runtime/config/config.yaml`
- `SEED_AGENT_HEARTBEAT_FILE=/workspace/runtime/state/schedule-heartbeat.json`
- `SEED_AGENT_EXECUTE=true`
- `SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW=true`

## WebUI Button

`seed-agent` does not expose an HTTP control panel today.

The Unraid template therefore points the WebUI button at the GitHub project
page so the container still has a useful landing target in DockerMan.

If the project later grows a read-only status UI, update the template to point
WebUI at that service instead.
