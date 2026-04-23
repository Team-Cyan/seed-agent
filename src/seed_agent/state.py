from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from seed_agent.models import (
    IntentState,
    LifecycleState,
    ManagedTorrent,
    RankedRelease,
    ResourceIntent,
)

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

    def mark_torrent_paused(self, torrent_hash: str, paused_at: datetime | None = None) -> None:
        now = _utc_now()
        paused_value = (paused_at or _utc_now_datetime()).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    paused_at,
                    updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    paused_at = excluded.paused_at,
                    updated_at = excluded.updated_at
                """,
                (torrent_hash, paused_value, now),
            )

    def clear_torrent_runtime(self, torrent_hash: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                DELETE FROM torrent_runtime
                WHERE torrent_hash = ?
                """,
                (torrent_hash,),
            )

    def get_torrent_runtime(self, torrent_hash: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT torrent_hash, paused_at, updated_at
                FROM torrent_runtime
                WHERE torrent_hash = ?
                """,
                (torrent_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def apply_torrent_runtime(self, torrents: list[ManagedTorrent]) -> list[ManagedTorrent]:
        enriched: list[ManagedTorrent] = []
        for torrent in torrents:
            runtime = self.get_torrent_runtime(torrent.hash)
            if runtime is None:
                enriched.append(torrent)
                continue
            if not _is_paused_state(torrent.state):
                enriched.append(torrent)
                continue
            metadata = dict(torrent.metadata)
            paused_at = _parse_datetime(runtime.get("paused_at"))
            if paused_at is not None:
                metadata["paused_at"] = paused_at
            enriched.append(torrent.model_copy(update={"metadata": metadata}))
        return enriched

    def upsert_intent(
        self,
        intent: ResourceIntent,
        selected_release_id: str | None = None,
    ) -> None:
        current = self.get_intent(intent.intent_id)
        now = _utc_now()
        created_at = current["created_at"] if current is not None else now
        selected_value = selected_release_id
        if selected_value is None and current is not None:
            selected_value = current["selected_release_id"]

        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO intents (
                    intent_id,
                    source,
                    raw_text,
                    title,
                    kind,
                    state,
                    normalized_json,
                    selected_release_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(intent_id) DO UPDATE SET
                    source = excluded.source,
                    raw_text = excluded.raw_text,
                    title = excluded.title,
                    kind = excluded.kind,
                    state = excluded.state,
                    normalized_json = excluded.normalized_json,
                    selected_release_id = excluded.selected_release_id,
                    updated_at = excluded.updated_at
                """,
                (
                    intent.intent_id,
                    intent.source.value,
                    intent.raw_text,
                    intent.title,
                    intent.kind.value,
                    intent.state.value,
                    _json_dumps(intent.model_dump(mode="json")),
                    selected_value,
                    created_at,
                    now,
                ),
            )

    def get_intent(self, intent_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    intent_id,
                    source,
                    raw_text,
                    title,
                    kind,
                    state,
                    normalized_json,
                    selected_release_id,
                    created_at,
                    updated_at
                FROM intents
                WHERE intent_id = ?
                """,
                (intent_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_intents_by_state(self, state: IntentState) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    intent_id,
                    source,
                    raw_text,
                    title,
                    kind,
                    state,
                    normalized_json,
                    selected_release_id,
                    created_at,
                    updated_at
                FROM intents
                WHERE state = ?
                ORDER BY updated_at ASC, intent_id ASC
                """,
                (state.value,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_intent_state(
        self,
        intent_id: str,
        state: IntentState,
        selected_release_id: str | None = None,
    ) -> bool:
        current = self.get_intent(intent_id)
        if current is None:
            return False
        normalized = json.loads(str(current["normalized_json"]))
        normalized["state"] = state.value
        intent = ResourceIntent.model_validate(normalized)
        self.upsert_intent(intent, selected_release_id=selected_release_id)
        return True

    def save_ranked_releases(self, releases: list[RankedRelease]) -> None:
        now = _utc_now()
        with sqlite3.connect(self.path) as conn:
            for ranked in releases:
                conn.execute(
                    """
                    INSERT INTO release_candidates (
                        release_id,
                        intent_id,
                        site,
                        title,
                        score,
                        confidence,
                        accepted,
                        confirmation_required,
                        release_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(intent_id, release_id) DO UPDATE SET
                        site = excluded.site,
                        title = excluded.title,
                        score = excluded.score,
                        confidence = excluded.confidence,
                        accepted = excluded.accepted,
                        confirmation_required = excluded.confirmation_required,
                        release_json = excluded.release_json
                    """,
                    (
                        ranked.release.release_id,
                        ranked.intent_id,
                        ranked.release.site,
                        ranked.release.title,
                        ranked.score,
                        ranked.confidence,
                        int(ranked.accepted),
                        int(ranked.confirmation_required),
                        _json_dumps(ranked.model_dump(mode="json")),
                        now,
                    ),
                )

    def list_release_candidates(self, intent_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    release_id,
                    intent_id,
                    site,
                    title,
                    score,
                    confidence,
                    accepted,
                    confirmation_required,
                    release_json,
                    created_at
                FROM release_candidates
                WHERE intent_id = ?
                ORDER BY score DESC, confidence DESC, release_id ASC
                """,
                (intent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
                CREATE TABLE IF NOT EXISTS intents (
                  intent_id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  raw_text TEXT NOT NULL,
                  title TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  state TEXT NOT NULL,
                  normalized_json TEXT NOT NULL,
                  selected_release_id TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS release_candidates (
                  intent_id TEXT NOT NULL,
                  release_id TEXT NOT NULL,
                  site TEXT NOT NULL,
                  title TEXT NOT NULL,
                  score INTEGER,
                  confidence REAL,
                  accepted INTEGER NOT NULL,
                  confirmation_required INTEGER NOT NULL,
                  release_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (intent_id, release_id)
                );
                CREATE TABLE IF NOT EXISTS torrent_runtime (
                  torrent_hash TEXT PRIMARY KEY,
                  paused_at TEXT,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intents_state ON intents(state);
                CREATE INDEX IF NOT EXISTS idx_release_candidates_intent
                  ON release_candidates(intent_id);
                """
            )
            self._migrate_release_candidates(conn)

    def _migrate_release_candidates(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'release_candidates'
            """
        ).fetchone()
        sql = row[0] if row is not None else ""
        if "PRIMARY KEY (intent_id, release_id)" in sql:
            return
        conn.executescript(
            """
            ALTER TABLE release_candidates RENAME TO release_candidates_old;
            CREATE TABLE release_candidates (
              intent_id TEXT NOT NULL,
              release_id TEXT NOT NULL,
              site TEXT NOT NULL,
              title TEXT NOT NULL,
              score INTEGER,
              confidence REAL,
              accepted INTEGER NOT NULL,
              confirmation_required INTEGER NOT NULL,
              release_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (intent_id, release_id)
            );
            INSERT INTO release_candidates (
              intent_id,
              release_id,
              site,
              title,
              score,
              confidence,
              accepted,
              confirmation_required,
              release_json,
              created_at
            )
            SELECT
              intent_id,
              release_id,
              site,
              title,
              score,
              confidence,
              accepted,
              confirmation_required,
              release_json,
              created_at
            FROM release_candidates_old;
            DROP TABLE release_candidates_old;
            CREATE INDEX IF NOT EXISTS idx_release_candidates_intent
              ON release_candidates(intent_id);
            """
        )


def _utc_now() -> str:
    return _utc_now_datetime().isoformat()


def _utc_now_datetime() -> datetime:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_paused_state(state: str) -> bool:
    normalized = state.strip().lower()
    return normalized.startswith("paused") or normalized.startswith("stopped")


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

    return (
        incoming_state.value,
        incoming_score if incoming_score is not None else current["score"],
        incoming_torrent_hash
        if incoming_torrent_hash is not None
        else current["torrent_hash"],
    )
