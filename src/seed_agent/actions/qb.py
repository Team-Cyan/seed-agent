from __future__ import annotations

from collections.abc import Iterable, Sequence

from seed_agent.downloaders.base import Downloader
from seed_agent.models import Decision, ScoreBreakdown

ROLLBACK_INSTRUCTION = "Delete torrent from qBittorrent if enqueue was accidental"


async def enqueue_candidates(
    scored: Sequence[ScoreBreakdown] | Iterable[ScoreBreakdown],
    downloader: Downloader,
    category: str,
    tags: Sequence[str],
    execute: bool,
) -> list[Decision]:
    decisions: list[Decision] = []
    tags_list = list(tags)

    for item in scored:
        if not item.accepted:
            continue

        candidate = item.candidate
        reason = _build_reason(item)
        new_state: dict[str, object] = {
            "candidate_id": item.candidate_id,
            "candidate_title": candidate.title,
            "download_url": candidate.download_url,
            "category": category,
            "tags": tags_list,
            "score": item.score,
            "reasons": list(item.reasons),
        }

        torrent_hash = None
        if execute:
            torrent_hash = await downloader.add_url(candidate.download_url, category, tags_list)
            if torrent_hash is not None:
                new_state["torrent_hash"] = torrent_hash

        decisions.append(
            Decision(
                action="qb.enqueue",
                target_id=item.candidate_id,
                execute=execute,
                reason=reason,
                new_state=new_state,
                rollback=ROLLBACK_INSTRUCTION,
            )
        )

    return decisions


def _build_reason(item: ScoreBreakdown) -> str:
    if item.reasons:
        return f"accepted for enqueue: score={item.score}; reasons={'; '.join(item.reasons)}"
    return f"accepted for enqueue: score={item.score}"
