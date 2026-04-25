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
            }
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
                }
            ],
            "budget_pools": [
                {
                    "name": "downloads",
                    "max_size_tib": 10,
                }
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


def _phase2_data() -> dict[str, object]:
    data = _valid_config_data("local/secrets/qb.yaml")
    data.update(
        {
            "intent": {
                "confirmation_threshold": 0.82,
                "auto_enqueue_threshold": 0.94,
                "ambiguity_gap": 0.08,
                "default_resolution": "1080p",
                "preferred_languages": ["zh", "en"],
                "inbox_ref": "local/inbox/intents.jsonl",
            },
            "search": {
                "site_priority": {"demo-free": 10},
                "max_results_per_site": 20,
                "prefer_free": True,
                "reject_hr_by_default": True,
            },
            "sources": {
                "telegram": {
                    "enabled": False,
                    "secret_ref": "local/secrets/telegram.yaml",
                },
                "wechat_bridge": {
                    "enabled": False,
                    "secret_ref": "local/secrets/wechat-bridge.yaml",
                },
                "douban_wanted": {
                    "enabled": False,
                    "export_ref": "local/inbox/douban-wanted.json",
                },
                "subscription": {
                    "enabled": False,
                    "rules_ref": "config/subscriptions.yaml",
                },
            },
        }
    )
    return data


def test_phase2_config_accepts_intent_search_and_source_sections() -> None:
    config = SeedAgentConfig(**_phase2_data())

    assert config.intent.confirmation_threshold == 0.82
    assert config.intent.auto_enqueue_threshold == 0.94
    assert config.intent.inbox_ref == "local/inbox/intents.jsonl"
    assert config.search.site_priority == {"demo-free": 10}
    assert config.sources.telegram.secret_ref == "local/secrets/telegram.yaml"
    assert config.sources.douban_wanted.export_ref == "local/inbox/douban-wanted.json"


def test_phase2_config_defaults_keep_phase1_configs_loadable() -> None:
    config = SeedAgentConfig(**_valid_config_data("local/secrets/qb.yaml"))

    assert config.intent.confirmation_threshold == 0.82
    assert config.search.max_results_per_site == 20
    assert config.sources.telegram.enabled is False


def test_load_config_reads_phase2_example(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode: balanced
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
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
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: local/secrets/qbittorrent.yaml
cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
intent:
  confirmation_threshold: 0.82
  auto_enqueue_threshold: 0.94
  ambiguity_gap: 0.08
  default_resolution: 1080p
  preferred_languages: ["zh", "en"]
  inbox_ref: local/inbox/intents.jsonl
search:
  site_priority:
    demo-free: 10
  max_results_per_site: 20
  prefer_free: true
  reject_hr_by_default: true
sources:
  telegram:
    enabled: false
    secret_ref: local/secrets/telegram.yaml
  wechat_bridge:
    enabled: false
    secret_ref: local/secrets/wechat-bridge.yaml
  douban_wanted:
    enabled: false
    export_ref: local/inbox/douban-wanted.json
  subscription:
    enabled: false
    rules_ref: config/subscriptions.yaml
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.intent.default_resolution == "1080p"
    assert config.search.site_priority["demo-free"] == 10
    assert config.sources.subscription.rules_ref == "config/subscriptions.yaml"
    assert config.downloader.default_category == "seed"


def test_phase2_config_accepts_category_policy_downloader_shape() -> None:
    config = SeedAgentConfig(**_phase2_data())

    assert config.downloader.default_category == "seed"
    assert config.downloader.category_policies[0].budget_pool == "downloads"


def test_phase2_config_rejects_unknown_intent_key() -> None:
    data = _phase2_data()
    data["intent"] = {**data["intent"], "surprise": True}

    with pytest.raises(ValidationError, match="surprise"):
        SeedAgentConfig(**data)


def test_phase2_config_rejects_invalid_threshold_order() -> None:
    data = _phase2_data()
    data["intent"] = {
        **data["intent"],
        "confirmation_threshold": 0.95,
        "auto_enqueue_threshold": 0.9,
    }

    with pytest.raises(ValidationError, match="auto_enqueue_threshold"):
        SeedAgentConfig(**data)


def test_phase2_config_rejects_string_bool_and_invalid_search_limit() -> None:
    data = _phase2_data()
    data["sources"] = {
        **data["sources"],
        "telegram": {"enabled": "false", "secret_ref": "local/secrets/telegram.yaml"},
    }

    with pytest.raises(ValidationError, match="enabled"):
        SeedAgentConfig(**data)

    data = _phase2_data()
    data["search"] = {**data["search"], "max_results_per_site": 0}

    with pytest.raises(ValidationError, match="max_results_per_site"):
        SeedAgentConfig(**data)


def test_phase2_config_rejects_source_specific_wrong_ref_fields() -> None:
    data = _phase2_data()
    data["sources"] = {
        **data["sources"],
        "telegram": {"enabled": False, "export_ref": "local/inbox/telegram.json"},
    }

    with pytest.raises(ValidationError, match="export_ref"):
        SeedAgentConfig(**data)

    data = _phase2_data()
    data["sources"] = {
        **data["sources"],
        "douban_wanted": {"enabled": False, "secret_ref": "local/secrets/douban.yaml"},
    }

    with pytest.raises(ValidationError, match="secret_ref"):
        SeedAgentConfig(**data)
