# Phase 1 PT Upload Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable `seed-agent` loop: read config, discover RSS candidates, score them, optionally enqueue strong candidates to qBittorrent, review managed torrents, prune cold torrents under the balanced policy, and write redacted audit records for every external decision.

**Architecture:** Use a small Python package with explicit structured models, pure policy functions, downloader interfaces, and thin CLI/actions wrappers. State lives in local SQLite for lifecycle metadata; audit lives in append-only JSONL because operators and AI agents need easy inspection. External systems are isolated behind site and downloader adapters so tests can mock HTTP and Phase 2 can reuse the same action boundary.

**Tech Stack:** Python 3.12, `uv`, Pydantic v2, Typer, Rich, PyYAML, feedparser, httpx, sqlite3, pytest, respx, ruff.

---

## Source Inputs

- Product spec: `docs/superpowers/specs/2026-04-20-seed-agent-design.md`
- Repo handoff: `docs/operations/session-handoff.md`
- Research map: `docs/research/inspiration-pool.md`
- Product positioning: `README.md`

## Scope

This plan implements Phase 1 only. Phase 2 resource intent actions remain outside this plan because they introduce independent input sources, search ranking, and human confirmation workflows. Phase 1 exposes structured action functions now so Phase 2 can call them without changing downloader or policy internals.

## Decisions Locked By This Plan

- State format: SQLite at `.seed-agent/state.db`.
- Audit format: JSONL at `.seed-agent/audit.jsonl`.
- CLI shape: `seed-agent discover`, `seed-agent score`, `seed-agent enqueue`, `seed-agent review`, `seed-agent prune`, `seed-agent daily-report`, plus `seed-agent run-once`.
- Dry-run default: mutating commands default to `--dry-run`; `--execute` is required for qB add, pause, or delete.
- First site adapter: generic RSS/NexusPHP-like parser using RSS fields plus title/detail metadata heuristics.
- Scheduler: no scheduler in Phase 1. Operators can run CLI commands manually or from cron/launchd using the documented command.
- qB credentials: loaded from local gitignored YAML referenced by config, never committed.

## File Structure

- Create `pyproject.toml`: project metadata, dependencies, CLI entry point, pytest/ruff config.
- Create `.gitignore`: ignore local runtime and secret files.
- Create `src/seed_agent/__init__.py`: package version.
- Create `src/seed_agent/models.py`: shared Pydantic models and enums.
- Create `src/seed_agent/config.py`: config loading, validation, secret reference loading.
- Create `src/seed_agent/audit.py`: JSONL writer and redaction helpers.
- Create `src/seed_agent/state.py`: SQLite lifecycle store.
- Create `src/seed_agent/sites/__init__.py`: site adapter exports.
- Create `src/seed_agent/sites/rss.py`: RSS parser and fetcher.
- Create `src/seed_agent/policies/__init__.py`: policy exports.
- Create `src/seed_agent/policies/scoring.py`: filtering and scoring.
- Create `src/seed_agent/policies/cleanup.py`: balanced cleanup decisions.
- Create `src/seed_agent/downloaders/__init__.py`: downloader exports.
- Create `src/seed_agent/downloaders/base.py`: downloader protocol and DTOs.
- Create `src/seed_agent/downloaders/qbittorrent.py`: qBittorrent Web API implementation.
- Create `src/seed_agent/actions/__init__.py`: action exports.
- Create `src/seed_agent/actions/pt.py`: discover, score, daily report actions.
- Create `src/seed_agent/actions/qb.py`: enqueue, review, prune actions.
- Create `src/seed_agent/cli.py`: Typer commands.
- Create `config/example.yaml`: safe example config.
- Create `local/secrets/.gitkeep`: directory placeholder only.
- Create `tests/fixtures/nexusphp-rss.xml`: RSS fixture with free/hot candidates.
- Create tests under `tests/` matching each module.
- Modify `README.md`: add install, config, dry-run, and safety usage.
- Modify `docs/operations/session-handoff.md`: add implementation-plan pointer, runtime paths, and next execution commands.

---

### Task 1: Bootstrap Python Package

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/seed_agent/__init__.py`
- Create: `tests/test_package_import.py`

- [ ] **Step 1: Create project metadata**

Write `pyproject.toml`:

```toml
[project]
name = "seed-agent"
version = "0.1.0"
description = "AI-first PT and downloader operations toolkit for a personal NAS"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "feedparser>=6.0,<7.0",
  "httpx>=0.27,<1.0",
  "pydantic>=2.7,<3.0",
  "pyyaml>=6.0,<7.0",
  "rich>=13.7,<14.0",
  "typer>=0.12,<1.0",
]

[project.scripts]
seed-agent = "seed_agent.cli:app"

[dependency-groups]
dev = [
  "pytest-asyncio>=0.23,<1.0",
  "pytest>=8.2,<9.0",
  "respx>=0.21,<1.0",
  "ruff>=0.5,<1.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Ignore local runtime and credentials**

Write `.gitignore`:

```gitignore
.DS_Store
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.seed-agent/
local/secrets/*
!local/secrets/.gitkeep
```

- [ ] **Step 3: Add import surface**

Write `src/seed_agent/__init__.py`:

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

Write `tests/test_package_import.py`:

```python
from seed_agent import __version__


def test_package_imports() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 4: Verify bootstrap**

Run:

```bash
uv sync --dev
uv run pytest tests/test_package_import.py -q
uv run ruff check .
```

Expected:

```text
1 passed
All checks passed!
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore pyproject.toml src/seed_agent/__init__.py tests/test_package_import.py
git commit -m "chore: bootstrap seed-agent package"
```

---

### Task 2: Define Config And Domain Models

**Files:**
- Create: `src/seed_agent/models.py`
- Create: `src/seed_agent/config.py`
- Create: `config/example.yaml`
- Create: `local/secrets/.gitkeep`
- Create: `tests/test_config.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write model tests first**

Write `tests/test_models.py`:

```python
from seed_agent.models import Discount, TorrentCandidate


def test_candidate_normalizes_discount_and_stable_id() -> None:
    candidate = TorrentCandidate(
        site="demo",
        title="Example Free Torrent",
        source_url="https://tracker.example/details.php?id=42&passkey=secret",
        download_url="https://tracker.example/download.php?id=42&passkey=secret",
        size_bytes=10_000,
        seeders=10,
        leechers=20,
        discount="FREE",
        left_time_minutes=180,
        hr=False,
    )

    assert candidate.discount == Discount.FREE
    assert candidate.stable_id == "demo:https://tracker.example/details.php?id=42"
```

- [ ] **Step 2: Write config tests first**

Write `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from seed_agent.config import load_config


def test_load_config_accepts_example_shape(tmp_path: Path) -> None:
    secret = tmp_path / "qb.yaml"
    secret.write_text(
        "base_url: http://qb.local:8080\nusername: user\npassword: pass\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "seed-agent.yaml"
    config_path.write_text(
        f"""
mode: balanced
sites:
  - name: demo
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php?passkey=secret
    cookie_ref: local/secrets/demo.cookie
discovery:
  discounts: [free, 2xfree]
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
  category: pt-auto
  tags: [seed-agent, pt-auto]
  secret_ref: "{secret}"
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

    assert config.mode == "balanced"
    assert config.enabled_sites[0].name == "demo"
    assert config.downloader.category == "pt-auto"


def test_config_rejects_delete_delay_below_pause_window(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.yaml"
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
  weights: {discount: 30, leechers: 25, seeders: 15, left_time: 15, size: 10, site_history: 5}
downloader:
  type: qbittorrent
  target: unraid-qb
  category: pt-auto
  tags: [seed-agent]
cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pause_before_delete_hours"):
        load_config(config_path)
```

- [ ] **Step 3: Implement models**

Implement `src/seed_agent/models.py` with these public types:

```python
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Discount(StrEnum):
    FREE = "free"
    TWO_X_FREE = "2xfree"
    HALF = "50%"
    TWO_X_HALF = "2x50%"
    NORMAL = "normal"


class LifecycleState(StrEnum):
    DISCOVERED = "discovered"
    SCORED = "scored"
    ENQUEUED = "enqueued"
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    COLD = "cold"
    PAUSED = "paused"
    DELETED = "deleted"


SENSITIVE_QUERY_KEYS = {"passkey", "token", "auth", "key", "rsskey", "uid"}


def safe_url_identity(url: str) -> str:
    parts = urlsplit(url)
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


class TorrentCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    title: str
    source_url: str
    download_url: str
    size_bytes: int = Field(ge=0)
    seeders: int = Field(ge=0)
    leechers: int = Field(ge=0)
    discount: Discount = Discount.NORMAL
    left_time_minutes: int | None = Field(default=None, ge=0)
    hr: bool = False
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("discount", mode="before")
    @classmethod
    def normalize_discount(cls, value: str | Discount) -> Discount:
        if isinstance(value, Discount):
            return value
        normalized = value.strip().lower().replace(" ", "")
        aliases = {
            "free": Discount.FREE,
            "2xfree": Discount.TWO_X_FREE,
            "2x_free": Discount.TWO_X_FREE,
            "50%": Discount.HALF,
            "half": Discount.HALF,
            "2x50%": Discount.TWO_X_HALF,
            "normal": Discount.NORMAL,
            "none": Discount.NORMAL,
        }
        return aliases.get(normalized, Discount.NORMAL)

    @property
    def stable_id(self) -> str:
        return f"{self.site}:{safe_url_identity(self.source_url)}"


class ScoreBreakdown(BaseModel):
    candidate_id: str
    score: int = Field(ge=0, le=100)
    accepted: bool
    reasons: list[str]
    candidate: TorrentCandidate


class ManagedTorrent(BaseModel):
    hash: str
    name: str
    category: str | None = None
    tags: set[str] = Field(default_factory=set)
    state: str
    size_bytes: int = Field(ge=0)
    uploaded_bytes: int = Field(ge=0)
    downloaded_bytes: int = Field(ge=0)
    added_at: datetime
    completed_at: datetime | None = None
    last_activity_at: datetime | None = None
    save_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    action: str
    target_id: str
    execute: bool
    reason: str
    old_state: dict[str, Any] = Field(default_factory=dict)
    new_state: dict[str, Any] = Field(default_factory=dict)
    confirmation_required: bool = False
    confirmation_received: bool = False
    rollback: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

- [ ] **Step 4: Implement config**

Implement `src/seed_agent/config.py` with Pydantic models named `SeedAgentConfig`, `SiteConfig`, `DiscoveryConfig`, `ScoringConfig`, `DownloaderConfig`, `CleanupConfig`, and a `load_config(path: Path) -> SeedAgentConfig` function. Use `yaml.safe_load`. Add `enabled_sites` property returning enabled sites. Validate `cleanup.pause_before_delete_hours >= 1`. Validate the scoring weights sum to `100`.

- [ ] **Step 5: Add example config**

Write `config/example.yaml` using the README shape plus `downloader.secret_ref: local/secrets/qbittorrent.yaml`. Write `local/secrets/.gitkeep` as an empty file.

- [ ] **Step 6: Verify**

Run:

```bash
uv run pytest tests/test_models.py tests/test_config.py -q
uv run ruff check .
```

Expected:

```text
4 passed
All checks passed!
```

- [ ] **Step 7: Commit**

```bash
git add src/seed_agent/models.py src/seed_agent/config.py config/example.yaml local/secrets/.gitkeep tests/test_models.py tests/test_config.py
git commit -m "feat: add config and domain models"
```

---

### Task 3: Add Audit Logging And Redaction

**Files:**
- Create: `src/seed_agent/audit.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: Write audit tests first**

Write `tests/test_audit.py`:

```python
import json
from pathlib import Path

from seed_agent.audit import AuditLogger, redact_sensitive_text
from seed_agent.models import Decision


def test_redacts_sensitive_urls_and_values() -> None:
    text = "https://tracker.example/rss?passkey=abc&uid=12 password=hunter2"
    redacted = redact_sensitive_text(text)

    assert "abc" not in redacted
    assert "hunter2" not in redacted
    assert "passkey=<redacted>" in redacted
    assert "password=<redacted>" in redacted


def test_audit_logger_writes_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)
    logger.write(
        Decision(
            action="qb.enqueue",
            target_id="demo:1",
            execute=False,
            reason="score 82 >= threshold 70",
            new_state={"download_url": "https://tracker.example/dl?passkey=abc"},
            rollback="delete torrent hash after enqueue",
        )
    )

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["action"] == "qb.enqueue"
    assert rows[0]["execute"] is False
    assert "abc" not in json.dumps(rows[0])
```

- [ ] **Step 2: Implement audit module**

Implement `src/seed_agent/audit.py` with:

```python
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from seed_agent.models import Decision

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<key>password|passkey|token|secret|cookie|rsskey)=(?P<value>[^&\\s]+)",
    re.IGNORECASE,
)


def redact_sensitive_text(value: str) -> str:
    return SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group('key')}=<redacted>", value)


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"password", "passkey", "token", "secret", "cookie"}:
                output[key] = "<redacted>"
            else:
                output[key] = redact_payload(item)
        return output
    return value


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, decision: Decision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = decision.model_dump(mode="json")
        redacted = redact_payload(payload)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redacted, sort_keys=True, ensure_ascii=False) + "\n")
```

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_audit.py -q
uv run ruff check .
```

Expected:

```text
2 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/audit.py tests/test_audit.py
git commit -m "feat: add redacted audit logging"
```

---

### Task 4: Parse RSS Torrent Candidates

**Files:**
- Create: `src/seed_agent/sites/__init__.py`
- Create: `src/seed_agent/sites/rss.py`
- Create: `tests/fixtures/nexusphp-rss.xml`
- Create: `tests/test_rss_site.py`

- [ ] **Step 1: Add RSS fixture**

Create `tests/fixtures/nexusphp-rss.xml` with two items: one accepted free hot torrent and one normal low-leecher torrent. Include `title`, `link`, `enclosure url`, `published`, `size`, `seeders`, `leechers`, `discount`, `left_time_minutes`, and `hr` fields using simple namespaced or plain RSS elements.

- [ ] **Step 2: Write parser tests first**

Write `tests/test_rss_site.py`:

```python
from pathlib import Path

from seed_agent.sites.rss import parse_rss_candidates


def test_parse_rss_candidates_from_fixture() -> None:
    xml = Path("tests/fixtures/nexusphp-rss.xml").read_text(encoding="utf-8")

    candidates = parse_rss_candidates(xml, site="demo")

    assert len(candidates) == 2
    assert candidates[0].site == "demo"
    assert candidates[0].discount == "free"
    assert candidates[0].seeders == 12
    assert candidates[0].leechers == 24
    assert candidates[0].left_time_minutes == 240
    assert candidates[0].hr is False
```

- [ ] **Step 3: Implement RSS parser**

Implement `src/seed_agent/sites/rss.py` with a pure `parse_rss_candidates(xml: str, site: str) -> list[TorrentCandidate]` function and an async `fetch_rss_candidates(url: str, site: str, cookie: str | None = None) -> list[TorrentCandidate]` function using `httpx.AsyncClient`. Parser rules:

- prefer `entry.enclosures[0].href` for `download_url`;
- use `entry.link` for `source_url`;
- parse integer fields from `seeders`, `leechers`, `size`, and `left_time_minutes`;
- parse booleans for `hr` from `true`, `yes`, `1`, `hr`;
- store unknown RSS fields in candidate `metadata`.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_rss_site.py -q
uv run ruff check .
```

Expected:

```text
1 passed
All checks passed!
```

- [ ] **Step 5: Commit**

```bash
git add src/seed_agent/sites tests/fixtures/nexusphp-rss.xml tests/test_rss_site.py
git commit -m "feat: parse rss torrent candidates"
```

---

### Task 5: Implement Scoring And Filtering

**Files:**
- Create: `src/seed_agent/policies/__init__.py`
- Create: `src/seed_agent/policies/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 1: Write scoring tests first**

Write `tests/test_scoring.py`:

```python
from seed_agent.config import DiscoveryConfig, ScoringConfig
from seed_agent.models import TorrentCandidate
from seed_agent.policies.scoring import score_candidate


def make_candidate(**overrides: object) -> TorrentCandidate:
    data = {
        "site": "demo",
        "title": "Free Hot Torrent",
        "source_url": "https://tracker.example/details.php?id=1",
        "download_url": "https://tracker.example/download.php?id=1",
        "size_bytes": 10 * 1024 * 1024 * 1024,
        "seeders": 20,
        "leechers": 30,
        "discount": "free",
        "left_time_minutes": 240,
        "hr": False,
    }
    data.update(overrides)
    return TorrentCandidate(**data)


def discovery() -> DiscoveryConfig:
    return DiscoveryConfig(
        discounts=["free", "2xfree"],
        min_left_time_minutes=120,
        min_leechers=8,
        max_seeders=80,
        allow_hr=False,
    )


def scoring() -> ScoringConfig:
    return ScoringConfig(
        min_score_to_enqueue=70,
        weights={
            "discount": 30,
            "leechers": 25,
            "seeders": 15,
            "left_time": 15,
            "size": 10,
            "site_history": 5,
        },
    )


def test_scores_high_confidence_candidate() -> None:
    result = score_candidate(make_candidate(), discovery(), scoring())

    assert result.accepted is True
    assert result.score >= 70
    assert "discount free accepted" in result.reasons


def test_rejects_hr_when_not_allowed() -> None:
    result = score_candidate(make_candidate(hr=True), discovery(), scoring())

    assert result.accepted is False
    assert result.score == 0
    assert "hr protected by config" in result.reasons
```

- [ ] **Step 2: Implement scoring**

Implement `src/seed_agent/policies/scoring.py` with `score_candidate(candidate, discovery, scoring) -> ScoreBreakdown`. Hard filters return score `0` and `accepted=False`. Weighted scoring:

- discount: full weight when candidate discount is configured, half for `50%` if not configured but not normal;
- leechers: full weight when `leechers >= min_leechers`, capped at twice the minimum;
- seeders: full weight when `seeders <= max_seeders`, taper to zero at twice max;
- left_time: full weight when `left_time_minutes >= min_left_time_minutes`;
- size: full weight for `2 GiB <= size <= 80 GiB`, half for `80 GiB < size <= 150 GiB`;
- site_history: use candidate metadata `site_history_score` from `0.0` to `1.0`, default `0.5`.

Return reasons as readable strings like `seeders 20 <= max 80`.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_scoring.py -q
uv run ruff check .
```

Expected:

```text
2 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/policies tests/test_scoring.py
git commit -m "feat: score torrent candidates"
```

---

### Task 6: Add SQLite Lifecycle State

**Files:**
- Create: `src/seed_agent/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write state tests first**

Write `tests/test_state.py`:

```python
from pathlib import Path

from seed_agent.models import LifecycleState
from seed_agent.state import StateStore


def test_state_store_records_candidate_lifecycle(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.upsert_candidate(
        stable_id="demo:1",
        title="Free Hot Torrent",
        site="demo",
        state=LifecycleState.SCORED,
        score=82,
        torrent_hash=None,
    )
    store.upsert_candidate(
        stable_id="demo:1",
        title="Free Hot Torrent",
        site="demo",
        state=LifecycleState.ENQUEUED,
        score=82,
        torrent_hash="abc123",
    )

    row = store.get_candidate("demo:1")

    assert row is not None
    assert row["state"] == "enqueued"
    assert row["torrent_hash"] == "abc123"
```

- [ ] **Step 2: Implement state store**

Implement `src/seed_agent/state.py` with schema:

```sql
CREATE TABLE IF NOT EXISTS candidates (
  stable_id TEXT PRIMARY KEY,
  site TEXT NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  score INTEGER,
  torrent_hash TEXT,
  first_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_state ON candidates(state);
CREATE INDEX IF NOT EXISTS idx_candidates_hash ON candidates(torrent_hash);
```

Expose methods:

- `upsert_candidate(stable_id, title, site, state, score, torrent_hash)`;
- `get_candidate(stable_id) -> dict[str, Any] | None`;
- `list_by_state(state: LifecycleState) -> list[dict[str, Any]]`.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_state.py -q
uv run ruff check .
```

Expected:

```text
1 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/state.py tests/test_state.py
git commit -m "feat: add lifecycle state store"
```

---

### Task 7: Add Downloader Abstraction And qBittorrent Executor

**Files:**
- Create: `src/seed_agent/downloaders/__init__.py`
- Create: `src/seed_agent/downloaders/base.py`
- Create: `src/seed_agent/downloaders/qbittorrent.py`
- Create: `tests/test_qbittorrent.py`

- [ ] **Step 1: Write qB request tests first**

Write `tests/test_qbittorrent.py` using `respx`:

```python
import respx
from httpx import Response

from seed_agent.downloaders.qbittorrent import QbittorrentClient


@respx.mock
async def test_qb_adds_torrent_with_category_and_tags() -> None:
    respx.post("http://qb.local:8080/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))
    add_route = respx.post("http://qb.local:8080/api/v2/torrents/add").mock(
        return_value=Response(200, text="Ok.")
    )
    client = QbittorrentClient(
        base_url="http://qb.local:8080",
        username="user",
        password="pass",
    )

    await client.add_url(
        url="https://tracker.example/download.php?id=1&passkey=secret",
        category="pt-auto",
        tags=["seed-agent", "pt-auto"],
    )

    assert add_route.called
    request = add_route.calls[0].request
    assert "category" in request.content.decode()
    assert "pt-auto" in request.content.decode()
```

- [ ] **Step 2: Define downloader protocol**

Implement `src/seed_agent/downloaders/base.py` with a `Downloader` `Protocol` exposing:

- `add_url(url, category, tags) -> str | None`;
- `list_torrents(category, tags) -> list[ManagedTorrent]`;
- `pause(hash) -> None`;
- `delete(hash, delete_files) -> None`.

- [ ] **Step 3: Implement qBittorrent client**

Implement `src/seed_agent/downloaders/qbittorrent.py` with:

- `QbittorrentClient(base_url, username, password)`;
- session login through `/api/v2/auth/login`;
- add URL through `/api/v2/torrents/add`;
- list through `/api/v2/torrents/info`;
- pause through `/api/v2/torrents/pause`;
- delete through `/api/v2/torrents/delete`.

Convert qB torrent rows into `ManagedTorrent`. Keep all methods async.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_qbittorrent.py -q
uv run ruff check .
```

Expected:

```text
1 passed
All checks passed!
```

- [ ] **Step 5: Commit**

```bash
git add src/seed_agent/downloaders tests/test_qbittorrent.py
git commit -m "feat: add qbittorrent downloader executor"
```

---

### Task 8: Implement Structured PT Actions

**Files:**
- Create: `src/seed_agent/actions/__init__.py`
- Create: `src/seed_agent/actions/pt.py`
- Create: `tests/test_pt_actions.py`

- [ ] **Step 1: Write action tests first**

Write `tests/test_pt_actions.py`:

```python
from seed_agent.actions.pt import score_candidates
from seed_agent.config import DiscoveryConfig, ScoringConfig
from seed_agent.models import TorrentCandidate


def test_score_candidates_returns_structured_results() -> None:
    candidate = TorrentCandidate(
        site="demo",
        title="Free Hot Torrent",
        source_url="https://tracker.example/details.php?id=1",
        download_url="https://tracker.example/download.php?id=1",
        size_bytes=10_000_000_000,
        seeders=10,
        leechers=20,
        discount="free",
        left_time_minutes=240,
        hr=False,
    )

    results = score_candidates(
        [candidate],
        DiscoveryConfig(
            discounts=["free"],
            min_left_time_minutes=120,
            min_leechers=8,
            max_seeders=80,
            allow_hr=False,
        ),
        ScoringConfig(
            min_score_to_enqueue=70,
            weights={
                "discount": 30,
                "leechers": 25,
                "seeders": 15,
                "left_time": 15,
                "size": 10,
                "site_history": 5,
            },
        ),
    )

    assert results[0].accepted is True
```

- [ ] **Step 2: Implement PT actions**

Implement `src/seed_agent/actions/pt.py` with:

- `discover_candidates(config) -> list[TorrentCandidate]`: fetch enabled RSS sites;
- `score_candidates(candidates, discovery_config, scoring_config) -> list[ScoreBreakdown]`;
- `daily_report(scored, managed_torrents) -> dict[str, object]`.

Keep discovery async because HTTP fetches are async. Keep scoring pure and synchronous.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_pt_actions.py -q
uv run ruff check .
```

Expected:

```text
1 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/actions tests/test_pt_actions.py
git commit -m "feat: add structured pt actions"
```

---

### Task 9: Implement Enqueue Action With Dry-Run Safety

**Files:**
- Create: `src/seed_agent/actions/qb.py`
- Create: `tests/test_enqueue_action.py`

- [ ] **Step 1: Write enqueue tests first**

Write `tests/test_enqueue_action.py` with a fake downloader:

```python
from seed_agent.actions.qb import enqueue_candidates
from seed_agent.models import ScoreBreakdown, TorrentCandidate


class FakeDownloader:
    def __init__(self) -> None:
        self.added: list[str] = []

    async def add_url(self, url: str, category: str, tags: list[str]) -> str | None:
        self.added.append(url)
        return "abc123"


def accepted_candidate() -> ScoreBreakdown:
    candidate = TorrentCandidate(
        site="demo",
        title="Free Hot Torrent",
        source_url="https://tracker.example/details.php?id=1",
        download_url="https://tracker.example/download.php?id=1&passkey=secret",
        size_bytes=10_000_000_000,
        seeders=10,
        leechers=20,
        discount="free",
        left_time_minutes=240,
        hr=False,
    )
    return ScoreBreakdown(
        candidate_id=candidate.stable_id,
        score=82,
        accepted=True,
        reasons=["score 82 >= threshold 70"],
        candidate=candidate,
    )


async def test_enqueue_dry_run_does_not_call_downloader() -> None:
    downloader = FakeDownloader()
    decisions = await enqueue_candidates(
        [accepted_candidate()],
        downloader=downloader,
        category="pt-auto",
        tags=["seed-agent"],
        execute=False,
    )

    assert downloader.added == []
    assert decisions[0].execute is False


async def test_enqueue_execute_calls_downloader() -> None:
    downloader = FakeDownloader()
    decisions = await enqueue_candidates(
        [accepted_candidate()],
        downloader=downloader,
        category="pt-auto",
        tags=["seed-agent"],
        execute=True,
    )

    assert downloader.added == ["https://tracker.example/download.php?id=1&passkey=secret"]
    assert decisions[0].new_state["torrent_hash"] == "abc123"
```

- [ ] **Step 2: Implement enqueue action**

Implement `enqueue_candidates(scored, downloader, category, tags, execute) -> list[Decision]`. Behavior:

- skip `accepted=False`;
- in dry-run, produce `Decision(action="qb.enqueue", execute=False)` and do not call downloader;
- in execute mode, call `downloader.add_url`;
- include rollback instruction `Delete torrent from qBittorrent if enqueue was accidental`;
- never log unredacted URL directly outside `Decision.new_state`, because audit redaction handles that field.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_enqueue_action.py -q
uv run ruff check .
```

Expected:

```text
2 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/actions/qb.py tests/test_enqueue_action.py
git commit -m "feat: add safe enqueue action"
```

---

### Task 10: Implement Balanced Cleanup Policy

**Files:**
- Modify: `src/seed_agent/policies/cleanup.py`
- Modify: `src/seed_agent/actions/qb.py`
- Create: `tests/test_cleanup.py`
- Create: `tests/test_prune_action.py`

- [ ] **Step 1: Write cleanup policy tests first**

Write `tests/test_cleanup.py`:

```python
from datetime import UTC, datetime, timedelta

from seed_agent.config import CleanupConfig
from seed_agent.models import ManagedTorrent
from seed_agent.policies.cleanup import classify_cleanup


def torrent(**overrides: object) -> ManagedTorrent:
    data = {
        "hash": "abc123",
        "name": "Managed Torrent",
        "category": "pt-auto",
        "tags": {"seed-agent"},
        "state": "uploading",
        "size_bytes": 10_000,
        "uploaded_bytes": 0,
        "downloaded_bytes": 10_000,
        "added_at": datetime.now(UTC) - timedelta(days=10),
        "completed_at": datetime.now(UTC) - timedelta(days=10),
        "last_activity_at": datetime.now(UTC) - timedelta(days=8),
        "save_path": "/downloads/pt-auto",
        "metadata": {},
    }
    data.update(overrides)
    return ManagedTorrent(**data)


def cleanup() -> CleanupConfig:
    return CleanupConfig(
        cold_after_days=7,
        min_upload_delta_gb=1,
        protect_hr=True,
        protect_manual=True,
        protect_media_library=True,
        pause_before_delete_hours=24,
    )


def test_protects_unmanaged_torrent() -> None:
    decision = classify_cleanup(
        torrent(category="movies", tags=set()),
        cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent"},
    )

    assert decision.action == "protect"
    assert "not managed" in decision.reason


def test_pauses_cold_managed_torrent() -> None:
    decision = classify_cleanup(
        torrent(),
        cleanup(),
        managed_category="pt-auto",
        managed_tags={"seed-agent"},
    )

    assert decision.action == "pause"
    assert "cold for 8 days" in decision.reason
```

- [ ] **Step 2: Implement cleanup classifier**

Implement `src/seed_agent/policies/cleanup.py` with `classify_cleanup(torrent, cleanup, managed_category, managed_tags)`. Return an object or Pydantic model with `action` values `protect`, `keep`, `pause`, `delete`. Rules:

- protect if category and tags do not prove management;
- protect if metadata has `hr=True`;
- protect if metadata has `manual=True`;
- protect if metadata has `media_library=True`;
- keep if `last_activity_at` is newer than `cold_after_days`;
- pause if cold and not already paused;
- delete if already paused, metadata has `paused_at`, and pause age is at least `pause_before_delete_hours`.

- [ ] **Step 3: Add prune action tests**

Write `tests/test_prune_action.py` with a fake downloader that records `pause` and `delete` calls. Assert dry-run does not call either, execute pauses a cold managed torrent, and execute never deletes unmanaged torrents.

- [ ] **Step 4: Implement prune action**

Extend `src/seed_agent/actions/qb.py` with `prune_cold_torrents(torrents, downloader, cleanup, managed_category, managed_tags, execute) -> list[Decision]`. The action must convert cleanup classifier results into audit decisions and call downloader only when `execute=True` and action is `pause` or `delete`.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/test_cleanup.py tests/test_prune_action.py -q
uv run ruff check .
```

Expected:

```text
5 passed
All checks passed!
```

- [ ] **Step 6: Commit**

```bash
git add src/seed_agent/policies/cleanup.py src/seed_agent/actions/qb.py tests/test_cleanup.py tests/test_prune_action.py
git commit -m "feat: add balanced cleanup policy"
```

---

### Task 11: Add CLI Commands

**Files:**
- Create: `src/seed_agent/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write CLI smoke tests first**

Write `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from seed_agent.cli import app


def test_cli_help_lists_phase_one_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "discover" in result.output
    assert "run-once" in result.output


def test_mutating_commands_default_to_dry_run() -> None:
    result = CliRunner().invoke(app, ["enqueue", "--help"])

    assert result.exit_code == 0
    assert "--execute" in result.output
```

- [ ] **Step 2: Implement CLI**

Implement Typer commands:

- `discover --config config/example.yaml`;
- `score --config config/example.yaml`;
- `enqueue --config config/example.yaml --execute`;
- `review --config config/example.yaml`;
- `prune --config config/example.yaml --execute`;
- `daily-report --config config/example.yaml`;
- `run-once --config config/example.yaml --execute`.

Every command should print JSON-compatible Rich output and write audit decisions when a qB action is planned or executed. Mutating commands must treat missing `--execute` as dry-run.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_cli.py -q
uv run ruff check .
```

Expected:

```text
2 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/cli.py tests/test_cli.py
git commit -m "feat: add phase one cli"
```

---

### Task 12: Connect State And Audit In Run-Once

**Files:**
- Modify: `src/seed_agent/cli.py`
- Modify: `src/seed_agent/actions/pt.py`
- Modify: `src/seed_agent/actions/qb.py`
- Create: `tests/test_run_once.py`

- [ ] **Step 1: Write run-once integration test first**

Write `tests/test_run_once.py` using fixture XML and fake downloader/config. Assert:

- discovered candidates are stored as `discovered`;
- scored candidates are stored as `scored`;
- accepted dry-run enqueue decisions are written to audit;
- no downloader mutation happens without `--execute`.

- [ ] **Step 2: Implement state updates**

Update actions or CLI orchestration so:

- discovery inserts candidates with `LifecycleState.DISCOVERED`;
- scoring updates rows to `LifecycleState.SCORED` and score;
- execute enqueue updates rows to `LifecycleState.ENQUEUED` and stores torrent hash;
- prune updates rows to `PAUSED` or `DELETED` when the hash maps to a known candidate.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_run_once.py -q
uv run ruff check .
```

Expected:

```text
1 passed
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add src/seed_agent/cli.py src/seed_agent/actions/pt.py src/seed_agent/actions/qb.py tests/test_run_once.py
git commit -m "feat: wire run-once state and audit"
```

---

### Task 13: Update Documentation And Handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/session-handoff.md`
- Create: `docs/operations/phase-1-usage.md`

- [ ] **Step 1: Update README**

Add sections:

````markdown
## Local Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
```

## Phase 1 CLI

All mutating downloader commands default to dry-run. Add `--execute` only after reviewing the printed decisions and audit output.

```bash
uv run seed-agent discover --config config/example.yaml
uv run seed-agent score --config config/example.yaml
uv run seed-agent run-once --config config/example.yaml
uv run seed-agent run-once --config config/example.yaml --execute
```

Runtime files are written under `.seed-agent/`:

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`

Downloader credentials belong in `local/secrets/qbittorrent.yaml`, which is gitignored.
````

- [ ] **Step 2: Add operations guide**

Create `docs/operations/phase-1-usage.md` with:

- config setup steps;
- qB secret file shape;
- dry-run review flow;
- execute flow;
- audit inspection commands;
- safety notes for managed category and tags.

Use this qB secret shape:

```yaml
base_url: "http://unraid-qb.local:8080"
username: "your-qb-username"
password: "your-qb-password"
```

- [ ] **Step 3: Update session handoff**

Append a new section to `docs/operations/session-handoff.md`:

```markdown
## Phase 1 Implementation Plan

- Plan file: `docs/superpowers/plans/2026-04-20-phase-1-pt-upload-loop.md`
- Runtime state path: `.seed-agent/state.db`
- Audit log path: `.seed-agent/audit.jsonl`
- Local qB secret path: `local/secrets/qbittorrent.yaml`
- First safe verification command: `uv run seed-agent run-once --config config/example.yaml`
- First execute command after review: `uv run seed-agent run-once --config config/example.yaml --execute`
```

- [ ] **Step 4: Verify docs mention handoff**

Run:

```bash
rg "phase-1-pt-upload-loop|state.db|audit.jsonl|qbittorrent.yaml" README.md docs/operations
uv run pytest -q
uv run ruff check .
```

Expected:

```text
README.md
docs/operations/session-handoff.md
docs/operations/phase-1-usage.md
All tests pass
All checks passed!
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations/session-handoff.md docs/operations/phase-1-usage.md
git commit -m "docs: add phase one usage and handoff"
```

---

### Task 14: Full Verification

**Files:**
- No source edits unless verification exposes a concrete failure.

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 2: Run lint**

```bash
uv run ruff check .
```

Expected:

```text
All checks passed!
```

- [ ] **Step 3: Run CLI dry-run smoke**

```bash
uv run seed-agent --help
uv run seed-agent run-once --config config/example.yaml
```

Expected:

```text
The help output lists Phase 1 commands.
The dry-run output prints decisions without mutating qBittorrent.
```

- [ ] **Step 4: Review audit redaction**

```bash
rg "passkey|password|token|cookie" .seed-agent/audit.jsonl
```

Expected:

```text
Only redacted keys such as passkey=<redacted> appear; no real secret values appear.
```

- [ ] **Step 5: Commit verification fixes if any were needed**

If verification required source or doc fixes, run `git status --short`, stage only the files changed by the fix, and commit with `git commit -m "fix: stabilize phase one verification"`. If no fixes were needed, do not create an empty commit.

---

## Self-Review

### Spec Coverage

- Discovery: covered by Task 4 and Task 8.
- Filtering and scoring: covered by Task 5.
- qB downloader abstraction and executor: covered by Task 7.
- Lifecycle state: covered by Task 6 and Task 12.
- Balanced cleanup policy: covered by Task 10.
- Audit records and redaction: covered by Task 3, Task 9, Task 10, and Task 12.
- Structured Phase 1 actions: covered by Task 8, Task 9, Task 10, and Task 11.
- Testing strategy: covered across tasks and final verification.
- Handoff continuity: covered by Task 13.

### Out Of Scope

- Telegram, WeChat bridge, Douban wanted-list, subscription sync, resource search, and intent ranking.
- Rule import/export, auto-reseed, local HTTP API, optional UI, and rules assistant.
- Live tracker and live qB tests by default. These require explicit local credentials and operator consent.

### Execution Notes

- Keep commits task-sized so the repo remains easy to inspect.
- Preserve dry-run behavior as the default for all mutating actions.
- Never commit `local/secrets/*` or `.seed-agent/*`.
- When a task touches downloader mutation, verify audit redaction in the same task.
