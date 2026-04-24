# seed-agent

`seed-agent` is an AI-first PT and downloader operations toolkit for a personal NAS.

The project is not intended to be a dashboard, a media server, or a full MoviePilot-style platform. It is a structured strategy runner that helps an AI agent and a human operator manage PT discovery, qBittorrent tasks, cleanup decisions, and future resource-intent workflows through clear configuration, command-line actions, and auditable records.

## Core Idea

The first interface is documentation plus configuration, not a custom UI.

- Humans describe intent in plain language.
- AI agents read this README and the design docs.
- Strategy parameters live in versioned config files.
- Execution happens through structured actions.
- Every external change is written to an audit log.

The implementation should be API-ready internally, even before a long-running HTTP API exists. Every core operation should accept structured input and return structured output so Telegram, Douban, a future API server, or a lightweight UI can be added later without rewriting the policy engine.

Current RSS adapters:

- `nexusphp`: full RSS candidate parsing with peer stats and size fields.
- `mteam`: RSS list parsing with direct torrent download links and category metadata. The public feed shape does not currently expose peer stats or size, so those candidates are marked as sparse by default. If `api_key_ref` points to an M-Team laboratory access token, `seed-agent` will use `x-api-key` detail enrichment to fill `size`, `seeders`, `leechers`, and `times_completed`. `cookie_ref` remains available as a compatibility fallback for a logged-in browser session.

## Agent Docs

This repository follows the thin-entrypoint pattern described by OpenAI for agent-oriented repos:

- root `AGENTS.md` as the agent entrypoint
- `docs/` as the structured system of record

Recommended AI read order:

1. `AGENTS.md`
2. `docs/roadmap.md`
3. matching `docs/ai/modules/*.md`
4. only then the relevant spec, plan, or handoff note

## Phases

### Phase 1: PT Upload Strategy Loop

Build the smallest useful closed loop:

1. Fetch free and hot candidate torrents from configured PT sites.
2. Score candidates using discount, seeders, leechers, remaining discount time, H&R status, size, and site history.
3. Enqueue high-confidence candidates into qBittorrent with managed categories and tags.
4. Review existing managed torrents for upload performance.
5. Pause or delete cold managed torrents under a balanced safety policy.
6. Write an audit record explaining every enqueue, skip, pause, and delete decision.

Phase 1 should learn from `pt-tools` and `flexget-nexusphp`, but use this project's own models, policies, and audit trail.

### Phase 2: Resource Intent Loop

Expand from "find upload candidates" to "act on user intent":

1. Accept Telegram messages, WeChat bridge events, and Douban wanted-list items.
2. Convert each request into a search intent.
3. Search configured sources and PT sites.
4. Rank candidate releases.
5. Ask for confirmation when multiple reasonable choices exist.
6. Enqueue the selected result through the same downloader abstraction.

Phase 2 should learn from `PT-Plugin-Plus`, `Auto_Bangumi`, `ani-rss`, and `bgmi`.

### Roadmap

Later work can add rule import/export, auto-reseed, local HTTP APIs, richer reports, and optional UI surfaces. These should stay outside the Phase 1 critical path.

## Safety Defaults

Phase 1 uses `balanced` cleanup by default:

- Managed `pt-auto` torrents may be paused or deleted automatically when rules are explicit.
- H&R torrents are protected.
- Manually added torrents are protected.
- Media-library-associated torrents are protected.
- Unknown-origin torrents are never deleted automatically.
- A pause-before-delete delay should be supported before permanent removal.

## Documentation

- [Roadmap](docs/roadmap.md)
- [Inspiration Pool](docs/research/inspiration-pool.md)
- [Seed Agent Design](docs/superpowers/specs/2026-04-20-seed-agent-design.md)
- [M-Team API-Driven Discovery Spec](docs/superpowers/specs/2026-04-24-mteam-api-driven-discovery.md)
- [Phase 1 Usage](docs/operations/phase-1-usage.md)
- [Phase 2 Usage](docs/operations/phase-2-usage.md)
- [Phase 2 Resource Intent Plan](docs/superpowers/plans/2026-04-22-phase-2-resource-intent-loop.md)
- [Session Handoff](docs/operations/session-handoff.md)

## Local Development

Use `uv` for the local development loop:

```bash
uv sync --dev
uv run pytest
uv run ruff check .
```

## Phase 1 CLI

Phase 1 commands default to dry-run for mutating downloader actions. Pass `--execute` only when you are ready for qBittorrent changes to be applied.

Example commands:

```bash
uv run seed-agent discover --config config/example.yaml
uv run seed-agent score --config config/example.yaml
uv run seed-agent run-once --config config/example.yaml
uv run seed-agent run-once --config config/example.yaml --execute
```

## Phase 2 CLI

Phase 2 commands are also dry-run first. `intent-confirm` and `intent-reject` only change local state. `intent-enqueue --execute` and `intent-run-once --execute` are the commands that may touch qBittorrent.

Example commands:

```bash
uv run seed-agent intent-add "download Inception 2010 1080p" --config config/example.yaml
uv run seed-agent intent-inbox --config config/example.yaml
uv run seed-agent intent-search <intent-id> --config config/example.yaml
uv run seed-agent intent-rank <intent-id> --config config/example.yaml
uv run seed-agent intent-review --config config/example.yaml
uv run seed-agent intent-confirm <intent-id> <release-id> --config config/example.yaml
uv run seed-agent intent-reject <intent-id> --config config/example.yaml
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml --execute
uv run seed-agent intent-run-once --config config/example.yaml
uv run seed-agent intent-run-once --config config/example.yaml --execute
```

## Runtime Files

Phase 1 and Phase 2 store local state and audit records in the repository workspace:

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`

Local intent inbox files live under `local/inbox/`. This directory is gitignored except for `.gitkeep`, because inbox exports can contain private media preferences.

## Downloader Credentials

qBittorrent credentials belong in `local/secrets/qbittorrent.yaml`, and that file is gitignored.

## Early Configuration Shape

```yaml
mode: balanced

discovery:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  max_seeders: 80
  allow_hr: false

scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5

downloader:
  type: qbittorrent
  target: unraid-qb
  category: pt-auto
  tags: ["seed-agent", "pt-auto"]

cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24

intent:
  confirmation_threshold: 0.82
  auto_enqueue_threshold: 0.94
  ambiguity_gap: 0.08
  default_resolution: 1080p
  preferred_languages: ["zh", "en"]
  inbox_ref: local/inbox/intents.jsonl

search:
  site_priority:
    demo-free: 10
  max_results_per_site: 20
  prefer_free: true
  reject_hr_by_default: true
```

## AI Operating Notes

When an AI agent works in this repository:

- Prefer editing configuration and docs before adding code.
- Keep credentials in local gitignored files.
- Keep strategy decisions explainable.
- Never delete unmanaged torrents automatically.
- Treat cleanup actions as high-risk unless the torrent is clearly managed by `seed-agent`.
- Preserve a complete audit trail for downloader changes.

## Thanks And References

This project has learned from several open-source projects and public references. `seed-agent` does not aim to clone their product shape, but they have been valuable for patterns, constraints, and troubleshooting clues.

- [`pt-tools`](https://github.com/sunerpy/pt-tools)
- [`PT-Plugin-Plus`](https://github.com/pt-plugins/PT-Plugin-Plus)
- [`MoviePilot`](https://github.com/jxxghp/MoviePilot)
- [`nas-tools`](https://github.com/NAStool/nas-tools)
- [`vertex`](https://github.com/vertex-app/vertex)
- [`Auto_Bangumi`](https://github.com/EstrellaXD/Auto_Bangumi)
- [`ani-rss`](https://github.com/walse0/ani-rss)
- [`bgmi`](https://github.com/BGmi/BGmi)
- [`mteam-active-top-rss`](https://hub.docker.com/r/xiaohaigreen/mteam-active-top-rss)

For AI-session-specific notes on what each reference is useful for, see `docs/ai/reference-repos.md`.
