# qB Category Policy And Budgeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single qB managed-category model with shared budget pools and per-category policy so `seed-agent` can manage `seed` as a mutable pool while treating `movie` and `tv` as add-only categories.

**Architecture:** Add a unified `CategoryPolicy` plus shared `BudgetPool` configuration to `DownloaderConfig`, then route enqueue/review/prune/report flows through pool-aware helpers. Keep the current product boundary qB-only by computing budget pressure from torrent `size` totals and using qB paused-add behavior instead of NAS disk inspection.

**Tech Stack:** Python 3.14, Typer, Pydantic v2, httpx, pytest, qBittorrent Web API

---

## File Structure

- `src/seed_agent/config.py`
  - Add `CategoryPolicyConfig`, `BudgetPoolConfig`, `CategoryMode`, and the new downloader config shape.
- `src/seed_agent/downloaders/base.py`
  - Extend the downloader protocol to support paused add behavior.
- `src/seed_agent/downloaders/qbittorrent.py`
  - Implement paused adds through qB Web API.
- `src/seed_agent/policies/category_policy.py`
  - New helper module for pool usage aggregation, category lookup, and over-budget decisions.
- `src/seed_agent/policies/eviction.py`
  - New helper module for composite ranking of mutable-category eviction candidates.
- `src/seed_agent/actions/qb.py`
  - Route enqueue and prune through category policy objects instead of a single category/tag pair.
- `src/seed_agent/cli.py`
  - Switch review, prune, daily-report, run-once, and intent enqueue paths to policy/pool-aware behavior.
- `config/example.yaml`
  - Migrate example config to `default_category`, `category_policies`, and `budget_pools`.
- `docs/operations/phase-1-usage.md`
  - Update operator-facing examples and budget semantics.
- `docs/roadmap.md`
  - Already references the spec; verify wording still matches shipped behavior.
- `tests/test_config.py`
  - Validate the new downloader config shape.
- `tests/test_phase2_config.py`
  - Keep Phase 2 config validation aligned with the new downloader shape.
- `tests/test_qbittorrent.py`
  - Add paused-add coverage.
- `tests/test_enqueue_action.py`
  - Verify over-budget add-paused behavior and policy-driven enqueue state.
- `tests/test_prune_action.py`
  - Verify add-only categories never auto-delete and mutable categories can evict ranked losers.
- `tests/test_cleanup.py`
  - Keep existing cleanup protections intact while policy scope shifts.
- `tests/test_cli.py`
  - Verify review/prune/report output includes pool/category policy context.
- `tests/test_run_once.py`
  - Verify the PT loop uses `default_category` and paused-add when over budget.
- `tests/test_intent_enqueue.py`
  - Verify intent enqueue uses `default_category`.
- `tests/test_intent_run_once.py`
  - Verify intent run-once stays compatible with the new downloader config.

## Plan Review Notes

This plan resolves one implementation gap that the spec leaves open: current enqueue commands do not know how to pick a category when multiple category policies exist. To keep scope bounded and behavior explicit, this implementation adds `downloader.default_category` and keeps all existing automatic enqueue flows targeting that one category unless a later feature introduces smarter routing.

### Task 1: Add downloader category-policy and budget-pool config

**Files:**
- Modify: `src/seed_agent/config.py`
- Modify: `config/example.yaml`
- Test: `tests/test_config.py`
- Test: `tests/test_phase2_config.py`

- [ ] **Step 1: Write the failing config test for category policies and pools**

```python
def test_load_config_supports_category_policies_and_budget_pools(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode: balanced
sites:
  - name: demo
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
discovery:
  discounts: ["free"]
  min_left_time_minutes: 120
  min_leechers: 8
  max_seeders: 80
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
  target: unraid-qb
  default_category: seed
  secret_ref: local/secrets/qbittorrent.yaml
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: ["seed-agent", "movie"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.downloader.default_category == "seed"
    assert [policy.name for policy in config.downloader.category_policies] == ["seed", "movie"]
    assert [pool.name for pool in config.downloader.budget_pools] == ["downloads", "media"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_config.py -k category_policies_and_budget_pools`
Expected: FAIL with a validation or attribute error because `DownloaderConfig` does not yet define `default_category`, `category_policies`, or `budget_pools`

- [ ] **Step 3: Implement the new downloader config models**

```python
class CategoryPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    mode: Literal["mutable", "add_only"]
    budget_pool: str
    delete_enabled: bool
    over_budget_behavior: Literal["add_paused"]
    tags: list[str] = Field(default_factory=list)


class BudgetPoolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    max_size_tib: float

    @model_validator(mode="after")
    def validate_positive_size(self) -> BudgetPoolConfig:
        if self.max_size_tib <= 0:
            raise ValueError("max_size_tib must be > 0")
        return self


class DownloaderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["qbittorrent"]
    target: str
    default_category: str
    secret_ref: str | None = None
    category_policies: list[CategoryPolicyConfig] = Field(default_factory=list)
    budget_pools: list[BudgetPoolConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_category_policy_links(self) -> DownloaderConfig:
        pool_names = {pool.name for pool in self.budget_pools}
        if self.default_category not in {policy.name for policy in self.category_policies}:
            raise ValueError("default_category must match a configured category policy")
        for policy in self.category_policies:
            if policy.budget_pool not in pool_names:
                raise ValueError(
                    f"category policy {policy.name} references unknown budget pool {policy.budget_pool}"
                )
        return self
```

- [ ] **Step 4: Update the example config to the new shape**

```yaml
downloader:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  secret_ref: local/secrets/qbittorrent.yaml
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: [seed-agent, seed]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: [seed-agent, movie]
    - name: tv
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: [seed-agent, tv]
  budget_pools:
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
```

- [ ] **Step 5: Add Phase 2 config coverage for the new downloader shape**

```python
def test_phase_two_config_accepts_category_policy_downloader_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "phase2.yaml"
    config_path.write_text(
        _PHASE2_CONFIG_TEXT.replace(
            "downloader:\n  type: qbittorrent\n  target: unraid-qb\n  category: pt-auto\n  tags: [\"seed-agent\", \"pt-auto\"]\n  secret_ref: local/secrets/qbittorrent.yaml",
            "downloader:\n  type: qbittorrent\n  target: unraid-qb\n  default_category: seed\n  secret_ref: local/secrets/qbittorrent.yaml\n  category_policies:\n    - name: seed\n      mode: mutable\n      budget_pool: downloads\n      delete_enabled: true\n      over_budget_behavior: add_paused\n      tags: [\"seed-agent\", \"seed\"]\n  budget_pools:\n    - name: downloads\n      max_size_tib: 10",
        ),
        encoding=\"utf-8\",
    )

    config = load_config(config_path)

    assert config.downloader.default_category == "seed"
```

- [ ] **Step 6: Run config tests to verify they pass**

Run: `uv run pytest -q tests/test_config.py tests/test_phase2_config.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/seed_agent/config.py config/example.yaml tests/test_config.py tests/test_phase2_config.py
git commit -m "feat: add qbt category policy config"
```

### Task 2: Add qB paused-add support and pool usage helpers

**Files:**
- Modify: `src/seed_agent/downloaders/base.py`
- Modify: `src/seed_agent/downloaders/qbittorrent.py`
- Create: `src/seed_agent/policies/category_policy.py`
- Test: `tests/test_qbittorrent.py`
- Test: `tests/test_category_policy.py`

- [ ] **Step 1: Write the failing paused-add downloader test**

```python
@respx.mock
async def test_add_url_can_request_paused_state() -> None:
    respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=Response(200, text="Ok.")
    )
    add_route = respx.post("https://qb.example/api/v2/torrents/add").mock(
        return_value=Response(200, text="Ok.")
    )

    client = QbittorrentClient("https://qb.example", "alice", "secret")

    await client.add_url(
        "https://tracker.example/download?id=1",
        category="seed",
        tags=["seed-agent", "seed"],
        paused=True,
    )

    assert add_route.called
    assert add_route.calls.last.request.content.decode().count("stopped=true") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_qbittorrent.py -k paused_state`
Expected: FAIL because `add_url()` does not accept a `paused` parameter yet

- [ ] **Step 3: Extend the downloader protocol and qB client**

```python
class Downloader(Protocol):
    async def add_url(
        self,
        url: str,
        category: str,
        tags: list[str],
        *,
        paused: bool = False,
    ) -> str | None: ...
```

```python
async def add_url(
    self,
    url: str,
    category: str,
    tags: list[str],
    *,
    paused: bool = False,
) -> str | None:
    async with self._client() as client:
        response = await self._post_form(
            client,
            "/api/v2/torrents/add",
            {
                "urls": url,
                "category": category,
                "tags": ",".join(tags),
                "stopped": "true" if paused else "false",
            },
        )
        return _extract_add_hash(response)
```

- [ ] **Step 4: Write the failing pool-usage helper test**

```python
def test_usage_by_pool_aggregates_categories_sharing_a_budget_pool() -> None:
    policies = [
        CategoryPolicyConfig(
            name="movie",
            mode="add_only",
            budget_pool="media",
            delete_enabled=False,
            over_budget_behavior="add_paused",
            tags=["seed-agent", "movie"],
        ),
        CategoryPolicyConfig(
            name="tv",
            mode="add_only",
            budget_pool="media",
            delete_enabled=False,
            over_budget_behavior="add_paused",
            tags=["seed-agent", "tv"],
        ),
    ]
    torrents = [
        _torrent(category="movie", size_bytes=3 * 1024**4),
        _torrent(category="tv", size_bytes=2 * 1024**4),
    ]

    usage = usage_by_pool(policies, torrents)

    assert usage["media"].size_bytes == 5 * 1024**4
```

- [ ] **Step 5: Run helper test to verify it fails**

Run: `uv run pytest -q tests/test_category_policy.py -k usage_by_pool`
Expected: FAIL because `src/seed_agent/policies/category_policy.py` does not exist yet

- [ ] **Step 6: Implement pool/category helper utilities**

```python
@dataclass(frozen=True)
class PoolUsage:
    pool_name: str
    size_bytes: int
    max_size_bytes: int

    @property
    def over_budget(self) -> bool:
        return self.size_bytes > self.max_size_bytes


def pool_size_bytes(pool: BudgetPoolConfig) -> int:
    return int(pool.max_size_tib * 1024**4)


def usage_by_pool(
    policies: Sequence[CategoryPolicyConfig],
    pools: Sequence[BudgetPoolConfig],
    torrents: Sequence[ManagedTorrent],
) -> dict[str, PoolUsage]:
    pool_lookup = {pool.name: pool for pool in pools}
    category_to_pool = {policy.name: policy.budget_pool for policy in policies}
    totals = {pool.name: 0 for pool in pools}
    for torrent in torrents:
        if torrent.category not in category_to_pool:
            continue
        totals[category_to_pool[torrent.category]] += torrent.size_bytes
    return {
        pool.name: PoolUsage(
            pool_name=pool.name,
            size_bytes=totals[pool.name],
            max_size_bytes=pool_size_bytes(pool),
        )
        for pool in pools
    }
```

- [ ] **Step 7: Run downloader and helper tests to verify they pass**

Run: `uv run pytest -q tests/test_qbittorrent.py tests/test_category_policy.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/seed_agent/downloaders/base.py src/seed_agent/downloaders/qbittorrent.py src/seed_agent/policies/category_policy.py tests/test_qbittorrent.py tests/test_category_policy.py
git commit -m "feat: add qbt paused add and pool helpers"
```

### Task 3: Make enqueue and prune policy-aware

**Files:**
- Create: `src/seed_agent/policies/eviction.py`
- Modify: `src/seed_agent/actions/qb.py`
- Test: `tests/test_enqueue_action.py`
- Test: `tests/test_prune_action.py`
- Test: `tests/test_cleanup.py`
- Test: `tests/test_eviction.py`

- [ ] **Step 1: Write the failing over-budget enqueue test**

```python
async def test_execute_accepted_candidate_adds_paused_when_pool_is_over_budget() -> None:
    downloader = DummyDownloader(torrent_hash="0123456789abcdef0123456789abcdef01234567")
    policy = CategoryPolicyConfig(
        name="seed",
        mode="mutable",
        budget_pool="downloads",
        delete_enabled=True,
        over_budget_behavior="add_paused",
        tags=["seed-agent", "seed"],
    )

    decisions = await enqueue_candidates(
        [_scored()],
        downloader,
        policy,
        execute=True,
        paused=True,
    )

    assert downloader.calls == [
        (
            "https://tracker.example/download.php?id=1&passkey=secret",
            "seed",
            ["seed-agent", "seed"],
            True,
        )
    ]
    assert decisions[0].new_state["paused"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_enqueue_action.py -k over_budget`
Expected: FAIL because `enqueue_candidates()` still expects plain category/tag arguments

- [ ] **Step 3: Refactor enqueue decisions around `CategoryPolicyConfig`**

```python
async def enqueue_candidates(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    downloader: Downloader,
    policy: CategoryPolicyConfig,
    execute: bool,
    *,
    paused: bool = False,
) -> list[Decision]:
    decisions: list[Decision] = []
    for item in scored:
        if not item.accepted:
            continue
        candidate = item.candidate
        new_state = {
            "candidate_id": item.candidate_id,
            "candidate_title": candidate.title,
            "download_url": candidate.download_url,
            "category": policy.name,
            "tags": list(policy.tags),
            "paused": paused,
            "score": item.score,
            "reasons": list(item.reasons),
        }
        torrent_hash = None
        if execute:
            torrent_hash = await downloader.add_url(
                candidate.download_url,
                policy.name,
                list(policy.tags),
                paused=paused,
            )
        if torrent_hash is not None:
            new_state["torrent_hash"] = torrent_hash
        decisions.append(
            Decision(
                action="qb.enqueue",
                target_id=item.candidate_id,
                execute=execute,
                reason=_build_reason(item),
                new_state=new_state,
                rollback=ROLLBACK_INSTRUCTION,
            )
        )
    return decisions
```

- [ ] **Step 4: Write the failing eviction ranking test**

```python
def test_rank_eviction_candidates_prefers_low_upload_density_large_cold_torrents() -> None:
    ranked = rank_eviction_candidates(
        [
            _torrent(
                hash="keep",
                size_bytes=20 * 1024**3,
                uploaded_bytes=200 * 1024**3,
                metadata={"recent_upload_gb": 40},
            ),
            _torrent(
                hash="drop",
                size_bytes=400 * 1024**3,
                uploaded_bytes=2 * 1024**3,
                metadata={"recent_upload_gb": 0.2},
            ),
        ]
    )

    assert ranked[0].hash == "drop"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest -q tests/test_eviction.py -k rank_eviction_candidates`
Expected: FAIL because `src/seed_agent/policies/eviction.py` does not exist yet

- [ ] **Step 6: Implement composite eviction ranking**

```python
@dataclass(frozen=True)
class EvictionCandidate:
    torrent: ManagedTorrent
    score: float


def rank_eviction_candidates(torrents: Sequence[ManagedTorrent]) -> list[ManagedTorrent]:
    def eviction_score(torrent: ManagedTorrent) -> float:
        recent_upload = float(torrent.metadata.get("recent_upload_gb", 0) or 0)
        size_gib = torrent.size_bytes / 1024**3
        uploaded_gib = torrent.uploaded_bytes / 1024**3
        upload_density = uploaded_gib / size_gib if size_gib else 0
        activity_penalty = 0 if torrent.last_activity_at else 25
        return (size_gib * 0.05) + activity_penalty - (recent_upload * 2.0) - (upload_density * 10.0)

    return [
        candidate.torrent
        for candidate in sorted(
            (EvictionCandidate(torrent=torrent, score=eviction_score(torrent)) for torrent in torrents),
            key=lambda item: item.score,
            reverse=True,
        )
    ]
```

- [ ] **Step 7: Make prune accept mutable policy scope and protect add-only categories**

```python
async def prune_cold_torrents(
    torrents: Sequence[ManagedTorrent] | Iterable[ManagedTorrent],
    downloader: Downloader,
    cleanup: CleanupConfig,
    policy: CategoryPolicyConfig,
    execute: bool,
) -> list[Decision]:
    if policy.mode != "mutable" or not policy.delete_enabled:
        return [
            Decision(
                action="qb.cleanup.protect",
                target_id=torrent.hash,
                execute=execute,
                reason=f"cleanup protect: category {policy.name} is add_only or delete-disabled",
                old_state=torrent.model_dump(mode="json"),
                new_state={
                    "torrent_hash": torrent.hash,
                    "cleanup_action": "protect",
                    "managed": False,
                    "protected": True,
                },
            )
            for torrent in torrents
        ]
    return _prune_mutable_category(torrents, downloader, cleanup, policy, execute)
```

- [ ] **Step 8: Run action and policy tests to verify they pass**

Run: `uv run pytest -q tests/test_enqueue_action.py tests/test_prune_action.py tests/test_cleanup.py tests/test_eviction.py`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/seed_agent/actions/qb.py src/seed_agent/policies/eviction.py tests/test_enqueue_action.py tests/test_prune_action.py tests/test_cleanup.py tests/test_eviction.py
git commit -m "feat: add policy-aware qbt enqueue and prune"
```

### Task 4: Wire CLI review, report, and run loops through policies and pools

**Files:**
- Modify: `src/seed_agent/cli.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_run_once.py`
- Test: `tests/test_intent_enqueue.py`
- Test: `tests/test_intent_run_once.py`

- [ ] **Step 1: Write the failing review output test**

```python
def test_review_reports_pool_usage_and_category_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from seed_agent import cli

    config_path = _config_file(tmp_path)
    config = _config_with_category_policies()

    class FakeDownloader:
        async def list_torrents(self, category=None, tags=None):
            return [
                _managed_torrent(category="seed", size_bytes=3 * 1024**4),
                _managed_torrent(category="movie", size_bytes=2 * 1024**4, tags={"seed-agent", "movie"}),
            ]

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda loaded: FakeDownloader())

    result = CliRunner().invoke(cli.app, ["review", "--config", str(config_path)])
    payload = _json_output(result)

    assert payload["pool_usage"]["downloads"]["size_tib"] == 3.0
    assert payload["pool_usage"]["media"]["size_tib"] == 2.0
    assert payload["managed_torrents"][0]["policy_mode"] == "mutable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_cli.py -k pool_usage_and_category_mode`
Expected: FAIL because review output does not expose policy/pool data yet

- [ ] **Step 3: Add policy and pool resolution helpers to the CLI**

```python
def _policy_by_name(config: SeedAgentConfig) -> dict[str, CategoryPolicyConfig]:
    return {policy.name: policy for policy in config.downloader.category_policies}


def _default_category_policy(config: SeedAgentConfig) -> CategoryPolicyConfig:
    policies = _policy_by_name(config)
    return policies[config.downloader.default_category]


def _pool_usage_summary(
    config: SeedAgentConfig,
    torrents: list[ManagedTorrent],
) -> dict[str, dict[str, float | bool]]:
    usage = usage_by_pool(
        config.downloader.category_policies,
        config.downloader.budget_pools,
        torrents,
    )
    return {
        name: {
            "size_tib": round(item.size_bytes / 1024**4, 2),
            "max_size_tib": round(item.max_size_bytes / 1024**4, 2),
            "over_budget": item.over_budget,
        }
        for name, item in usage.items()
    }
```

- [ ] **Step 4: Route run-once and intent enqueue through `default_category` and paused-over-budget behavior**

```python
policy = _default_category_policy(loaded)
usage = usage_by_pool(
    loaded.downloader.category_policies,
    loaded.downloader.budget_pools,
    current_torrents,
)
pool = usage[policy.budget_pool]
paused = pool.over_budget and policy.over_budget_behavior == "add_paused"
decisions = _run(
    enqueue_candidates(
        scored,
        downloader,
        policy,
        execute,
        paused=paused,
    )
)
```

- [ ] **Step 5: Update managed torrent summaries and review/report payloads**

```python
def _managed_torrent_summary(
    torrent: ManagedTorrent,
    policy: CategoryPolicyConfig | None = None,
) -> dict[str, Any]:
    summary = {
        "hash": torrent.hash,
        "name": torrent.name,
        "category": torrent.category,
        "tags": sorted(torrent.tags),
        "state": torrent.state,
        "size_gb": round(torrent.size_bytes / (1024**3), 2),
        "uploaded_gb": round(torrent.uploaded_bytes / (1024**3), 2),
    }
    if policy is not None:
        summary["policy_mode"] = policy.mode
        summary["budget_pool"] = policy.budget_pool
    return summary
```

- [ ] **Step 6: Run CLI-focused tests to verify they pass**

Run: `uv run pytest -q tests/test_cli.py tests/test_run_once.py tests/test_intent_enqueue.py tests/test_intent_run_once.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/seed_agent/cli.py tests/test_cli.py tests/test_run_once.py tests/test_intent_enqueue.py tests/test_intent_run_once.py
git commit -m "feat: wire qbt category policies into cli flows"
```

### Task 5: Update operator docs and run the verification suite

**Files:**
- Modify: `docs/operations/phase-1-usage.md`
- Modify: `README.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Update docs to show category policies and shared pools**

```yaml
downloader:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  secret_ref: local/secrets/qbittorrent.yaml
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: [seed-agent, seed]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: [seed-agent, movie]
  budget_pools:
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
```

- [ ] **Step 2: Explain the logical-budget boundary in prose**

```markdown
`seed-agent` budgets qB categories by logical torrent size, not by NAS share inspection.
If a budget pool is over limit, new torrents may still be added to qB in a paused state.
Mutable categories may evict lower-value torrents automatically; add-only categories never auto-delete.
```

- [ ] **Step 3: Run the full targeted verification suite**

Run: `uv run pytest -q tests/test_config.py tests/test_phase2_config.py tests/test_qbittorrent.py tests/test_category_policy.py tests/test_eviction.py tests/test_enqueue_action.py tests/test_prune_action.py tests/test_cleanup.py tests/test_cli.py tests/test_run_once.py tests/test_intent_enqueue.py tests/test_intent_run_once.py`
Expected: PASS

- [ ] **Step 4: Run lint**

Run: `uv run ruff check .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations/phase-1-usage.md docs/roadmap.md
git commit -m "docs: describe qbt category policy budgeting"
```
