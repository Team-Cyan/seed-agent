from pathlib import Path

import pytest

from seed_agent.config import SeedAgentConfig, load_config


def test_load_config_accepts_example_shape(tmp_path: Path) -> None:
    secret_path = tmp_path / "downloader.secret.yaml"
    secret_path.write_text("username: qb\npassword: secret\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
mode: balanced
sites:
  - name: demo-free
    type: rss
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
  - name: demo-disabled
    type: rss
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
  category: pt-auto
  tags: ["seed-agent", "pt-auto"]
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


def test_cleanup_pause_before_delete_hours_below_one_raises() -> None:
    with pytest.raises(ValueError, match="pause_before_delete_hours"):
        SeedAgentConfig(
            mode="balanced",
            sites=[],
            discovery={
                "discounts": ["free"],
                "min_left_time_minutes": 120,
                "min_leechers": 8,
                "max_seeders": 80,
                "allow_hr": False,
            },
            scoring={
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
            downloader={
                "type": "qbittorrent",
                "target": "unraid-qb",
                "category": "pt-auto",
                "tags": ["seed-agent", "pt-auto"],
            },
            cleanup={
                "cold_after_days": 7,
                "min_upload_delta_gb": 1,
                "protect_hr": True,
                "protect_manual": True,
                "protect_media_library": True,
                "pause_before_delete_hours": 0,
            },
        )


def test_scoring_weights_must_sum_to_100() -> None:
    with pytest.raises(ValueError, match="weights"):
        SeedAgentConfig(
            mode="balanced",
            sites=[],
            discovery={
                "discounts": ["free"],
                "min_left_time_minutes": 120,
                "min_leechers": 8,
                "max_seeders": 80,
                "allow_hr": False,
            },
            scoring={
                "min_score_to_enqueue": 70,
                "weights": {
                    "discount": 30,
                    "leechers": 25,
                    "seeders": 15,
                    "left_time": 15,
                    "size": 10,
                    "site_history": 6,
                },
            },
            downloader={
                "type": "qbittorrent",
                "target": "unraid-qb",
                "category": "pt-auto",
                "tags": ["seed-agent", "pt-auto"],
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
