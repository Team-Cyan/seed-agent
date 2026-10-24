import base64
import json
from types import SimpleNamespace

import httpx
import pytest
import respx
from test_media_import import import_three
from test_media_import import media as media

from seed_agent.media_import.artwork import PosterJobs, TmdbPosters

PAYLOAD = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jV1sAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def image_probe(monkeypatch):
    # The host has no ffprobe; filesystem publication/receipts remain real. Image
    # inspection is the subprocess seam, exercised independently by API fixtures.
    monkeypatch.setattr(
        "seed_agent.media_import.artwork.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            stdout=b'{"streams":[{"codec_name":"png","width":1,"height":1}]}'
        ),
    )


class Posters:
    calls = 0
    late = None

    def fetch(self, mapping, locale):
        self.calls += 1
        if self.late:
            self.late()
        return (
            PAYLOAD,
            ".png",
            {
                "provider": "tmdb",
                "media_type": "tv",
                "tmdb_id": mapping["tmdb_id"],
                "poster_path": "/fixture.png",
            },
        )


def test_shared_show_poster_once_all_episode_refs_and_last_source_cleanup(media):
    import_three(media)
    engine, source, target, _ = media
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    assert jobs.run()[0]["status"] == "published"
    assert provider.calls == 1
    posters = list(target.rglob("poster.png"))
    assert len(posters) == 1
    with engine.store._connect() as conn:
        aid = conn.execute("SELECT id FROM media_artifacts WHERE kind='poster'").fetchone()[0]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources WHERE artifact_id=?", (aid,)
            ).fetchone()[0]
            == 3
        )
    engine.scan("tv", force=True)  # ordinary no-op imports must retain shared poster refs
    assert jobs.run()[0]["status"] == "owned" and provider.calls == 1
    engine.config.reconcile_policy = "execute"
    (source / "Episode1.mkv").unlink()
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert posters[0].exists()
    for path in source.glob("*.mkv"):
        path.unlink()
    engine.config.profiles[0].max_missing_fraction = 1
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert not posters[0].exists()


def test_manual_or_modified_poster_is_preserved(media):
    import_three(media)
    engine, _, target, _ = media
    parent = next(target.iterdir())
    manual = parent / "poster.png"
    manual.write_bytes(b"manual")
    provider = Posters()
    assert PosterJobs(engine, provider).run()[0]["status"] == "existing_unowned"
    assert manual.read_bytes() == b"manual" and provider.calls == 0


def test_source_replacement_during_poster_fetch_prevents_publication(media):
    import_three(media)
    engine, source, target, _ = media
    provider = Posters()
    provider.late = lambda: [p.write_bytes(b"replaced") for p in source.glob("*.mkv")]
    assert PosterJobs(engine, provider).run()[0]["status"] == "conflict"
    assert not list(target.rglob("poster.png"))


@respx.mock
def test_official_poster_fetch_limits_origins_and_credentials(monkeypatch):
    monkeypatch.setattr(
        "seed_agent.media_import.artwork.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            stdout=b'{"streams":[{"codec_name":"png","width":500,"height":750}]}'
        ),
    )
    detail = respx.get("https://api.themoviedb.org/3/movie/1").mock(
        return_value=httpx.Response(200, json={"poster_path": "/fixture.png"})
    )
    image = respx.get("https://image.tmdb.org/t/p/w500/fixture.png").mock(
        return_value=httpx.Response(200, content=PAYLOAD)
    )
    payload, extension, evidence = TmdbPosters("fixture-secret").fetch(
        {"media_type": "movie", "tmdb_id": 1}, "zh-CN"
    )
    assert payload == PAYLOAD and extension == ".png" and evidence["tmdb_id"] == 1
    assert detail.calls[0].request.headers["Authorization"] == "Bearer fixture-secret"
    assert "Authorization" not in image.calls[0].request.headers


@respx.mock
def test_poster_metadata_cannot_redirect_to_arbitrary_url():
    respx.get("https://api.themoviedb.org/3/movie/1").mock(
        return_value=httpx.Response(200, json={"poster_path": "https://other.invalid/poster.png"})
    )
    with pytest.raises(ValueError, match="unsafe"):
        TmdbPosters("fixture").fetch({"media_type": "movie", "tmdb_id": 1}, "zh-CN")


def test_poster_pending_publication_recovery_and_shared_reattachment(media, monkeypatch):
    import_three(media)
    engine, _, target, _ = media
    now = [engine.clock()]
    engine.clock = lambda: now[0]
    original = engine._link

    def fail(*args, **kwargs):
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(engine, "_link", fail)
    with pytest.raises(RuntimeError):
        PosterJobs(engine, Posters()).run()
    assert not list(target.rglob("poster.png"))
    monkeypatch.setattr(engine, "_link", original)
    with engine.lease():
        engine.recover(engine.profile("tv"))
    now[0] += 601
    provider = Posters()
    assert PosterJobs(engine, provider).run()[0]["status"] == "owned"
    assert provider.calls == 0
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources r "
                "JOIN media_artifacts a ON a.id=r.artifact_id WHERE a.kind='poster'"
            ).fetchone()[0]
            == 3
        )


def test_review_during_poster_fetch_revokes_publication(media):
    import_three(media)
    engine, _, target, _ = media
    source = engine.snapshot()["sources"][0]
    provider = Posters()
    provider.late = lambda: engine.review(
        source["id"],
        json.loads(source["mapping_json"]),
        fingerprint=source["fingerprint"],
        ready=True,
    )
    assert PosterJobs(engine, provider).run()[0]["status"] == "conflict"
    assert not list(target.rglob("poster.png"))


@pytest.mark.parametrize(
    "root_name,status", [("source", "blocked_source"), ("target", "blocked_destination")]
)
def test_root_fault_is_persisted_before_network_and_recovers(media, root_name, status):
    import_three(media)
    engine, source, target, _ = media
    now = [engine.clock()]
    engine.clock = lambda: now[0]
    marker = (source if root_name == "source" else target) / ".media-volume"
    marker.write_text("offline")
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    assert jobs.run()[0]["status"] == status
    assert jobs.status()[0]["status"] == status
    assert provider.calls == 0
    assert all(s["missing_count"] == 0 for s in engine.snapshot()["sources"])
    marker.write_text("fixture")
    # A new jobs instance uses persisted delay, then retries automatically.
    restarted = PosterJobs(engine, provider)
    assert restarted.run()[0]["status"] == status
    now[0] += 61
    assert restarted.run()[0]["status"] == "published"
    assert provider.calls == 1
    assert next(target.rglob("poster.png")).read_bytes() == PAYLOAD


@pytest.mark.parametrize("change", ["source", "video"])
def test_changed_source_or_video_is_conflict_and_spends_no_provider_call(media, change):
    import_three(media)
    engine, source, _, _ = media
    item = engine.snapshot()["sources"][0]
    if change == "source":
        (source / item["path"]).unlink()
    else:
        from pathlib import Path

        video = Path(item["target"])
        video.unlink()
        video.write_bytes(b"manual replacement")
    provider = Posters()
    assert PosterJobs(engine, provider).run()[0]["status"] == "conflict"
    assert provider.calls == 0


@pytest.mark.parametrize("change", ["config", "route", "epoch", "claim"])
def test_late_poster_response_cannot_cross_fences(media, change):
    import_three(media)
    engine, _, target, _ = media
    provider = Posters()
    jobs = PosterJobs(engine, provider)

    def late():
        if change == "config":
            engine.config.profiles[0].locale = "en-US"
        elif change == "route":
            engine.config.profiles[0].target_root = str(target / "new-route")
        else:
            with engine.store._connect() as conn:
                if change == "epoch":
                    conn.execute("UPDATE media_control SET epoch='restored-timeline'")
                else:
                    conn.execute(
                        "UPDATE media_provider_state SET status="
                        "json_set(status,'$.claim_token','new-claim') "
                        "WHERE provider LIKE 'artwork:tmdb:job:%'"
                    )

    provider.late = late
    result = jobs.run()[0]
    assert result["status"] == ("conflict" if change in {"config", "route"} else "superseded")
    assert not list(target.rglob("poster.png"))


def test_provider_runs_outside_transaction_and_live_claim_cannot_be_stolen(media):
    import_three(media)
    engine, _, _, _ = media
    provider = Posters()
    jobs = PosterJobs(engine, provider)

    def during_fetch():
        # A second SQLite writer can commit while the network adapter is active.
        with engine.store._connect() as conn:
            conn.execute(
                "INSERT INTO media_events(event,created,payload_json) VALUES('probe',0,'{}')"
            )
        nested = jobs.run(refresh=True)
        assert nested[0]["status"] == "running"
        assert provider.calls == 1

    provider.late = during_fetch
    assert jobs.run()[0]["status"] == "published"
    assert jobs.status(profile="tv", limit=1)[0]["attempts"] == 1
    assert jobs.status(profile="other") == []
    assert jobs.status(limit=0) == []


def test_interrupted_publication_recovers_in_next_batch_without_second_fetch(media, monkeypatch):
    import_three(media)
    engine, _, target, _ = media
    now = [engine.clock()]
    engine.clock = lambda: now[0]
    original = engine._link
    provider = Posters()
    jobs = PosterJobs(engine, provider)

    def interrupt(*args, **kwargs):
        raise RuntimeError("process terminated after temporary payload")

    monkeypatch.setattr(engine, "_link", interrupt)
    with pytest.raises(RuntimeError):
        jobs.run()
    monkeypatch.setattr(engine, "_link", original)
    assert jobs.status()[0]["status"] == "running"
    now[0] += 601
    assert jobs.run()[0]["status"] == "owned"
    assert provider.calls == 1
    assert len(list(target.rglob("poster.png"))) == 1
    assert not list(target.rglob(".media-poster-*"))
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources r JOIN media_artifacts a "
                "ON a.id=r.artifact_id WHERE a.kind='poster'"
            ).fetchone()[0]
            == 3
        )


def test_modified_owned_poster_preserved_without_refetch(media):
    import_three(media)
    engine, source, target, _ = media
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    assert jobs.run()[0]["status"] == "published"
    poster = next(target.rglob("poster.png"))
    poster.write_bytes(b"manual edit")
    assert jobs.run()[0]["status"] == "conflict"
    assert provider.calls == 1 and poster.read_bytes() == b"manual edit"
    engine.config.reconcile_policy = "execute"
    engine.profile("tv").max_missing_fraction = 1
    for path in source.glob("*.mkv"):
        path.unlink()
    for _ in range(2):
        engine.scan("tv", force=True)
    assert poster.read_bytes() == b"manual edit"


def test_mixed_poster_routes_use_content_identity_and_historical_root(tmp_path):
    from pathlib import Path

    from test_media_source_routing import mixed_engine

    engine, source, destinations, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    calls = []

    class MixedPosters:
        def fetch(self, mapping, locale):
            calls.append((mapping["media_type"], mapping["tmdb_id"]))
            return (
                PAYLOAD,
                ".png",
                {
                    "provider": "tmdb",
                    "media_type": mapping["media_type"],
                    "tmdb_id": mapping["tmdb_id"],
                    "poster_path": "/fixture.png",
                },
            )

    # A changed default does not move existing output authority to the new root.
    destinations.movies.root = str(tmp_path / "unavailable-new-movies")
    jobs = PosterJobs(engine, MixedPosters())
    assert len(jobs.run(limit=1)) == 1
    for _ in range(3):
        assert len(jobs.run(limit=1)) == 1
    assert set(calls) == {("movie", 1), ("tv", 2), ("movie", 3), ("tv", 4)}
    assert len(list(Path(source.root).rglob("poster.png"))) == 4
    assert jobs.run(limit=0) == []
    engine.config.max_inventory_files = 1
    assert jobs.run()[0]["status"] == "coverage_pending"
    assert len(calls) == 4


@respx.mock
def test_tmdb_429_pauses_other_posters_and_persists_retry_after(tmp_path):
    from pathlib import Path

    from test_media_source_routing import mixed_engine

    engine, source, _, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    now = [engine.clock()]
    engine.clock = lambda: now[0]
    route = respx.route().mock(return_value=httpx.Response(429, headers={"Retry-After": "7200"}))
    jobs = PosterJobs(engine, TmdbPosters("fixture"))
    result = jobs.run()
    assert len(result) == 4 and all(r["status"] == "rate_limited" for r in result)
    assert route.call_count == 1
    assert all(r["next_attempt"] == now[0] + 7200 for r in jobs.status())
    assert all(r["status"] == "rate_limited" for r in jobs.run(refresh=True))
    assert route.call_count == 1


def test_shared_show_across_independent_sources_keeps_last_support(media, tmp_path):
    import_three(media)
    engine, source, target, _ = media
    other = tmp_path / "other-source"
    other.mkdir()
    (other / ".media-volume").write_text("fixture")
    (other / "Episode4.mkv").write_bytes(b"another independent source")
    engine.config.profiles.append(
        engine.profile("tv").model_copy(
            update={
                "name": "other",
                "source_root": str(other),
            }
        )
    )
    for _ in range(2):
        engine.scan("other", force=True)
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    assert jobs.run()[0]["status"] == "published"
    poster = next(target.rglob("poster.png"))
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources r JOIN media_artifacts a "
                "ON a.id=r.artifact_id WHERE a.kind='poster'"
            ).fetchone()[0]
            == 4
        )
    engine.config.reconcile_policy = "execute"
    engine.profile("tv").max_missing_fraction = 1
    for path in source.glob("*.mkv"):
        path.unlink()
    for _ in range(2):
        engine.scan("tv", force=True)
    assert poster.exists()
    assert jobs.run(profile="other")[0]["status"] == "owned"
    (other / "Episode4.mkv").unlink()
    for _ in range(2):
        engine.scan("other", force=True)
    assert not poster.exists()
    assert provider.calls == 1


def test_new_epoch_reclaims_restored_running_job_without_waiting(media):
    from seed_agent.media_import.engine import Engine

    import_three(media)
    engine, _, target, _ = media
    provider = Posters()

    def restore():
        with engine.store._connect() as conn:
            conn.execute("UPDATE media_control SET epoch='new-timeline'")

    provider.late = restore
    assert PosterJobs(engine, provider).run()[0]["status"] == "superseded"
    replacement = Engine(engine.store, engine.config, clock=engine.clock)
    assert PosterJobs(replacement, Posters()).run()[0]["status"] == "published"
    assert next(target.rglob("poster.png")).read_bytes() == PAYLOAD


def test_preview_does_not_request_or_publish_posters(media):
    import_three(media)
    engine, _, target, _ = media
    engine.config.import_policy = "preview"
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    assert jobs.run()[0]["status"] == "preview"
    assert not list(target.rglob("poster.png")) and provider.calls == 0


def test_partial_interrupted_payload_stays_visible_without_refetch(media, monkeypatch):
    from pathlib import Path

    import_three(media)
    engine, _, target, _ = media
    now = [engine.clock()]
    engine.clock = lambda: now[0]
    original = engine._link
    provider = Posters()
    jobs = PosterJobs(engine, provider)

    def interrupt(*args, **kwargs):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(engine, "_link", interrupt)
    with pytest.raises(RuntimeError):
        jobs.run()
    monkeypatch.setattr(engine, "_link", original)
    with engine.store._connect() as conn:
        temporary = conn.execute(
            "SELECT temporary FROM media_publications WHERE status='pending' "
            "AND temporary LIKE '%media-poster%'"
        ).fetchone()[0]
    Path(temporary).write_bytes(b"damaged during interruption")
    now[0] += 601
    result = jobs.run()[0]
    assert result["status"] == "conflict"
    assert provider.calls == 1 and Path(temporary).exists()
    assert not list(target.rglob("poster.png"))
    assert jobs.status()[0]["status"] == "conflict"


@pytest.mark.parametrize(
    "failure,status",
    [
        ("auth", "credentials_required"),
        ("server", "retrying"),
        ("timeout", "retrying"),
        ("adapter", "retrying"),
    ],
)
def test_provider_failure_states_are_visible_and_do_not_publish(media, failure, status):
    import_three(media)
    engine, _, target, _ = media

    class FailingPosters:
        def fetch(self, mapping, locale):
            request = httpx.Request("GET", "https://api.themoviedb.org/3/tv/12")
            if failure in {"auth", "server"}:
                httpx.Response(
                    401 if failure == "auth" else 503, request=request
                ).raise_for_status()
            if failure == "timeout":
                raise httpx.ReadTimeout("private provider exception", request=request)
            raise RuntimeError("private provider exception")

    jobs = PosterJobs(engine, FailingPosters())
    assert jobs.run()[0]["status"] == status
    assert jobs.status()[0]["status"] == status
    assert "private provider exception" not in json.dumps(jobs.status())
    assert not list(target.rglob("poster.png"))


@pytest.mark.parametrize(
    "policy,command_preview,apply_mode",
    [
        ("preview", False, False),
        ("execute", True, False),
        ("execute", True, True),
    ],
)
def test_real_guarded_preview_and_pinned_command_modes_do_not_publish(
    media, tmp_path, monkeypatch, policy, command_preview, apply_mode
):
    import yaml

    from seed_agent.config_views import MediaConfigGuard, load_view

    import_three(media)
    engine, source, target, _ = media
    engine.config.import_policy = policy
    config = tmp_path / "guarded-config.yaml"
    config.write_text(yaml.safe_dump({"media_import": engine.config.model_dump(mode="json")}))
    modes = {"import": "preview", "subtitle": "preview", "reconcile": "preview"}
    engine.config_guard = MediaConfigGuard(
        load_view(config, "media"), modes=modes if command_preview else None
    )
    if apply_mode:
        # execute_command applies each persisted command mode to engine.config.
        for kind, mode in modes.items():
            setattr(engine.config, kind + "_policy", mode)
    before = {
        str(path): (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
        for root in [source, target]
        for path in root.rglob("*")
        if path.is_file()
    }

    def forbid(*args, **kwargs):
        raise AssertionError("preview attempted filesystem publication/recovery")

    monkeypatch.setattr(engine, "_link", forbid)
    monkeypatch.setattr(engine, "_unlink", forbid)
    monkeypatch.setattr(engine, "recover_publication", forbid)
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    assert jobs.run()[0]["status"] == "preview"
    assert jobs.status()[0]["status"] == "preview"
    assert provider.calls == 0
    after = {
        str(path): (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
        for root in [source, target]
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before
    with engine.store._connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM media_artifacts WHERE kind='poster'").fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_publications WHERE temporary LIKE '%media-poster%'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("changed", [False, True])
def test_real_guarded_execute_still_checks_configuration_before_publish(media, tmp_path, changed):
    import yaml

    from seed_agent.config_views import MediaConfigGuard, load_view

    import_three(media)
    engine, _, target, _ = media
    config = tmp_path / "guarded-config.yaml"
    document = {"media_import": engine.config.model_dump(mode="json")}
    config.write_text(yaml.safe_dump(document))
    engine.config_guard = MediaConfigGuard(load_view(config, "media"))
    provider = Posters()
    if changed:

        def late():
            document["media_import"]["profiles"][0]["locale"] = "en-US"
            config.write_text(yaml.safe_dump(document))

        provider.late = late
    result = PosterJobs(engine, provider).run()[0]
    assert result["status"] == ("conflict" if changed else "published")
    assert provider.calls == 1
    assert bool(list(target.rglob("poster.png"))) is not changed


def test_guarded_preview_cannot_replace_live_execute_claim(media, tmp_path):
    import yaml

    from seed_agent.config_views import MediaConfigGuard, load_view

    import_three(media)
    engine, _, target, _ = media
    config = tmp_path / "guarded-config.yaml"
    config.write_text(yaml.safe_dump({"media_import": engine.config.model_dump(mode="json")}))
    view = load_view(config, "media")
    owner_guard = MediaConfigGuard(view)
    engine.config_guard = owner_guard
    provider = Posters()
    jobs = PosterJobs(engine, provider)
    nested = []

    def preview_during_fetch():
        before = jobs.status()[0]["claim_token"]
        engine.config_guard = MediaConfigGuard(
            view, modes={"import": "preview", "subtitle": "preview", "reconcile": "preview"}
        )
        try:
            nested.extend(jobs.run(refresh=True))
            assert jobs.status()[0]["claim_token"] == before
        finally:
            engine.config_guard = owner_guard

    provider.late = preview_during_fetch
    assert jobs.run()[0]["status"] == "published"
    assert nested[0]["status"] == "running"
    assert provider.calls == 1
    assert len(list(target.rglob("poster.png"))) == 1
