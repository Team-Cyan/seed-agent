from __future__ import annotations

from datetime import UTC, datetime

from seed_agent.config import BudgetPoolConfig, CategoryPolicyConfig
from seed_agent.models import ManagedTorrent
from seed_agent.policies.category_policy import usage_by_pool


def _torrent(*, category: str, size_bytes: int) -> ManagedTorrent:
    return ManagedTorrent(
        hash=f"{category}-{size_bytes}",
        name=f"{category}-{size_bytes}",
        category=category,
        tags={"seed-agent", category},
        state="uploading",
        size_bytes=size_bytes,
        uploaded_bytes=0,
        downloaded_bytes=size_bytes,
        added_at=datetime.now(UTC),
        completed_at=None,
        last_activity_at=None,
        save_path=f"/downloads/{category}",
        metadata={},
    )


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
    pools = [BudgetPoolConfig(name="media", max_size_tib=10)]
    torrents = [
        _torrent(category="movie", size_bytes=3 * 1024**4),
        _torrent(category="tv", size_bytes=2 * 1024**4),
    ]

    usage = usage_by_pool(policies, pools, torrents)

    assert usage["media"].size_bytes == 5 * 1024**4
