# Repo Init Kit

This directory is a reusable repo-initialization kit for agent-first projects.

It follows the OpenAI-aligned pattern:

- root `AGENTS.md` stays short,
- structured knowledge lives under `docs/`,
- agents read a small table of contents first and only pull deeper docs as needed.

## What This Kit Contains

- `README.md`: usage guide for the kit
- `path-architecture.md`: recommended docs layout
- `bootstrap-checklist.md`: step-by-step initialization checklist
- `templates/`: minimal reusable templates

## Adoption Modes

### Minimal

Use this when a repo is still small or early:

- `AGENTS.md`
- `docs/ai/project-overview.md`
- `docs/roadmap.md`
- `docs/ai/modules/<one-or-two>.md`

### Standard

Use this when the repo will span many sessions or contributors:

- everything in Minimal
- `docs/ai/harness-workflow.md`
- `docs/ai/reference-repos.md`
- `docs/ai/templates/`
- `docs/operations/session-handoff.md`

## Suggested Profiles

### `small-app`

Use for:

- a small local app,
- a utility repo,
- an early prototype,
- a single-runtime tool.

Recommended minimum:

- `AGENTS.md`
- `docs/ai/project-overview.md`
- `docs/roadmap.md`
- `docs/ai/modules/<1-3>.md`

Usually optional:

- `docs/operations/session-handoff.md`
- `docs/specs/`
- `docs/plans/`

### `service-backend`

Use for:

- backend services,
- API repos,
- automation systems,
- repos expected to grow across multiple loops and integrations.

Recommended minimum:

- everything in `small-app`
- `docs/ai/harness-workflow.md`
- `docs/ai/reference-repos.md`
- `docs/ai/templates/`
- `docs/operations/session-handoff.md`
- `docs/specs/`
- `docs/plans/`

### `infra-ops`

Use for:

- infrastructure repos,
- deployment or platform repos,
- operational automation,
- safety-sensitive environments.

Recommended minimum:

- everything in `service-backend`
- stronger safety notes in `AGENTS.md`
- module docs for deployment, secrets, runtime, rollback, and audit
- richer `docs/operations/`

Recommended bias:

- dry-run first,
- explicit rollback notes,
- higher write-back discipline after each session.

## Quickstart

Copy these first:

1. `templates/AGENTS.md` -> `AGENTS.md`
2. `templates/project-overview.md` -> `docs/ai/project-overview.md`
3. `templates/roadmap.md` -> `docs/roadmap.md`
4. `templates/module-doc.md` -> `docs/ai/modules/<module-name>.md`

Then add, as needed:

5. `templates/reference-repos.md` -> `docs/ai/reference-repos.md`
6. `templates/harness-workflow.md` -> `docs/ai/harness-workflow.md`
7. `templates/delivery-checklist.md` -> `docs/ai/templates/delivery-checklist.md`
8. `templates/session-handoff.md` -> `docs/operations/session-handoff.md`

## Intended Outcome

After applying this kit to a repository, the project should have:

- a thin root `AGENTS.md`,
- a `docs/ai/` knowledge base,
- a current `docs/roadmap.md`,
- reusable module docs and session templates,
- a stable way to run many small, focused agent sessions without reloading the whole project context.

## Suggested Adoption Order

1. Copy `templates/AGENTS.md`
2. Create the recommended `docs/` structure from `path-architecture.md`
3. Copy the minimum template set:
   - `project-overview.md`
   - `reference-repos.md`
   - `roadmap.md`
   - one or more module docs
4. Customize the repo-specific notes
5. Add project-specific specs, plans, and operations docs later

## Copy Recipe

If you want a concrete copy plan for a new repo:

```text
AGENTS.md
docs/ai/project-overview.md
docs/roadmap.md
docs/ai/modules/<module>.md
docs/ai/harness-workflow.md
docs/ai/reference-repos.md
docs/ai/templates/delivery-checklist.md
docs/operations/session-handoff.md
```

## Profile Quick Picks

- If the repo is mostly one executable and a few modules: use `small-app`
- If the repo has APIs, workflows, integrations, or multiple stateful loops: use `service-backend`
- If the repo can affect deployed systems, production data, or operational safety: use `infra-ops`

## Notes

- This is a starter kit, not a rigid framework.
- Keep only the docs that stay useful.
- If a repo is very small, the same structure still works with fewer files.
- The main success criterion is that future sessions can read less, not that every possible template exists on day one.
