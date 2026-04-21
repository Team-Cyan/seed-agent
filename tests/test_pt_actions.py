from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import ManagedTorrent, ScoreBreakdown, TorrentCandidate


def _candidate(**overrides: object) -> TorrentCandidate:
    data: dict[str, object] = {
        "site": "demo-free",
        "title": "High Confidence Torrent",
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


def _config(cookie_ref: str | None = None) -> SeedAgentConfig:
    return SeedAgentConfig(
        mode="balanced",
        sites=[
            {
                "name": "demo-free",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss.php",
                "cookie_ref": cookie_ref,
            },
            {
                "name": "demo-disabled",
                "type": "nexusphp",
                "enabled": False,
                "rss_url": "https://tracker.example/rss-disabled.php",
            },
        ],
        discovery=DiscoveryConfig(
            discounts=["free", "2xfree"],
            min_left_time_minutes=120,
            min_leechers=8,
            max_seeders=80,
            allow_hr=False,
        ),
        scoring=ScoringConfig(
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
        downloader={
            "type": "qbittorrent",
            "target": "unraid-qb",
            "category": "pt-auto",
            "tags": ["seed-agent", "pt-auto"],
            "secret_ref": None,
        },
        cleanup={
            "cold_after_days": 7,
            "min_upload_delta_gb": 1,
            "protect_hr": True,
            "protect_manual": True,
            "protect_media_library": True,
            "pause_before_delete_hours": 24,
        },
    )


def test_score_candidates_returns_structured_breakdown() -> None:
    from seed_agent.actions.pt import score_candidates

    scored = score_candidates(
        [_candidate()],
        _config().discovery,
        _config().scoring,
    )

    assert len(scored) == 1
    assert isinstance(scored[0], ScoreBreakdown)
    assert scored[0].accepted is True
    assert scored[0].candidate_id == _candidate().stable_id


@pytest.mark.asyncio
async def test_discover_candidates_skips_disabled_sites_and_calls_enabled_site(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    calls: list[tuple[str, str, str | None]] = []

    async def fake_fetch_rss_candidates(url: str, site: str, cookie: str | None = None):
        calls.append((url, site, cookie))
        return [_candidate(site=site)]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    candidates = await pt_actions.discover_candidates(_config())

    assert calls == [("https://tracker.example/rss.php", "demo-free", None)]
    assert len(candidates) == 1
    assert candidates[0].site == "demo-free"


@pytest.mark.asyncio
async def test_discover_candidates_keeps_going_when_one_site_fails(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    config = SeedAgentConfig(
        mode="balanced",
        sites=[
            {
                "name": "demo-bad",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss-bad.php",
                "cookie_ref": None,
            },
            {
                "name": "demo-good",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss-good.php",
                "cookie_ref": None,
            },
        ],
        discovery=_config().discovery,
        scoring=_config().scoring,
        downloader=_config().downloader,
        cleanup=_config().cleanup,
    )

    calls: list[str] = []

    async def fake_fetch_rss_candidates(url: str, site: str, cookie: str | None = None):
        calls.append(site)
        if site == "demo-bad":
            raise RuntimeError("boom")
        return [_candidate(site=site, title="Recovered Torrent")]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    candidates = await pt_actions.discover_candidates(config)

    assert calls == ["demo-bad", "demo-good"]
    assert len(candidates) == 1
    assert candidates[0].site == "demo-good"


@pytest.mark.asyncio
async def test_discover_candidates_reads_cookie_ref(tmp_path: Path, monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    cookie_path = tmp_path / "cookie.txt"
    cookie_path.write_text("session=abc123\n", encoding="utf-8")

    seen: list[str | None] = []

    async def fake_fetch_rss_candidates(url: str, site: str, cookie: str | None = None):
        seen.append(cookie)
        return []

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    config = _config(cookie_ref=str(cookie_path))
    await pt_actions.discover_candidates(config)

    assert seen == ["session=abc123"]


@pytest.mark.asyncio
async def test_discover_candidates_resolves_relative_cookie_ref_against_config_path(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent.actions import pt as pt_actions
    from seed_agent.config import load_config

    config_dir = tmp_path / "config-root"
    cookie_path = config_dir / "local" / "secrets" / "demo.cookie"
    cookie_path.parent.mkdir(parents=True)
    cookie_path.write_text("session=relative-cookie\n", encoding="utf-8")

    config_path = config_dir / "seed-agent.yaml"
    config_path.write_text(
        """
mode: balanced
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: local/secrets/demo.cookie
discovery:
  discounts: ["free", "2xfree"]
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
  tags: ["seed-agent", "pt-auto"]
  secret_ref: null
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

    seen: list[str | None] = []

    async def fake_fetch_rss_candidates(url: str, site: str, cookie: str | None = None):
        seen.append(cookie)
        return []

    other_working_dir = tmp_path / "other-working-dir"
    other_working_dir.mkdir()
    monkeypatch.chdir(other_working_dir)
    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    await pt_actions.discover_candidates(config)

    assert seen == ["session=relative-cookie"]
    assert config.config_dir == config_dir


def test_daily_report_returns_stable_counts() -> None:
    from seed_agent.actions.pt import daily_report

    scored = [
        ScoreBreakdown(
            candidate_id="demo-free:https://tracker.example/details.php?id=1",
            score=95,
            accepted=True,
            reasons=["ok"],
            candidate=_candidate(),
        ),
        ScoreBreakdown(
            candidate_id="demo-free:https://tracker.example/details.php?id=2",
            score=40,
            accepted=False,
            reasons=["reject"],
            candidate=_candidate(title="Cold Torrent", source_url="https://tracker.example/details.php?id=2"),
        ),
    ]
    managed = [
        ManagedTorrent(
            hash="abc",
            name="Managed One",
            state="seeding",
            size_bytes=1,
            uploaded_bytes=1,
            downloaded_bytes=1,
            added_at=datetime(2026, 4, 21, 0, 0, tzinfo=UTC),
        )
    ]

    report = daily_report(scored, managed)

    assert report["total_scored"] == 2
    assert report["accepted"] == 1
    assert report["rejected"] == 1
    assert report["managed_torrents"] == 1
    assert report["top_candidates"][0]["score"] == 95
