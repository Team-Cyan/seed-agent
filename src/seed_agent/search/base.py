from __future__ import annotations

from typing import Protocol

from seed_agent.models import ReleaseCandidate, ResourceIntent


class SearchProvider(Protocol):
    async def search(self, intent: ResourceIntent) -> list[ReleaseCandidate]:
        """Return release candidates for a normalized resource intent."""
