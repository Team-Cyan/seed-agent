import json

from test_media_import import media as media
from test_media_subtitles import FakeProvider, import_three

from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.progress import subtitle_progress


def test_all_sources_independent_of_snapshot_page_and_embedded_coverage(media):
    import_three(media)
    engine = media[0]
    engine.clock = lambda: 1000.0
    assert len(engine.snapshot(limit=1)["sources"]) == 1
    before = subtitle_progress(engine)
    assert (
        before["eligible_sources"],
        before["expected_requirements"],
        before["jobs_initialized"],
    ) == (3, 3, 0)
    assert before["state"] == "processing"
    SubtitleJobs(engine).run(limit=0)
    with engine.store._connect() as conn:
        jid = conn.execute("SELECT id FROM media_subtitle_jobs LIMIT 1").fetchone()[0]
        conn.execute(
            "UPDATE media_subtitle_jobs SET status='satisfied',payload_json=?,"
            "next_attempt=2000 WHERE id=?",
            (json.dumps({"coverage_satisfied": True, "search_state": "complete"}), jid),
        )
        conn.execute(
            "UPDATE media_subtitle_jobs SET status='daily_quota',next_attempt=3000 WHERE id != ?",
            (jid,),
        )
    progress = subtitle_progress(engine)
    assert progress["jobs_initialized"] == 3
    assert progress["sources_with_any_coverage"] == progress["discovery_completed_jobs"] == 1
    assert progress["sources_without_managed_external"] == 3
    assert progress["managed_external_artifacts"] == 0
    assert (progress["due"], progress["waiting"], progress["next_attempt"], progress["state"]) == (
        0,
        3,
        2000,
        "waiting",
    )
    engine.clock = lambda: 2001.0
    progress = subtitle_progress(engine)
    assert (progress["due"], progress["waiting"], progress["oldest_due"]) == (1, 2, 2000)
    assert subtitle_progress(engine, profile="absent")["state"] == "no_sources"


def test_stale_and_inactive_jobs_excluded_and_publication_receipts_counted(media):
    import_three(media)
    engine = media[0]
    engine.config.subtitle_policy = "execute"
    SubtitleJobs(engine).run(limit=0)
    with engine.store._connect() as conn:
        sid, generation = conn.execute(
            "SELECT id,generation FROM media_source_files LIMIT 1"
        ).fetchone()
        conn.execute(
            "INSERT INTO media_subtitle_jobs VALUES(?,?,?,?,?,0,0,0,'{}',NULL,NULL,NULL,NULL)",
            (
                "stale",
                sid,
                generation - 1,
                json.dumps(["zh-Hans", "zh-Hant"], separators=(",", ":")),
                "terminal_failure",
            ),
        )
        conn.execute(
            "INSERT INTO media_subtitle_jobs VALUES(?,?,?,?,?,0,0,0,'{}',NULL,NULL,NULL,NULL)",
            ("inactive", sid, generation, '["en"]', "terminal_failure"),
        )
    before = subtitle_progress(engine)
    assert before["jobs_initialized"] == 3 and before["review"] == 0
    SubtitleJobs(engine, FakeProvider()).run(source_id=sid, limit=1)
    after = subtitle_progress(engine)
    assert after["managed_external_artifacts"] == 1
    assert after["sources_with_managed_external"] == 1
    assert after["sources_without_managed_external"] == 2
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_artifacts SET status='retired' WHERE kind='subtitle'")
    assert subtitle_progress(engine)["managed_external_artifacts"] == 0


def test_multiple_requirements_need_every_current_job_for_full_coverage(media):
    import_three(media)
    engine = media[0]
    engine.config.profiles[0].languages = [["zh-Hans"], ["en"]]
    SubtitleJobs(engine).run(limit=0)
    with engine.store._connect() as conn:
        source_id = conn.execute("SELECT id FROM media_source_files LIMIT 1").fetchone()[0]
        jobs = conn.execute(
            "SELECT id FROM media_subtitle_jobs WHERE source_id=? ORDER BY id", (source_id,)
        ).fetchall()
        assert len(jobs) == 2
        conn.execute(
            "UPDATE media_subtitle_jobs SET payload_json=? WHERE id=?",
            (json.dumps({"coverage_satisfied": True}), jobs[0][0]),
        )
    partial = subtitle_progress(engine)
    assert partial["sources_with_any_coverage"] == 1
    assert partial["fully_covered_sources"] == 0
    with engine.store._connect() as conn:
        conn.execute("DELETE FROM media_subtitle_jobs WHERE id=?", jobs[1])
    assert subtitle_progress(engine)["fully_covered_sources"] == 0
    # Recreate the absent requirement through normal job initialization.
    SubtitleJobs(engine).run(limit=0)
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_subtitle_jobs SET payload_json=? WHERE source_id=?",
            (json.dumps({"coverage_satisfied": True}), source_id),
        )
    complete = subtitle_progress(engine)
    assert complete["sources_with_any_coverage"] == 1
    assert complete["fully_covered_sources"] == 1
