from test_media_import import media as media
from test_media_subtitles import import_three

from seed_agent.media_import.source_progress import source_progress


def test_source_progress_partitions_latest_configured_generations(media):
    import_three(media)
    engine = media[0]
    with engine.store._connect() as conn:
        source_ids = [r[0] for r in conn.execute("SELECT id FROM media_source_files ORDER BY path")]
        conn.execute("UPDATE media_source_files SET missing_count=1 WHERE id=?", (source_ids[0],))
        conn.execute(
            "UPDATE media_import_jobs SET status='blocked_destination' WHERE source_id=?",
            (source_ids[1],),
        )
        original = conn.execute(
            "SELECT * FROM media_source_files WHERE id=?", (source_ids[2],)
        ).fetchone()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(media_source_files)")]
        data = dict(zip(cols, original, strict=True))
        data.update(
            id="new-generation",
            generation=data["generation"] + 1,
            status="stabilizing",
            readiness=None,
        )
        conn.execute(
            "INSERT INTO media_source_files ("
            + ",".join(cols)
            + ") VALUES ("
            + ",".join("?" for _ in cols)
            + ")",
            tuple(data[c] for c in cols),
        )
        data.update(id="unconfigured", profile="disabled", path="other.mkv")
        conn.execute(
            "INSERT INTO media_source_files ("
            + ",".join(cols)
            + ") VALUES ("
            + ",".join("?" for _ in cols)
            + ")",
            tuple(data[c] for c in cols),
        )
    assert len(engine.snapshot(limit=1)["sources"]) == 1
    progress = source_progress(engine)
    assert (
        progress["records"],
        progress["historical_generations"],
        progress["total"],
        progress["present"],
    ) == (4, 1, 3, 2)
    assert (
        progress["missing"],
        progress["blocked"],
        progress["pending"],
        progress["imported"],
    ) == (1, 1, 1, 0)
    assert progress["by_status"] == {
        "missing_pending": 1,
        "blocked_destination": 1,
        "stabilizing": 1,
    }
    assert progress["by_source_status"] == {"imported": 2, "stabilizing": 1}
    assert (
        sum(
            progress[k]
            for k in ("missing", "blocked", "pending", "imported", "review", "conflict", "unknown")
        )
        == progress["total"]
    )


def test_source_progress_review_conflict_imported_unknown(media):
    import_three(media)
    engine = media[0]
    with engine.store._connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM media_source_files ORDER BY path")]
        conn.execute(
            "UPDATE media_source_files SET readiness='completion_unverified' WHERE id=?", (ids[0],)
        )
        conn.execute(
            "UPDATE media_import_jobs SET status='target_missing' WHERE source_id=?", (ids[1],)
        )
    progress = source_progress(engine)
    assert (progress["review"], progress["conflict"], progress["imported"]) == (1, 1, 1)
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_source_files SET status='future_status',readiness=NULL WHERE id=?",
            (ids[2],),
        )
        conn.execute("DELETE FROM media_import_jobs WHERE source_id=?", (ids[2],))
    assert source_progress(engine)["unknown"] == 1
