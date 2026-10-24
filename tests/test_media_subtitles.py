import io
import json
import zipfile
from pathlib import Path

import pytest
from test_media_import import import_three as base_import_three
from test_media_import import media as media

from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.provider import Candidate, ProviderError
from seed_agent.media_import.subtitles.validation import validate


def import_three(media):
    base_import_three(media)
    media[0].config.provider_interval_seconds = 0


PAYLOAD = b"1\n00:00:01,000 --> 00:00:03,000\nfixture subtitle\n"


class FakeProvider:
    name = "fake"
    calls = 0
    downloads = 0
    error = None
    late = None

    def search(self, mapping, source, languages):
        self.calls += 1
        if self.error:
            raise self.error
        return [
            Candidate(
                id="one",
                language="zh-Hans",
                tmdb_id=mapping["tmdb_id"],
                season=mapping["season"],
                episodes=tuple(mapping["episodes"]),
                release=source["original_release"].rsplit(".", 1)[0],
                fps=24,
            )
        ]

    def download(self, candidate):
        self.downloads += 1
        if self.late:
            self.late()
        return PAYLOAD


def test_subtitle_preview_no_payload_or_library_writes(media):
    import_three(media)
    engine, _, target, _ = media
    provider = FakeProvider()
    assert SubtitleJobs(engine, provider).run()
    assert provider.calls == 3 and provider.downloads == 0
    assert not list(target.rglob("*.srt"))


def test_subtitle_success_restart_and_alternatives_existing(media):
    import_three(media)
    engine, source, target, _ = media
    (source / "Episode1.zh-Hans.srt").write_bytes(PAYLOAD)
    engine.config.subtitle_policy = "execute"
    provider = FakeProvider()
    jobs = SubtitleJobs(engine, provider)
    result = jobs.run()
    assert all(r["status"] == "satisfied" for r in result)
    assert provider.downloads == 3  # existing coverage still discovers alternatives
    assert len(list(target.rglob("*.srt"))) == 3
    jobs.run(refresh=True)
    assert provider.downloads == 3  # provider identity dedup


def test_subtitle_missing_provider_visible(media):
    import_three(media)
    engine, _, _, _ = media
    assert all(r["status"] == "credentials_required" for r in SubtitleJobs(engine).run())


@pytest.mark.parametrize(
    "error,status",
    [
        (ProviderError("quota", 4000), "quota"),
        (ProviderError("credentials_required"), "credentials_required"),
    ],
)
def test_provider_errors_persist_retry(media, error, status):
    import_three(media)
    engine, _, _, _ = media
    provider = FakeProvider()
    provider.error = error
    assert all(r["status"] == status for r in SubtitleJobs(engine, provider).run())
    assert all(j["next_attempt"] > engine.clock() for j in engine.snapshot()["subtitles"])


def test_late_response_fenced_by_source_disappearance(media):
    import_three(media)
    engine, source, target, _ = media
    engine.config.subtitle_policy = "execute"
    provider = FakeProvider()
    provider.late = lambda: [(p.unlink()) for p in source.glob("*.mkv")]
    result = SubtitleJobs(engine, provider).run()
    assert all(r["status"] == "terminal_failure" for r in result)
    assert not list(target.rglob("*.srt"))


def test_subtitle_modified_prevents_cleanup(media):
    import_three(media)
    engine, source, target, _ = media
    engine.config.subtitle_policy = "execute"
    SubtitleJobs(engine, FakeProvider()).run()
    video = engine.snapshot()["sources"][0]
    subtitle = next(
        a
        for a in engine.snapshot()["artifacts"]
        if a["kind"] == "subtitle" and Path(a["path"]).parent == Path(video["target"]).parent
    )
    Path(subtitle["path"]).write_bytes(PAYLOAD + b"user edit")
    (source / video["path"]).unlink()
    engine.config.reconcile_policy = "execute"
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert Path(subtitle["path"]).exists()
    assert any(a["status"] == "conflict" for a in engine.snapshot()["cleanup"])


@pytest.mark.parametrize("path", ["../evil.srt", "/evil.srt", "a\\evil.srt"])
def test_malicious_archive_rejected(path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as z:
        z.writestr(path, PAYLOAD)
    with pytest.raises(ValueError, match="unsafe"):
        validate(payload.getvalue(), duration=1000)


def test_html_and_impossible_timing_rejected():
    with pytest.raises(ValueError):
        validate(b"<html>error</html>", duration=10)
    with pytest.raises(ValueError):
        validate(PAYLOAD.replace(b"00:00:03", b"02:00:03"), duration=10)


def test_local_subtitle_and_artwork_are_owned_and_reconciled(media):
    import_three(media)
    engine, source, target, _ = media
    (source / "Episode1.zh-Hans.srt").write_bytes(PAYLOAD)
    (source / "Episode1.jpg").write_bytes(b"\xff\xd8\xfffixture")
    engine.config.subtitle_policy = "execute"
    SubtitleJobs(engine).run()
    owned = engine.snapshot()["artifacts"]
    assert any(a["kind"] == "artwork" for a in owned)
    assert any(a["kind"] == "subtitle" for a in owned)
    source_subtitle = (source / "Episode1.zh-Hans.srt").read_bytes()
    (source / "Episode1.mkv").unlink()
    engine.config.reconcile_policy = "execute"
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert not list(target.rglob("*.srt"))
    assert not list(target.rglob("*.jpg"))
    assert (source / "Episode1.zh-Hans.srt").read_bytes() == source_subtitle


def test_actual_opensubtitles_adapter_script_country_roundtrip_and_hash(tmp_path, monkeypatch):
    from seed_agent.media_import.filesystem import fingerprint
    from seed_agent.media_import.subtitles.provider import OpenSubtitles, movie_hash

    provider = OpenSubtitles({"api_key": "fixture", "username": "fixture", "password": "fixture"})
    path = tmp_path / "video.mkv"
    path.write_bytes(b"\x01" * 200000)
    source = {
        "source_root": str(tmp_path),
        "absolute_path": str(path),
        "fingerprint": fingerprint(path),
    }
    expected = movie_hash(source)
    assert expected and len(expected) == 16
    observed = []

    def search(**kwargs):
        observed.append(kwargs)
        for sid, lang in enumerate(["zh-cn", "zh-tw"], 1):
            yield {
                "id": str(sid),
                "attributes": {
                    "language": lang,
                    "hearing_impaired": 0,
                    "foreign_parts_only": 0,
                    "machine_translated": 0,
                    "fps": 24,
                    "feature_details": {
                        "feature_id": 1,
                        "movie_name": "Example",
                        "year": 2024,
                        "feature_type": "Movie",
                        "tmdb_id": 12,
                        "imdb_id": 123,
                    },
                    "files": [{"file_id": 1, "file_name": "Example.srt"}],
                    "release": "Example",
                    "download_count": 100,
                    "ratings": 8.5,
                    "from_trusted": True,
                },
            }

    monkeypatch.setattr(provider.adapter, "_search", search)
    mapping = {"media_type": "movie", "tmdb_id": 12, "imdb_id": "tt0000123", "episodes": []}
    result = provider.search(mapping, source, ["zh-Hans", "zh-Hant"])
    assert {c.language for c in result} == {"zh-Hans", "zh-Hant"}
    assert all(call["languages"] == "zh-cn,zh-tw" for call in observed)
    assert any(call.get("moviehash") == expected for call in observed)
    assert all(c.downloads == 100 for c in result)
    assert all(c.rating == 8.5 and c.trusted for c in result)


def test_late_response_cannot_overwrite_repaired_jobs(media):
    import_three(media)
    engine, _, _, _ = media
    engine.config.subtitle_policy = "execute"
    provider = FakeProvider()
    triggered = []

    def repair():
        if triggered:
            return
        triggered.append(True)
        row = engine.snapshot()["sources"][0]
        mapping = json.loads(row["mapping_json"])
        mapping["original_title"] = "Correct"
        engine.review(row["id"], mapping, fingerprint=row["fingerprint"], ready=True)
        engine.scan("tv", force=True)

    provider.late = repair
    jobs = SubtitleJobs(engine, provider)
    jobs.run()
    changed = next(s for s in engine.snapshot()["sources"] if "Correct" in (s["target"] or ""))
    job = next(j for j in engine.snapshot()["subtitles"] if j["source_id"] == changed["id"])
    assert job["status"] != "terminal_failure"
    provider.late = None
    jobs.run(refresh=True)
    job = next(j for j in engine.snapshot()["subtitles"] if j["source_id"] == changed["id"])
    assert job["status"] == "satisfied"


def test_refresh_cannot_steal_live_claim(media):
    import_three(media)
    engine, _, _, _ = media
    engine.config.subtitle_policy = "execute"
    provider = FakeProvider()
    nested = []

    def refresh():
        if not nested:
            nested.append(SubtitleJobs(engine, provider).run(refresh=True))

    provider.late = refresh
    SubtitleJobs(engine, provider).run()
    assert nested == [[]]


def test_profile_filter_does_not_publish_other_profile_sidecars(media):
    import_three(media)
    engine, source, target, _ = media
    second_source = source.with_name("second-source")
    second_target = target.with_name("second-library")
    second_source.mkdir()
    second_target.mkdir()
    for p in [second_source, second_target]:
        (p / ".media-volume").write_text("fixture")
    profile = engine.config.profiles[0].model_copy(
        update={
            "name": "movie",
            "source_root": str(second_source),
            "target_root": str(second_target),
        }
    )
    engine.config.profiles.append(profile)
    (second_source / "Episode1.mkv").write_bytes(b"fixture second")
    (second_source / "Episode1.zh-Hans.srt").write_bytes(PAYLOAD)
    engine.scan("movie", force=True)
    engine.scan("movie", force=True)
    engine.config.subtitle_policy = "execute"
    SubtitleJobs(engine, FakeProvider()).run(profile="tv")
    assert not list(second_target.rglob("*.srt"))
    assert all(
        j["source_id"]
        not in {s["id"] for s in engine.snapshot()["sources"] if s["profile"] == "movie"}
        for j in engine.snapshot()["subtitles"]
    )


def test_real_adapter_paces_every_search_request_and_retry_after(monkeypatch):
    import requests

    from seed_agent.media_import.subtitles.provider import OpenSubtitles

    events = []
    provider = OpenSubtitles({"api_key": "fixture"})
    provider.request_pacer = lambda: events.append("pace")

    def response(self, method, url, **kwargs):
        events.append("http")
        result = requests.Response()
        result.status_code = 200
        result._content = b'{"data":[],"total_pages":1}'
        result._content_consumed = True
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    mapping = {"media_type": "movie", "tmdb_id": 12, "imdb_id": "tt0000123", "episodes": []}
    provider.search(mapping, {}, ["zh-Hans"])
    assert len(events) >= 4 and len(events) % 2 == 0
    assert events == ["pace", "http"] * (len(events) // 2)

    def quota(self, method, url, **kwargs):
        result = requests.Response()
        result.status_code = 429
        result.headers["Retry-After"] = "123"
        result._content = b"{}"
        result._content_consumed = True
        return result

    monkeypatch.setattr(requests.Session, "request", quota)
    with pytest.raises(ProviderError) as exc:
        provider.search(mapping, {}, ["zh-Hans"])
    assert exc.value.status == "rate_limited" and exc.value.retry_after == 123


def test_partial_payload_recovery_isolated_from_other_imports(media, monkeypatch):
    import_three(media)
    engine, source, target, _ = media
    engine.config.subtitle_policy = "execute"
    import os

    original = os.fsync

    class Crash(BaseException):
        pass

    def crash(fd):
        raise Crash()

    monkeypatch.setattr(os, "fsync", crash)
    with pytest.raises(Crash):
        SubtitleJobs(engine, FakeProvider()).run()
    monkeypatch.setattr(os, "fsync", original)
    publication = next(p for p in engine.snapshot()["publications"] if p["status"] == "pending")
    Path(publication["temporary"]).write_bytes(b"partial interrupted bytes")
    (source / "Episode4.mkv").write_bytes(b"new unrelated media")
    assert engine.scan("tv", force=True)["status"] == "complete"
    assert engine.scan("tv", force=True)["status"] == "complete"
    assert len(list(target.rglob("*.mkv"))) == 4
    state = engine.snapshot()
    assert any(p["status"] == "conflict" for p in state["publications"])
    assert any(e["event"] == "publication_recovery_conflict" for e in state["events"])


def test_no_result_mismatch_and_multiple_compatible_choices(media):
    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"

    class Alternatives(FakeProvider):
        def search(self, mapping, source, languages):
            base = super().search(mapping, source, languages)[0]
            from dataclasses import replace

            return [
                replace(base, id="bad", tmdb_id=999, rating=100),
                replace(base, id="first"),
                replace(base, id="second"),
            ]

        def download(self, candidate):
            return PAYLOAD.replace(b"fixture subtitle", candidate.id.encode())

    jobs = SubtitleJobs(engine, Alternatives())
    assert all(j["status"] == "satisfied" for j in jobs.run())
    assert len(list(target.rglob("*.srt"))) == 3
    jobs.run(refresh=True)
    assert len(list(target.rglob("*.srt"))) == 6
    assert all("bad" not in j["payload_json"] for j in engine.snapshot()["subtitles"])

    class Empty(FakeProvider):
        def search(self, *args):
            return []

    assert all(j["status"] == "satisfied" for j in SubtitleJobs(engine, Empty()).run(refresh=True))


def test_operator_subtitle_choice_persists_and_publishes_only_after_confirmation(media):
    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"

    class Probable(FakeProvider):
        def search(self, *args):
            result = super().search(*args)
            result[0].release = "different release needs operator preview"
            return result

    jobs = SubtitleJobs(engine, Probable())
    jobs.run()
    assert not list(target.rglob("*.srt"))
    job = engine.snapshot()["subtitles"][0]
    jobs.select(job["id"], "one")
    jobs.run()
    assert len(list(target.rglob("*.srt"))) == 1


def test_restore_fences_inflight_network_response(media):
    from seed_agent.media_import.maintenance import backup_media_database, restore_media_database

    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"
    provider = FakeProvider()
    restored = []

    def restore():
        if restored:
            return
        restored.append(True)
        backup = engine.store.path.with_name("inflight-backup.db")
        assert backup_media_database(engine.store.path, backup)["valid"]
        assert (
            restore_media_database(engine.store.path, backup, execute=True)["status"] == "restored"
        )

    provider.late = restore
    SubtitleJobs(engine, provider).run()
    assert not list(target.rglob("*.srt"))
    assert all(j["claim_token"] is None for j in engine.snapshot()["subtitles"])
    provider.late = None
    from seed_agent.media_import.engine import Engine

    restarted = Engine(
        engine.store, engine.config, metadata=engine.metadata, media_probe=engine.probe
    )
    SubtitleJobs(restarted, provider).run()
    assert len(list(target.rglob("*.srt"))) == 3


def test_api_key_only_download_never_requires_login(monkeypatch):
    import requests
    import respx

    from seed_agent.media_import.subtitles.provider import OpenSubtitles

    provider = OpenSubtitles({"api_key": "fixture-key"})

    def response(self, method, url, **kwargs):
        assert not url.endswith("/login")
        assert url.endswith("/download")
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps(
            {"link": "https://dl.opensubtitles.com/fixture.srt", "remaining": 0}
        ).encode()
        result._content_consumed = True
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    with respx.mock:
        respx.get("https://dl.opensubtitles.com/fixture.srt").respond(200, content=PAYLOAD)
        assert provider.download(Candidate(id="one", language="zh-Hans", file_id=1)) == PAYLOAD


@pytest.mark.parametrize(
    "location,accepted",
    [
        ("https://api.opensubtitles.com/api/v1/subtitles?languages=zh-cn", True),
        ("https://attacker.example/subtitles", False),
    ],
)
def test_api_redirect_is_bounded_and_never_forwards_credentials_to_other_host(
    monkeypatch, location, accepted
):
    import requests

    from seed_agent.media_import.subtitles.provider import OpenSubtitles

    provider = OpenSubtitles({"api_key": "fixture-key"})
    events = []
    calls = []
    provider.request_pacer = lambda: events.append("pace")

    def response(self, method, url, **kwargs):
        calls.append(url)
        result = requests.Response()
        result._content_consumed = True
        result._content = b'{"data":[],"total_pages":1}'
        result.status_code = 301 if len(calls) == 1 else 200
        if len(calls) == 1:
            result.headers["Location"] = location
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    provider.initialize()
    try:
        if accepted:
            assert provider.adapter.api_get("subtitles", {"page": 1})["data"] == []
            assert len(calls) == 2 and len(events) == 2
        else:
            with pytest.raises(ProviderError):
                provider.adapter.api_get("subtitles", {"page": 1})
            assert len(calls) == 1
    finally:
        provider.adapter.terminate()


def test_anonymous_quota_is_not_misreported_as_missing_credentials(monkeypatch):
    import requests

    from seed_agent.media_import.subtitles.provider import OpenSubtitles

    provider = OpenSubtitles({"api_key": "fixture-key"})

    def response(*args, **kwargs):
        result = requests.Response()
        result.status_code = 403
        result._content = b'{"message":"Anonymous download limit reached"}'
        result._content_consumed = True
        result.headers["Retry-After"] = "77"
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    with pytest.raises(ProviderError) as exc:
        provider.download(Candidate(id="one", language="zh-Hans", file_id=1))
    assert exc.value.status == "daily_quota" and exc.value.retry_after == 77


def test_revoked_policy_during_provider_response_prevents_actual_publication(media, tmp_path):
    import yaml

    from seed_agent.config import atomic_write_text
    from seed_agent.config_views import MediaConfigGuard, load_view

    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"
    config = tmp_path / "guard.yaml"
    raw = {"media_import": engine.config.model_dump(mode="json")}
    raw["media_import"]["provider_interval_seconds"] = 1
    atomic_write_text(config, yaml.safe_dump(raw))
    engine.config_guard = MediaConfigGuard(load_view(config, "media"))
    provider = FakeProvider()

    def revoke():
        raw["media_import"]["subtitle_policy"] = "preview"
        atomic_write_text(config, yaml.safe_dump(raw))

    provider.late = revoke
    SubtitleJobs(engine, provider).run()
    assert provider.downloads > 0
    assert not list(target.rglob("*.srt"))
    assert engine.config_guard.error == "ValueError"


def test_daily_quota_stops_whole_library_and_survives_retry_horizon(media):
    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"

    class BudgetProvider(FakeProvider):
        download_gate = None
        download_observer = None

        def download(self, candidate):
            self.download_gate()
            self.downloads += 1
            self.download_observer({"remaining": 0, "reset_time": "01:00:00"})
            return PAYLOAD

    provider = BudgetProvider()
    jobs = SubtitleJobs(engine, provider)
    result = jobs.run()
    assert [r["status"] for r in result].count("daily_quota") == 2
    assert provider.calls == provider.downloads == 1
    assert len(list(target.rglob("*.srt"))) == 1
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_subtitle_jobs SET first_attempt=0,next_attempt=0")
    restarted = SubtitleJobs(engine, provider)
    result = restarted.run()
    assert all(r["status"] == "daily_quota" for r in result)
    assert provider.calls == provider.downloads == 1
    assert all(j["status"] != "terminal_failure" for j in engine.snapshot()["subtitles"])


def test_duplicate_payload_consumes_only_one_link_per_file_per_cycle(media):
    from dataclasses import replace

    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"

    class DuplicateAlternatives(FakeProvider):
        alternatives = False

        def search(self, *args):
            candidate = super().search(*args)[0]
            return (
                [replace(candidate, id="duplicate-a"), replace(candidate, id="duplicate-b")]
                if self.alternatives
                else [candidate]
            )

    provider = DuplicateAlternatives()
    jobs = SubtitleJobs(engine, provider)
    jobs.run()
    assert provider.downloads == 3
    provider.alternatives = True
    jobs.run(refresh=True)
    assert provider.downloads == 6
    assert len(list(target.rglob("*.srt"))) == 3


@pytest.mark.parametrize("coverage_kind", ["sidecar", "embedded", "owned"])
def test_real_coverage_priority_survives_quota_status_and_restart(media, coverage_kind):
    import_three(media)
    engine, source, target, _ = media
    engine.config.subtitle_policy = "execute"
    if coverage_kind == "owned":
        first = SubtitleJobs(engine, FakeProvider()).run(limit=1)[0]
        with engine.store._connect() as conn:
            covered = conn.execute(
                "SELECT s.path FROM media_source_files s JOIN media_subtitle_jobs j "
                "ON j.source_id=s.id WHERE j.id=?",
                (first["id"],),
            ).fetchone()[0]
    else:
        covered = engine.snapshot()["sources"][0]["path"]
        if coverage_kind == "sidecar":
            (source / covered).with_suffix(".zh-Hans.srt").write_bytes(PAYLOAD)
        else:
            with engine.store._connect() as conn:
                row = conn.execute(
                    "SELECT probe_json FROM media_source_files WHERE path=?", (covered,)
                ).fetchone()
                probe = json.loads(row[0])
                probe["streams"] = [{"codec_type": "subtitle", "tags": {"language": "zh-cn"}}]
                conn.execute(
                    "UPDATE media_source_files SET probe_json=? WHERE path=?",
                    (json.dumps(probe), covered),
                )
    SubtitleJobs(engine, FakeProvider()).run(limit=0)
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_subtitle_jobs SET next_attempt=0,status='daily_quota'")

    class Recording(FakeProvider):
        paths = []

        def search(self, mapping, source, languages):
            self.paths.append(source["path"])
            return super().search(mapping, source, languages)

    provider = Recording()
    provider.paths = []
    SubtitleJobs(engine, provider).run(limit=1)
    assert provider.paths[0] != covered


@pytest.mark.parametrize("change", ["delete", "corrupt"])
def test_priority_refresh_detects_removed_or_invalid_sidecar(media, change):
    import_three(media)
    engine, source, _, _ = media
    engine.config.subtitle_policy = "execute"
    selected = engine.snapshot()["sources"][0]
    for row in engine.snapshot()["sources"]:
        (source / row["path"]).with_suffix(".zh-Hans.srt").write_bytes(PAYLOAD)
    SubtitleJobs(engine, FakeProvider()).run(limit=0)
    # Classify without consuming allowance under preview.
    engine.config.subtitle_policy = "preview"
    SubtitleJobs(engine, FakeProvider()).run()
    changed = (source / selected["path"]).with_suffix(".zh-Hans.srt")
    if change == "delete":
        changed.unlink()
    else:
        changed.write_bytes(b"<html>not subtitles</html>")

    class Recording(FakeProvider):
        paths = []

        def search(self, mapping, source, languages):
            self.paths.append(source["path"])
            return super().search(mapping, source, languages)

    provider = Recording()
    provider.paths = []
    SubtitleJobs(engine, provider).run(refresh=True, limit=1)
    assert provider.paths == [selected["path"]]


def test_duplicate_candidates_do_not_fill_independent_choice_cap(media):
    from dataclasses import replace

    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config.profiles[0].max_subtitles = 2

    class Choices(FakeProvider):
        mode = "first"

        def search(self, *args):
            candidate = super().search(*args)[0]
            return [replace(candidate, id=self.mode)]

        def download(self, candidate):
            self.downloads += 1
            return (
                PAYLOAD.replace(b"fixture subtitle", b"new choice")
                if self.mode == "new"
                else PAYLOAD
            )

    provider = Choices()
    jobs = SubtitleJobs(engine, provider)
    jobs.run()
    provider.mode = "duplicate"
    jobs.run(refresh=True)
    assert all(
        len(json.loads(j["payload_json"])["downloaded"]) == 1
        for j in engine.snapshot()["subtitles"]
    )
    provider.mode = "new"
    jobs.run(refresh=True)
    assert len(list(target.rglob("*.srt"))) == 6
    assert all(
        len(json.loads(j["payload_json"])["downloaded"]) == 2
        for j in engine.snapshot()["subtitles"]
    )
