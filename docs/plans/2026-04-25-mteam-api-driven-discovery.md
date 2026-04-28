# M-Team API-Driven Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive M-Team API discovery mode that supports FREE filtering and activity-based sorting while preserving the existing RSS path and downstream `TorrentCandidate` pipeline unchanged.

**Architecture:** Extend `SiteConfig` with M-Team-only discovery controls, add API list discovery beside the existing detail-enrichment client in `src/seed_agent/sites/mteam.py`, and dispatch per-site discovery in `src/seed_agent/actions/pt.py`. Keep `TorrentCandidate` as the stable boundary so scoring, enqueue, and audit code remain unchanged, then expose the chosen discovery mode in `site-probe` and docs.

**Tech Stack:** Python 3.14, Typer CLI, Pydantic v2, httpx, pytest, respx, YAML config

---

## File Structure

- `src/seed_agent/config.py`
  Defines `discovery_mode` and `api_discovery` for `mteam` sites, validates that API mode is only used on `mteam`, and keeps the existing RSS-first shape valid. `api_discovery` is versioned config in the site YAML, while `api_key_ref` and `cookie_ref` remain secret references.
- `src/seed_agent/sites/mteam.py`
  Owns M-Team API behavior: config-backed query construction, API list discovery, response normalization, existing detail enrichment, and download token reuse.
- `src/seed_agent/actions/pt.py`
  Chooses RSS or API discovery per site, resolves secrets once, and returns unified `TorrentCandidate` objects.
- `src/seed_agent/cli.py`
  Makes diagnostics show access mode plus discovery mode so operators can confirm whether `mteam` is using API or RSS.
- `config/example.yaml`
  Documents the recommended M-Team API mode shape without removing RSS.
- `tests/test_config.py`
  Locks config validation and backwards compatibility.
- `tests/test_mteam_site.py`
  Covers M-Team API list discovery, query parameters, and candidate mapping.
- `tests/test_pt_actions.py`
  Verifies dispatcher behavior and secret wiring.
- `tests/test_cli.py`
  Verifies `site-probe` reports the selected discovery mode.
- `docs/ai/modules/discovery.md`
  Updates module guidance to reflect the new M-Team API path.
- `docs/ai/modules/mteam.md`
  Updates the M-Team module doc to state that API discovery is preferred and RSS remains fallback.
- `docs/roadmap.md`
  Moves the roadmap item from “Next” to “Completed” once implementation lands.

### Task 1: Add Config Support For M-Team API Discovery

**Files:**
- Modify: `src/seed_agent/config.py`
- Modify: `tests/test_config.py`
- Modify: `config/example.yaml`

`api_discovery` belongs in the checked-in config shape because it describes operator strategy such as filtering, sorting, and page size. Only credential material stays in `local/secrets/*`, referenced by `api_key_ref` or `cookie_ref`.

- [ ] **Step 1: Write the failing config tests**

```python
def test_mteam_site_accepts_api_discovery_mode() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["sites"] = [
        {
            "name": "mt",
            "type": "mteam",
            "enabled": True,
            "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
            "api_key_ref": "local/secrets/mt.api-key",
            "discovery_mode": "api",
            "api_discovery": {
                "mode": "adult",
                "only_free": True,
                "sort_field": "downloads",
                "sort_order": "desc",
                "page_size": 50,
                "min_seeders": 0,
                "max_seeders": 200,
                "min_leechers": 0,
                "min_times_completed": 0,
            },
        }
    ]

    config = SeedAgentConfig(**data)

    site = config.enabled_sites[0]
    assert site.discovery_mode == "api"
    assert site.api_discovery is not None
    assert site.api_discovery.sort_field == "downloads"


def test_non_mteam_site_rejects_api_discovery_mode() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["sites"][0] = {
        "name": "demo-free",
        "type": "nexusphp",
        "enabled": True,
        "rss_url": "https://tracker.example/rss.php",
        "discovery_mode": "api",
        "api_discovery": {
            "mode": "adult",
            "only_free": True,
            "sort_field": "downloads",
            "sort_order": "desc",
            "page_size": 50,
            "min_seeders": 0,
            "max_seeders": 200,
            "min_leechers": 0,
            "min_times_completed": 0,
        },
    }

    with pytest.raises(ValidationError, match="mteam"):
        SeedAgentConfig(**data)


def test_mteam_api_discovery_requires_api_key_ref() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["sites"] = [
        {
            "name": "mt",
            "type": "mteam",
            "enabled": True,
            "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
            "api_key_ref": None,
            "discovery_mode": "api",
            "api_discovery": {
                "mode": "adult",
                "only_free": True,
                "sort_field": "downloads",
                "sort_order": "desc",
                "page_size": 50,
                "min_seeders": 0,
                "max_seeders": 200,
                "min_leechers": 0,
                "min_times_completed": 0,
            },
        }
    ]

    with pytest.raises(ValidationError, match="api_key_ref"):
        SeedAgentConfig(**data)
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run: `uv run pytest -q tests/test_config.py -k "api_discovery or discovery_mode"`
Expected: FAIL with `ValidationError` mismatches or missing `SiteConfig` fields such as `discovery_mode` / `api_discovery`

- [ ] **Step 3: Add the minimal config models and validators**

```python
class MTeamApiDiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["adult", "movie", "tvshow", "normal"] = "adult"
    only_free: bool = True
    sort_field: Literal["createdDate", "id", "downloads", "seeders", "size"] = "downloads"
    sort_order: Literal["asc", "desc"] = "desc"
    page_size: int = 50
    min_seeders: int = 0
    max_seeders: int | None = 200
    min_leechers: int = 0
    min_times_completed: int = 0

    @model_validator(mode="after")
    def validate_limits(self) -> MTeamApiDiscoveryConfig:
        if self.page_size < 1:
            raise ValueError("page_size must be >= 1")
        if self.max_seeders is not None and self.max_seeders < self.min_seeders:
            raise ValueError("max_seeders must be >= min_seeders")
        return self


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    type: Literal["nexusphp", "mteam"]
    enabled: bool = True
    rss_url: str
    cookie_ref: str | None = None
    api_key_ref: str | None = None
    discovery_mode: Literal["rss", "api"] = "rss"
    api_discovery: MTeamApiDiscoveryConfig | None = None

    @model_validator(mode="after")
    def validate_discovery_mode(self) -> SiteConfig:
        if self.discovery_mode == "api":
            if self.type != "mteam":
                raise ValueError("discovery_mode=api is only supported for mteam")
            if self.api_discovery is None:
                raise ValueError("api_discovery must be set when discovery_mode=api")
            if not self.api_key_ref:
                raise ValueError("api_key_ref is required when discovery_mode=api")
        if self.type != "mteam" and self.api_discovery is not None:
            raise ValueError("api_discovery is only supported for mteam")
        return self
```

- [ ] **Step 4: Document the example config shape**

```yaml
sites:
  - name: mt
    type: mteam
    enabled: false
    rss_url: https://rss.m-team.cc/api/rss/fetch?dl=1&pageSize=10&sign=secret
    # Secret reference only. The token value itself stays in local/secrets/mt.api-key.
    api_key_ref: local/secrets/mt.api-key
    discovery_mode: api
    # Versioned strategy config. Keep this block in config, not in secrets.
    api_discovery:
      mode: adult
      only_free: true
      sort_field: downloads
      sort_order: desc
      page_size: 50
      min_seeders: 0
      max_seeders: 200
      min_leechers: 0
      min_times_completed: 0
    # Optional compatibility fallback for detail enrichment:
    cookie_ref: local/secrets/mt.cookie
```

- [ ] **Step 5: Run the config tests to verify they pass**

Run: `uv run pytest -q tests/test_config.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/example.yaml src/seed_agent/config.py tests/test_config.py
git commit -m "feat: add mteam api discovery config"
```

### Task 2: Add M-Team API List Discovery In The Site Adapter

**Files:**
- Modify: `src/seed_agent/sites/mteam.py`
- Modify: `tests/test_mteam_site.py`

- [ ] **Step 1: Write the failing M-Team discovery tests**

```python
@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_discovers_free_candidates_with_sorting() -> None:
    route = respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 1171443,
                            "name": "Inception 2010 1080p BluRay",
                            "discount": "FREE",
                            "size": "1234567890",
                            "status": {
                                "seeders": 15,
                                "leechers": 3,
                                "timesCompleted": 28,
                            },
                            "createdDate": "2026-04-24T01:02:03+00:00",
                        }
                    ]
                },
            },
        )
    )

    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=0,
            max_seeders=200,
            min_leechers=0,
            min_times_completed=0,
        ),
    )

    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "secret-api-key"
    assert request.content
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.site == "mt"
    assert candidate.discount.value == "free"
    assert candidate.seeders == 15
    assert candidate.metadata["mteam_discovery_mode"] == "api"
    assert candidate.metadata["times_completed"] == 28


@pytest.mark.asyncio
@respx.mock
async def test_mteam_api_client_filters_out_candidates_below_thresholds() -> None:
    respx.post("https://api.m-team.cc/api/torrent/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "data": [
                        {
                            "id": 1,
                            "name": "Too Cold",
                            "discount": "FREE",
                            "size": "1000",
                            "status": {"seeders": 1, "leechers": 0, "timesCompleted": 0},
                        }
                    ]
                },
            },
        )
    )

    client = MTeamApiClient(api_key="secret-api-key")
    candidates = await client.discover_torrents(
        site="mt",
        options=MTeamApiDiscoveryOptions(
            mode="adult",
            only_free=True,
            sort_field="downloads",
            sort_order="desc",
            page_size=50,
            min_seeders=5,
            max_seeders=200,
            min_leechers=1,
            min_times_completed=1,
        ),
    )

    assert candidates == []
```

- [ ] **Step 2: Run the M-Team tests to verify they fail**

Run: `uv run pytest -q tests/test_mteam_site.py -k "discover_torrents or threshold"`
Expected: FAIL with missing `discover_torrents`, missing `MTeamApiDiscoveryOptions`, or assertion failures around payload mapping

- [ ] **Step 3: Add the discovery options model and query builder**

```python
class MTeamApiDiscoveryOptions(BaseModel):
    mode: Literal["adult", "movie", "tvshow", "normal"] = "adult"
    only_free: bool = True
    sort_field: Literal["createdDate", "id", "downloads", "seeders", "size"] = "downloads"
    sort_order: Literal["asc", "desc"] = "desc"
    page_size: int = 50
    min_seeders: int = 0
    max_seeders: int | None = 200
    min_leechers: int = 0
    min_times_completed: int = 0


def _search_payload(options: MTeamApiDiscoveryOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": options.mode,
        "visible": 1,
        "pageNumber": 1,
        "pageSize": options.page_size,
        "sortDirection": options.sort_order.upper(),
        "sortField": options.sort_field,
    }
    if options.only_free:
        payload["discount"] = "FREE"
    return payload
```

- [ ] **Step 4: Implement API discovery and candidate mapping**

```python
async def discover_torrents(
    self,
    *,
    site: str,
    options: MTeamApiDiscoveryOptions,
) -> list[TorrentCandidate]:
    if not self.api_key:
        return []

    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
        "x-api-key": self.api_key,
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
        response = await client.post(
            f"{self.API_BASE_URL}/torrent/search",
            headers=headers,
            json=_search_payload(options),
        )
        response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        return []

    rows = _extract_search_rows(payload)
    return [
        candidate
        for candidate in (_candidate_from_search_row(site, row) for row in rows)
        if candidate is not None and _meets_thresholds(candidate, options)
    ]


def _candidate_from_search_row(site: str, row: dict[str, Any]) -> TorrentCandidate | None:
    torrent_id = _coerce_int(row.get("id"))
    title = str(row.get("name") or "").strip()
    if torrent_id is None or not title:
        return None

    status = row.get("status")
    status_data = status if isinstance(status, dict) else {}
    metadata = {
        "mteam_discovery_mode": "api",
        "times_completed": _coerce_int(status_data.get("timesCompleted")) or 0,
        "mteam_api_sort_field": row.get("sortField"),
    }

    return TorrentCandidate(
        site=site,
        title=title,
        source_url=f"https://kp.m-team.cc/detail/{torrent_id}",
        download_url=f"https://api.m-team.cc/api/torrent/genDlToken?id={torrent_id}",
        size_bytes=_coerce_int(row.get("size")) or 0,
        seeders=_coerce_int(status_data.get("seeders")) or 0,
        leechers=_coerce_int(status_data.get("leechers")) or 0,
        discount=_normalize_discount_label(row.get("discount")),
        published_at=_parse_api_datetime(row.get("createdDate")),
        metadata=metadata,
    )
```

- [ ] **Step 5: Reuse existing enrichment behavior only when it still adds value**

```python
async def fetch_api_candidates(
    *,
    site: str,
    api_key: str,
    options: MTeamApiDiscoveryOptions,
    cookie: str | None = None,
) -> list[TorrentCandidate]:
    client = MTeamApiClient(cookie=cookie, api_key=api_key)
    candidates = await client.discover_torrents(site=site, options=options)
    return await enrich_candidates(
        candidates,
        cookie=cookie,
        api_key=api_key,
        fetch_detail=client.fetch_torrent_detail,
    )
```

- [ ] **Step 6: Run the adapter tests to verify they pass**

Run: `uv run pytest -q tests/test_mteam_site.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/seed_agent/sites/mteam.py tests/test_mteam_site.py
git commit -m "feat: add mteam api discovery adapter"
```

### Task 3: Dispatch Discovery Per Site In PT Actions

**Files:**
- Modify: `src/seed_agent/actions/pt.py`
- Modify: `tests/test_pt_actions.py`

- [ ] **Step 1: Write the failing PT action tests**

```python
@pytest.mark.asyncio
async def test_discover_candidates_uses_mteam_api_mode_when_configured(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": "local/secrets/mt.api-key",
                    "discovery_mode": "api",
                    "api_discovery": {
                        "mode": "adult",
                        "only_free": True,
                        "sort_field": "downloads",
                        "sort_order": "desc",
                        "page_size": 50,
                        "min_seeders": 0,
                        "max_seeders": 200,
                        "min_leechers": 0,
                        "min_times_completed": 0,
                    },
                }
            ],
        }
    )

    called: list[tuple[str, str]] = []

    async def fake_fetch_api_candidates(*, site: str, api_key: str, options, cookie: str | None = None):
        called.append((site, api_key))
        return [_candidate(site=site, metadata={"mteam_discovery_mode": "api"})]

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fake_fetch_api_candidates)

    candidates = await pt_actions.discover_candidates(config)

    assert called == [("mt", "secret-api-key")]
    assert candidates[0].metadata["mteam_discovery_mode"] == "api"


@pytest.mark.asyncio
async def test_discover_candidates_keeps_rss_mode_for_non_api_sites(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    rss_calls: list[str] = []

    async def fake_fetch_rss_candidates(url: str, site: str, cookie=None, api_key=None, *, site_type="nexusphp"):
        rss_calls.append(site)
        return [_candidate(site=site)]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    candidates = await pt_actions.discover_candidates(_config())

    assert rss_calls == ["demo-free"]
    assert candidates[0].site == "demo-free"
```

- [ ] **Step 2: Run the PT action tests to verify they fail**

Run: `uv run pytest -q tests/test_pt_actions.py -k "mteam_api_mode or rss_mode"`
Expected: FAIL because `discover_candidates()` only calls `fetch_rss_candidates`

- [ ] **Step 3: Implement per-site dispatch with shared secret resolution**

```python
from seed_agent.sites.mteam import (
    MTeamApiDiscoveryOptions,
    fetch_api_candidates as fetch_mteam_api_candidates,
)


async def discover_candidates(config: SeedAgentConfig) -> list[TorrentCandidate]:
    tasks = [_discover_site_candidates(site, config.config_dir) for site in config.enabled_sites]
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    candidates: list[TorrentCandidate] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        candidates.extend(result)
    return candidates


async def _discover_site_candidates(site, config_dir: Path | None) -> list[TorrentCandidate]:
    cookie = _read_cookie(site.cookie_ref, config_dir)
    api_key = _read_secret(site.api_key_ref, config_dir)

    if site.type == "mteam" and site.discovery_mode == "api" and site.api_discovery is not None:
        return await fetch_mteam_api_candidates(
            site=site.name,
            api_key=api_key or "",
            cookie=cookie,
            options=MTeamApiDiscoveryOptions(**site.api_discovery.model_dump()),
        )

    return await fetch_rss_candidates(
        site.rss_url,
        site.name,
        cookie=cookie,
        api_key=api_key,
        site_type=site.type,
    )
```

- [ ] **Step 4: Run the PT action tests to verify they pass**

Run: `uv run pytest -q tests/test_pt_actions.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/seed_agent/actions/pt.py tests/test_pt_actions.py
git commit -m "feat: dispatch mteam discovery by mode"
```

### Task 4: Surface Discovery Mode In CLI Diagnostics

**Files:**
- Modify: `src/seed_agent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI diagnostic tests**

```python
def test_site_probe_reports_api_discovery_mode_for_mteam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path, secret_ref=None)
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": "local/secrets/mt.api-key",
                    "discovery_mode": "api",
                    "api_discovery": {
                        "mode": "adult",
                        "only_free": True,
                        "sort_field": "downloads",
                        "sort_order": "desc",
                        "page_size": 50,
                        "min_seeders": 0,
                        "max_seeders": 200,
                        "min_leechers": 0,
                        "min_times_completed": 0,
                    },
                }
            ],
        }
    )

    async def fake_discover_candidates(config: SeedAgentConfig):
        return [
            _candidate(
                site="mt",
                source_url="https://kp.m-team.cc/detail/1",
                metadata={"mteam_discovery_mode": "api", "times_completed": 10},
            )
        ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "discover_candidates", fake_discover_candidates)
    monkeypatch.setattr(cli, "_read_secret_ref", lambda secret_ref, config_dir: "secret-api-key")
    monkeypatch.setattr(cli, "_read_cookie_ref", lambda cookie_ref, config_dir: None)

    result = CliRunner().invoke(cli.app, ["site-probe", "--config", str(config_path)])

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["sites"]["mt"]["discovery_mode"] == "api"
```

- [ ] **Step 2: Run the CLI test to verify it fails**

Run: `uv run pytest -q tests/test_cli.py -k "discovery_mode_for_mteam"`
Expected: FAIL because `site-probe` does not include `discovery_mode`

- [ ] **Step 3: Add discovery-mode reporting without changing downstream command shape**

```python
for site in loaded.enabled_sites:
    summary_by_site[site.name] = {
        "site_type": site.type,
        "rss_url_configured": bool(site.rss_url),
        "access_mode": _site_access_mode(site, loaded.config_dir),
        "discovery_mode": _site_discovery_mode(site),
        "discovered": 0,
        "sparse": 0,
        "detail_enriched": 0,
        "sample_titles": [],
    }


def _site_discovery_mode(site) -> str:
    if site.type == "mteam":
        return site.discovery_mode
    return "rss"
```

- [ ] **Step 4: Run the CLI test suite to verify it passes**

Run: `uv run pytest -q tests/test_cli.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/seed_agent/cli.py tests/test_cli.py
git commit -m "feat: expose mteam discovery mode in diagnostics"
```

### Task 5: Update Documentation And Run Focused Regression Coverage

**Files:**
- Modify: `docs/ai/modules/discovery.md`
- Modify: `docs/ai/modules/mteam.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Write the doc updates**

```markdown
## Near-Term Work

- keep RSS solid for generic and fallback use,
- prefer `discovery_mode: api` for M-Team when `api_key_ref` is available,
- keep `TorrentCandidate` as the boundary between discovery and scoring.
```

```markdown
## Current Status

Implemented today:

- RSS candidate parsing for M-Team feed shape
- `x-api-key` detail enrichment
- API-driven discovery with FREE filtering and activity-based sorting
- `site-probe` visibility for authenticated M-Team access and discovery mode
```

```markdown
## Completed

### M-Team Current Integration

- M-Team RSS parsing
- M-Team `x-api-key` detail enrichment
- M-Team API-driven discovery with FREE filtering and activity-based sorting
- `site-probe` reporting for authenticated M-Team access and discovery mode
```

- [ ] **Step 2: Run the focused regression suite**

Run: `uv run pytest -q tests/test_config.py tests/test_mteam_site.py tests/test_pt_actions.py tests/test_cli.py tests/test_rss_site.py`
Expected: PASS

- [ ] **Step 3: Run manual CLI verification for the operator surface**

Run: `uv run seed-agent site-probe --config config/example.yaml`
Expected: JSON output with each site showing `site_type`, `access_mode`, and `discovery_mode`; M-Team reports `api` when configured that way

- [ ] **Step 4: Commit**

```bash
git add docs/ai/modules/discovery.md docs/ai/modules/mteam.md docs/roadmap.md
git commit -m "docs: record mteam api discovery"
```

## Self-Review

- Spec coverage: configuration shape, additive M-Team-only API mode, FREE filtering, downloads-oriented sorting, page-size bounds, unchanged `TorrentCandidate` boundary, `site-probe` diagnostics, and RSS preservation are all covered by Tasks 1-5.
- Placeholder scan: no `TODO`, `TBD`, or “similar to Task N” shortcuts remain; every task includes concrete files, commands, and code snippets.
- Type consistency: the plan consistently uses `discovery_mode`, `api_discovery`, `MTeamApiDiscoveryConfig`, `MTeamApiDiscoveryOptions`, `discover_torrents()`, and `fetch_mteam_api_candidates()`.

Plan complete and saved to `docs/plans/2026-04-25-mteam-api-driven-discovery.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
