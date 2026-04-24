# OpenAI-Aligned `AGENTS.md` Template

Use this template when initializing another repository for agent-first work.

The goal is to keep `AGENTS.md` short and make it act as a table of contents into `docs/`.

```md
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
- `docs/specs/` or `docs/design-docs/`: durable design decisions
- `docs/plans/` or `docs/exec-plans/`: implementation sequencing

## Working Rules

- Keep AI-facing docs in English.
- Reply to the human user in their preferred language.
- Prefer small, well-bounded sessions.
- Work on one module or one roadmap item at a time.
- Update the most relevant module doc and `docs/roadmap.md` when project state materially changes.

## Safety

- Keep secrets in gitignored local files.
- Do not commit credentials, tokens, or cookies.
- Prefer dry-run defaults for destructive or external side-effect operations.

## Project-Specific Notes

- Add only the few repo-specific constraints that agents cannot infer from code alone.

## Useful Docs

- `docs/ai/project-overview.md`
- `docs/ai/harness-workflow.md`
- `docs/ai/reference-repos.md`
- `docs/ai/modules/*.md`
- `docs/ai/templates/*.md`
```

## Suggested Matching Docs Layout

```text
AGENTS.md
README.md
docs/
├── ai/
│   ├── project-overview.md
│   ├── harness-workflow.md
│   ├── reference-repos.md
│   ├── modules/
│   └── templates/
├── roadmap.md
├── operations/
├── specs/
└── plans/
```

## What To Customize Per Repo

- project-specific safety rules
- canonical verification commands
- module list
- roadmap categories
- external references that are actually useful for that repo
