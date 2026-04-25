from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from seed_agent.config import BudgetPoolConfig, CategoryPolicyConfig
from seed_agent.models import ManagedTorrent


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
        pool_name: PoolUsage(
            pool_name=pool_name,
            size_bytes=totals[pool_name],
            max_size_bytes=pool_size_bytes(pool_lookup[pool_name]),
        )
        for pool_name in totals
    }
