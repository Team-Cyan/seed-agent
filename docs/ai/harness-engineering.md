# Harness Engineering Notes

## Intent

This repo is being shaped to work well with Codex as a repeated engineering harness, not just as a single long conversation artifact.

That means we want the project itself to carry enough structure that future sessions can be small, targeted, and reliable.

## Design Principles

### 1. Put durable knowledge in files, not only in chat history

Important decisions should live in:

- specs,
- plans,
- module docs,
- roadmap,
- handoff notes.

This keeps later sessions from re-deriving the same context.

### 2. Prefer module-local context

Most work should fit inside one subsystem. Module docs exist so later sessions can load only what they need.

### 3. Keep plans lighter than code

Not every module needs a heavy implementation plan on day one. Today the useful minimum is:

- module boundary,
- task expectation,
- verification entrypoints,
- roadmap status.

Module-owned plans can come later when a module gets deep or busy enough.

### 4. Separate product truth from execution truth

- product/design truth lives in specs,
- implementation sequencing lives in plans,
- current status lives in roadmap,
- recent transient nuance lives in handoff.

### 5. Optimize for future narrow sessions

The target state is:

- one session per roadmap item,
- one session per bug cluster,
- one session per integration spike.

That is usually more token-efficient than keeping one giant session alive.

## What We Add Today

Today the repo should have:

- Codex project entry docs,
- module docs,
- roadmap,
- reference repo index,
- session/task/checklist templates.

## What We Delay

We intentionally delay heavier scaffolding until the module boundaries settle more:

- module-owned execution plans,
- recurring per-module task packs,
- more formal delivery pipelines.

That keeps the project light while still making future work cheaper.
