# WebUI Product Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the current WebUI product-review findings and refine the operator experience around config navigation, runtime provenance, Want List enqueue safety, strategy settings, and operator docs.

**Architecture:** Keep the existing lightweight local WebUI: `src/seed_agent/web/app.py` remains the HTTP API, `src/seed_agent/web/static/app.js` remains the static frontend, and `src/seed_agent/web/static/styles.css` remains the visual system. Avoid introducing a JS build pipeline. Extend current API payloads and UI copy instead of creating new product surfaces.

**Tech Stack:** Python 3.14+, Typer, Pydantic, SQLite via `StateStore`, stdlib HTTP server, static HTML/CSS/JavaScript, pytest, ruff. Docker and CI already target Python 3.14, so this plan formalizes that baseline unless dependency resolution exposes a blocker.

---

## Product Decisions

- Treat `seed-agent web` as a local operator console, not a dashboard-first media product.
- Keep search/sync operations non-mutating.
- Make qB enqueue from WebUI preview-first, then execute after explicit operator confirmation.
- Show where config and runtime state come from, because one config file can read shared workspace runtime state.
- Keep advanced YAML available, but make common product choices easier through summaries and presets.
- Keep docs AI-facing text in English and user-facing UI text bilingual where existing UI already is bilingual.
- Treat Python 3.14+ as the supported runtime baseline. Use 3.14 language/runtime improvements where they simplify code, and update project metadata plus lockfile as part of release verification.

## File Structure

- Modify `src/seed_agent/web/static/app.js`
  - Fix `config_file` navigation.
  - Add runtime provenance copy and rendering.
  - Change candidate enqueue flow to preview-first.
  - Add compact strategy summary and release preference preset controls.
  - Tighten mobile header behavior.
- Modify `src/seed_agent/web/static/styles.css`
  - Style provenance rows, preview confirmation panel, preset controls, mobile compact header, and strategy summary chips.
- Modify `src/seed_agent/web/app.py`
  - Add runtime provenance to status/config payloads if needed.
  - Honor `execute: false` for Want List candidate enqueue preview.
  - Return preview payload fields useful to the UI.
- Modify `src/seed_agent/cli.py`
  - Improve `web` port-conflict message with a concrete alternate-port suggestion.
- Modify `tests/test_web_static.py`
  - Add static assertions for fixed navigation, preview-first enqueue UI, runtime provenance copy, mobile header refinements, and presets.
- Modify `tests/test_web_settings.py`
  - Add HTTP tests for runtime provenance payload and non-mutating enqueue preview.
  - Update existing enqueue test to assert execute behavior only when `execute: true`.
- Modify `tests/test_cli.py`
  - Add test for actionable port conflict output.
- Create `docs/operations/web-ui-operator-guide.md`
  - Explain WebUI surfaces, risk levels, and CLI/WebUI decision path.
- Modify `README.md`
  - Link to the Web UI operator guide and clarify WebUI vs CLI.
- Modify `docs/architecture.md`
  - Update WebUI supported-feature description for preview-first enqueue and runtime provenance.
- Modify `docs/roadmap.md`
  - Mark the P0 WebUI hardening as completed or update next-work wording.
- Modify `pyproject.toml`, `uv.lock`
  - Raise the supported Python baseline to 3.14+ and update Ruff target to `py314`.
- Modify `docs/operations/release-process.md`, `VERSION`, `src/seed_agent/__init__.py`, `tests/test_package_import.py`, `CHANGELOG.md`
  - Bump from `0.11.1` to `0.11.2` if this plan is implemented for deployment.

---

### Task 1: Fix Config File Navigation Breakage

**Files:**
- Modify: `src/seed_agent/web/static/app.js`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write the failing static test**

Append this test to `tests/test_web_static.py`:

```python
def test_config_file_navigation_uses_existing_placeholder_key() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "placeholders.config_file" in script
    assert "placeholders.advanced" not in script
    assert 'config_file: {' in script
    assert "renderConfigFilePanel" in script
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run:

```bash
uv run pytest -q tests/test_web_static.py::test_config_file_navigation_uses_existing_placeholder_key
```

Expected: FAIL because `renderSection()` currently references `copy[state.language].placeholders.advanced`.

- [ ] **Step 3: Implement the minimal fix**

In `src/seed_agent/web/static/app.js`, replace the `config_file` branch in `renderSection()` with:

```javascript
  if (state.currentSection === "config_file") {
    const placeholder = copy[state.language].placeholders.config_file;
    title.textContent = placeholder.title;
    subtitle.textContent = placeholder.description;
    addTrackerButton.hidden = true;
    trackerList.replaceChildren(renderConfigFilePanel());
    return;
  }
```

- [ ] **Step 4: Run the targeted tests**

Run:

```bash
uv run pytest -q tests/test_web_static.py::test_config_file_navigation_uses_existing_placeholder_key tests/test_web_static.py::test_each_config_page_exposes_section_yaml_editor
```

Expected: PASS.

- [ ] **Step 5: Browser verify**

Run:

```bash
uv run seed-agent web --config config/example.yaml --host 127.0.0.1 --port 8876
```

Open `http://127.0.0.1:8876`, click `配置文件`, and verify:

- Header title is `配置文件`.
- Body shows the normalized config preview.
- Browser console has no `Cannot read properties of undefined (reading 'title')` error.

- [ ] **Step 6: Commit**

```bash
git add src/seed_agent/web/static/app.js tests/test_web_static.py
git commit -m "fix: restore config file webui navigation"
```

---

### Task 2: Show Config And Runtime Provenance

**Files:**
- Modify: `src/seed_agent/web/app.py`
- Modify: `src/seed_agent/web/static/app.js`
- Modify: `src/seed_agent/web/static/styles.css`
- Test: `tests/test_web_settings.py`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write failing HTTP provenance test**

Append this test to `tests/test_web_settings.py` near `test_http_state_summary_reports_local_state_counts`:

```python
def test_http_status_payloads_expose_runtime_provenance(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    with _running_server(config_path) as base_url:
        config_payload = _request_json(base_url, "GET", "/api/config")
        state_payload = _request_json(base_url, "GET", "/api/state/summary")
        health_payload = _request_json(base_url, "GET", "/api/health")

    assert config_payload["config_path"] == str(config_path)
    assert config_payload["runtime_root"] == str(tmp_path)
    assert config_payload["state_path"] == str(tmp_path / ".seed-agent" / "state.db")
    assert config_payload["heartbeat_file"] == str(
        tmp_path / "state" / "schedule-heartbeat.json"
    )
    assert state_payload["runtime_root"] == str(tmp_path)
    assert health_payload["runtime_root"] == str(tmp_path)
```

- [ ] **Step 2: Write failing static provenance test**

Append this test to `tests/test_web_static.py`:

```python
def test_overview_surfaces_config_and_runtime_provenance() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "runtimeRoot" in script
    assert "statePath" in script
    assert "heartbeatFile" in script
    assert "runtimeSource" in script
    assert "状态来源" in script
    assert "Runtime source" in script
    assert ".runtime-provenance" in styles
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_web_settings.py::test_http_status_payloads_expose_runtime_provenance tests/test_web_static.py::test_overview_surfaces_config_and_runtime_provenance
```

Expected: FAIL because payload and UI copy do not expose runtime provenance yet.

- [ ] **Step 4: Add API provenance fields**

In `src/seed_agent/web/app.py`, add helper functions:

```python
def _heartbeat_path(root: Path) -> Path:
    return root / "state" / "schedule-heartbeat.json"


def _runtime_provenance(root: Path) -> dict[str, str]:
    return {
        "runtime_root": str(root),
        "state_path": str(_state_db_path(root)),
        "heartbeat_file": str(_heartbeat_path(root)),
    }
```

Update `/api/config` payload inside `do_GET`:

```python
                self._send_json(
                    {
                        "config_path": str(resolved_config_path),
                        **_runtime_provenance(root),
                        "trackers": [_tracker_summary(site, root) for site in config.tracker_sites],
                        "sections": config_sections_payload(config),
                        "section_yamls": config_section_yamls_payload(config),
                        "config_yaml": normalized_config_yaml(config),
                    }
                )
```

Update `_state_summary_payload()` initial payload:

```python
        **_runtime_provenance(root),
```

Update `_health_payload()` to use `_heartbeat_path(root)` and include provenance:

```python
    heartbeat_path = _heartbeat_path(root)
    payload: dict[str, Any] = {
        "status": "unknown",
        **_runtime_provenance(root),
        "heartbeat_exists": heartbeat_path.exists(),
    }
```

- [ ] **Step 5: Add frontend state fields**

In `src/seed_agent/web/static/app.js`, extend `state`:

```javascript
  runtimeRoot: "",
  statePath: "",
  heartbeatFile: "",
```

In `loadConfig()`, store fields:

```javascript
  state.runtimeRoot = payload.runtime_root || "";
  state.statePath = payload.state_path || "";
  state.heartbeatFile = payload.heartbeat_file || "";
```

Add bilingual copy under `copy.CN.ui`:

```javascript
      runtimeSource: "状态来源",
      runtimeRoot: "运行目录",
      stateDb: "状态库",
      heartbeatFile: "心跳文件",
```

Add under `copy.EN.ui`:

```javascript
      runtimeSource: "Runtime source",
      runtimeRoot: "Runtime root",
      stateDb: "State DB",
      heartbeatFile: "Heartbeat file",
```

Add renderer:

```javascript
function renderRuntimeProvenance() {
  return `
    <div class="runtime-provenance">
      <div class="section-title">${escapeHtml(uiText("runtimeSource"))}</div>
      <div class="provenance-row">
        <span>${escapeHtml(uiText("runtimeRoot"))}</span>
        <code>${escapeHtml(state.runtimeRoot || uiText("unknown"))}</code>
      </div>
      <div class="provenance-row">
        <span>${escapeHtml(uiText("stateDb"))}</span>
        <code>${escapeHtml(state.statePath || uiText("unknown"))}</code>
      </div>
      <div class="provenance-row">
        <span>${escapeHtml(uiText("heartbeatFile"))}</span>
        <code>${escapeHtml(state.heartbeatFile || uiText("unknown"))}</code>
      </div>
    </div>
  `;
}
```

In `renderOverviewPanel()`, insert provenance into the detail grid:

```javascript
    <article class="overview-detail-panel wide">
      ${renderRuntimeProvenance()}
    </article>
```

- [ ] **Step 6: Add CSS**

Append to `src/seed_agent/web/static/styles.css`:

```css
.runtime-provenance {
  display: grid;
  gap: 10px;
}

.provenance-row {
  align-items: start;
  display: grid;
  gap: 8px;
  grid-template-columns: 130px minmax(0, 1fr);
}

.provenance-row span {
  color: var(--muted);
  font-size: 13px;
}

.provenance-row code {
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
  padding: 6px 8px;
}
```

Inside `@media (max-width: 700px)`, add:

```css
  .provenance-row {
    grid-template-columns: 1fr;
  }
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
uv run pytest -q tests/test_web_settings.py::test_http_status_payloads_expose_runtime_provenance tests/test_web_static.py::test_overview_surfaces_config_and_runtime_provenance
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/seed_agent/web/app.py src/seed_agent/web/static/app.js src/seed_agent/web/static/styles.css tests/test_web_settings.py tests/test_web_static.py
git commit -m "feat: show webui runtime provenance"
```

---

### Task 3: Make Want List Enqueue Preview-First

**Files:**
- Modify: `src/seed_agent/web/app.py`
- Modify: `src/seed_agent/web/static/app.js`
- Modify: `src/seed_agent/web/static/styles.css`
- Test: `tests/test_web_settings.py`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Replace existing enqueue test expectations with preview-first behavior**

In `tests/test_web_settings.py`, rename `test_http_want_enqueue_can_select_lower_match_release` to:

```python
def test_http_want_enqueue_preview_does_not_mutate_downloader(
    tmp_path: Path,
    monkeypatch,
) -> None:
```

Within that test, change the request body to:

```python
            {"release_id": "mt:https://kp.m-team.cc/detail/99", "execute": False},
```

Change assertions to:

```python
    assert payload["execute"] is False
    assert payload["selected"]["release_id"] == "mt:https://kp.m-team.cc/detail/99"
    assert payload["enqueued"] == 0
    assert payload["decisions"] == []
    assert downloader.calls == []
    row = store.get_intent(intent.intent_id)
    assert row["selected_release_id"] is None
    assert row["state"] == IntentState.CONFIRMATION_REQUIRED.value
```

Add a second test immediately after it:

```python
def test_http_want_enqueue_execute_mutates_after_preview_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    config_path = _write_minimal_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent = ResourceIntent(
        intent_id="douban_wanted:call-me-by-your-name",
        source=IntentSource.DOUBAN_WANTED,
        raw_text="Call Me by Your Name 2017",
        kind=IntentKind.MOVIE,
        title="Call Me by Your Name",
        year=2017,
        requested_at=datetime(2025, 1, 1, tzinfo=UTC),
        state=IntentState.CONFIRMATION_REQUIRED,
    )
    store.upsert_intent(intent)
    store.save_ranked_releases(
        [
            RankedRelease(
                intent_id=intent.intent_id,
                release=ReleaseCandidate(
                    release_id="mt:https://kp.m-team.cc/detail/99",
                    site="mt",
                    title="Call Me by Your Name 2017 1080p WEB-DL",
                    source_url="https://kp.m-team.cc/detail/99",
                    download_url="https://tracker.example/download?id=99",
                    size_bytes=8 * 1024**3,
                    seeders=100,
                    leechers=1,
                    discount=Discount.FREE,
                ),
                score=40,
                confidence=0.4,
                accepted=False,
                confirmation_required=True,
                reasons=["title tokens matched", "quality tag score -20: WEB-DL"],
                risks=[],
            )
        ]
    )

    class FakeDownloader:
        calls: list[tuple[str, str, list[str]]] = []

        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            self.calls.append((url, category, tags))
            return "0123456789abcdef0123456789abcdef01234567"

        async def list_torrents(self, category=None, tags=None):
            return []

    downloader = FakeDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda loaded: downloader)

    with _running_server(config_path) as base_url:
        payload = _request_json(
            base_url,
            "POST",
            f"/api/wants/{intent.intent_id}/enqueue",
            {"release_id": "mt:https://kp.m-team.cc/detail/99", "execute": True},
        )

    assert payload["execute"] is True
    assert payload["enqueued"] == 1
    assert any(item["action"] == "qb.enqueue" for item in payload["decisions"])
    assert downloader.calls == [
        (
            "https://tracker.example/download?id=99",
            "seed",
            ["seed-agent"],
        )
    ]
    row = store.get_intent(intent.intent_id)
    assert row["selected_release_id"] == "mt:https://kp.m-team.cc/detail/99"
    assert row["state"] == IntentState.ENQUEUED.value
```

- [ ] **Step 2: Write failing static UI test**

Update `test_want_list_exposes_candidate_review_drawer` in `tests/test_web_static.py`:

```python
    assert "预览入队" in script
    assert "确认加入 qB" in script
    assert "预览强制入队" in script
    assert 'data-want-candidate-action="preview"' in script
    assert 'data-want-candidate-action="enqueue"' in script
```

Remove these old negative assertions from that test:

```python
    assert "预览强制入队" not in script
    assert 'data-want-candidate-action="preview"' not in script
```

- [ ] **Step 3: Run targeted tests to verify failure**

Run:

```bash
uv run pytest -q tests/test_web_settings.py::test_http_want_enqueue_preview_does_not_mutate_downloader tests/test_web_static.py::test_want_list_exposes_candidate_review_drawer
```

Expected: FAIL because the API ignores `execute: false` and UI only exposes direct enqueue.

- [ ] **Step 4: Honor execute flag in API**

In `src/seed_agent/web/app.py`, change:

```python
    execute = True
```

to:

```python
    execute = _truthy_execute_flag(body.get("execute"))
```

Keep the existing `_enqueue_runtime_context(... execute=execute)` call. It already receives the execute flag.

In the success payload, keep:

```python
        "execute": execute,
```

and keep the message:

```python
                "message": "已加入 qB" if execute else "入队试运行完成",
```

Add the helper near the other small parsing helpers:

```python
def _truthy_execute_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
```

Add one API test case that sends `"execute": "false"` and verifies it is treated as preview, not execution.

- [ ] **Step 5: Add frontend copy**

In `src/seed_agent/web/static/app.js`, add under `copy.CN.ui`:

```javascript
      previewEnqueue: "预览入队",
      previewForceEnqueue: "预览强制入队",
      confirmExecuteEnqueue: "确认加入 qB",
      enqueuePreviewReady: "入队预览完成。确认后才会向 qB 发送添加任务。",
      enqueuePreviewRequired: "请先预览这个候选，再确认加入 qB。",
```

Add under `copy.EN.ui`:

```javascript
      previewEnqueue: "Preview queue",
      previewForceEnqueue: "Preview forced queue",
      confirmExecuteEnqueue: "Confirm add to qB",
      enqueuePreviewReady: "Queue preview is ready. Confirmation sends the add request to qB.",
      enqueuePreviewRequired: "Preview this candidate before confirming qB enqueue.",
```

- [ ] **Step 6: Render preview and confirm actions**

In `renderWantCandidateCard(item)`, replace action label logic with:

```javascript
  const previewLabel = item.matches_requirements ? uiText("previewEnqueue") : uiText("previewForceEnqueue");
```

Replace the action button block with:

```javascript
      <div class="tracker-actions-group candidate-actions">
        <button class="${item.matches_requirements ? "primary-button" : "secondary-button"}" type="button" data-want-candidate-action="preview" data-release-id="${escapeAttribute(item.release_id)}">${escapeHtml(previewLabel)}</button>
        <button class="secondary-button" type="button" data-want-candidate-action="enqueue" data-release-id="${escapeAttribute(item.release_id)}" data-requires-preview="true">${escapeHtml(uiText("confirmExecuteEnqueue"))}</button>
      </div>
```

- [ ] **Step 7: Track previewed release in modal**

In `openWantCandidates()`, after `modal.dataset.intentId = intentId;`, add:

```javascript
  modal.dataset.previewedReleaseId = "";
```

In `handleWantCandidateAction()`, add preview branch before confirm:

```javascript
  const execute = action === "enqueue";
  if (execute && modal.dataset.previewedReleaseId !== releaseId) {
    status.innerHTML = `<div class="status-item warning">${escapeHtml(uiText("enqueuePreviewRequired"))}</div>`;
    return;
  }
  if (execute) {
    const ok = window.confirm(uiText("confirmEnqueue"));
    if (!ok) {
      return;
    }
  }
```

Replace body construction with:

```javascript
  const body = { release_id: releaseId, execute };
```

After successful response and before `await loadWants();`, add:

```javascript
    if (!execute) {
      modal.dataset.previewedReleaseId = releaseId;
      status.innerHTML = `<div class="status-item ok">${escapeHtml(payload.status?.[0]?.message || uiText("enqueuePreviewReady"))}</div>`;
      return;
    }
```

Remove the old unconditional `window.confirm()` block.

- [ ] **Step 8: Add CSS for two-button candidate actions**

In `src/seed_agent/web/static/styles.css`, add:

```css
.candidate-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
}
```

Keep the existing mobile `.candidate-actions button:last-child` rule if present.

- [ ] **Step 9: Run targeted tests**

Run:

```bash
uv run pytest -q tests/test_web_settings.py::test_http_want_enqueue_preview_does_not_mutate_downloader tests/test_web_settings.py::test_http_want_enqueue_execute_mutates_after_preview_confirmation tests/test_http_want_enqueue_failure_returns_actionable_status tests/test_web_static.py::test_want_list_exposes_candidate_review_drawer
```

Expected: PASS.

- [ ] **Step 10: Browser verify**

Start WebUI and use a state DB with at least one Want List candidate. Verify:

- Candidate card first button says `预览入队` or `预览强制入队`.
- Clicking confirm before preview shows warning.
- Preview returns status and does not call qB.
- Confirm after preview sends qB request.

- [ ] **Step 11: Commit**

```bash
git add src/seed_agent/web/app.py src/seed_agent/web/static/app.js src/seed_agent/web/static/styles.css tests/test_web_settings.py tests/test_web_static.py
git commit -m "feat: make webui want enqueue preview-first"
```

---

### Task 4: Add Strategy Summary And Release Preference Presets

**Files:**
- Modify: `src/seed_agent/web/static/app.js`
- Modify: `src/seed_agent/web/static/styles.css`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write failing static test**

Append to `tests/test_web_static.py`:

```python
def test_strategy_pages_expose_operator_summary_and_release_presets() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "renderStrategySummary" in script
    assert "strategySummary" in script
    assert "策略概要" in script
    assert "Strategy summary" in script
    assert "releasePreferencePresets" in script
    assert "movie_remux_first" in script
    assert "tv_webdl_first" in script
    assert "anime_subtitle_friendly" in script
    assert "space_saving" in script
    assert "applyReleasePreferencePreset" in script
    assert ".strategy-summary" in styles
    assert ".preset-grid" in styles
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest -q tests/test_web_static.py::test_strategy_pages_expose_operator_summary_and_release_presets
```

Expected: FAIL.

- [ ] **Step 3: Add copy and preset definitions**

In `src/seed_agent/web/static/app.js`, add under `copy.CN.ui`:

```javascript
      strategySummary: "策略概要",
      releasePresets: "资源偏好模板",
      applyPreset: "应用模板",
      presetMovieRemux: "电影 Remux 优先",
      presetTvWebdl: "剧集 WEB-DL 优先",
      presetAnimeSubtitle: "动漫字幕友好",
      presetSpaceSaving: "空间节省",
```

Add under `copy.EN.ui`:

```javascript
      strategySummary: "Strategy summary",
      releasePresets: "Release presets",
      applyPreset: "Apply preset",
      presetMovieRemux: "Movie Remux first",
      presetTvWebdl: "TV WEB-DL first",
      presetAnimeSubtitle: "Anime subtitle friendly",
      presetSpaceSaving: "Space saving",
```

Add near `qualityTagGroups`:

```javascript
const releasePreferencePresets = {
  movie_remux_first: {
    labelKey: "presetMovieRemux",
    scores: {
      remux: 20,
      uhd_bluray: 12,
      dolby_vision: 15,
      hdr10_plus: 10,
      truehd: 8,
      dts_hd_ma: 8,
      webdl: -10,
    },
  },
  tv_webdl_first: {
    labelKey: "presetTvWebdl",
    scores: {
      webdl: 18,
      ddp: 8,
      atmos: 6,
      hdtv: -12,
      remux: -8,
      bluray: -6,
    },
  },
  anime_subtitle_friendly: {
    labelKey: "presetAnimeSubtitle",
    scores: {
      webdl: 12,
      hevc: 8,
      flac: 8,
      ass: 14,
      "1080p": 8,
      "2160p": -8,
      bluray: -6,
    },
  },
  space_saving: {
    labelKey: "presetSpaceSaving",
    scores: {
      webdl: 12,
      webrip: 4,
      avc: 6,
      "1080p": 10,
      remux: -25,
      uhd_bluray: -20,
      truehd: -10,
      dts_hd_ma: -10,
    },
  },
};
```

- [ ] **Step 4: Render strategy summary**

Add function:

```javascript
function renderStrategySummary(section, sectionData) {
  if (!["pt_filters", "seed_cleanup", "want_decision", "release_preferences"].includes(section)) {
    return "";
  }
  const chips = [];
  if (section === "pt_filters") {
    chips.push(`free ≥ ${sectionData.min_left_time_minutes ?? "?"}m`);
    chips.push(`leechers ≥ ${sectionData.min_leechers ?? "?"}`);
    chips.push(`max ${sectionData.max_size_gb ?? "∞"} GB`);
  }
  if (section === "seed_cleanup") {
    chips.push(`${sectionData.cold_after_days ?? "?"}d cold`);
    chips.push(`${sectionData.pause_before_delete_hours ?? "?"}h pause before delete`);
    chips.push(sectionData.protect_media_library ? "media protected" : "media not protected");
  }
  if (section === "want_decision") {
    chips.push(`review ≥ ${sectionData.confirmation_threshold ?? "?"}`);
    chips.push(`auto ≥ ${sectionData.auto_enqueue_threshold ?? "?"}`);
    chips.push(sectionData.series_search_mode || "season");
  }
  if (section === "release_preferences") {
    const scores = sectionData.quality_tag_scores || {};
    Object.entries(scores)
      .filter(([, value]) => Number(value) !== 0)
      .slice(0, 6)
      .forEach(([key, value]) => chips.push(`${key} ${value > 0 ? "+" : ""}${value}`));
  }
  return `
    <div class="strategy-summary">
      <div class="section-title">${escapeHtml(uiText("strategySummary"))}</div>
      <div class="overview-chip-list">
        ${chips.map((chip) => `<span class="overview-chip"><span>${escapeHtml(chip)}</span></span>`).join("")}
      </div>
    </div>
  `;
}
```

In `renderSettingsPanel(section)`, insert the summary before the form fields:

```javascript
      ${renderStrategySummary(section, sectionData)}
```

- [ ] **Step 5: Render release preference presets**

Add:

```javascript
function renderReleasePresetControls() {
  return `
    <div class="preset-grid" data-release-preset-grid>
      <div class="section-title">${escapeHtml(uiText("releasePresets"))}</div>
      ${Object.entries(releasePreferencePresets)
        .map(
          ([key, preset]) => `
            <button class="secondary-button" type="button" data-release-preset="${escapeAttribute(key)}">
              ${escapeHtml(uiText(preset.labelKey))}
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}
```

In `renderSettingsPanel(section)`, before `renderSearchTagScoreEditor(sectionData)` for `release_preferences`, insert:

```javascript
${section === "release_preferences" ? renderReleasePresetControls() : ""}
```

In the settings panel click handler, add:

```javascript
  const presetKey = event.target?.dataset?.releasePreset;
  if (presetKey) {
    applyReleasePreferencePreset(page, presetKey);
    return;
  }
```

Add:

```javascript
function applyReleasePreferencePreset(page, presetKey) {
  const preset = releasePreferencePresets[presetKey];
  if (!preset) {
    return;
  }
  qualityTagGroups.forEach((group) => {
    const input = page.querySelector(`[data-quality-tag-score="${group.key}"]`);
    if (input) {
      input.value = preset.scores[group.key] ?? 0;
    }
  });
  updateSettingsPanelStatus(page, [{ level: "info", message: uiText("formEditable") }]);
}
```

- [ ] **Step 6: Add CSS**

Append:

```css
.strategy-summary,
.preset-grid {
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  border-radius: 7px;
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
  padding: 14px;
}

.preset-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.preset-grid .section-title {
  grid-column: 1 / -1;
  margin-bottom: 0;
}
```

Inside `@media (max-width: 900px)`, add:

```css
  .preset-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
```

Inside `@media (max-width: 700px)`, add:

```css
  .preset-grid {
    grid-template-columns: 1fr;
  }
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
uv run pytest -q tests/test_web_static.py::test_strategy_pages_expose_operator_summary_and_release_presets tests/test_web_static.py::test_non_tracker_sections_render_config_panels
```

Expected: PASS.

- [ ] **Step 8: Browser verify**

Open `资源匹配` and verify:

- Strategy summary appears above the fields.
- Preset buttons populate the tag score inputs.
- YAML is not saved until the operator clicks preview/save.

- [ ] **Step 9: Commit**

```bash
git add src/seed_agent/web/static/app.js src/seed_agent/web/static/styles.css tests/test_web_static.py
git commit -m "feat: add webui strategy summaries and presets"
```

---

### Task 5: Tighten Mobile Header And Empty States

**Files:**
- Modify: `src/seed_agent/web/static/index.html`
- Modify: `src/seed_agent/web/static/app.js`
- Modify: `src/seed_agent/web/static/styles.css`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write failing static test**

Append:

```python
def test_mobile_header_and_want_empty_state_are_operator_focused() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "wantEmptyNextStep" in script
    assert "先配置来源，刷新列表，再搜索种子；搜索不会加入 qB。" in script
    assert "Configure sources, refresh the list, then search torrents; search does not add to qB." in script
    assert ".mobile-config-path" in styles
    assert "@media (max-width: 700px)" in styles
    assert ".config-path {\n    display: none;" in styles
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest -q tests/test_web_static.py::test_mobile_header_and_want_empty_state_are_operator_focused
```

Expected: FAIL.

- [ ] **Step 3: Add empty state copy**

In `copy.CN.ui`, add:

```javascript
      wantEmptyNextStep: "先配置来源，刷新列表，再搜索种子；搜索不会加入 qB。",
```

In `copy.EN.ui`, add:

```javascript
      wantEmptyNextStep: "Configure sources, refresh the list, then search torrents; search does not add to qB.",
```

In `renderWantTable()`, replace the empty state with:

```javascript
    wrapper.innerHTML = `
      <div class="empty-state">
        <strong>${escapeHtml(uiText("noWants"))}</strong>
        <div class="muted-line">${escapeHtml(uiText("wantEmptyNextStep"))}</div>
      </div>
    `;
```

- [ ] **Step 4: Add mobile config path duplicate**

In `src/seed_agent/web/static/index.html`, under the existing `div.config-path`, add:

```html
            <div class="mobile-config-path" data-mobile-config-path>配置文件: 加载中</div>
```

In `src/seed_agent/web/static/app.js`, add:

```javascript
const mobileConfigPathLabel = document.querySelector("[data-mobile-config-path]");
```

In `renderSection()`, after setting `configPathLabel.textContent`, add:

```javascript
  if (mobileConfigPathLabel) {
    mobileConfigPathLabel.textContent = configPathLabel.textContent;
  }
```

- [ ] **Step 5: Add mobile CSS**

In base CSS near `.config-path`, add:

```css
.mobile-config-path {
  display: none;
}
```

Inside `@media (max-width: 700px)`, add:

```css
  .config-path {
    display: none;
  }

  .mobile-config-path {
    color: var(--muted);
    display: block;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    margin-top: 8px;
    overflow-wrap: anywhere;
  }
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
uv run pytest -q tests/test_web_static.py::test_mobile_header_and_want_empty_state_are_operator_focused tests/test_web_static.py::test_index_contains_tracker_first_ui_anchors tests/test_mobile_ui_uses_touch_sized_controls_and_modal_actions
```

Expected: PASS.

- [ ] **Step 7: Browser verify mobile viewport**

Start WebUI and inspect a 390x844 viewport. Verify:

- No horizontal overflow.
- Mobile section selector remains visible.
- Config path is de-emphasized and does not crowd the main header actions.
- Want List empty state gives the next operation path.

- [ ] **Step 8: Commit**

```bash
git add src/seed_agent/web/static/index.html src/seed_agent/web/static/app.js src/seed_agent/web/static/styles.css tests/test_web_static.py
git commit -m "fix: tighten mobile webui operator states"
```

---

### Task 6: Improve Web Command Port Conflict Message

**Files:**
- Modify: `src/seed_agent/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Append near `test_web_help_includes_local_server_options` in `tests/test_cli.py`:

```python
def test_web_reports_actionable_port_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from seed_agent.cli import app
    from seed_agent.web import app as web_app

    import errno

    def raise_port_conflict(config_path: Path, host: str, port: int) -> None:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(web_app, "serve", raise_port_conflict)

    result = CliRunner().invoke(
        app,
        [
            "web",
            "--config",
            str(_config_file(tmp_path)),
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
    )

    assert result.exit_code != 0
    assert "port 8765 is already in use" in result.output
    assert "try --port 8766" in result.output
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest -q tests/test_cli.py::test_web_reports_actionable_port_conflict
```

Expected: FAIL because the raw traceback is not converted to actionable output.

- [ ] **Step 3: Implement actionable error**

In `src/seed_agent/cli.py`, import `errno` at the top:

```python
import errno
```

In `web()`, replace:

```python
    serve(config, host, port)
```

with:

```python
    try:
        serve(config, host, port)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            next_port = port + 1
            typer.echo(
                f"port {port} is already in use on {host}; try --port {next_port}",
                err=True,
            )
            raise typer.Exit(1) from exc
        raise
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
uv run pytest -q tests/test_cli.py::test_web_reports_actionable_port_conflict tests/test_cli.py::test_web_help_includes_local_server_options
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/seed_agent/cli.py tests/test_cli.py
git commit -m "fix: explain webui port conflicts"
```

---

### Task 7: Add Operator Guide And Update Project Docs

**Files:**
- Create: `docs/operations/web-ui-operator-guide.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/roadmap.md`
- Test: `tests/test_project_metadata.py` if it has doc-link checks; otherwise use `rg`.

- [ ] **Step 1: Create guide**

Create `docs/operations/web-ui-operator-guide.md`:

```markdown
# Web UI Operator Guide

`seed-agent web` is a local operator console for a Docker-first automation app.
It does not replace the CLI, the mounted YAML config, or the audit log.

## Use The Web UI For

- checking scheduler heartbeat and local state counts,
- editing common config sections with schema validation and diff preview,
- configuring Douban and IMDb Want List sources,
- refreshing Want List sources,
- running search-only Want List candidate discovery,
- previewing a candidate enqueue before confirming qB mutation.

## Use The CLI For

- release and deployment checks,
- full `run-once`, `schedule-run`, `review`, `daily-report`, and `strategy-report`,
- bulk cleanup planning and execution,
- scripted or repeatable operations,
- diagnosis that needs full JSON output.

## Risk Levels

| Surface | Risk | Notes |
| --- | --- | --- |
| Status | Read-only | Reads `.seed-agent/state.db` and `state/schedule-heartbeat.json`. |
| Config preview | Read-only | Validates and shows diff without writing YAML. |
| Config save | Local config write | Writes only the selected YAML section after full schema validation. |
| Want List refresh | Local state write | Ingests configured Douban/IMDb source events into local SQLite. |
| Want List search | Local state write | Searches providers and stores ranked candidates; does not call qB enqueue. |
| Enqueue preview | Downloader dry-run | Resolves policy and selected release without adding a task to qB. It may still read downloader/runtime state for preview. |
| Enqueue confirm | qB mutation | Sends the selected candidate to qB and writes audit decisions. |

## Runtime Provenance

The active config path and the runtime state path are related but not identical.
When the config lives under `config/`, Web UI reads runtime files from the
workspace root:

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`
- `state/schedule-heartbeat.json`

Always check the runtime provenance block on the Status page before treating
counts as evidence for the active deployment.

## Recommended Operator Flow

1. Open Status and confirm the config path, runtime root, state DB, and heartbeat file.
2. Open Want List and refresh configured sources.
3. Search current filters.
4. Open a candidate list and review score, tags, size, seeders, leechers, risks, and reasons.
5. Preview enqueue.
6. Confirm qB enqueue only when category, pause behavior, and selected release are correct.

## Safety Notes

- Search does not add torrents to qB.
- Preview does not add torrents to qB.
- Confirm enqueue is a qB mutation.
- Cleanup remains CLI-first and should start from an explicit candidate list.
- Secrets stay in `local/secrets/*`; Web UI stores references, not plaintext config values.
```

- [ ] **Step 2: Update README link**

In `README.md`, under the Web Settings UI paragraph or Docs list, add:

```markdown
- [Web UI Operator Guide](docs/operations/web-ui-operator-guide.md)
```

Also add this sentence near Web Settings UI description:

```markdown
Use the Web UI for local status, safe config edits, Want List review, and preview-first candidate enqueue. Use the CLI for full scheduled runs, cleanup, strategy reports, and release workflows.
```

- [ ] **Step 3: Update architecture supported features**

In `docs/architecture.md`, update the Web UI row to mention:

```markdown
runtime provenance, preview-first candidate enqueue,
```

Keep the existing statement that it is a local settings/status surface.

- [ ] **Step 4: Update roadmap**

In `docs/roadmap.md`, under `Next P1 - Web UI polish`, add:

```markdown
  - Continue refining operator summaries and preset-based strategy controls after the preview-first enqueue hardening.
```

If implementation is completed, add a completed entry:

```markdown
- Completed 2026-06 - Web UI product hardening
  - Fixed Config File navigation, surfaced runtime provenance, made Want List qB enqueue preview-first, added strategy summaries/presets, tightened mobile empty states, and documented WebUI risk levels.
```

- [ ] **Step 5: Verify docs references**

Run:

```bash
rg -n "Web UI Operator Guide|preview-first|runtime provenance|web-ui-operator-guide" README.md docs/architecture.md docs/roadmap.md docs/operations/web-ui-operator-guide.md
```

Expected: output includes all four files.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/architecture.md docs/roadmap.md docs/operations/web-ui-operator-guide.md
git commit -m "docs: add webui operator guide"
```

---

### Task 8: Python Baseline, Version Bump, And Final Verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `VERSION`
- Modify: `src/seed_agent/__init__.py`
- Modify: `tests/test_package_import.py`
- Modify: `docs/operations/release-process.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Classify release**

This implementation changes published WebUI behavior and operator safety. Classify as a code/operational fix with UI refinement. Bump patch from `0.11.1` to `0.11.2`.

- [ ] **Step 2: Formalize Python 3.14+ baseline**

In `pyproject.toml`, update:

```toml
requires-python = ">=3.14"

[tool.ruff]
target-version = "py314"
```

Run:

```bash
uv lock
uv run python --version
```

Expected: lockfile refresh succeeds and reports Python 3.14.x.

- [ ] **Step 3: Run version bump helper**

Run:

```bash
uv run python scripts/bump_version.py 0.11.2
```

Expected: `VERSION`, `pyproject.toml`, `src/seed_agent/__init__.py`, `tests/test_package_import.py`, and release docs update to `0.11.2`.

- [ ] **Step 4: Update CHANGELOG**

In `CHANGELOG.md`, under `Unreleased` or a new `0.11.2` section, add:

```markdown
## 0.11.2

- Fixed Web UI Config File navigation.
- Added Status-page runtime provenance for config, state DB, and heartbeat paths.
- Made Want List candidate enqueue preview-first before qB mutation.
- Added operator strategy summaries and release preference presets.
- Improved mobile Web UI empty states and Web UI port conflict guidance.
- Added a Web UI operator guide.
- Raised the supported Python runtime baseline to 3.14+.
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_web_static.py tests/test_web_settings.py tests/test_cli.py::test_web_help_includes_local_server_options tests/test_cli.py::test_web_reports_actionable_port_conflict tests/test_package_import.py
```

Expected: PASS.

- [ ] **Step 6: Run full verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
```

Expected: both PASS.

- [ ] **Step 7: Browser smoke test**

Run:

```bash
uv run seed-agent web --config config/example.yaml --host 127.0.0.1 --port 8876
```

Verify:

- `状态` shows runtime provenance.
- `配置文件` opens without console errors.
- Mobile viewport has no horizontal overflow.
- `想看列表` empty state explains next step.
- `资源匹配` shows strategy summary and presets.
- Candidate review is preview-first when candidates are present.

- [ ] **Step 8: Commit release metadata**

```bash
git add pyproject.toml uv.lock VERSION src/seed_agent/__init__.py tests/test_package_import.py docs/operations/release-process.md CHANGELOG.md
git commit -m "chore: bump version to 0.11.2"
```

---

## Self-Review Checklist

- Spec coverage:
  - Config File navigation bug: Task 1.
  - WebUI product boundary and qB risk: Task 3.
  - Runtime/config provenance: Task 2.
  - Strategy settings overload and presets: Task 4.
  - Mobile header and Want List empty state: Task 5.
  - CLI port conflict affordance: Task 6.
  - WebUI/CLI docs and risk levels: Task 7.
  - Release policy: Task 8.
- Placeholder scan:
  - No `TBD`, `TODO`, or vague "add tests" steps.
  - Each code-changing task includes exact test names and implementation snippets.
- Type consistency:
  - API fields use `runtime_root`, `state_path`, and `heartbeat_file`.
  - Frontend state uses `runtimeRoot`, `statePath`, and `heartbeatFile`.
  - Want enqueue body uses `execute: false` for preview and `execute: true` for confirm.

## Execution Options

Plan complete. Recommended execution:

1. **Subagent-Driven**: one fresh subagent per task, main agent reviews after each task.
2. **Inline Execution**: execute tasks in this session in order, with checkpoint verification after Tasks 1, 3, 5, and 8.

Use Subagent-Driven if speed matters. Use Inline Execution if you want tighter continuity over product decisions.
