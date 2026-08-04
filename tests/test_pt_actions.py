from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from seed_agent.config import DiscoveryConfig, ScoringConfig, SeedAgentConfig
from seed_agent.models import Discount, ManagedTorrent, ScoreBreakdown, TorrentCandidate


async def _accept_mteam_preflight(
    item: ScoreBreakdown,
    **_: object,
) -> ScoreBreakdown:
    return item


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


def _config(cookie_ref: str | None = None, api_key_ref: str | None = None) -> SeedAgentConfig:
    return SeedAgentConfig(
        mode="balanced",
        tracker_sites=[
            {
                "name": "demo-free",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss.php",
                "cookie_ref": cookie_ref,
                "api_key_ref": api_key_ref,
            },
            {
                "name": "demo-disabled",
                "type": "nexusphp",
                "enabled": False,
                "rss_url": "https://tracker.example/rss-disabled.php",
            },
        ],
        pt_filters=DiscoveryConfig(
            discounts=["free", "2xfree"],
            min_left_time_minutes=120,
            min_leechers=8,
            target_seed_leecher_ratio=10,
            allow_hr=False,
        ),
        pt_scoring=ScoringConfig(
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
        download_client={
            "type": "qbittorrent",
            "target": "unraid-qb",
            "default_category": "seed",
            "category_policies": [
                {
                    "name": "seed",
                    "mode": "mutable",
                    "budget_pool": "downloads",
                    "delete_enabled": True,
                    "over_budget_behavior": "add_paused",
                    "tags": ["seed-agent", "seed"],
                }
            ],
            "budget_pools": [{"name": "downloads", "max_size_tib": 10}],
            "secret_ref": None,
        },
        seed_cleanup={
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
        _config().pt_filters,
        _config().pt_scoring,
    )

    assert len(scored) == 1
    assert isinstance(scored[0], ScoreBreakdown)
    assert scored[0].accepted is True
    assert scored[0].candidate_id == _candidate().stable_id


def test_apply_site_history_feedback_sets_candidate_metadata_when_available() -> None:
    from seed_agent.actions.pt import apply_site_history_feedback

    explicit = _candidate(
        source_url="https://tracker.example/details.php?id=2",
        metadata={"site_history_score": 0.9},
    )
    updated = apply_site_history_feedback(
        [_candidate(), explicit],
        {"demo-free": {"applied": True, "score": 0.72, "samples": 4, "window_days": 30}},
    )

    assert updated[0].metadata["site_history_score"] == 0.72
    assert updated[0].metadata["site_history_source"] == "state_feedback"
    assert updated[0].metadata["site_history_samples"] == 4
    assert updated[1].metadata["site_history_score"] == 0.9


@pytest.mark.asyncio
async def test_discover_candidates_skips_disabled_sites_and_calls_enabled_site(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    calls: list[tuple[str, str, str | None, str | None, str]] = []

    async def fake_fetch_rss_candidates(
        url: str,
        site: str,
        cookie: str | None = None,
        api_key: str | None = None,
        *,
        site_type: str = "nexusphp",
    ):
        calls.append((url, site, cookie, api_key, site_type))
        return [_candidate(site=site)]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    candidates = await pt_actions.discover_candidates(_config())

    assert calls == [("https://tracker.example/rss.php", "demo-free", None, None, "nexusphp")]
    assert len(candidates) == 1
    assert candidates[0].site == "demo-free"


@pytest.mark.asyncio
async def test_discover_candidates_keeps_going_when_one_site_fails(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    config = SeedAgentConfig(
        mode="balanced",
        tracker_sites=[
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
        pt_filters=_config().pt_filters,
        pt_scoring=_config().pt_scoring,
        download_client=_config().download_client,
        seed_cleanup=_config().seed_cleanup,
    )

    calls: list[str] = []

    async def fake_fetch_rss_candidates(
        url: str,
        site: str,
        cookie: str | None = None,
        api_key: str | None = None,
        *,
        site_type: str = "nexusphp",
    ):
        calls.append(site)
        if site == "demo-bad":
            raise RuntimeError("boom")
        return [_candidate(site=site, title="Recovered Torrent")]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    candidates = await pt_actions.discover_candidates(config)

    assert calls == ["demo-bad", "demo-good"]
    assert len(candidates) == 1
    assert candidates[0].site == "demo-good"
    assert pt_actions.get_last_discovery_warnings() == [
        {
            "site": "demo-bad",
            "error_type": "RuntimeError",
            "message": "boom",
            "endpoint": None,
            "rate_limited": False,
            "unavailable": False,
        }
    ]


@pytest.mark.asyncio
async def test_discover_candidates_clears_runtime_warnings_on_success(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    async def fail_fetch_rss_candidates(*args, **kwargs):
        raise RuntimeError("temporary")

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fail_fetch_rss_candidates)

    await pt_actions.discover_candidates(_config())
    assert pt_actions.get_last_discovery_warnings()

    async def good_fetch_rss_candidates(*args, **kwargs):
        return [_candidate()]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", good_fetch_rss_candidates)

    await pt_actions.discover_candidates(_config())
    assert pt_actions.get_last_discovery_warnings() == []


@pytest.mark.asyncio
async def test_discover_candidates_reads_cookie_ref(tmp_path: Path, monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    cookie_path = tmp_path / "cookie.txt"
    cookie_path.write_text("session=abc123\n", encoding="utf-8")

    seen: list[str | None] = []

    async def fake_fetch_rss_candidates(
        url: str,
        site: str,
        cookie: str | None = None,
        api_key: str | None = None,
        *,
        site_type: str = "nexusphp",
    ):
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
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: local/secrets/demo.cookie
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  target_seed_leecher_ratio: 10
  allow_hr: false
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: null
seed_cleanup:
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

    async def fake_fetch_rss_candidates(
        url: str,
        site: str,
        cookie: str | None = None,
        api_key: str | None = None,
        *,
        site_type: str = "nexusphp",
    ):
        seen.append(cookie)
        return []

    other_working_dir = tmp_path / "other-working-dir"
    other_working_dir.mkdir()
    monkeypatch.chdir(other_working_dir)
    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    await pt_actions.discover_candidates(config)

    assert seen == ["session=relative-cookie"]
    assert config.config_dir == config_dir


@pytest.mark.asyncio
async def test_discover_candidates_resolves_repo_relative_site_secret_for_config_dir_named_config(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent.actions import pt as pt_actions
    from seed_agent.config import load_config

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    secret_path = tmp_path / "local" / "secrets" / "mt.api-key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("secret-api-key\n", encoding="utf-8")

    config_path = config_dir / "example.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.cc/api/rss/fetch?dl=1
    api_key_ref: local/secrets/mt.api-key
    discovery_mode: api
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
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  target_seed_leecher_ratio: 10
  allow_hr: false
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: null
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )

    called: list[str] = []

    async def fake_fetch_api_candidates(*, site: str, api_key: str, options, cookie=None):
        called.append(api_key)
        return []

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fake_fetch_api_candidates)

    await pt_actions.discover_candidates(load_config(config_path))

    assert called == ["secret-api-key"]


@pytest.mark.asyncio
async def test_discover_candidates_expands_mteam_api_modes_and_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent.actions import pt as pt_actions
    from seed_agent.config import load_config

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    secret_path = tmp_path / "local" / "secrets" / "mt.api-key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("secret-api-key\n", encoding="utf-8")

    config_path = config_dir / "example.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.cc/api/rss/fetch?dl=1
    api_key_ref: local/secrets/mt.api-key
    discovery_mode: api
    api_discovery:
      mode: adult
      modes: [normal, adult]
      only_free: true
      sort_field: leechers
      sort_order: desc
      page_size: 50
      min_seeders: null
      max_seeders: 0
      min_leechers: null
      min_times_completed: 0
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 30
  min_seeders: 1
  target_seed_leecher_ratio: 4
  allow_hr: false
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: null
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )

    seen_modes: list[str] = []

    async def fake_fetch_api_candidates(*, site: str, api_key: str, options, cookie=None):
        seen_modes.append(options.mode)
        shared = _candidate(site=site, source_url="https://kp.m-team.cc/detail/1")
        if options.mode == "normal":
            return [shared, _candidate(site=site, source_url="https://kp.m-team.cc/detail/2")]
        return [shared]

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fake_fetch_api_candidates)

    candidates = await pt_actions.discover_candidates(load_config(config_path))

    assert seen_modes == ["normal", "adult"]
    assert [candidate.stable_id for candidate in candidates] == [
        "mt:https://kp.m-team.cc/detail/1",
        "mt:https://kp.m-team.cc/detail/2",
    ]


@pytest.mark.asyncio
async def test_discover_candidates_errors_when_mteam_api_secret_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    from seed_agent.actions import pt as pt_actions
    from seed_agent.config import load_config

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "example.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.cc/api/rss/fetch?dl=1
    api_key_ref: local/secrets/missing.api-key
    discovery_mode: api
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
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  target_seed_leecher_ratio: 10
  allow_hr: false
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: null
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )

    async def fail_fetch_api_candidates(*args, **kwargs):
        raise AssertionError("api discovery should not run without a readable key")

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fail_fetch_api_candidates)

    with pytest.raises(
        pt_actions.SiteDiscoveryConfigError,
        match="missing api_key_ref secret for site mt",
    ):
        await pt_actions.discover_candidates(load_config(config_path))


@pytest.mark.asyncio
async def test_discover_candidates_reads_api_key_ref(tmp_path: Path, monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    api_key_path = tmp_path / "mteam.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")

    seen: list[str | None] = []

    async def fake_fetch_rss_candidates(
        url: str,
        site: str,
        cookie: str | None = None,
        api_key: str | None = None,
        *,
        site_type: str = "nexusphp",
    ):
        seen.append(api_key)
        return []

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    config = _config(api_key_ref=str(api_key_path))
    await pt_actions.discover_candidates(config)

    assert seen == ["secret-api-key"]


@pytest.mark.asyncio
async def test_discover_candidates_uses_mteam_api_mode_when_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions

    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")

    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
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

    called: list[tuple[str, str, str | None, str]] = []

    async def fake_fetch_api_candidates(
        *,
        site: str,
        api_key: str,
        options,
        cookie: str | None = None,
    ):
        called.append((site, api_key, cookie, options.sort_field))
        return [_candidate(site=site, metadata={"mteam_discovery_mode": "api"})]

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fake_fetch_api_candidates)

    candidates = await pt_actions.discover_candidates(config)

    assert called == [("mt", "secret-api-key", None, "downloads")]
    assert candidates[0].metadata["mteam_discovery_mode"] == "api"


@pytest.mark.asyncio
async def test_discover_candidates_inherits_mteam_api_thresholds_from_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions

    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")
    base = _config().model_dump()
    base["pt_filters"]["min_seeders"] = 2
    base["pt_filters"]["min_leechers"] = 8
    config = SeedAgentConfig(
        **{
            **base,
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
                    "discovery_mode": "api",
                    "api_discovery": {
                        "mode": "adult",
                        "only_free": True,
                        "sort_field": "downloads",
                        "sort_order": "desc",
                        "page_size": 50,
                        "min_seeders": None,
                        "max_seeders": 200,
                        "min_leechers": None,
                        "min_times_completed": 0,
                    },
                }
            ],
        }
    )

    seen: list[tuple[int, int]] = []

    async def fake_fetch_api_candidates(
        *,
        site: str,
        api_key: str,
        options,
        cookie: str | None = None,
    ):
        seen.append((options.min_seeders, options.min_leechers))
        return []

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fake_fetch_api_candidates)

    await pt_actions.discover_candidates(config)

    assert seen == [(2, 8)]


@pytest.mark.asyncio
async def test_discover_candidates_preserves_explicit_zero_mteam_api_thresholds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions

    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")
    base = _config().model_dump()
    base["pt_filters"]["min_seeders"] = 2
    base["pt_filters"]["min_leechers"] = 8
    config = SeedAgentConfig(
        **{
            **base,
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
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

    seen: list[tuple[int, int]] = []

    async def fake_fetch_api_candidates(
        *,
        site: str,
        api_key: str,
        options,
        cookie: str | None = None,
    ):
        seen.append((options.min_seeders, options.min_leechers))
        return []

    monkeypatch.setattr(pt_actions, "fetch_mteam_api_candidates", fake_fetch_api_candidates)

    await pt_actions.discover_candidates(config)

    assert seen == [(0, 0)]


@pytest.mark.asyncio
async def test_resolve_deferred_download_urls_uses_mteam_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions

    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
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
    candidate = _candidate(
        site="mt",
        source_url="https://kp.m-team.cc/detail/1171443",
        download_url="mteam-api://torrent/1171443",
        metadata={
            "mteam_discovery_mode": "api",
            "download_url_source": "mteam_api_deferred",
            "mteam_torrent_id": "1171443",
        },
    )
    scored = [
        ScoreBreakdown(
            candidate_id=candidate.stable_id,
            score=95,
            accepted=True,
            reasons=["ok"],
            candidate=candidate,
        )
    ]
    calls: list[str] = []

    async def fake_resolve_deferred_download_url(
        candidate: TorrentCandidate,
        *,
        api_key: str,
        api_key_header: str,
    ) -> TorrentCandidate | None:
        calls.append(api_key)
        return candidate.model_copy(update={"download_url": "https://dl.example/torrent"})

    monkeypatch.setattr(pt_actions, "_revalidate_mteam_candidate", _accept_mteam_preflight)
    monkeypatch.setattr(
        pt_actions,
        "resolve_deferred_download_url",
        fake_resolve_deferred_download_url,
    )

    resolved = await pt_actions.resolve_deferred_download_urls(scored, config)

    assert calls == ["secret-api-key"]
    assert resolved[0].accepted is True
    assert resolved[0].candidate.download_url == "https://dl.example/torrent"


@pytest.mark.asyncio
async def test_mteam_preflight_rejects_discount_that_changed_to_half(
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions

    config = _config()
    candidate = _candidate(
        site="mt",
        source_url="https://kp.m-team.cc/detail/1171443",
        download_url="mteam-api://torrent/1171443",
        metadata={
            "mteam_discovery_mode": "api",
            "download_url_source": "mteam_api_deferred",
            "mteam_torrent_id": "1171443",
        },
    )
    scored = ScoreBreakdown(
        candidate_id=candidate.stable_id,
        score=95,
        accepted=True,
        reasons=["discount free accepted"],
        candidate=candidate,
    )

    async def fake_enrich(candidates, **_):
        return [
            candidates[0].model_copy(
                update={
                    "discount": Discount.HALF,
                    "metadata": {
                        **candidates[0].metadata,
                        "mteam_detail_enriched": True,
                    },
                }
            )
        ]

    monkeypatch.setattr(pt_actions, "enrich_candidates", fake_enrich)

    result = await pt_actions._revalidate_mteam_candidate(
        scored,
        config=config,
        api_key="secret-api-key",
        api_key_header="x-api-key",
    )

    assert result.accepted is False
    assert result.score == 0
    assert "discount 50% rejected by free-only policy" in result.reasons
    assert result.reasons[-1] == "mteam promotion preflight rejected"


@pytest.mark.asyncio
async def test_execute_free_only_guard_rejects_before_preflight_or_token(
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions

    config = _config()
    candidate = _candidate(
        site="mt",
        discount=Discount.HALF,
        source_url="https://kp.m-team.cc/detail/1171443",
        download_url="mteam-api://torrent/1171443",
        metadata={
            "download_url_source": "mteam_api_deferred",
            "mteam_torrent_id": "1171443",
        },
    )
    scored = [
        ScoreBreakdown(
            candidate_id=candidate.stable_id,
            score=95,
            accepted=True,
            reasons=["incorrectly accepted upstream"],
            candidate=candidate,
        )
    ]

    async def fail_preflight(*args, **kwargs):
        raise AssertionError("paid candidate must be rejected before tracker API calls")

    monkeypatch.setattr(pt_actions, "_revalidate_mteam_candidate", fail_preflight)

    resolved = await pt_actions.resolve_deferred_download_urls(scored, config)

    assert resolved[0].accepted is False
    assert resolved[0].score == 0
    assert resolved[0].reasons[-1] == ("discount 50% rejected by execute free-only policy")


def test_mteam_preflight_reapplies_execute_free_window_threshold() -> None:
    from seed_agent.actions import pt as pt_actions

    candidate = _candidate(left_time_minutes=150)
    item = ScoreBreakdown(
        candidate_id=candidate.stable_id,
        score=95,
        accepted=True,
        reasons=["mteam promotion preflight accepted"],
        candidate=candidate,
    )

    result = pt_actions._apply_mteam_preflight_free_window(
        item,
        min_free_window_minutes=180,
        require_known_free_window=True,
    )

    assert result.accepted is False
    assert result.score == 0
    assert result.reasons[-1] == ("mteam promotion preflight left_time 150 < execute safety 180")


def test_mteam_preflight_rejects_missing_refreshed_free_window() -> None:
    from seed_agent.actions import pt as pt_actions

    candidate = _candidate(
        left_time_minutes=None,
        metadata={"left_time_source": "mteam_api_missing"},
    )
    item = ScoreBreakdown(
        candidate_id=candidate.stable_id,
        score=95,
        accepted=True,
        reasons=["mteam promotion preflight accepted"],
        candidate=candidate,
    )

    result = pt_actions._apply_mteam_preflight_free_window(
        item,
        min_free_window_minutes=180,
        require_known_free_window=True,
    )

    assert result.accepted is False
    assert result.score == 0
    assert result.reasons[-1] == "mteam promotion preflight requires known free window"


@pytest.mark.asyncio
async def test_resolve_deferred_download_urls_rejects_candidate_on_mteam_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import httpx

    from seed_agent.actions import pt as pt_actions

    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
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
    candidate = _candidate(
        site="mt",
        source_url="https://kp.m-team.cc/detail/1171443",
        download_url="mteam-api://torrent/1171443",
        metadata={
            "mteam_discovery_mode": "api",
            "download_url_source": "mteam_api_deferred",
            "mteam_torrent_id": "1171443",
        },
    )
    scored = [
        ScoreBreakdown(
            candidate_id=candidate.stable_id,
            score=95,
            accepted=True,
            reasons=["ok"],
            candidate=candidate,
        )
    ]

    async def fake_resolve_deferred_download_url(
        candidate: TorrentCandidate,
        *,
        api_key: str,
        api_key_header: str,
    ) -> TorrentCandidate | None:
        raise httpx.ConnectTimeout("connect timed out")

    monkeypatch.setattr(pt_actions, "_revalidate_mteam_candidate", _accept_mteam_preflight)
    monkeypatch.setattr(
        pt_actions,
        "resolve_deferred_download_url",
        fake_resolve_deferred_download_url,
    )

    resolved = await pt_actions.resolve_deferred_download_urls(scored, config)

    assert resolved[0].accepted is False
    assert resolved[0].score == 0
    assert resolved[0].candidate.download_url == "mteam-api://torrent/1171443"
    assert resolved[0].reasons[-1] == "download_url unavailable from mteam api: ConnectTimeout"


@pytest.mark.asyncio
async def test_resolve_deferred_download_urls_stops_after_mteam_rate_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions
    from seed_agent.sites.mteam import MTeamApiResponseError

    monkeypatch.setattr(pt_actions, "_LAST_DISCOVERY_WARNINGS", ())
    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
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
    candidates = [
        _candidate(
            site="mt",
            source_url=f"https://kp.m-team.cc/detail/{torrent_id}",
            download_url=f"mteam-api://torrent/{torrent_id}",
            metadata={
                "mteam_discovery_mode": "api",
                "download_url_source": "mteam_api_deferred",
                "mteam_torrent_id": str(torrent_id),
            },
        )
        for torrent_id in (1171443, 1171444)
    ]
    scored = [
        ScoreBreakdown(
            candidate_id=candidate.stable_id,
            score=95,
            accepted=True,
            reasons=["ok"],
            candidate=candidate,
        )
        for candidate in candidates
    ]
    calls: list[str] = []

    async def fake_resolve_deferred_download_url(
        candidate: TorrentCandidate,
        *,
        api_key: str,
        api_key_header: str,
    ) -> TorrentCandidate | None:
        calls.append(candidate.stable_id)
        raise MTeamApiResponseError(
            endpoint="torrent/genDlToken",
            code="1",
            message="請求過於頻繁",
        )

    monkeypatch.setattr(pt_actions, "_revalidate_mteam_candidate", _accept_mteam_preflight)
    monkeypatch.setattr(
        pt_actions,
        "resolve_deferred_download_url",
        fake_resolve_deferred_download_url,
    )

    resolved = await pt_actions.resolve_deferred_download_urls(scored, config)

    assert calls == [candidates[0].stable_id]
    assert [item.accepted for item in resolved] == [False, False]
    assert [item.score for item in resolved] == [0, 0]
    assert [item.reasons[-1] for item in resolved] == [
        "mteam api rate limited",
        "mteam api rate limited",
    ]
    assert pt_actions.get_last_discovery_warnings() == [
        {
            "site": "mt",
            "error_type": "MTeamApiResponseError",
            "message": "torrent/genDlToken failed: code=1 message=請求過於頻繁",
            "endpoint": "torrent/genDlToken",
            "rate_limited": True,
            "unavailable": False,
        }
    ]


@pytest.mark.asyncio
async def test_resolve_deferred_download_urls_stops_after_mteam_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent.actions import pt as pt_actions
    from seed_agent.sites.mteam import MTeamApiResponseError

    monkeypatch.setattr(pt_actions, "_LAST_DISCOVERY_WARNINGS", ())
    api_key_path = tmp_path / "mt.api-key"
    api_key_path.write_text("secret-api-key\n", encoding="utf-8")
    config = SeedAgentConfig(
        **{
            **_config().model_dump(),
            "tracker_sites": [
                {
                    "name": "mt",
                    "type": "mteam",
                    "enabled": True,
                    "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
                    "api_key_ref": str(api_key_path),
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
    candidates = [
        _candidate(
            site="mt",
            source_url=f"https://kp.m-team.cc/detail/{torrent_id}",
            download_url=f"mteam-api://torrent/{torrent_id}",
            metadata={
                "mteam_discovery_mode": "api",
                "download_url_source": "mteam_api_deferred",
                "mteam_torrent_id": str(torrent_id),
            },
        )
        for torrent_id in (1171443, 1171444)
    ]
    scored = [
        ScoreBreakdown(
            candidate_id=candidate.stable_id,
            score=95,
            accepted=True,
            reasons=["ok"],
            candidate=candidate,
        )
        for candidate in candidates
    ]
    calls: list[str] = []

    async def fake_resolve_deferred_download_url(
        candidate: TorrentCandidate,
        *,
        api_key: str,
        api_key_header: str,
    ) -> TorrentCandidate | None:
        calls.append(candidate.stable_id)
        raise MTeamApiResponseError(
            endpoint="torrent/genDlToken",
            code="503",
            message="Service Unavailable",
            status_code=503,
        )

    monkeypatch.setattr(pt_actions, "_revalidate_mteam_candidate", _accept_mteam_preflight)
    monkeypatch.setattr(
        pt_actions,
        "resolve_deferred_download_url",
        fake_resolve_deferred_download_url,
    )

    resolved = await pt_actions.resolve_deferred_download_urls(scored, config)

    assert calls == [candidates[0].stable_id]
    assert [item.accepted for item in resolved] == [False, False]
    assert [item.reasons[-1] for item in resolved] == [
        "mteam api unavailable",
        "mteam api unavailable",
    ]
    assert pt_actions.get_last_discovery_warnings() == [
        {
            "site": "mt",
            "error_type": "MTeamApiResponseError",
            "message": "torrent/genDlToken failed: code=503 message=Service Unavailable",
            "endpoint": "torrent/genDlToken",
            "rate_limited": False,
            "unavailable": True,
        }
    ]


@pytest.mark.asyncio
async def test_discover_candidates_keeps_rss_mode_for_non_api_sites(monkeypatch) -> None:
    from seed_agent.actions import pt as pt_actions

    rss_calls: list[str] = []

    async def fake_fetch_rss_candidates(
        url: str,
        site: str,
        cookie: str | None = None,
        api_key: str | None = None,
        *,
        site_type: str = "nexusphp",
    ):
        rss_calls.append(site)
        return [_candidate(site=site)]

    monkeypatch.setattr(pt_actions, "fetch_rss_candidates", fake_fetch_rss_candidates)

    candidates = await pt_actions.discover_candidates(_config())

    assert rss_calls == ["demo-free"]
    assert candidates[0].site == "demo-free"


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
            candidate=_candidate(
                title="Cold Torrent", source_url="https://tracker.example/details.php?id=2"
            ),
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


def test_strategy_report_groups_tracker_signals_and_runtime_outcomes() -> None:
    from seed_agent.actions.pt import strategy_report

    hot_large = _candidate(
        title="Hot Large Pack",
        source_url="https://tracker.example/details.php?id=10",
        size_bytes=220 * 1024**3,
        seeders=180,
        leechers=30,
    )
    cold_small = _candidate(
        title="Cold Small Pack",
        source_url="https://tracker.example/details.php?id=11",
        size_bytes=12 * 1024**3,
        seeders=100,
        leechers=2,
    )
    scored = [
        ScoreBreakdown(
            candidate_id=hot_large.stable_id,
            score=91,
            accepted=True,
            reasons=["ok"],
            candidate=hot_large,
        ),
        ScoreBreakdown(
            candidate_id=cold_small.stable_id,
            score=0,
            accepted=False,
            reasons=["leechers 2 < min 8"],
            candidate=cold_small,
        ),
    ]
    managed = [
        ManagedTorrent(
            hash="hot-hash",
            name="Hot Large Pack",
            state="seeding",
            size_bytes=220 * 1024**3,
            uploaded_bytes=80 * 1024**3,
            downloaded_bytes=220 * 1024**3,
            added_at=datetime(2026, 5, 19, 0, 0, tzinfo=UTC),
        )
    ]
    managed_summaries = [
        {
            "hash": "hot-hash",
            "uploaded_gb": 80.0,
            "state": "seeding",
            "candidate_evidence": {
                "candidate_id": hot_large.stable_id,
                "seeders": 180,
                "leechers": 30,
                "size_gb": 220.0,
                "score": 91,
            },
        }
    ]

    report = strategy_report(
        scored,
        managed,
        managed_summaries=managed_summaries,
        site_history={
            "demo-free": {
                "site": "demo-free",
                "samples": 3,
                "score": 0.72,
                "applied": True,
            }
        },
    )

    assert report["candidate_distribution"]["total_scored"] == 2
    assert report["candidate_distribution"]["accepted"] == 1
    assert report["candidate_distribution"]["leechers"]["25+"]["accepted"] == 1
    assert report["candidate_distribution"]["leechers"]["0-4"]["rejected"] == 1
    assert report["candidate_distribution"]["size_gb"]["150+"]["accepted"] == 1
    assert report["runtime_outcomes"]["managed_torrents"] == 1
    assert report["runtime_outcomes"]["with_candidate_evidence"] == 1
    assert report["runtime_outcomes"]["uploaded_count"] == 1
    assert report["runtime_outcomes"]["avg_uploaded_gb"] == 80.0
    assert report["runtime_outcomes"]["by_candidate_leechers"]["25+"]["avg_uploaded_gb"] == 80.0
    assert report["runtime_outcomes"]["by_enqueue_age"]["unknown"]["avg_uploaded_gb"] == 80.0
    assert report["site_history"]["demo-free"]["score"] == 0.72
