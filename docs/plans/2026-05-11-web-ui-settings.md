# Seed Agent Settings Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight local settings web UI for tracker configuration, preserving YAML-vs-secret boundaries and keeping all tracker actions inside tracker cards.

**Architecture:** Add a small stdlib HTTP server under `src/seed_agent/web/` with JSON endpoints and static HTML/CSS/JS assets. The server reuses existing Pydantic config models for validation, writes YAML config refs and local secret files separately, and exposes safe tracker-local validation/probe/dry-run summaries without execute-mode mutations.

**Tech Stack:** Python stdlib `http.server`, Pydantic config models, PyYAML, Typer CLI, vanilla HTML/CSS/JavaScript.

---

## File Structure

- Create `src/seed_agent/web/__init__.py`: package marker.
- Create `src/seed_agent/web/app.py`: request routing, HTTP handler factory, JSON response helpers, server entrypoint.
- Create `src/seed_agent/web/settings.py`: config file loading/saving helpers, tracker form normalization, secret write helpers, status summaries.
- Create `src/seed_agent/web/static/index.html`: single-page settings UI shell.
- Create `src/seed_agent/web/static/styles.css`: responsive layout, tracker cards, themes.
- Create `src/seed_agent/web/static/app.js`: client state, tracker add/edit flow, i18n/theme toggles, API calls.
- Modify `src/seed_agent/cli.py`: add `web` command.
- Modify `pyproject.toml`: include package data for static assets if needed by hatch.
- Create `tests/test_web_settings.py`: unit tests for settings helpers and HTTP endpoints.
- Create `tests/test_web_static.py`: static asset smoke tests.
- Modify `docs/roadmap.md`: add the settings UI work once implemented.

### Task 1: Settings Helper Boundaries

**Files:**
- Create: `src/seed_agent/web/__init__.py`
- Create: `src/seed_agent/web/settings.py`
- Test: `tests/test_web_settings.py`

- [ ] **Step 1: Write failing tests for tracker draft normalization and secret redaction**

Add tests that assert:

```python
from pathlib import Path

from seed_agent.web.settings import (
    TrackerDraft,
    build_tracker_status,
    tracker_draft_to_config,
)


def test_mteam_tracker_draft_keeps_secret_value_out_of_config() -> None:
    draft = TrackerDraft(
        type="mteam",
        name="mt",
        enabled=True,
        rss_url="https://rss.example/feed",
        discovery_mode="api",
        api_key_ref="local/secrets/mt.api-key",
        api_key_value="secret-token",
        auth_header="x-api-key",
        cookie_ref="local/secrets/mt.cookie",
    )

    site = tracker_draft_to_config(draft)

    assert site.name == "mt"
    assert site.type == "mteam"
    assert site.api_key_ref == "local/secrets/mt.api-key"
    assert site.cookie_ref == "local/secrets/mt.cookie"
    assert "secret-token" not in site.model_dump_json()


def test_tracker_status_reports_missing_required_fields() -> None:
    draft = TrackerDraft(type=None, name="")

    status = build_tracker_status(draft, root=Path("/tmp/seed-agent"))

    assert {"level": "warning", "message": "type is required"} in status
    assert {"level": "warning", "message": "tracker name is required"} in status
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_web_settings.py`

Expected: FAIL because `seed_agent.web.settings` does not exist.

- [ ] **Step 3: Implement minimal settings helpers**

Create `TrackerDraft` as a Pydantic model with optional fields, implement `tracker_draft_to_config()` returning existing `SiteConfig`, and implement `build_tracker_status()` with missing-field warnings.

For M-Team API mode, create `MTeamApiDiscoveryConfig()` with defaults when the draft does not provide an `api_discovery` block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q tests/test_web_settings.py`

Expected: PASS.

### Task 2: Config And Secret File Writes

**Files:**
- Modify: `src/seed_agent/web/settings.py`
- Test: `tests/test_web_settings.py`

- [ ] **Step 1: Write failing tests for saving tracker config and local secret files**

Add tests that create a temp repo root with `config/config.yaml` and `local/secrets/`, save an M-Team draft, then assert:

```python
from seed_agent.web.settings import save_tracker_draft


def test_save_tracker_draft_writes_config_ref_and_secret_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    secrets_dir = tmp_path / "local" / "secrets"
    config_dir.mkdir()
    secrets_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        """
mode: balanced
sites: []
discovery:
  discounts: [free]
  min_left_time_minutes: 120
  min_leechers: 1
  max_seeders: 100
  allow_hr: false
scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
downloader:
  type: qbittorrent
  target: local
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: [seed-agent]
  budget_pools:
    - name: downloads
      max_size_tib: 1
  secret_ref: null
cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""".lstrip(),
        encoding="utf-8",
    )

    save_tracker_draft(
        config_path,
        TrackerDraft(
            type="mteam",
            name="mt",
            enabled=True,
            rss_url="https://rss.example/feed",
            discovery_mode="api",
            api_key_ref="local/secrets/mt.api-key",
            api_key_value="secret-token",
        ),
    )

    saved = config_path.read_text(encoding="utf-8")
    assert "api_key_ref: local/secrets/mt.api-key" in saved
    assert "secret-token" not in saved
    assert (tmp_path / "local" / "secrets" / "mt.api-key").read_text(
        encoding="utf-8"
    ) == "secret-token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_web_settings.py::test_save_tracker_draft_writes_config_ref_and_secret_file`

Expected: FAIL because `save_tracker_draft` is not implemented.

- [ ] **Step 3: Implement `save_tracker_draft()`**

Load existing YAML as a mapping, replace an existing site with the same name or append a new site, dump YAML with `sort_keys=False`, and write `api_key_value` only to the resolved local secret path.

- [ ] **Step 4: Run targeted tests**

Run: `uv run pytest -q tests/test_web_settings.py`

Expected: PASS.

### Task 3: HTTP JSON API

**Files:**
- Create: `src/seed_agent/web/app.py`
- Test: `tests/test_web_settings.py`

- [ ] **Step 1: Write failing endpoint tests**

Use `http.client` against a server created by the app module. Cover:

- `GET /api/config` returns trackers with `has_api_key` but no secret value.
- `POST /api/trackers/validate` returns tracker-local status.
- `POST /api/trackers` saves config and local secret file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_web_settings.py`

Expected: FAIL because the HTTP app is not implemented.

- [ ] **Step 3: Implement the HTTP handler**

Implement routes:

- `GET /` -> static index,
- `GET /static/<name>` -> static assets,
- `GET /api/config`,
- `POST /api/trackers/validate`,
- `POST /api/trackers`,
- `POST /api/trackers/site-probe`,
- `POST /api/trackers/dry-run`.

For v1, `site-probe` and `dry-run` may return safe structured placeholders from existing config validation unless full single-tracker reuse is straightforward.

- [ ] **Step 4: Run endpoint tests**

Run: `uv run pytest -q tests/test_web_settings.py`

Expected: PASS.

### Task 4: Static Tracker UI

**Files:**
- Create: `src/seed_agent/web/static/index.html`
- Create: `src/seed_agent/web/static/styles.css`
- Create: `src/seed_agent/web/static/app.js`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write static asset smoke tests**

Assert the static files exist and contain the required UI anchors:

- `Add Tracker`,
- `Tracker`,
- language button,
- theme button,
- field help markers,
- no top-level `Site Probe` toolbar outside tracker cards.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_web_static.py`

Expected: FAIL because static files do not exist.

- [ ] **Step 3: Implement HTML/CSS/JS**

Implement the v12 design:

- empty tracker list for new config,
- top right globe and sun/moon icon buttons,
- Add Tracker creates a large tracker card,
- first field is `type`, second is `tracker name`,
- type-specific fields render only after type is selected,
- authentication and status live inside the tracker card,
- tracker-local `Validate This Tracker`, `Site Probe`, and `Dry-run Preview`.

- [ ] **Step 4: Run static tests**

Run: `uv run pytest -q tests/test_web_static.py`

Expected: PASS.

### Task 5: CLI Command And Packaging

**Files:**
- Modify: `src/seed_agent/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Add a test that asserts `seed-agent web --help` includes:

- `--config`,
- `--host`,
- `--port`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_cli.py::test_web_help`

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Add `web` CLI command**

Implement `seed-agent web --config config/config.yaml --host 127.0.0.1 --port 8765`, calling `seed_agent.web.app.serve()`.

Ensure static assets are included as package data.

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest -q tests/test_cli.py::test_web_help tests/test_web_settings.py tests/test_web_static.py`

Expected: PASS.

### Task 6: Docs And Verification

**Files:**
- Modify: `docs/roadmap.md`
- Modify: `docs/ai/modules/cli.md`
- Modify: `docs/specs/2026-05-11-web-ui-settings.md` if implementation details drift.

- [ ] **Step 1: Update docs**

Document:

- `seed-agent web --config config/config.yaml`,
- Tracker-local action boundary,
- secret write behavior,
- v1 execute-mode exclusion.

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_web_settings.py tests/test_web_static.py tests/test_cli.py
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 4: Manual browser verification**

Run:

```bash
uv run seed-agent web --config config/example.yaml --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765` and verify:

- page loads,
- Add Tracker creates one large empty tracker card,
- type is the first field and name is the second,
- type-specific fields are hidden until type is selected,
- auth, status, validation, site probe, and dry-run preview live inside the card,
- language and theme buttons are in the top right,
- saved API key values do not appear in YAML or UI responses.

