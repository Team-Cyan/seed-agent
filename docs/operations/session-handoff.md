# Session Handoff

This document captures the durable handoff state from the initial `seed-agent` planning session. It is intentionally concise and does not include private keys, tokens, cookies, or PT site credentials.

## Repository State

- Local repository: `/Users/lancer/projects/seed-agent`
- GitHub remote: `git@github.com:Team-Cyan/seed-agent.git`
- Default branch: `main`
- Latest known synchronized commit during setup: `a013fa7 chore: align local and remote histories`

## Durable Knowledge Already Recorded

- `README.md`: project positioning, config-first/no-custom-UI-for-v1 stance, API-ready internal boundary, Phase 1, Phase 2, roadmap, early config shape, and AI operating notes.
- `docs/research/inspiration-pool.md`: inspiration pool from PT and NAS automation projects, including Phase 1, Phase 2, and future ideas.
- `docs/superpowers/specs/2026-04-20-seed-agent-design.md`: full product and architecture spec covering discovery, scoring, qBittorrent execution, lifecycle state, cleanup, audit records, intent sources, roadmap, config design, modules, structured actions, tests, and open decisions.
- `docs/superpowers/plans/2026-04-20-phase-1-pt-upload-loop.md`: executable Phase 1 implementation plan for the PT upload strategy loop, including package bootstrap, config/models, audit, RSS discovery, scoring, SQLite state, qBittorrent executor, safe dry-run actions, cleanup policy, CLI, docs, and verification.

## Core Decisions

- Project name: `seed-agent`.
- Build as a standalone repository, not inside `homelab-agent`.
- Treat the first interface as documentation, configuration, CLI/dry-run output, and audit records rather than a custom UI.
- Keep internal operations API-ready from the start so Telegram, WeChat bridge, Douban, local HTTP API, or optional UI surfaces can be added later without rewriting the policy engine.
- Phase 1 focuses on PT upload strategy: fetch free/hot candidates, score them, enqueue strong candidates, and clean up cold managed torrents.
- Phase 2 focuses on resource intent: accept Telegram, WeChat bridge, and Douban wanted-list intents, search resources, rank candidates, and require confirmation when ambiguity is high.
- qBittorrent is the first downloader implementation, but downloader operations should go through an abstraction to keep Transmission or other clients possible later.
- Cleanup should default to a conservative/balanced mode: pause before delete, delete only managed torrents, protect torrents with meaningful recent upload, and keep explainable audit records.
- Phase 1 implementation will use SQLite for local lifecycle state at `.seed-agent/state.db` and append-only JSONL audit records at `.seed-agent/audit.jsonl`.
- Mutating downloader commands should default to dry-run. The operator must pass `--execute` before qBittorrent add, pause, or delete calls happen.
- Local qBittorrent credentials should live in `local/secrets/qbittorrent.yaml`, which must stay gitignored.

## Current Implementation Handoff

- Current plan: `docs/superpowers/plans/2026-04-20-phase-1-pt-upload-loop.md`
- Recommended next mode: execute the plan task-by-task with `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
- First implementation task: bootstrap the Python package with `pyproject.toml`, `.gitignore`, `src/seed_agent/__init__.py`, and `tests/test_package_import.py`.
- First verification commands after bootstrap: `uv sync --dev`, `uv run pytest tests/test_package_import.py -q`, and `uv run ruff check .`.
- Keep Phase 2 intent routing, Telegram, WeChat bridge, Douban wanted-list sync, and optional UI outside the Phase 1 implementation path.

## Inspiration Sources

Initial source projects discussed as inspiration:

- `https://github.com/appotry/PTtool`
- `https://github.com/jxxghp/MoviePilot`
- `https://github.com/wangyan/nas-tools`
- `https://github.com/vertex-app/vertex`
- `https://github.com/sunerpy/pt-tools`
- `https://github.com/appotry/IYUUAutoReseed`
- `https://github.com/appotry/PT-Plugin-Plus`
- Additional inspiration named during brainstorming: `flexget-nexusphp`, `qb-rss-manager`, `Auto_Bangumi`, `ani-rss`, and `bgmi`.

The strongest Phase 1 inspirations were `pt-tools` and `flexget-nexusphp`; the strongest Phase 2 inspirations were `PT-Plugin-Plus`, `Auto_Bangumi`, `ani-rss`, and `bgmi`; later roadmap inspiration includes `qb-rss-manager`, `IYUUAutoReseed`, MoviePilot, vertex, and nas-tools.

## Git And SSH Setup Notes

GitHub SSH was fixed on this machine during setup:

- The local Ed25519 key was added to `ssh-agent` and macOS Keychain.
- `~/.ssh/config` was adjusted so `github.com` uses `ssh.github.com` on port `443`.
- Authentication was verified as GitHub user `CNlancer` with `ssh -T git@github.com`.
- `git push -u origin main` succeeded after local and remote histories were aligned.

If GitHub SSH fails after a reboot, first try:

```bash
ssh -T git@github.com
```

If the key is not loaded, this machine should normally recover through Keychain automatically. A manual fallback is:

```bash
ssh-add --apple-load-keychain
```

## What Is Not Preserved Here

- The full raw chat transcript is not copied into the repository.
- Full raw command outputs are not copied, except for the operational summary above.
- Full upstream README contents or source-code excerpts are not vendored into this repository.

This is intentional. The repo preserves the decisions, architecture, inspiration map, and operational handoff needed to resume work without depending on the original conversation.
