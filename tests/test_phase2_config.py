from pathlib import Path

import pytest
from pydantic import ValidationError

from seed_agent.config import SeedAgentConfig, load_config


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
            }
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
        "seed_cleanup": {
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
            "want_decision": {
                "confirmation_threshold": 0.82,
                "auto_enqueue_threshold": 0.94,
                "ambiguity_gap": 0.08,
                "default_resolution": "1080p",
                "preferred_languages": ["zh", "en"],
                "inbox_ref": "local/inbox/intents.jsonl",
            },
            "release_preferences": {
                "site_priority": {"demo-free": 10},
                "max_results_per_site": 20,
                "prefer_free": True,
                "reject_hr_by_default": True,
                "quality_tag_scores": {
                    "remux": 20,
                    "dolby_vision": 15,
                    "webdl": -10,
                },
            },
            "want_sources": {
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
                    "user_name": "example-user",
                    "max_pages": 2,
                },
                "want_lists": [
                    {
                        "provider": "douban",
                        "id": "douban-me",
                        "label": "我",
                        "enabled": True,
                        "user_name": "example-user",
                        "max_pages": 2,
                    },
                    {
                        "provider": "imdb",
                        "id": "imdb-weekend",
                        "label": "周末清单",
                        "enabled": True,
                        "watchlist_url": "https://www.imdb.com/user/p.demo/watchlist/",
                        "export_ref": "local/inbox/imdb-weekend.csv",
                    },
                    {
                        "provider": "letterboxd",
                        "id": "letterboxd-watchlist",
                        "label": "Watchlist",
                        "enabled": True,
                        "export_ref": "local/inbox/letterboxd-watchlist.csv",
                    },
                ],
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

    assert config.want_decision.confirmation_threshold == 0.82
    assert config.want_decision.auto_enqueue_threshold == 0.94
    assert config.want_decision.inbox_ref == "local/inbox/intents.jsonl"
    assert config.want_decision.series_search_mode == "season"
    assert config.release_preferences.site_priority == {"demo-free": 10}
    assert config.release_preferences.quality_tag_scores == {
        "remux": 20,
        "dolby_vision": 15,
        "webdl": -10,
    }
    assert config.want_sources.telegram.secret_ref == "local/secrets/telegram.yaml"
    assert config.want_sources.douban_wanted.export_ref == "local/inbox/douban-wanted.json"
    assert config.want_sources.douban_wanted.user_name == "example-user"
    assert config.want_sources.douban_wanted.max_pages == 2
    assert config.want_sources.want_lists[0].provider == "douban"
    assert config.want_sources.want_lists[0].id == "douban-me"
    assert config.want_sources.want_lists[0].label == "我"
    assert config.want_sources.want_lists[1].provider == "imdb"
    assert config.want_sources.want_lists[1].watchlist_url == "https://www.imdb.com/user/p.demo/watchlist/"
    assert config.want_sources.want_lists[2].provider == "letterboxd"
    assert config.want_sources.want_lists[2].export_ref == "local/inbox/letterboxd-watchlist.csv"


def test_phase2_config_defaults_keep_phase1_configs_loadable() -> None:
    config = SeedAgentConfig(**_valid_config_data("local/secrets/qb.yaml"))

    assert config.want_decision.confirmation_threshold == 0.82
    assert config.want_decision.series_search_mode == "season"
    assert config.release_preferences.max_results_per_site == 20
    assert config.release_preferences.quality_tag_scores == {}
    assert config.want_sources.telegram.enabled is False
    assert config.want_sources.douban_wanted.max_pages == 1
    assert config.want_sources.want_lists == []


def test_phase2_config_accepts_episode_series_search_mode() -> None:
    data = _phase2_data()
    intent = data["want_decision"]
    assert isinstance(intent, dict)
    intent["series_search_mode"] = "episode"

    config = SeedAgentConfig(**data)

    assert config.want_decision.series_search_mode == "episode"


def test_load_config_reads_phase2_example(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode: balanced
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
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
  secret_ref: local/secrets/qbittorrent.yaml
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
want_decision:
  confirmation_threshold: 0.82
  auto_enqueue_threshold: 0.94
  ambiguity_gap: 0.08
  default_resolution: 1080p
  preferred_languages: ["zh", "en"]
  inbox_ref: local/inbox/intents.jsonl
release_preferences:
  site_priority:
    demo-free: 10
  max_results_per_site: 20
  prefer_free: true
  reject_hr_by_default: true
  quality_tag_scores:
    remux: 20
    webdl: -10
want_sources:
  telegram:
    enabled: false
    secret_ref: local/secrets/telegram.yaml
  wechat_bridge:
    enabled: false
    secret_ref: local/secrets/wechat-bridge.yaml
  douban_wanted:
    enabled: false
    export_ref: local/inbox/douban-wanted.json
    user_name: example-user
    max_pages: 2
  want_lists:
    - provider: douban
      id: douban-me
      label: 我
      enabled: true
      user_name: example-user
      max_pages: 2
    - provider: imdb
      id: imdb-weekend
      label: 周末清单
      enabled: true
      watchlist_url: https://www.imdb.com/user/p.demo/watchlist/
      export_ref: local/inbox/imdb-weekend.csv
    - provider: letterboxd
      id: letterboxd-watchlist
      label: Watchlist
      enabled: true
      export_ref: local/inbox/letterboxd-watchlist.csv
  subscription:
    enabled: false
    rules_ref: config/subscriptions.yaml
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.want_decision.default_resolution == "1080p"
    assert config.release_preferences.site_priority["demo-free"] == 10
    assert config.release_preferences.quality_tag_scores == {"remux": 20, "webdl": -10}
    assert config.want_sources.douban_wanted.user_name == "example-user"
    assert config.want_sources.douban_wanted.max_pages == 2
    assert config.want_sources.want_lists[0].provider == "douban"
    assert config.want_sources.want_lists[1].provider == "imdb"
    assert config.want_sources.want_lists[1].export_ref == "local/inbox/imdb-weekend.csv"
    assert config.want_sources.want_lists[2].provider == "letterboxd"
    assert config.want_sources.subscription.rules_ref == "config/subscriptions.yaml"
    assert config.download_client.default_category == "seed"


def test_phase2_config_rejects_invalid_douban_page_limit() -> None:
    data = _phase2_data()
    sources = dict(data["want_sources"])  # type: ignore[arg-type]
    douban = dict(sources["douban_wanted"])  # type: ignore[index]
    douban["max_pages"] = 0
    sources["douban_wanted"] = douban
    data["want_sources"] = sources

    with pytest.raises(ValidationError, match="max_pages"):
        SeedAgentConfig(**data)


def test_phase2_config_accepts_category_policy_downloader_shape() -> None:
    config = SeedAgentConfig(**_phase2_data())

    assert config.download_client.default_category == "seed"
    assert config.download_client.category_policies[0].budget_pool == "downloads"


def test_phase2_config_rejects_unknown_intent_key() -> None:
    data = _phase2_data()
    data["want_decision"] = {**data["want_decision"], "surprise": True}

    with pytest.raises(ValidationError, match="surprise"):
        SeedAgentConfig(**data)


def test_phase2_config_rejects_invalid_threshold_order() -> None:
    data = _phase2_data()
    data["want_decision"] = {
        **data["want_decision"],
        "confirmation_threshold": 0.95,
        "auto_enqueue_threshold": 0.9,
    }

    with pytest.raises(ValidationError, match="auto_enqueue_threshold"):
        SeedAgentConfig(**data)


def test_phase2_config_rejects_string_bool_and_invalid_search_limit() -> None:
    data = _phase2_data()
    data["want_sources"] = {
        **data["want_sources"],
        "telegram": {"enabled": "false", "secret_ref": "local/secrets/telegram.yaml"},
    }

    with pytest.raises(ValidationError, match="enabled"):
        SeedAgentConfig(**data)

    data = _phase2_data()
    data["release_preferences"] = {**data["release_preferences"], "max_results_per_site": 0}

    with pytest.raises(ValidationError, match="max_results_per_site"):
        SeedAgentConfig(**data)


def test_phase2_config_rejects_source_specific_wrong_ref_fields() -> None:
    data = _phase2_data()
    data["want_sources"] = {
        **data["want_sources"],
        "telegram": {"enabled": False, "export_ref": "local/inbox/telegram.json"},
    }

    with pytest.raises(ValidationError, match="export_ref"):
        SeedAgentConfig(**data)

    data = _phase2_data()
    data["want_sources"] = {
        **data["want_sources"],
        "douban_wanted": {"enabled": False, "secret_ref": "local/secrets/douban.yaml"},
    }

    with pytest.raises(ValidationError, match="secret_ref"):
        SeedAgentConfig(**data)

    data = _phase2_data()
    sources = dict(data["want_sources"])  # type: ignore[arg-type]
    sources["want_lists"] = [
        {
            "provider": "letterboxd",
            "id": "letterboxd-empty",
            "label": "Empty",
            "enabled": True,
        }
    ]
    data["want_sources"] = sources

    with pytest.raises(ValidationError, match="letterboxd want list requires export_ref"):
        SeedAgentConfig(**data)
