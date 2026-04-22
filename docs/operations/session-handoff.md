# Session Handoff

This document captures the durable handoff state from the initial `seed-agent` planning session. It is intentionally concise and does not include private keys, tokens, cookies, or PT site credentials.

## Repository State

- Local repository: `/Users/lancer/projects/seed-agent`
- Implementation worktree: `/Users/lancer/.config/superpowers/worktrees/seed-agent/phase-1-pt-upload-loop`
- Implementation branch: `feat/phase-1-pt-upload-loop`
- GitHub remote: `git@github.com:Team-Cyan/seed-agent.git`
- Default branch: `main`
- Latest known synchronized commit during setup: `a013fa7 chore: align local and remote histories`

## Durable Knowledge Already Recorded

- `README.md`: project positioning, config-first/no-custom-UI-for-v1 stance, API-ready internal boundary, Phase 1, Phase 2, roadmap, early config shape, and AI operating notes.
- `docs/research/inspiration-pool.md`: inspiration pool from PT and NAS automation projects, including Phase 1, Phase 2, and future ideas.
- `docs/superpowers/specs/2026-04-20-seed-agent-design.md`: full product and architecture spec covering discovery, scoring, qBittorrent execution, lifecycle state, cleanup, audit records, intent sources, roadmap, config design, modules, structured actions, tests, and open decisions.
- `docs/superpowers/plans/2026-04-20-phase-1-pt-upload-loop.md`: executable Phase 1 implementation plan for the PT upload strategy loop, including package bootstrap, config/models, audit, RSS discovery, scoring, SQLite state, qBittorrent executor, safe dry-run actions, cleanup policy, CLI, docs, and verification.
- `docs/superpowers/plans/2026-04-22-phase-2-resource-intent-loop.md`: executable Phase 2 implementation plan for resource intents, search, ranking, confirmation, and enqueue reuse.
- `docs/operations/phase-1-usage.md`: operator-facing Phase 1 usage guide for config setup, dry-run review, execution, and audit inspection.
- `docs/operations/phase-2-usage.md`: operator-facing Phase 2 usage guide for local inbox setup, intent commands, confirmation, enqueue, run-once, audit, and integration source boundaries.

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

- Current plan: `docs/superpowers/plans/2026-04-20-phase-1-pt-upload-loop.md`.
- Current implementation branch: `feat/phase-2-resource-intent-loop`.
- Current implementation worktree: `/Users/lancer/.config/superpowers/worktrees/seed-agent/phase-2-resource-intent-loop`.
- Latest Phase 1 safety baseline before Phase 2 planning: `970b49d fix: preserve audit state during batch failures`.
- Current Phase 2 plan: `docs/superpowers/plans/2026-04-22-phase-2-resource-intent-loop.md`.
- Phase 1 is implemented as a CLI-first Python package under `src/seed_agent/`.
- The implemented Phase 1 command surface is `discover`, `score`, `enqueue`, `review`, `prune`, `daily-report`, and `run-once`.
- The implemented Phase 2 intent command surface is `intent-add`, `intent-inbox`, `intent-search`, `intent-rank`, `intent-review`, `intent-confirm`, `intent-reject`, `intent-enqueue`, and `intent-run-once`.
- Mutating downloader operations still default to dry-run. Use `--execute` only after reviewing printed decisions and audit output.
- First safe verification command: `uv run seed-agent run-once --config config/example.yaml`.
- First execute command after review: `uv run seed-agent run-once --config config/example.yaml --execute`.
- Full local verification commands: `uv run pytest -q`, `uv run ruff check .`, and `uv run seed-agent --help`.
- Runtime state remains local to the active workspace at `.seed-agent/state.db`; audit records remain at `.seed-agent/audit.jsonl`.
- qBittorrent credentials remain external to git in `local/secrets/qbittorrent.yaml`.
- Known non-blocking warning: pytest currently emits `pytest_asyncio` loop-scope deprecation warnings under the local Python toolchain.
- Keep Phase 2 intent routing, Telegram, WeChat bridge, Douban wanted-list sync, and optional UI outside the Phase 1 implementation path.

## Phase 1 Implementation Summary

The branch includes:

- Strict Pydantic configuration and domain models.
- RSS discovery for NexusPHP-style feeds.
- Candidate scoring for free/hot upload strategy decisions.
- Redacted JSONL audit logging.
- SQLite lifecycle state with monotonic candidate state preservation.
- qBittorrent Web API support for add, inspect, pause/stop, and delete.
- Conservative cleanup policy that protects unmanaged, H&R, manual, and media-library torrents.
- CLI dry-run and execute paths for discovery, scoring, enqueue, review, pruning, daily reporting, and the combined `run-once` loop.

Important safety behavior preserved in the latest implementation:

- `run-once --execute` records accepted enqueue decisions as `ENQUEUED` even when qBittorrent returns success without an info hash.
- Later dry-runs do not downgrade candidates that already reached `ENQUEUED`, `PAUSED`, or `DELETED`.
- `prune --execute` writes known torrent hashes back to the local state database as `PAUSED` or `DELETED`.
- qBittorrent torrent rows infer cleanup protection metadata conservatively from tags and save paths.
- Dry-run prune does not build a live downloader, call qBittorrent, or update lifecycle state.

## Phase 1 Review Notes

Review performed before Phase 2 planning:

- `uv run pytest -q` passed with 104 tests.
- `uv run ruff check .` passed.
- `uv run seed-agent --help` loaded all Phase 1 commands.
- `uv run seed-agent run-once --config config/example.yaml` completed as a dry-run smoke.
- One Phase 1 state durability issue was fixed: repeated same-state writes now preserve existing score and torrent hash when the incoming update does not provide replacement values.

Recommended next branch:

- `feat/phase-2-resource-intent-loop`
- Suggested worktree: `/Users/lancer/.config/superpowers/worktrees/seed-agent/phase-2-resource-intent-loop`

## Phase 2 Implementation Handoff

Phase 2 has started on:

- Branch: `feat/phase-2-resource-intent-loop`
- Worktree: `/Users/lancer/.config/superpowers/worktrees/seed-agent/phase-2-resource-intent-loop`

Completed Phase 2 slices:

- Task 1: Phase 2 intent/release/ranking models and strict config sections.
- Task 2: Additive SQLite state tables and store methods for intents and ranked releases.
- Task 3: Deterministic resource-intent parser for CLI/file/source events.
- Task 4: Local intent ingestion actions and CLI commands, including `intent-add` and `intent-inbox`.
- Task 5: Search provider protocol and RSS-backed intent search provider.
- Task 6: Explainable intent ranking policy with reasons, risks, ambiguity detection, and confirmation gating.
- Task 7: Intent search/rank/review actions and CLI commands, with ranked release candidate persistence and redacted output.
- Task 8: Local confirmation and rejection commands with selected release persistence and audit records.
- Task 9: Intent enqueue command that reuses the existing qB enqueue path and only mutates qBittorrent with explicit `--execute`.
- Task 10: Source adapter skeletons for file inbox, Telegram payloads, WeChat bridge payloads, and local Douban wanted-list exports.
- Task 11: Combined `intent-run-once` command for inbox ingest, search, rank, and dry-run/execute enqueue decisions.
- Task 12: README and Phase 2 operator documentation.

Current Phase 2 commits:

- `6118231 feat: add phase two intent models and config`
- `1f3ecbd feat: add phase two intent state store`
- `350f1c7 feat: add deterministic intent parser`
- `617b556 feat: add local intent ingestion cli`
- `de1523c feat: add rss-backed intent search provider`
- `48bb8c5 feat: add explainable intent ranking`
- `cd93eea feat: add intent search review commands`
- `62cc979 feat: add intent confirmation commands`
- `9e3b186 feat: add intent enqueue command`
- `bb1e02b feat: add intent source adapter skeletons`
- `115e824 feat: add intent run once command`

Latest verification:

- `uv run pytest -q` passed with 160 tests.
- `uv run ruff check .` passed.
- `uv run seed-agent --help` shows `intent-add`, `intent-inbox`, `intent-search`, `intent-rank`, `intent-review`, `intent-confirm`, `intent-reject`, `intent-enqueue`, and `intent-run-once`.
- `uv run seed-agent intent-add "Inception 2010 1080p" --config config/example.yaml` writes a local normalized intent without downloader mutation.
- `uv run seed-agent intent-run-once --config config/example.yaml` is an empty dry-run when the configured inbox is absent.
- Docs gate: `rg "intent-run-once|confirmation_required|local/inbox|phase-2" README.md docs/operations`.
- Focused CLI verification: `uv run pytest tests/test_intent_cli.py tests/test_intent_search_cli.py -q`.
- Focused confirmation verification: `uv run pytest tests/test_intent_confirmation.py tests/test_intent_cli.py -q`.
- Focused enqueue verification: `uv run pytest tests/test_intent_enqueue.py tests/test_intent_cli.py tests/test_cli.py -q`.
- Focused source verification: `uv run pytest tests/test_intent_sources.py tests/test_intent_actions.py tests/test_intent_cli.py -q`.
- Focused run-once verification: `uv run pytest tests/test_intent_run_once.py tests/test_run_once.py tests/test_cli.py tests/test_intent_cli.py -q`.

Recommended next task:

- Review Phase 2 end-to-end, then decide whether to merge, polish docs further, or start a Phase 3 branch for long-running integration loops.

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
