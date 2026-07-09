from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from seed_agent.models import ManagedTorrent
from seed_agent.policies.quality import torrent_eviction_pressure_score


@dataclass(frozen=True)
class EvictionCandidate:
    torrent: ManagedTorrent
    score: float


def rank_eviction_candidates(torrents: Sequence[ManagedTorrent]) -> list[ManagedTorrent]:
    return [
        candidate.torrent
        for candidate in sorted(
            (
                EvictionCandidate(
                    torrent=torrent,
                    score=torrent_eviction_pressure_score(torrent),
                )
                for torrent in torrents
            ),
            key=lambda item: item.score,
            reverse=True,
        )
    ]
