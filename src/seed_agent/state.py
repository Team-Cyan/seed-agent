from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
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
GIB = 1024**3
_UNSET = object()
SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30_000


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
        *,
        free_window_expires_at: str | None | object = _UNSET,
        size_bytes: int | None | object = _UNSET,
        seeders: int | None | object = _UNSET,
        leechers: int | None | object = _UNSET,
        discount: str | None | object = _UNSET,
        left_time_minutes: int | None | object = _UNSET,
        score_reasons: list[str] | None | object = _UNSET,
    ) -> None:
        current = self.get_candidate(stable_id)
        now = _utc_now()
        first_seen_at = current["first_seen_at"] if current is not None else now
        free_window_value = _preserved_value(
            current,
            "free_window_expires_at",
            free_window_expires_at,
        )
        size_value = _preserved_value(current, "size_bytes", size_bytes)
        seeders_value = _preserved_value(current, "seeders", seeders)
        leechers_value = _preserved_value(current, "leechers", leechers)
        discount_value = _preserved_value(current, "discount", discount)
        left_time_value = _preserved_value(current, "left_time_minutes", left_time_minutes)
        score_reasons_value = _preserved_value(current, "score_reasons", score_reasons)
        score_reasons_json = (
            _json_dumps(score_reasons_value) if score_reasons_value is not None else None
        )
        state_value, score_value, torrent_hash_value = _monotonic_values(
            current,
            state,
            score,
            torrent_hash,
        )

        with self._connect(row_factory=sqlite3.Row) as conn:
            conn.execute(
                """
                INSERT INTO candidates (
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stable_id) DO UPDATE SET
                    site = excluded.site,
                    title = excluded.title,
                    state = excluded.state,
                    score = excluded.score,
                    torrent_hash = excluded.torrent_hash,
                    free_window_expires_at = excluded.free_window_expires_at,
                    size_bytes = excluded.size_bytes,
                    seeders = excluded.seeders,
                    leechers = excluded.leechers,
                    discount = excluded.discount,
                    left_time_minutes = excluded.left_time_minutes,
                    score_reasons = excluded.score_reasons,
                    updated_at = excluded.updated_at
                """,
                (
                    stable_id,
                    site,
                    title,
                    state_value,
                    score_value,
                    torrent_hash_value,
                    free_window_value,
                    size_value,
                    seeders_value,
                    leechers_value,
                    discount_value,
                    left_time_value,
                    score_reasons_json,
                    first_seen_at,
                    now,
                ),
            )

    def get_candidate(self, stable_id: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE stable_id = ?
                """,
                (stable_id,),
            ).fetchone()
        return _candidate_row(row)

    def list_by_state(self, state: LifecycleState) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE state = ?
                ORDER BY updated_at ASC, stable_id ASC
                """,
                (state.value,),
            ).fetchall()
        return [_candidate_row(row) for row in rows]

    def list_by_torrent_hash(self, torrent_hash: str) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE torrent_hash = ?
                ORDER BY updated_at ASC, stable_id ASC
                """,
                (torrent_hash,),
            ).fetchall()
        return [_candidate_row(row) for row in rows]

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

    def mark_present_by_torrent_hash(self, torrent_hash: str, state: LifecycleState) -> int:
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            cursor = conn.execute(
                """
                UPDATE candidates
                SET state = ?, updated_at = ?
                WHERE torrent_hash = ?
                  AND state = ?
                """,
                (state.value, now, torrent_hash, LifecycleState.DELETED.value),
            )
            return int(cursor.rowcount)

    def prune_stale_candidates(
        self,
        *,
        retention_days: int,
        states: tuple[LifecycleState, ...] = (
            LifecycleState.DISCOVERED,
            LifecycleState.SCORED,
        ),
    ) -> int:
        if retention_days <= 0:
            return 0
        cutoff = (_utc_now_datetime() - timedelta(days=retention_days)).isoformat()
        state_values = tuple(state.value for state in states)
        placeholders = ", ".join("?" for _ in state_values)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                DELETE FROM candidates
                WHERE torrent_hash IS NULL
                  AND state IN ({placeholders})
                  AND updated_at < ?
                """,
                (*state_values, cutoff),
            )
            return int(cursor.rowcount)

    def mark_torrent_paused(self, torrent_hash: str, paused_at: datetime | None = None) -> None:
        self._upsert_torrent_runtime(
            torrent_hash,
            paused_at=(paused_at or _utc_now_datetime()).isoformat(),
            replace_paused_at=True,
        )

    def clear_torrent_runtime(self, torrent_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM torrent_runtime
                WHERE torrent_hash = ?
                """,
                (torrent_hash,),
            )

    def get_torrent_runtime(self, torrent_hash: str) -> dict[str, Any] | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                """
                SELECT
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                FROM torrent_runtime
                WHERE torrent_hash = ?
                """,
                (torrent_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def apply_torrent_runtime(self, torrents: list[ManagedTorrent]) -> list[ManagedTorrent]:
        torrent_hashes = [torrent.hash for torrent in torrents if torrent.hash]
        runtime_by_hash = self._torrent_runtime_by_hash(torrent_hashes)
        candidate_rows_by_hash = self._candidate_rows_by_torrent_hash(torrent_hashes)
        seen_at = _utc_now()
        updates: list[tuple[object, ...]] = []
        enriched: list[ManagedTorrent] = []
        for torrent in torrents:
            runtime = runtime_by_hash.get(torrent.hash)
            metadata = dict(torrent.metadata)
            candidate_rows = candidate_rows_by_hash.get(torrent.hash, [])
            candidate_free_expiry = next(
                (
                    row.get("free_window_expires_at")
                    for row in candidate_rows
                    if row.get("free_window_expires_at")
                ),
                None,
            )
            if candidate_free_expiry:
                metadata["free_window_expires_at"] = candidate_free_expiry
                metadata["free_window_source"] = "candidate_state"
            recent_upload_gb = _recent_upload_gb(runtime, torrent.uploaded_bytes)
            if recent_upload_gb is not None:
                metadata["recent_upload_gb"] = recent_upload_gb
                metadata["upload_delta_gb"] = recent_upload_gb
            no_upload_since_at = _no_upload_since_at(
                runtime,
                torrent_added_at=torrent.added_at,
                uploaded_bytes=torrent.uploaded_bytes,
                recent_upload_gb=recent_upload_gb,
            )
            if no_upload_since_at is not None:
                metadata["no_upload_since_at"] = no_upload_since_at
            paused_at = _parse_datetime(runtime.get("paused_at")) if runtime is not None else None
            if paused_at is None:
                paused_at = _parse_datetime(metadata.get("paused_at"))
            if _is_paused_state(torrent.state):
                if paused_at is None:
                    paused_at = _utc_now_datetime()
                metadata["paused_at"] = paused_at
            else:
                paused_at = None
            updates.append(
                (
                    torrent.hash,
                    paused_at.isoformat() if paused_at is not None else None,
                    torrent.uploaded_bytes,
                    torrent.downloaded_bytes,
                    int(metadata.get("upspeed_bps", 0) or 0),
                    int(metadata.get("dlspeed_bps", 0) or 0),
                    None,
                    None,
                    (
                        no_upload_since_at.isoformat()
                        if no_upload_since_at is not None
                        else None
                    ),
                    seen_at,
                    seen_at,
                )
            )
            enriched.append(torrent.model_copy(update={"metadata": metadata}))
        self._bulk_upsert_torrent_runtime(updates)
        return enriched

    def reconcile_missing_torrents(
        self,
        live_hashes: set[str],
        *,
        reason: str = "missing from qB live torrent list",
        min_age_minutes: int = 15,
    ) -> int:
        now = _utc_now()
        cutoff = (
            _utc_now_datetime() - timedelta(minutes=max(min_age_minutes, 0))
        ).isoformat()
        with self._connect() as conn:
            if live_hashes:
                placeholders = ", ".join("?" for _ in live_hashes)
                missing_rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.torrent_hash
                    FROM candidates c
                    WHERE c.torrent_hash IS NOT NULL
                      AND c.state IN (?, ?, ?, ?, ?)
                      AND c.updated_at < ?
                      AND c.torrent_hash NOT IN ({placeholders})
                    """,
                    (
                        LifecycleState.ENQUEUED.value,
                        LifecycleState.DOWNLOADING.value,
                        LifecycleState.SEEDING.value,
                        LifecycleState.COLD.value,
                        LifecycleState.PAUSED.value,
                        cutoff,
                        *tuple(live_hashes),
                    ),
                ).fetchall()
            else:
                missing_rows = conn.execute(
                    """
                    SELECT DISTINCT c.torrent_hash
                    FROM candidates c
                    WHERE c.torrent_hash IS NOT NULL
                      AND c.state IN (?, ?, ?, ?, ?)
                      AND c.updated_at < ?
                    """,
                    (
                        LifecycleState.ENQUEUED.value,
                        LifecycleState.DOWNLOADING.value,
                        LifecycleState.SEEDING.value,
                        LifecycleState.COLD.value,
                        LifecycleState.PAUSED.value,
                        cutoff,
                    ),
                ).fetchall()
            missing_hashes = [str(row[0]) for row in missing_rows if row[0]]
            if not missing_hashes:
                return 0
            placeholders = ", ".join("?" for _ in missing_hashes)
            conn.execute(
                f"""
                UPDATE candidates
                SET state = ?, updated_at = ?
                WHERE torrent_hash IN ({placeholders})
                  AND state IN (?, ?, ?, ?, ?)
                """,
                (
                    LifecycleState.DELETED.value,
                    now,
                    *missing_hashes,
                    LifecycleState.ENQUEUED.value,
                    LifecycleState.DOWNLOADING.value,
                    LifecycleState.SEEDING.value,
                    LifecycleState.COLD.value,
                    LifecycleState.PAUSED.value,
                ),
            )
            conn.executemany(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    missing_from_qb_at = excluded.missing_from_qb_at,
                    missing_from_qb_reason = excluded.missing_from_qb_reason,
                    updated_at = excluded.updated_at
                """,
                [(torrent_hash, now, reason, now) for torrent_hash in missing_hashes],
            )
            return len(missing_hashes)

    def _torrent_runtime_by_hash(self, torrent_hashes: list[str]) -> dict[str, dict[str, Any]]:
        if not torrent_hashes:
            return {}
        placeholders = ", ".join("?" for _ in torrent_hashes)
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                FROM torrent_runtime
                WHERE torrent_hash IN ({placeholders})
                """,
                tuple(torrent_hashes),
            ).fetchall()
        return {str(row["torrent_hash"]): dict(row) for row in rows}

    def _candidate_rows_by_torrent_hash(
        self, torrent_hashes: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not torrent_hashes:
            return {}
        placeholders = ", ".join("?" for _ in torrent_hashes)
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    stable_id,
                    site,
                    title,
                    state,
                    score,
                    torrent_hash,
                    free_window_expires_at,
                    size_bytes,
                    seeders,
                    leechers,
                    discount,
                    left_time_minutes,
                    score_reasons,
                    first_seen_at,
                    updated_at
                FROM candidates
                WHERE torrent_hash IN ({placeholders})
                ORDER BY updated_at ASC, stable_id ASC
                """,
                tuple(torrent_hashes),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["torrent_hash"]), []).append(_candidate_row(row))
        return grouped

    def _bulk_upsert_torrent_runtime(self, rows: list[tuple[object, ...]]) -> None:
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    paused_at = excluded.paused_at,
                    uploaded_bytes = excluded.uploaded_bytes,
                    downloaded_bytes = excluded.downloaded_bytes,
                    upspeed_bps = excluded.upspeed_bps,
                    dlspeed_bps = excluded.dlspeed_bps,
                    missing_from_qb_at = excluded.missing_from_qb_at,
                    missing_from_qb_reason = excluded.missing_from_qb_reason,
                    no_upload_since_at = excluded.no_upload_since_at,
                    seen_at = excluded.seen_at,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def _upsert_torrent_runtime(
        self,
        torrent_hash: str,
        *,
        paused_at: str | None | object = _UNSET,
        replace_paused_at: bool = False,
        uploaded_bytes: int | None = None,
        downloaded_bytes: int | None = None,
        upspeed_bps: int | None = None,
        dlspeed_bps: int | None = None,
        missing_from_qb_at: str | None | object = _UNSET,
        missing_from_qb_reason: str | None | object = _UNSET,
        no_upload_since_at: str | None = None,
        seen_at: str | None = None,
    ) -> None:
        current = self.get_torrent_runtime(torrent_hash) or {}
        now = _utc_now()
        paused_value = current.get("paused_at")
        if replace_paused_at or paused_at is not _UNSET:
            paused_value = paused_at

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO torrent_runtime (
                    torrent_hash,
                    paused_at,
                    uploaded_bytes,
                    downloaded_bytes,
                    upspeed_bps,
                    dlspeed_bps,
                    missing_from_qb_at,
                    missing_from_qb_reason,
                    no_upload_since_at,
                    seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    paused_at = excluded.paused_at,
                    uploaded_bytes = excluded.uploaded_bytes,
                    downloaded_bytes = excluded.downloaded_bytes,
                    upspeed_bps = excluded.upspeed_bps,
                    dlspeed_bps = excluded.dlspeed_bps,
                    missing_from_qb_at = excluded.missing_from_qb_at,
                    missing_from_qb_reason = excluded.missing_from_qb_reason,
                    no_upload_since_at = excluded.no_upload_since_at,
                    seen_at = excluded.seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    torrent_hash,
                    paused_value,
                    uploaded_bytes if uploaded_bytes is not None else current.get("uploaded_bytes"),
                    downloaded_bytes
                    if downloaded_bytes is not None
                    else current.get("downloaded_bytes"),
                    upspeed_bps if upspeed_bps is not None else current.get("upspeed_bps"),
                    dlspeed_bps if dlspeed_bps is not None else current.get("dlspeed_bps"),
                    missing_from_qb_at
                    if missing_from_qb_at is not _UNSET
                    else current.get("missing_from_qb_at"),
                    missing_from_qb_reason
                    if missing_from_qb_reason is not _UNSET
                    else current.get("missing_from_qb_reason"),
                    no_upload_since_at,
                    seen_at if seen_at is not None else current.get("seen_at"),
                    now,
                ),
            )

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

        with self._connect() as conn:
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
        with self._connect(row_factory=sqlite3.Row) as conn:
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
        with self._connect(row_factory=sqlite3.Row) as conn:
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

    def find_intent_id_by_alias(self, alias: str) -> str | None:
        with self._connect(row_factory=sqlite3.Row) as conn:
            row = conn.execute(
                "SELECT intent_id FROM intent_aliases WHERE alias = ?",
                (alias,),
            ).fetchone()
        return None if row is None else str(row["intent_id"])

    def upsert_intent_alias(self, alias: str, intent_id: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_aliases (alias, intent_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    intent_id = excluded.intent_id,
                    updated_at = excluded.updated_at
                """,
                (alias, intent_id, now, now),
            )

    def list_intent_aliases(self, intent_id: str) -> list[str]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT alias
                FROM intent_aliases
                WHERE intent_id = ?
                ORDER BY alias ASC
                """,
                (intent_id,),
            ).fetchall()
        return [str(row["alias"]) for row in rows]

    def upsert_intent_source_evidence(
        self,
        *,
        intent_id: str,
        source: str,
        raw_text: str,
        source_event_id: str | None,
        requested_at: str | None,
        metadata: dict[str, Any],
    ) -> None:
        source_config_id = _optional_text(metadata.get("source_config_id"))
        source_label = _optional_text(metadata.get("source_label"))
        evidence_id = _evidence_id(source, source_config_id, source_event_id, raw_text)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_source_evidence (
                    evidence_id,
                    intent_id,
                    source,
                    source_event_id,
                    source_config_id,
                    source_label,
                    requested_at,
                    raw_text,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    intent_id = excluded.intent_id,
                    source = excluded.source,
                    source_event_id = excluded.source_event_id,
                    source_config_id = excluded.source_config_id,
                    source_label = excluded.source_label,
                    requested_at = excluded.requested_at,
                    raw_text = excluded.raw_text,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    evidence_id,
                    intent_id,
                    source,
                    source_event_id,
                    source_config_id,
                    source_label,
                    requested_at,
                    raw_text,
                    _json_dumps(metadata),
                    now,
                    now,
                ),
            )

    def list_intent_source_evidence(self, intent_id: str) -> list[dict[str, Any]]:
        with self._connect(row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT
                    evidence_id,
                    intent_id,
                    source,
                    source_event_id,
                    source_config_id,
                    source_label,
                    requested_at,
                    raw_text,
                    metadata_json,
                    created_at,
                    updated_at
                FROM intent_source_evidence
                WHERE intent_id = ?
                ORDER BY
                    COALESCE(requested_at, created_at) ASC,
                    created_at ASC,
                    evidence_id ASC
                """,
                (intent_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                loaded = json.loads(str(item.pop("metadata_json")))
            except json.JSONDecodeError:
                loaded = {}
            item["metadata"] = loaded if isinstance(loaded, dict) else {}
            items.append(item)
        return items

    def merge_intents(self, canonical_intent_id: str, duplicate_intent_id: str) -> bool:
        if canonical_intent_id == duplicate_intent_id:
            return True
        canonical = self.get_intent(canonical_intent_id)
        duplicate = self.get_intent(duplicate_intent_id)
        if canonical is None or duplicate is None:
            return False
        canonical_payload = json.loads(str(canonical["normalized_json"]))
        duplicate_payload = json.loads(str(duplicate["normalized_json"]))
        canonical_metadata = dict(canonical_payload.get("metadata") or {})
        duplicate_metadata = dict(duplicate_payload.get("metadata") or {})
        canonical_payload["metadata"] = _merge_intent_metadata(
            canonical_metadata,
            duplicate_metadata,
        )
        merged_intent = ResourceIntent.model_validate(canonical_payload)
        selected_release_id = canonical["selected_release_id"] or duplicate["selected_release_id"]
        now = _utc_now()
        with self._connect(row_factory=sqlite3.Row) as conn:
            duplicate_rows = conn.execute(
                """
                SELECT release_id, site, title, score, confidence, accepted,
                       confirmation_required, release_json, created_at
                FROM release_candidates
                WHERE intent_id = ?
                """,
                (duplicate_intent_id,),
            ).fetchall()
            for row in duplicate_rows:
                data = dict(row)
                try:
                    release_payload = json.loads(str(data["release_json"]))
                except json.JSONDecodeError:
                    release_payload = {}
                if isinstance(release_payload, dict):
                    release_payload["intent_id"] = canonical_intent_id
                conn.execute(
                    """
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
                        canonical_intent_id,
                        data["release_id"],
                        data["site"],
                        data["title"],
                        data["score"],
                        data["confidence"],
                        data["accepted"],
                        data["confirmation_required"],
                        _json_dumps(release_payload),
                        data["created_at"],
                    ),
                )
            conn.execute(
                "UPDATE intent_aliases SET intent_id = ?, updated_at = ? WHERE intent_id = ?",
                (canonical_intent_id, now, duplicate_intent_id),
            )
            conn.execute(
                """
                UPDATE intent_source_evidence
                SET intent_id = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (canonical_intent_id, now, duplicate_intent_id),
            )
            conn.execute(
                "DELETE FROM release_candidates WHERE intent_id = ?",
                (duplicate_intent_id,),
            )
            conn.execute("DELETE FROM intents WHERE intent_id = ?", (duplicate_intent_id,))
        self.upsert_intent(merged_intent, selected_release_id=selected_release_id)
        return True

    def save_ranked_releases(self, releases: list[RankedRelease]) -> None:
        now = _utc_now()
        with self._connect() as conn:
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
        with self._connect(row_factory=sqlite3.Row) as conn:
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
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                  stable_id TEXT PRIMARY KEY,
                  site TEXT NOT NULL,
                  title TEXT NOT NULL,
                  state TEXT NOT NULL,
                  score INTEGER,
                  torrent_hash TEXT,
                  free_window_expires_at TEXT,
                  size_bytes INTEGER,
                  seeders INTEGER,
                  leechers INTEGER,
                  discount TEXT,
                  left_time_minutes INTEGER,
                  score_reasons TEXT,
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
                CREATE TABLE IF NOT EXISTS intent_aliases (
                  alias TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_aliases_intent
                  ON intent_aliases(intent_id);
                CREATE TABLE IF NOT EXISTS intent_source_evidence (
                  evidence_id TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL,
                  source TEXT NOT NULL,
                  source_event_id TEXT,
                  source_config_id TEXT,
                  source_label TEXT,
                  requested_at TEXT,
                  raw_text TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intent_source_evidence_intent
                  ON intent_source_evidence(intent_id);
                CREATE TABLE IF NOT EXISTS torrent_runtime (
                  torrent_hash TEXT PRIMARY KEY,
                  paused_at TEXT,
                  uploaded_bytes INTEGER,
                  downloaded_bytes INTEGER,
                  upspeed_bps INTEGER,
                  dlspeed_bps INTEGER,
                  missing_from_qb_at TEXT,
                  missing_from_qb_reason TEXT,
                  no_upload_since_at TEXT,
                  seen_at TEXT,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intents_state ON intents(state);
                CREATE INDEX IF NOT EXISTS idx_release_candidates_intent
                  ON release_candidates(intent_id);
                """
            )
            self._migrate_candidates(conn)
            self._migrate_release_candidates(conn)
            self._migrate_torrent_runtime(conn)

    def _connect(self, *, row_factory: Any | None = None) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=SQLITE_TIMEOUT_SECONDS)
        conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode=WAL")
        if row_factory is not None:
            conn.row_factory = row_factory
        return conn

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

    def _migrate_candidates(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()}
        additions = {
            "free_window_expires_at": "TEXT",
            "size_bytes": "INTEGER",
            "seeders": "INTEGER",
            "leechers": "INTEGER",
            "discount": "TEXT",
            "left_time_minutes": "INTEGER",
            "score_reasons": "TEXT",
        }
        for column, column_type in additions.items():
            if column in columns:
                continue
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {column} {column_type}")

    def _migrate_torrent_runtime(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(torrent_runtime)").fetchall()}
        additions = {
            "uploaded_bytes": "INTEGER",
            "downloaded_bytes": "INTEGER",
            "upspeed_bps": "INTEGER",
            "dlspeed_bps": "INTEGER",
            "missing_from_qb_at": "TEXT",
            "missing_from_qb_reason": "TEXT",
            "no_upload_since_at": "TEXT",
            "seen_at": "TEXT",
        }
        for column, column_type in additions.items():
            if column in columns:
                continue
            conn.execute(f"ALTER TABLE torrent_runtime ADD COLUMN {column} {column_type}")


def _utc_now() -> str:
    return _utc_now_datetime().isoformat()


def _utc_now_datetime() -> datetime:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence_id(
    source: str,
    source_config_id: str | None,
    source_event_id: str | None,
    raw_text: str,
) -> str:
    identity = source_event_id or raw_text
    return f"{source}:{source_config_id or ''}:{identity}"


def _merge_intent_metadata(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
) -> dict[str, Any]:
    merged = {**canonical, **duplicate}
    external_ids = {
        **_dict_value(canonical.get("external_ids")),
        **_dict_value(duplicate.get("external_ids")),
    }
    if external_ids:
        merged["external_ids"] = external_ids
    return merged


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _preserved_value(
    current: dict[str, Any] | None,
    key: str,
    value: Any,
) -> Any:
    if value is _UNSET:
        return current.get(key) if current is not None else None
    return value


def _candidate_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["score_reasons"] = _json_loads_list(data.get("score_reasons"))
    return data


def _json_loads_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return None
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, list):
        return None
    return [str(item) for item in loaded]


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_paused_state(state: str) -> bool:
    normalized = state.strip().lower()
    return normalized.startswith("paused") or normalized.startswith("stopped")


def _recent_upload_gb(runtime: dict[str, Any] | None, uploaded_bytes: int) -> float | None:
    if runtime is None:
        return None
    previous = runtime.get("uploaded_bytes")
    if not isinstance(previous, int):
        return None
    if uploaded_bytes < previous:
        return 0.0
    return (uploaded_bytes - previous) / GIB


def _no_upload_since_at(
    runtime: dict[str, Any] | None,
    *,
    torrent_added_at: datetime,
    uploaded_bytes: int,
    recent_upload_gb: float | None,
) -> datetime | None:
    if uploaded_bytes <= 0:
        existing = (
            _parse_datetime(runtime.get("no_upload_since_at"))
            if runtime is not None
            else None
        )
        if existing is not None:
            return min(existing, torrent_added_at)
        return torrent_added_at
    if runtime is None or recent_upload_gb is None:
        return None
    if recent_upload_gb > 0:
        return None
    existing = _parse_datetime(runtime.get("no_upload_since_at"))
    if existing is not None:
        return existing
    seen_at = _parse_datetime(runtime.get("seen_at"))
    return seen_at or _utc_now_datetime()


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
        incoming_torrent_hash if incoming_torrent_hash is not None else current["torrent_hash"],
    )
