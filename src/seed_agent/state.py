from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from seed_agent.models import LifecycleState

STATE_PRIORITY = {
    LifecycleState.DISCOVERED.value: 0,
    LifecycleState.SCORED.value: 1,
    LifecycleState.ENQUEUED.value: 2,
    LifecycleState.DOWNLOADING.value: 3,
    LifecycleState.SEEDING.value: 4,
    LifecycleState.COLD.value: 5,
    LifecycleState.PAUSED.value: 6,
    LifecycleState.DELETED.value: 7,
}


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def upsert_candidate(
        self,
        stable_id: str,
        title: str,
        site: str,
        state: LifecycleState,
        score: int | None,
        torrent_hash: str | None,
    ) -> None:
        current = self.get_candidate(stable_id)
        now = _utc_now()
        first_seen_at = current["first_seen_at"] if current is not None else now
        state_value, score_value, torrent_hash_value = _monotonic_values(
            current,
            state,
            score,
            torrent_hash,
        )

        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO candidates (
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    first_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stable_id) DO UPDATE SET
                    site = excluded.site,
                    title = excluded.title,
                    state = excluded.state,
                    score = excluded.score,
                    torrent_hash = excluded.torrent_hash,
                    updated_at = excluded.updated_at
                """,
                (
                    stable_id,
                    site,
                    title,
                    state_value,
                    score_value,
                    torrent_hash_value,
                    first_seen_at,
                    now,
                ),
            )

    def get_candidate(self, stable_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT stable_id, site, title, state, score, torrent_hash, first_seen_at, updated_at
                FROM candidates
                WHERE stable_id = ?
                """,
                (stable_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_by_state(self, state: LifecycleState) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stable_id, site, title, state, score, torrent_hash, first_seen_at, updated_at
                FROM candidates
                WHERE state = ?
                ORDER BY updated_at ASC, stable_id ASC
                """,
                (state.value,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_by_torrent_hash(self, torrent_hash: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stable_id, site, title, state, score, torrent_hash, first_seen_at, updated_at
                FROM candidates
                WHERE torrent_hash = ?
                ORDER BY updated_at ASC, stable_id ASC
                """,
                (torrent_hash,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_by_torrent_hash(self, torrent_hash: str, state: LifecycleState) -> int:
        rows = self.list_by_torrent_hash(torrent_hash)
        for row in rows:
            self.upsert_candidate(
                stable_id=str(row["stable_id"]),
                title=str(row["title"]),
                site=str(row["site"]),
                state=state,
                score=row["score"],
                torrent_hash=str(row["torrent_hash"]) if row["torrent_hash"] is not None else None,
            )
        return len(rows)

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                  stable_id TEXT PRIMARY KEY,
                  site TEXT NOT NULL,
                  title TEXT NOT NULL,
                  state TEXT NOT NULL,
                  score INTEGER,
                  torrent_hash TEXT,
                  first_seen_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_state ON candidates(state);
                CREATE INDEX IF NOT EXISTS idx_candidates_hash ON candidates(torrent_hash);
                """
            )


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _monotonic_values(
    current: dict[str, Any] | None,
    incoming_state: LifecycleState,
    incoming_score: int | None,
    incoming_torrent_hash: str | None,
) -> tuple[str, int | None, str | None]:
    if current is None:
        return incoming_state.value, incoming_score, incoming_torrent_hash

    current_state_value = str(current["state"])
    current_rank = STATE_PRIORITY.get(current_state_value, -1)
    incoming_rank = STATE_PRIORITY.get(incoming_state.value, -1)

    if current_rank > incoming_rank:
        return (
            current_state_value,
            current["score"],
            current["torrent_hash"],
        )

    return incoming_state.value, incoming_score, incoming_torrent_hash
