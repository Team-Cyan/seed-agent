import json
from dataclasses import replace
from http.client import HTTPConnection

import yaml
from test_media_import import media as media
from test_media_runtime import media_config
from test_media_subtitles import PAYLOAD, FakeProvider, import_three
from test_web_settings import _running_server

from seed_agent.media_import.commands import submit
from seed_agent.media_import.subtitles.jobs import SubtitleJobs


def test_five_unique_choices_share_one_cap_across_languages_and_keep_existing(media):
    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config.profiles[0].languages = [["zh-Hans"], ["en"]]
    assert engine.config.profiles[0].max_subtitles == 5

    class Alternatives(FakeProvider):
        cycle = 0

        def search(self, mapping, source, languages):
            return [
                replace(
                    super().search(mapping, source, languages)[0],
                    id=f"{self.cycle}-{languages[0]}",
                    language=languages[0],
                )
            ]

        def download(self, candidate):
            self.downloads += 1
            return PAYLOAD.replace(b"fixture subtitle", candidate.id.encode())

    provider = Alternatives()
    jobs = SubtitleJobs(engine, provider)
    for n in range(7):
        provider.cycle = n
        jobs.run(refresh=True)
    assert provider.downloads == 15
    snapshot = engine.snapshot()
    for source in snapshot["sources"]:
        ids = {
            r["artifact_id"] for r in snapshot["artifact_sources"] if r["source_id"] == source["id"]
        }
        owned = [
            a
            for a in snapshot["artifacts"]
            if a["id"] in ids and a["kind"] == "subtitle" and a["status"] == "active"
        ]
        assert len(owned) == 5
        assert len({json.loads(a["receipt_json"])["digest"] for a in owned}) == 5
    engine.config.profiles[0].max_subtitles = 2
    jobs.run(refresh=True)
    assert provider.downloads == 15 and len(list(target.rglob("*.srt"))) == 15


def test_local_reuse_obeys_shared_cap_and_never_changes_source_sidecars(media):
    import_three(media)
    engine, source, _, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config.profiles[0].max_subtitles = 2
    originals = {}
    for n, lang in enumerate(["en", "zh-Hans", "zh-Hant"]):
        path = source / f"Episode1.{lang}.srt"
        data = PAYLOAD.replace(b"fixture subtitle", str(n).encode())
        path.write_bytes(data)
        originals[path] = data
    SubtitleJobs(engine).run()
    snapshot = engine.snapshot()
    sid = next(s["id"] for s in snapshot["sources"] if s["path"] == "Episode1.mkv")
    ids = {r["artifact_id"] for r in snapshot["artifact_sources"] if r["source_id"] == sid}
    assert (
        len([a for a in snapshot["artifacts"] if a["id"] in ids and a["kind"] == "subtitle"]) == 2
    )
    assert all(p.read_bytes() == data for p, data in originals.items())


def test_covered_job_does_not_inherit_one_second_partial_provider_retry(media):
    import_three(media)
    engine, *_ = media
    engine.config.subtitle_policy = "execute"

    class PartialPool(FakeProvider):
        managed = True
        next_retry = 1
        statuses = {"unavailable": {"status": "rate_limited"}}

    SubtitleJobs(engine, PartialPool()).run()
    assert all(
        j["status"] == "satisfied"
        and j["next_attempt"] - engine.clock() >= engine.config.subtitle_refresh_seconds - 1
        for j in engine.snapshot()["subtitles"]
    )


def test_ready_commands_link_video_before_enrichment_and_without_cursor_edit(tmp_path, monkeypatch):
    from seed_agent.media_import import worker

    config, source, target = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["deployment"] = {"source_id": "priority-fixture"}
    raw["media_import"]["import_policy"] = "execute"
    config.write_text(yaml.safe_dump(raw))
    for n in [1, 2]:
        (source / f"Film{n}.2025.mkv").write_bytes(b"video fixture")
    original = worker.build_engine

    def fixture_engine(*a, **kw):
        engine, root = original(*a, **kw)
        engine.probe = lambda p: {"duration": 100, "fps": 24, "streams": []}
        return engine, root

    monkeypatch.setattr(worker, "build_engine", fixture_engine)
    engine, _ = fixture_engine(config)
    engine.scan("movie", force=True)
    engine.scan("movie", force=True)
    rows = engine.snapshot()["sources"]
    for n, row in enumerate(rows):
        submit(
            config,
            "review",
            {
                "source_id": row["id"],
                "fingerprint": row["fingerprint"],
                "mapping": {
                    "media_type": "movie",
                    "tmdb_id": n + 1,
                    "original_title": f"Film{n + 1}",
                    "year": 2025,
                },
                "ready": True,
            },
            execute=True,
        )
    with engine.store._connect() as conn:
        before = conn.execute("SELECT * FROM media_work_cursor").fetchall()

    def forbidden(*a, **kw):
        raise AssertionError("enrichment must wait while reviewed video commands are queued")

    monkeypatch.setattr(worker, "run_engine", forbidden)
    worker.serve(config, max_cycles=1, poll_seconds=0)
    assert len(list(target.rglob("*.mkv"))) == 1
    assert worker.process_one(config)["status"] == "complete"
    assert len(list(target.rglob("*.mkv"))) == 2
    with engine.store._connect() as conn:
        assert conn.execute("SELECT * FROM media_work_cursor").fetchall() == before
        assert conn.execute("SELECT count(*) FROM media_subtitle_jobs").fetchone() == (0,)
    for video in target.rglob("*.mkv"):
        assert video.stat().st_nlink == 2


def test_media_cap_can_be_saved_through_existing_revision_checked_ui_api(tmp_path):
    config, _, _ = media_config(tmp_path)
    with _running_server(config) as host:
        conn = HTTPConnection(host)
        conn.request("GET", "/api/media")
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["profiles"][0]["max_subtitles"] == 5
        conn.request("GET", "/api/config")
        response = conn.getresponse()
        current = json.loads(response.read())
        data = current["sections"]["media_import"]
        data["profiles"][0]["max_subtitles"] = 4
        body = {"section": "media_import", "data": data, "revision": current["revision"]}
        conn.request(
            "POST", "/api/config/sections", json.dumps(body), {"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        assert response.status == 200, response.read()
        response.read()
        conn.request("GET", "/api/media")
        response = conn.getresponse()
        assert json.loads(response.read())["profiles"][0]["max_subtitles"] == 4
        body["data"]["profiles"][0]["max_subtitles"] = 2
        conn.request(
            "POST", "/api/config/sections", json.dumps(body), {"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        assert response.status >= 400
        response.read()
        conn.close()
    assert yaml.safe_load(config.read_text())["media_import"]["profiles"][0]["max_subtitles"] == 4


def test_local_sidecars_prioritize_requested_chinese_before_choice_cap(media):
    import_three(media)
    engine, source, _, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config.profiles[0].max_subtitles = 1
    for lang in ["en", "zh-Hans"]:
        (source / f"Episode1.{lang}.srt").write_bytes(
            PAYLOAD.replace(b"fixture subtitle", lang.encode())
        )
    SubtitleJobs(engine).run()
    snapshot = engine.snapshot()
    sid = next(s["id"] for s in snapshot["sources"] if s["path"] == "Episode1.mkv")
    ids = {r["artifact_id"] for r in snapshot["artifact_sources"] if r["source_id"] == sid}
    owned = [a for a in snapshot["artifacts"] if a["id"] in ids and a["kind"] == "subtitle"]
    assert len(owned) == 1 and ".zh-Hans.srt" in owned[0]["path"]


def test_worker_error_logs_safe_sqlite_code_even_when_status_write_fails(monkeypatch):
    import sqlite3
    from types import SimpleNamespace

    import pytest

    from seed_agent.media_import import role_health

    records = []
    monkeypatch.setattr(
        role_health,
        "logging",
        SimpleNamespace(
            getLogger=lambda name: SimpleNamespace(
                error=lambda fmt, payload: records.append(fmt % payload)
            )
        ),
    )
    lifecycle = object.__new__(role_health.MediaWorkerLifecycle)
    error = sqlite3.OperationalError("credential-like private exception text")
    error.sqlite_errorcode = 14
    error.sqlite_errorname = "SQLITE_CANTOPEN"

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("state write unavailable")

    monkeypatch.setattr(lifecycle, "_finish", unavailable)
    with pytest.raises(sqlite3.OperationalError):
        lifecycle.failed(error)
    observation = json.loads(records[0].split(" ", 1)[1])
    assert observation == {
        "error_type": "OperationalError",
        "sqlite_errorcode": 14,
        "sqlite_errorname": "SQLITE_CANTOPEN",
    }
    assert "credential-like" not in records[0]


def test_unrequested_local_languages_and_kinds_cannot_fill_chinese_choice_cap(media):
    import_three(media)
    engine, source, _, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config.profiles[0].max_subtitles = 5
    originals = {}
    for suffix in [*(f"en.{n}" for n in range(5)), "zh-Hans.forced"]:
        path = source / f"Episode1.{suffix}.srt"
        originals[path] = PAYLOAD.replace(b"fixture subtitle", suffix.encode())
        path.write_bytes(originals[path])
    provider = FakeProvider()
    SubtitleJobs(engine, provider).run()
    assert provider.downloads == 3
    snapshot = engine.snapshot()
    sid = next(s["id"] for s in snapshot["sources"] if s["path"] == "Episode1.mkv")
    ids = {r["artifact_id"] for r in snapshot["artifact_sources"] if r["source_id"] == sid}
    owned = [a for a in snapshot["artifacts"] if a["id"] in ids and a["kind"] == "subtitle"]
    assert len(owned) == 1 and ".zh-Hans.srt" in owned[0]["path"]
    assert all(path.read_bytes() == content for path, content in originals.items())
