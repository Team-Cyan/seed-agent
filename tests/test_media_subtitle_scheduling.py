"""Bounded idle work and persistent fairness, using actual fixture sidecar reads."""

from contextlib import contextmanager

from test_media_import import media as media
from test_media_subtitles import PAYLOAD, FakeProvider, import_three

from seed_agent.media_import.metadata import Mapping
from seed_agent.media_import.subtitles.jobs import SubtitleJobs


def test_idle_coverage_bound_and_94_new_jobs_progress_after_restart(media, monkeypatch):
    import_three(media)
    engine, source, _, _ = media
    SubtitleJobs(engine, FakeProvider()).run()
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_subtitle_jobs SET next_attempt=0")

    def identify(path, profile):
        return Mapping(
            media_type="tv",
            tmdb_id=12,
            original_title="Example",
            year=2024,
            season=int(path.stem.removeprefix("Episode")),
            episodes=[1],
        ), []

    engine.config.work_batch_size = 50
    engine.metadata.identify = identify
    for index in range(4, 98):
        (source / f"Episode{index}.mkv").write_bytes(b"fixture" + bytes([index]))
        (source / f"Episode{index}.zh-Hans.srt").write_bytes(PAYLOAD)
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert sum(s["import_status"] == "imported" for s in engine.snapshot()["sources"]) == 97
    SubtitleJobs(engine).run(limit=0)  # seed only
    statements, reads, searched = [], [], []
    connect = engine.store._connect

    @contextmanager
    def traced():
        with connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(engine.store, "_connect", traced)
    read_bytes = type(source).read_bytes

    def counted(path):
        value = read_bytes(path)
        if path.suffix == ".srt":
            reads.append(len(value))
        return value

    monkeypatch.setattr(type(source), "read_bytes", counted)

    class Recording(FakeProvider):
        def search(self, mapping, source, languages):
            searched.append(source["path"])
            return super().search(mapping, source, languages)

    # Reconstruct jobs/provider on every quantum: no in-memory cursor or cache.
    for _ in range(94):
        before_reads, before_sql = len(reads), len(statements)
        result = SubtitleJobs(engine, Recording()).run(limit=1)
        assert len(result) == 1
        assert len(reads) - before_reads <= 5  # four lookahead + claimed job recheck
        writes = statements[before_sql:]
        assert (
            sum(s.startswith("UPDATE media_subtitle_jobs SET payload_json=") for s in writes) <= 4
        )
        assert sum(s.startswith("BEGIN") for s in writes) <= 12
        assert not any(s.startswith("INSERT OR IGNORE INTO media_subtitle_jobs") for s in writes)
    assert len(set(searched)) == 94
    assert not set(searched) & {"Episode1.mkv", "Episode2.mkv", "Episode3.mkv"}
    assert sum(reads) <= 94 * 5 * len(PAYLOAD)
    with engine.store._connect() as conn:
        attempted = conn.execute(
            "SELECT COUNT(*) FROM media_subtitle_jobs WHERE attempts>0"
        ).fetchone()[0]
    assert attempted == 97


def test_removed_requirements_cannot_fill_bounded_window(media):
    import_three(media)
    engine = media[0]
    engine.config.profiles[0].languages = [["en"], ["zh-Hans"]]
    SubtitleJobs(engine).run(limit=0)
    engine.config.profiles[0].languages = [["zh-Hans"]]
    provider = FakeProvider()
    for _ in range(3):
        assert len(SubtitleJobs(engine, provider).run(limit=1)) == 1
    assert provider.calls == 3
