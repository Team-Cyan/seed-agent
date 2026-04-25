from pathlib import Path

import pytest
from pydantic import ValidationError

from seed_agent.config import SeedAgentConfig, load_config


def _valid_config_data(secret_ref: str) -> dict[str, object]:
    return {
        "mode": "balanced",
        "sites": [
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
        "discovery": {
            "discounts": ["free", "2xfree"],
            "min_left_time_minutes": 120,
            "min_leechers": 8,
            "max_seeders": 80,
            "allow_hr": False,
        },
        "scoring": {
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
        "downloader": {
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
        "cleanup": {
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
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
  - name: demo-disabled
    type: nexusphp
    enabled: false
    rss_url: https://tracker.example/rss-disabled.php
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

    assert isinstance(config, SeedAgentConfig)
    assert len(config.enabled_sites) == 1
    assert config.enabled_sites[0].name == "demo-free"
    assert config.downloader.secret_ref == secret_path.as_posix()
    assert config.downloader.default_category == "seed"
    assert [policy.name for policy in config.downloader.category_policies] == ["seed", "movie"]
    assert [pool.name for pool in config.downloader.budget_pools] == ["downloads", "media"]
    assert config.config_dir == config_path.parent.resolve()
    assert "config_dir" not in config.model_dump()


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


def test_unknown_config_key_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        SeedAgentConfig(**{**_valid_config_data("local/secrets/qb.yaml"), "unexpected": True})


def test_invalid_mode_raises_validation_error() -> None:
    data = {**_valid_config_data("local/secrets/qb.yaml"), "mode": "balaned"}

    with pytest.raises(ValidationError, match="balanced"):
        SeedAgentConfig(**data)


def test_invalid_site_type_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["sites"] = [
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
    data["sites"] = [
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


def test_invalid_downloader_type_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["downloader"] = {**data["downloader"], "type": "qbittorrentx"}

    with pytest.raises(ValidationError, match="qbittorrent"):
        SeedAgentConfig(**data)


def test_discovery_numeric_fields_reject_strings() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["discovery"] = {**data["discovery"], "min_left_time_minutes": "120"}

    with pytest.raises(ValidationError, match="min_left_time_minutes"):
        SeedAgentConfig(**data)


def test_discovery_bool_fields_reject_strings() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["discovery"] = {**data["discovery"], "allow_hr": "false"}

    with pytest.raises(ValidationError, match="allow_hr"):
        SeedAgentConfig(**data)


def test_unknown_site_key_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["sites"] = [
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
    data["discovery"] = {**data["discovery"], "discounts": ["free", "2xfre"]}

    with pytest.raises(ValidationError, match="unknown discount label"):
        SeedAgentConfig(**data)


def test_discovery_discounts_must_be_a_list() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["discovery"] = {**data["discovery"], "discounts": "free"}

    with pytest.raises(ValidationError, match="discounts must be a list"):
        SeedAgentConfig(**data)


def test_discovery_null_discounts_raise_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["discovery"] = {**data["discovery"], "discounts": None}

    with pytest.raises(ValidationError, match="discounts"):
        SeedAgentConfig(**data)


def test_scoring_weights_must_use_exact_keys() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["scoring"] = {
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
    data["scoring"] = {
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
    data["scoring"] = {
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


def test_cleanup_pause_before_delete_hours_zero_raises_validation_error() -> None:
    data = _valid_config_data("local/secrets/qb.yaml")
    data["cleanup"] = {**data["cleanup"], "pause_before_delete_hours": 0}

    with pytest.raises(ValidationError, match="pause_before_delete_hours"):
        SeedAgentConfig(**data)
