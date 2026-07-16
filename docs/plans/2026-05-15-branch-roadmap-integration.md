# Branch And Roadmap Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the current Web Settings UI feature, merge it into `main`, and update the roadmap with the deep research report todo.

**Architecture:** Treat `feature/web-ui-settings` as the only active feature branch. Verify and minimally repair the existing Web UI implementation, commit it separately from report-derived roadmap edits, merge into `main`, then clean only branches proven to already be ancestors of `main`.

**Tech Stack:** Git, uv, pytest, ruff, Typer CLI, stdlib web server, repository markdown docs.

---

## File Structure

- Modify `src/seed_agent/web/settings.py` only if Web UI helper tests expose a defect.
- Modify `src/seed_agent/web/app.py` only if Web endpoint tests expose a defect.
- Modify `src/seed_agent/web/static/index.html`, `src/seed_agent/web/static/styles.css`, or `src/seed_agent/web/static/app.js` only if static smoke tests expose a packaging or asset defect.
- Modify `src/seed_agent/cli.py`, `src/seed_agent/config.py`, `src/seed_agent/actions/pt.py`, and `src/seed_agent/sites/mteam.py` only if existing uncommitted feature changes fail focused tests.
- Modify `docs/roadmap.md` to map the report todo after the Web UI feature commit.
- Do not modify live secrets, `.seed-agent/state.db`, qBittorrent, or local runtime files.

### Task 1: Review And Verify The Web UI Feature

**Files:**
- Review: `docs/specs/2026-05-11-web-ui-settings.md`
- Review: `docs/plans/2026-05-11-web-ui-settings.md`
- Review: `src/seed_agent/web/settings.py`
- Review: `src/seed_agent/web/app.py`
- Review: `src/seed_agent/web/static/index.html`
- Review: `src/seed_agent/web/static/styles.css`
- Review: `src/seed_agent/web/static/app.js`
- Test: `tests/test_web_settings.py`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Inspect the current uncommitted feature surface**

Run:

```bash
git diff --stat
git status --short --branch
find src/seed_agent/web -maxdepth 3 -type f -print
```

Expected: Web UI source, tests, docs, and related CLI/config/M-Team changes are visible; generated `__pycache__` files remain untracked and unstaged.

- [ ] **Step 2: Run focused Web UI tests**

Run:

```bash
uv run pytest -q tests/test_web_settings.py tests/test_web_static.py
```

Expected: tests pass. If they fail, fix the smallest Web UI defect shown by the failing assertion, then rerun the same command.

- [ ] **Step 3: Run affected CLI and M-Team tests**

Run:

```bash
uv run pytest -q tests/test_cli.py tests/test_mteam_site.py
```

Expected: tests pass. If they fail, fix only the affected feature behavior, then rerun the same command.

- [ ] **Step 4: Run lint on changed Python files**

Run:

```bash
uv run ruff check src/seed_agent/actions/pt.py src/seed_agent/cli.py src/seed_agent/config.py src/seed_agent/sites/mteam.py src/seed_agent/web tests/test_cli.py tests/test_mteam_site.py tests/test_web_settings.py tests/test_web_static.py
```

Expected: `All checks passed!`. If lint fails, apply the minimal formatting or import fix and rerun.

### Task 2: Commit The Web Settings UI Feature

**Files:**
- Add: `docs/specs/2026-05-11-web-ui-settings.md`
- Add: `docs/plans/2026-05-11-web-ui-settings.md`
- Add: `src/seed_agent/web/__init__.py`
- Add: `src/seed_agent/web/app.py`
- Add: `src/seed_agent/web/settings.py`
- Add: `src/seed_agent/web/static/index.html`
- Add: `src/seed_agent/web/static/styles.css`
- Add: `src/seed_agent/web/static/app.js`
- Add: `tests/test_web_settings.py`
- Add: `tests/test_web_static.py`
- Modify: `config/example.yaml`
- Modify: `docs/ai/modules/cli.md`
- Modify: `docs/roadmap.md`
- Modify: `src/seed_agent/actions/pt.py`
- Modify: `src/seed_agent/cli.py`
- Modify: `src/seed_agent/config.py`
- Modify: `src/seed_agent/sites/mteam.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mteam_site.py`

- [ ] **Step 1: Check release policy impact**

Run:

```bash
sed -n '1,180p' docs/operations/release-process.md
printf 'VERSION=' && cat VERSION
rg -n "__version__|version =" pyproject.toml src/seed_agent/__init__.py
```

Expected: confirm whether this feature requires a minor version bump. Because the feature adds a user-facing `seed-agent web` command, apply the repository rule for a new feature: bump minor by `0.1.0` unless the current changed tree already contains a correct bump.

- [ ] **Step 2: Stage only feature files, excluding generated cache files**

Run:

```bash
git add config/example.yaml docs/ai/modules/cli.md docs/roadmap.md docs/specs/2026-05-11-web-ui-settings.md docs/plans/2026-05-11-web-ui-settings.md src/seed_agent/actions/pt.py src/seed_agent/cli.py src/seed_agent/config.py src/seed_agent/sites/mteam.py src/seed_agent/web tests/test_cli.py tests/test_mteam_site.py tests/test_web_settings.py tests/test_web_static.py
git status --short
```

Expected: intended feature files are staged; `src/seed_agent/web/__pycache__/` is not staged.

- [ ] **Step 3: Commit Web UI feature**

Run:

```bash
git commit -m "feat: add local settings web ui"
```

Expected: commit succeeds on `feature/web-ui-settings`.

### Task 3: Update Roadmap From The Research Report

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Edit roadmap sections**

Update `docs/roadmap.md` so it:

- Keeps Web Settings UI under `Completed`.
- Adds a `Project Credibility And Collaboration` item under `Next` with license, CI gate, README support matrix, Docker smoke test, and source-status clarity.
- Keeps qB live-state strategy under `Next`.
- Adds medium-term items under `Later` for Transmission, second API provider, read-only dashboard/API, and feedback-loop scoring.

- [ ] **Step 2: Review roadmap diff**

Run:

```bash
git diff -- docs/roadmap.md
```

Expected: the diff maps report todo without claiming future dashboard/API work is already done.

- [ ] **Step 3: Commit roadmap update**

Run:

```bash
git add docs/roadmap.md
git commit -m "docs: update roadmap from research report"
```

Expected: commit succeeds on `feature/web-ui-settings`.

### Task 4: Merge Feature Into Main

**Files:**
- Git branch state only.

- [ ] **Step 1: Verify branch and working tree before merge**

Run:

```bash
git status --short --branch
git branch --show-current
```

Expected: branch is `feature/web-ui-settings`; working tree has no tracked unstaged changes except intentionally ignored generated files.

- [ ] **Step 2: Switch to `main`**

Run:

```bash
git switch main
```

Expected: checkout succeeds.

- [ ] **Step 3: Merge the feature branch**

Run:

```bash
git merge --no-ff feature/web-ui-settings -m "merge: web settings ui and roadmap update"
```

Expected: merge succeeds without conflicts.

- [ ] **Step 4: Verify main**

Run:

```bash
uv run pytest -q tests/test_web_settings.py tests/test_web_static.py tests/test_cli.py tests/test_mteam_site.py
git status --short --branch
```

Expected: tests pass; `main` is clean or only shows ignored/generated files that are not staged.

### Task 5: Clean Already-Merged Feature Worktrees And Branches

**Files:**
- Git worktree and branch metadata only.

- [ ] **Step 1: Confirm old branches are ancestors of main**

Run:

```bash
git merge-base --is-ancestor feat/phase-1-pt-upload-loop main
git merge-base --is-ancestor feat/phase-2-resource-intent-loop main
git merge-base --is-ancestor feat/qb-category-policy-budgeting main
```

Expected: all commands exit `0`.

- [ ] **Step 2: Remove old superpowers worktrees**

Run:

```bash
git worktree remove $HOME/.config/superpowers/worktrees/seed-agent/phase-1-pt-upload-loop
git worktree remove $HOME/.config/superpowers/worktrees/seed-agent/phase-2-resource-intent-loop
git worktree remove $HOME/.config/superpowers/worktrees/seed-agent/feat-qb-category-policy-budgeting
```

Expected: each remove succeeds. If a worktree has unexpected local changes, stop and report the exact path.

- [ ] **Step 3: Delete old local branch refs**

Run:

```bash
git branch -d feat/phase-1-pt-upload-loop
git branch -d feat/phase-2-resource-intent-loop
git branch -d feat/qb-category-policy-budgeting
```

Expected: local branch deletion succeeds. Do not delete remote branches unless explicitly requested.

- [ ] **Step 4: Final verification**

Run:

```bash
git status --short --branch
git branch --all --verbose --no-abbrev
```

Expected: current branch is `main`; cleaned local branches no longer appear; remote branches remain untouched.
