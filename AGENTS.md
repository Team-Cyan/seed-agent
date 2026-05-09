# AGENTS.md

This file is the repository entrypoint for coding agents.

Keep this file short. Treat it as a table of contents, not the full knowledge base.

## Read Order

For most tasks, read in this order:

1. `docs/ai/project-overview.md`
2. `docs/roadmap.md`
3. The relevant module doc(s) under `docs/ai/modules/`
4. `docs/operations/session-handoff.md` only if the task depends on recent unfinished work
5. A matching spec or plan only when the task changes behavior, architecture, or sequencing

Do not start by reading every spec or every plan.

## Repository Model

- `AGENTS.md`: thin agent entrypoint
- `docs/ai/`: reusable AI knowledge base
- `docs/roadmap.md`: current project state and next work
- `docs/operations/`: operator workflows and handoff notes
- `docs/specs/`: durable design decisions
- `docs/plans/`: implementation sequencing

## Working Rules

- Keep AI-facing docs in English.
- Reply to the human user in Chinese unless they ask for another language.
- Prefer small, well-bounded sessions.
- Work on one module or one roadmap item at a time.
- Update the most relevant module doc and `docs/roadmap.md` when project state materially changes.
- Before commit, push, or release, check the release version policy in
  `docs/operations/release-process.md`. Code fixes and operational fixes bump
  patch by `0.0.1`; new features bump minor by `0.1.0`; docs-only changes may
  keep the version unchanged unless they are part of a deployment release.

## Safety

- Keep secrets in gitignored local files such as `local/secrets/`.
- Do not commit tokens, cookies, passkeys, or downloader credentials.
- qBittorrent mutations must stay dry-run by default unless the user explicitly wants execution.
- Cleanup actions are high risk. Do not widen delete or pause behavior casually.
- Preserve the existing RSS implementation. It remains useful for fallback flows and for other sites.

## Current Project-Specific Notes

- M-Team currently supports RSS parsing, API-key detail enrichment, and API-driven discovery.
- RSS should remain in the repo for fallback flows and other sites.
- Local state in `.seed-agent/state.db` and audit in `.seed-agent/audit.jsonl` are durable project evidence, not disposable temp files.

## Useful Docs

- `docs/ai/project-overview.md`
- `docs/ai/harness-workflow.md`
- `docs/ai/harness-engineering.md`
- `docs/ai/reference-repos.md`
- `docs/ai/modules/*.md`
- `docs/ai/templates/*.md`
