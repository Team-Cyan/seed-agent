# Docs Index

This repository keeps durable project knowledge under `docs/`.

## Repository Layout

- `.agents/`
  - repo-local agent assets and reusable prompts
  - not a durable knowledge base

- `docs/ai/`
  - shared AI knowledge base
  - overview, workflow, module docs, templates, repo-init kit

- `docs/roadmap.md`
  - current project status
  - completed, next, later, deferred work

- `docs/architecture.md`
  - current architecture diagram
  - supported feature matrix

- `docs/specs/`
  - durable design and architecture decisions

- `docs/plans/`
  - implementation plans and execution sequencing

- `docs/operations/`
  - operator procedures
  - session handoff notes

- `docs/research/`
  - inspiration and external research notes

## Suggested Read Paths

### For humans

1. `README.md`
2. `docs/roadmap.md`
3. `docs/architecture.md`
4. `docs/operations/docker-compose-user-guide.md`
5. `docs/operations/configuration-guide.md`
6. `docs/operations/config-and-state-fields.md`
7. `docs/operations/docker-scheduling.md`
8. `docs/operations/docker-image-publishing.md`
9. `docs/operations/release-process.md`
10. `deploy/docker-compose.example.yml`
11. `deploy/seed-agent.env.example`
12. `docs/operations/phase-1-usage.md` or `docs/operations/phase-2-usage.md`

### For agents

1. `AGENTS.md`
2. `docs/ai/project-overview.md`
3. `docs/roadmap.md`
4. one or two relevant module docs under `docs/ai/modules/`
5. only then a matching spec, plan, or handoff file
