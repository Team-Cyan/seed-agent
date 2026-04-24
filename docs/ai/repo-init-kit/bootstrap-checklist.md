# Bootstrap Checklist

Use this checklist when turning a repo into an agent-friendly project.

## Choose A Profile First

- [ ] `small-app`
- [ ] `service-backend`
- [ ] `infra-ops`

Use that choice to decide how much of the kit to apply on day one.

## Phase 1: Thin Entrypoint

- [ ] Add root `AGENTS.md`
- [ ] Add `docs/ai/project-overview.md`
- [ ] Add `docs/roadmap.md`

## Phase 2: Shared Knowledge Base

- [ ] Add `docs/ai/reference-repos.md`
- [ ] Add `docs/ai/modules/` with at least one module doc
- [ ] Add `docs/ai/templates/`

## Phase 3: Multi-Session Support

- [ ] Add `docs/operations/session-handoff.md` if the repo will span multiple sessions
- [ ] Add `docs/ai/harness-workflow.md` if the repo will use many small scoped sessions

## AGENTS.md Rules

- [ ] Keep it short
- [ ] Include read order
- [ ] Include only high-signal repo rules
- [ ] Do not dump the whole architecture into it

## Knowledge Base Rules

- [ ] Keep AI-facing docs in English
- [ ] Organize by module
- [ ] Keep roadmap separate from specs and plans
- [ ] Record external references with notes on what to borrow and what not to copy

## Session Workflow Rules

- [ ] Encourage one module or one roadmap item per session
- [ ] Require focused verification before claiming completion
- [ ] Update roadmap and module docs when project state changes

## Optional Later Additions

- [ ] richer ops docs
- [ ] more module docs
- [ ] per-module plans
- [ ] release checklist
- [ ] generated docs index
- [ ] repo-init copy commands or automation

## Profile Guidance

### `small-app`

- [ ] Keep the initial doc set small
- [ ] Only add handoff or specs when the repo starts to accumulate state or complexity

### `service-backend`

- [ ] Add handoff early
- [ ] Add reference repos early
- [ ] Add specs and plans once behavior spans multiple modules

### `infra-ops`

- [ ] Add explicit safety rules in `AGENTS.md`
- [ ] Add operations docs early
- [ ] Prefer stronger verification and rollback documentation
