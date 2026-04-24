# Harness Workflow

This repository is intended to work well with many short, targeted agent sessions instead of a few giant context-heavy sessions.

## Preferred Session Types

### 1. Project-init session

Use for:

- setting up docs,
- clarifying module boundaries,
- shaping the roadmap,
- creating templates and collaboration rules.

### 2. Module session

Use for:

- one subsystem,
- one bug cluster,
- one integration boundary.

### 3. Roadmap-item session

Use for:

- one concrete next task from `docs/roadmap.md`.

## Recommended Read Budget

Before editing:

1. `AGENTS.md`
2. `docs/roadmap.md`
3. one or two matching module docs

Only add:

- a relevant spec,
- a relevant plan,
- a handoff note if the task depends on recent unfinished work.

## Recommended Write-Back

At the end of a meaningful task, update:

- the relevant module doc,
- `docs/roadmap.md`,
- `docs/operations/session-handoff.md` if future sessions need the nuance.
