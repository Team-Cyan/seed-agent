from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from seed_agent.models import ManagedTorrent


@dataclass(frozen=True)
class EvictionCandidate:
    torrent: ManagedTorrent
    score: float


def rank_eviction_candidates(torrents: Sequence[ManagedTorrent]) -> list[ManagedTorrent]:
    def eviction_score(torrent: ManagedTorrent) -> float:
        recent_upload = float(torrent.metadata.get("recent_upload_gb", 0) or 0)
        size_gib = torrent.size_bytes / 1024**3
        uploaded_gib = torrent.uploaded_bytes / 1024**3
        upload_density = uploaded_gib / size_gib if size_gib else 0
        activity_penalty = 0 if torrent.last_activity_at else 25
        return (
            (size_gib * 0.05)
            + activity_penalty
            - (recent_upload * 2.0)
            - (upload_density * 10.0)
        )

    return [
        candidate.torrent
        for candidate in sorted(
            (
                EvictionCandidate(torrent=torrent, score=eviction_score(torrent))
                for torrent in torrents
            ),
            key=lambda item: item.score,
            reverse=True,
        )
    ]
