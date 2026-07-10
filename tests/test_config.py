from pathlib import Path

import pytest
from pydantic import ValidationError

from seed_agent.config import SeedAgentConfig, load_config, write_config_mapping


def _valid_config_data(secret_ref: str) -> dict[str, object]:
    return {
        "mode": "balanced",
        "tracker_sites": [
            {
                "name": "demo-free",
                "type": "nexusphp",
                "enabled": True,
                "rss_url": "https://tracker.example/rss.php",
                "cookie_ref": None,
                "api_key_ref": None,
            },
            {
                "name": "demo-disabled",
                "type": "nexusphp",
                "enabled": False,
                "rss_url": "https://tracker.example/rss-disabled.php",
            },
        ],
        "pt_filters": {
            "discounts": ["free", "2xfree"],
            "min_left_time_minutes": 120,
            "min_leechers": 8,
            "target_seed_leecher_ratio": 10,
            "allow_hr": False,
        },
        "pt_scoring": {
            "min_score_to_enqueue": 70,
            "weights": {
                "discount": 30,
                "leechers": 25,
                "seeders": 15,
                "left_time": 15,
                "size": 10,
                "site_history": 5,
            },
        },
        "download_client": {
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
                },
                {
                    "name": "movie",
                    "mode": "add_only",
                    "budget_pool": "media",
                    "delete_enabled": False,
                    "over_budget_behavior": "add_paused",
                    "tags": ["seed-agent", "movie"],
                },
            ],
            "budget_pools": [
                {
                    "name": "downloads",
                    "max_size_tib": 10,
                },
                {
                    "name": "media",
                    "max_size_tib": 10,
                },
            ],
            "secret_ref": secret_ref,
        },
        "seed_cleanup": {
            "cold_after_days": 7,
            "min_upload_delta_gb": 1,
            "protect_hr": True,
            "protect_manual": True,
            "protect_media_library": True,
            "pause_before_delete_hours": 24,
        },
    }


def test_load_config_accepts_example_shape(tmp_path: Path) -> None:
    secret_path = tmp_path / "downloader.secret.yaml"
    secret_path.write_text("username: qb\npassword: secret\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode: balanced
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
  - name: demo-disabled
    type: nexusphp
    enabled: false
    rss_url: https://tracker.example/rss-disabled.php
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
  secret_ref: {secret_path.as_posix()}
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

    assert isinstance(config, SeedAgentConfig)
    assert len(config.enabled_sites) == 1
    assert config.enabled_sites[0].name == "demo-free"
    assert config.download_client.secret_ref == secret_path.as_posix()
    assert config.download_client.default_category == "seed"
    assert [policy.name for policy in config.download_client.category_policies] == ["seed", "movie"]
    assert [pool.name for pool in config.download_client.budget_pools] == ["downloads", "media"]
    assert config.config_dir == config_path.parent.resolve()
    assert "config_dir" not in config.model_dump()


def test_load_config_supports_category_policies_and_budget_pools(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites:
  - name: demo
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
pt_filters:
  discounts: ["free"]
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

    assert config.download_client.default_category == "seed"
    assert [policy.name for policy in config.download_client.category_policies] == ["seed", "movie"]
    assert [pool.name for pool in config.download_client.budget_pools] == ["downloads", "media"]


def test_downloader_media_category_map_routes_want_types_to_configured_categories() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["download_client"]["category_policies"].append(
        {
            "name": "anime",
            "mode": "add_only",
            "budget_pool": "media",
            "delete_enabled": False,
            "over_budget_behavior": "add_paused",
            "tags": ["seed-agent", "anime"],
        }
    )
    data["download_client"]["category_policies"].append(
        {
            "name": "tv",
            "mode": "add_only",
            "budget_pool": "media",
            "delete_enabled": False,
            "over_budget_behavior": "add_paused",
            "tags": ["seed-agent", "tv"],
        }
    )
    data["download_client"]["media_category_map"] = {
        "movie": "movie",
        "tv": "tv",
        "anime": "anime",
    }

    config = SeedAgentConfig(**data)

    assert config.download_client.media_category_map == {
        "movie": "movie",
        "tv": "tv",
        "anime": "anime",
    }


def test_downloader_media_category_map_rejects_unknown_category() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["download_client"]["media_category_map"] = {"movie": "missing"}

    try:
        SeedAgentConfig(**data)
    except ValueError as exc:
        assert "media_category_map movie references unknown category missing" in str(exc)
    else:
        raise AssertionError("expected media_category_map validation failure")


def test_load_config_accepts_optional_runtime_enqueue_gates(tmp_path: Path) -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {
        **data["pt_filters"],
        "max_active_downloads": 3,
        "max_total_amount_left_gb": 150,
        "min_free_disk_gb": 250,
    }

    config = SeedAgentConfig(**data)

    assert config.pt_filters.max_active_downloads == 3
    assert config.pt_filters.max_total_amount_left_gb == 150
    assert config.pt_filters.min_free_disk_gb == 250


def test_discovery_accepts_ratio_seed_pressure_config_name() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    discovery = dict(data["pt_filters"])  # type: ignore[arg-type]
    discovery["target_seed_leecher_ratio"] = 12.5
    discovery["allow_non_free"] = True
    data["pt_filters"] = discovery

    config = SeedAgentConfig(**data)

    assert config.pt_filters.target_seed_leecher_ratio == 12.5
    assert config.pt_filters.allow_non_free is True


def test_discovery_rejects_legacy_max_seeders() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"]["max_seeders"] = 80  # type: ignore[index]

    with pytest.raises(ValidationError, match="max_seeders"):
        SeedAgentConfig(**data)


def test_unknown_config_key_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        SeedAgentConfig(**{**_valid_config_data("local/secrets/qb.yaml"), "unexpected": True})


def test_invalid_mode_raises_validation_error() -> None:
    data = {**_valid_config_data("local/secrets/qb.yaml"), "mode": "balaned"}

    with pytest.raises(ValidationError, match="balanced"):
        SeedAgentConfig(**data)


def test_invalid_site_type_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
        {
            "name": "demo-free",
            "type": "nexusphpp",
            "enabled": True,
            "rss_url": "https://tracker.example/rss.php",
            "cookie_ref": None,
            "api_key_ref": None,
        }
    ]

    with pytest.raises(ValidationError, match="nexusphp|mteam"):
        SeedAgentConfig(**data)


def test_mteam_site_type_is_accepted() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
        {
            "name": "mt",
            "type": "mteam",
            "enabled": True,
            "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
            "cookie_ref": None,
            "api_key_ref": "local/secrets/mt.api-key",
        }
    ]

    config = SeedAgentConfig(**data)

    assert config.enabled_sites[0].type == "mteam"
    assert config.enabled_sites[0].api_key_ref == "local/secrets/mt.api-key"


def test_mteam_site_accepts_api_discovery_mode() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
        {
            "name": "mt",
            "type": "mteam",
            "enabled": True,
            "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
            "api_key_ref": "local/secrets/mt.api-key",
            "discovery_mode": "api",
            "api_discovery": {
                "mode": "adult",
                "modes": ["normal", "adult"],
                "page_number": 2,
                "only_free": True,
                "discount": "_2X_FREE",
                "sort_field": "downloads",
                "sort_order": "desc",
                "page_size": 100,
                "max_pages": 3,
                "keyword": "demo",
                "categories": [410, 429],
                "sources": [8],
                "mediums": [10],
                "standards": [1, 6],
                "video_codecs": [1, 16],
                "audio_codecs": [6],
                "teams": [9],
                "processings": [2],
                "labels_new": ["DIY"],
                "hot": True,
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
    assert site.api_discovery.modes == ["normal", "adult"]
    assert site.api_discovery.page_number == 2
    assert site.api_discovery.max_pages == 3
    assert site.api_discovery.categories == [410, 429]
    assert site.api_discovery.standards == [1, 6]
    assert site.api_discovery.hot is True


def test_mteam_api_discovery_rejects_invalid_openapi_filter_limits() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
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
                "page_size": 201,
                "categories": [-1],
                "min_seeders": 0,
                "max_seeders": 200,
                "min_leechers": 0,
                "min_times_completed": 0,
            },
        }
    ]

    with pytest.raises(ValidationError):
        SeedAgentConfig(**data)


def test_mteam_api_discovery_rejects_duplicate_modes() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
        {
            "name": "mt",
            "type": "mteam",
            "enabled": True,
            "rss_url": "https://rss.m-team.cc/api/rss/fetch?dl=1",
            "api_key_ref": "local/secrets/mt.api-key",
            "discovery_mode": "api",
            "api_discovery": {
                "mode": "adult",
                "modes": ["normal", "normal"],
                "only_free": True,
                "sort_field": "downloads",
                "sort_order": "desc",
                "page_size": 100,
                "min_seeders": 0,
                "max_seeders": 200,
                "min_leechers": 0,
                "min_times_completed": 0,
            },
        }
    ]

    with pytest.raises(ValidationError, match="modes"):
        SeedAgentConfig(**data)


def test_mteam_api_discovery_allows_zero_max_seeders_as_unbounded() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
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
                "page_size": 100,
                "categories": [410],
                "min_seeders": 1,
                "max_seeders": 0,
                "min_leechers": 0,
                "min_times_completed": 0,
            },
        }
    ]

    config = SeedAgentConfig(**data)

    assert config.enabled_sites[0].api_discovery is not None
    assert config.enabled_sites[0].api_discovery.max_seeders == 0


def test_discovery_rejects_invalid_size_limits() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {
        **data["pt_filters"],
        "min_size_gb": 200,
        "max_size_gb": 150,
    }

    with pytest.raises(ValidationError, match="max_size_gb"):
        SeedAgentConfig(**data)


def test_discovery_rejects_zero_max_size() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {**data["pt_filters"], "max_size_gb": 0}

    with pytest.raises(ValidationError, match="max_size_gb"):
        SeedAgentConfig(**data)


def test_non_mteam_site_rejects_api_discovery_mode() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"][0] = {
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
    data["tracker_sites"] = [
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


def test_torznab_site_type_accepts_api_key_ref_without_mteam_api_discovery() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
        {
            "name": "torznab-demo",
            "type": "torznab",
            "enabled": True,
            "rss_url": "https://indexer.example/api",
            "api_key_ref": "local/secrets/torznab-api-key.txt",
        }
    ]

    config = SeedAgentConfig(**data)

    assert config.tracker_sites[0].type == "torznab"
    assert config.tracker_sites[0].api_key_ref == "local/secrets/torznab-api-key.txt"


def test_invalid_downloader_type_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["download_client"] = {**data["download_client"], "type": "qbittorrentx"}

    with pytest.raises(ValidationError, match="qbittorrent"):
        SeedAgentConfig(**data)


def test_transmission_downloader_type_uses_existing_policy_shape() -> None:
    data = _valid_config_data("local/secrets/transmission.yaml")
    data["download_client"] = {**data["download_client"], "type": "transmission"}

    config = SeedAgentConfig(**data)

    assert config.download_client.type == "transmission"
    assert config.download_client.default_category == "seed"


def test_discovery_numeric_fields_reject_strings() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {**data["pt_filters"], "min_left_time_minutes": "120"}

    with pytest.raises(ValidationError, match="min_left_time_minutes"):
        SeedAgentConfig(**data)


def test_discovery_bool_fields_reject_strings() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {**data["pt_filters"], "allow_hr": "false"}

    with pytest.raises(ValidationError, match="allow_hr"):
        SeedAgentConfig(**data)


def test_unknown_site_key_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["tracker_sites"] = [
        {
            "name": "demo-free",
            "type": "nexusphp",
            "enabled": True,
            "rss_url": "https://tracker.example/rss.php",
            "cookie_ref": None,
            "typo": "boom",
        }
    ]

    with pytest.raises(ValidationError):
        SeedAgentConfig(**data)


def test_discovery_unknown_discount_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {**data["pt_filters"], "discounts": ["free", "2xfre"]}

    with pytest.raises(ValidationError, match="unknown discount label"):
        SeedAgentConfig(**data)


def test_discovery_discounts_must_be_a_list() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {**data["pt_filters"], "discounts": "free"}

    with pytest.raises(ValidationError, match="discounts must be a list"):
        SeedAgentConfig(**data)


def test_discovery_null_discounts_raise_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_filters"] = {**data["pt_filters"], "discounts": None}

    with pytest.raises(ValidationError, match="discounts"):
        SeedAgentConfig(**data)


def test_scoring_weights_must_use_exact_keys() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_scoring"] = {
        "min_score_to_enqueue": 70,
        "weights": {
            "discount": 30,
            "leechers": 25,
            "seeders": 15,
            "left_time": 15,
            "size": 10,
            "site_history": 5,
            "bonus": 0,
        },
    }

    with pytest.raises(ValidationError, match="unknown keys: bonus"):
        SeedAgentConfig(**data)


def test_scoring_weights_missing_key_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_scoring"] = {
        "min_score_to_enqueue": 70,
        "weights": {
            "discount": 30,
            "leechers": 25,
            "seeders": 15,
            "left_time": 15,
            "size": 10,
        },
    }

    with pytest.raises(ValidationError, match="missing keys: site_history"):
        SeedAgentConfig(**data)


def test_scoring_weights_must_sum_to_100() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["pt_scoring"] = {
        "min_score_to_enqueue": 70,
        "weights": {
            "discount": 30,
            "leechers": 25,
            "seeders": 15,
            "left_time": 15,
            "size": 10,
            "site_history": 6,
        },
    }

    with pytest.raises(ValidationError, match="weights must sum to 100"):
        SeedAgentConfig(**data)


def test_cleanup_legacy_pause_delay_is_accepted_but_excluded() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["seed_cleanup"] = {**data["seed_cleanup"], "pause_before_delete_hours": 24}

    config = SeedAgentConfig(**data)

    assert not hasattr(config.seed_cleanup, "pause_before_delete_hours")
    assert "pause_before_delete_hours" not in config.seed_cleanup.model_dump()


def test_scheduler_config_defaults_preserve_existing_cli_behavior() -> None:
    config = SeedAgentConfig(**_valid_config_data("local/secrets/qb.yaml"))

    assert config.scheduler.interval_minutes == 60
    assert config.scheduler.prune_enabled is False
    assert config.scheduler.tracker_backfill_enabled is True
    assert config.scheduler.intent_search_mode == "daily"


def test_scheduler_config_rejects_invalid_daily_search_hour() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["scheduler"] = {"intent_search_hour": 24}

    with pytest.raises(ValidationError, match="intent_search_hour"):
        SeedAgentConfig(**data)


def test_scheduler_config_applies_only_explicit_overrides() -> None:
    base = SeedAgentConfig(**_valid_config_data("local/secrets/qb.yaml")).scheduler

    resolved = base.with_overrides(
        {
            "interval_minutes": 15,
            "min_free_window_minutes": 0,
            "prune_enabled": None,
        }
    )

    assert resolved.interval_minutes == 15
    assert resolved.min_free_window_minutes is None
    assert resolved.prune_enabled is base.prune_enabled


def test_write_config_mapping_atomically_replaces_valid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seed_agent import config as config_module

    path = tmp_path / "config.yaml"
    path.write_text("mode: balanced\n", encoding="utf-8")
    path.chmod(0o640)
    replacements: list[tuple[Path, Path]] = []
    real_replace = config_module.os.replace

    def track_replace(source: Path, target: Path) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(config_module.os, "replace", track_replace)

    write_config_mapping(path, _valid_config_data("local/secrets/qb.yaml"))

    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert path.stat().st_mode & 0o777 == 0o640
    assert load_config(path).download_client.default_category == "seed"
    written = path.read_text(encoding="utf-8")
    assert "scheduler:" in written
    assert "pause_before_delete_hours" not in written
