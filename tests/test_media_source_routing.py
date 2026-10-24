from pathlib import Path

import pytest
from test_media_artwork import PAYLOAD as IMAGE_PAYLOAD
from test_media_artwork import image_probe as image_probe
from test_media_import import media as media

from seed_agent.media_import.config import MediaImportConfig
from seed_agent.media_import.routing import Destinations, Source, validate_sources
from seed_agent.media_import.sources import inventory


def fixture(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / ".media-volume").write_text("source")
    outputs = root / "library"
    mapping = {
        key: {"root": str(outputs / key), "marker_value": "target"}
        for key in ["movies", "tv", "animation"]
    }
    targets = Destinations.model_validate(mapping)
    source = Source(id="main", root=str(root), marker_value="source")
    return source, targets


def test_separate_content_type_and_animation_routes(tmp_path):
    source, targets = fixture(tmp_path)
    validate_sources([source], targets)
    assert targets.route("movie", False)[0] == "movies"
    assert targets.route("tv", False)[0] == "tv"
    assert targets.route("movie", True)[2] == "Movies"
    assert targets.route("tv", True)[2] == "TV"
    with pytest.raises(ValueError):
        targets.route("anime", True)
    with pytest.raises(ValueError):
        targets.route("movie", None)


def test_output_subtrees_never_enter_source_authority(tmp_path):
    source, targets = fixture(tmp_path)
    root = Path(source.root)
    (root / "Real.Movie.2024.mkv").write_bytes(b"video")
    for output in targets.physical_roots():
        folder = Path(output)
        folder.mkdir(parents=True)
        (folder / "Generated.Movie.2024.mkv").write_bytes(b"linked output")
        (folder / "symlink-inside-output").symlink_to(tmp_path, target_is_directory=True)
    incomplete = root / "incomplete"
    incomplete.mkdir()
    (incomplete / "unfinished.mkv").write_bytes(b"not ready")
    assert set(inventory(source, targets)) == {"Real.Movie.2024.mkv"}
    old = root / "old-library"
    old.mkdir()
    (old / "previous-output.mkv").write_bytes(b"previous route")
    assert set(inventory(source, targets, historical_targets=[str(old)])) == {"Real.Movie.2024.mkv"}


def test_overlapping_sources_and_target_above_source_rejected(tmp_path):
    source, targets = fixture(tmp_path)
    child = source.model_copy(update={"id": "child", "root": str(Path(source.root) / "child")})
    with pytest.raises(ValueError, match="overlap"):
        validate_sources([source, child], targets)
    bad = targets.model_copy(deep=True)
    bad.movies.root = str(tmp_path)
    with pytest.raises(ValueError, match="contain"):
        validate_sources([source], bad)


def test_legacy_profiles_not_silently_mixed_with_new_sources(tmp_path):
    source, targets = fixture(tmp_path)
    config = MediaImportConfig(sources=[source], destinations=targets)
    assert config.sources[0].id == "main" and not config.profiles
    with pytest.raises(ValueError, match="require separate"):
        MediaImportConfig(sources=[source])


def mixed_engine(tmp_path):
    from seed_agent.media_import.engine import Engine
    from seed_agent.media_import.metadata import Mapping
    from seed_agent.media_import.store import MediaStore

    source, targets = fixture(tmp_path)
    source.readiness = "completed_folder"
    source.completed_contract_acknowledged = True
    source.min_age_seconds = 0
    source.grace_seconds = 0
    for path in targets.physical_roots():
        root = Path(path)
        root.mkdir(parents=True)
        (root / ".media-volume").write_text("target")
    mappings = {
        "live-movie.mkv": Mapping(
            media_type="movie", animation=False, tmdb_id=1, original_title="Live Film", year=2024
        ),
        "live-series.mkv": Mapping(
            media_type="tv",
            animation=False,
            tmdb_id=2,
            original_title="Live Series",
            year=2024,
            season=1,
            episodes=[1],
        ),
        "animated-movie.mkv": Mapping(
            media_type="movie", animation=True, tmdb_id=3, original_title="Animated Film", year=2024
        ),
        "animated-series.mkv": Mapping(
            media_type="tv",
            animation=True,
            tmdb_id=4,
            original_title="Animated Series",
            year=2024,
            season=1,
            episodes=[1],
        ),
    }

    class Metadata:
        def identify(self, path, profile):
            return mappings[path.name], []

    config = MediaImportConfig(
        enabled=True, sources=[source], destinations=targets, import_policy="execute"
    )
    engine = Engine(
        MediaStore(tmp_path / "mixed.db"),
        config,
        metadata=Metadata(),
        media_probe=lambda path: {"duration": 100, "fps": 24, "streams": []},
    )
    return engine, source, targets, mappings


def test_one_source_routes_four_metadata_types_and_never_reingests_outputs(tmp_path):
    engine, source, targets, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    for _ in range(2):
        assert engine.scan("main", force=True)["status"] == "complete"
    snapshot = engine.snapshot()
    assert len(snapshot["sources"]) == 4
    actual = {s["path"]: Path(s["target"]) for s in snapshot["sources"]}
    assert actual["live-movie.mkv"].is_relative_to(Path(targets.movies.root))
    assert actual["live-series.mkv"].is_relative_to(Path(targets.tv.root))
    assert actual["animated-movie.mkv"].is_relative_to(Path(targets.animation.root) / "Movies")
    assert actual["animated-series.mkv"].is_relative_to(Path(targets.animation.root) / "TV")
    assert all(
        p.stat().st_ino == (Path(source.root) / name).stat().st_ino for name, p in actual.items()
    )
    engine.scan("main", force=True)
    assert len(engine.snapshot()["sources"]) == 4


def test_legacy_source_history_keeps_old_outputs_until_explicit_route_repair(media, tmp_path):
    from test_media_import import import_three

    from seed_agent.media_import.engine import Engine

    import_three(media)
    old, source, _, _ = media
    before = old.snapshot()["sources"]
    destinations = {
        key: {"root": str(tmp_path / ("new-" + key)), "marker_value": "new"}
        for key in ["movies", "tv", "animation"]
    }
    targets = Destinations.model_validate(destinations)
    for path in targets.physical_roots():
        root = Path(path)
        root.mkdir()
        (root / ".media-volume").write_text("new")
    config = MediaImportConfig(
        enabled=True,
        import_policy="execute",
        sources=[
            Source(
                id="tv",
                root=str(source),
                marker_value="fixture",
                readiness="completed_folder",
                completed_contract_acknowledged=True,
                min_age_seconds=0,
            )
        ],
        destinations=targets,
    )
    new = Engine(old.store, config, metadata=old.metadata, media_probe=old.probe)
    assert new.scan("tv", force=True)["status"] == "complete"
    assert {s["id"] for s in new.snapshot()["sources"]} == {s["id"] for s in before}
    assert {s["target"] for s in new.snapshot()["sources"]} == {s["target"] for s in before}
    chosen = before[0]
    mapping = __import__("json").loads(chosen["mapping_json"])
    mapping["animation"] = False
    new.review(chosen["id"], mapping, fingerprint=chosen["fingerprint"], ready=True, repair=True)
    new.scan("tv", force=True)
    updated = next(s for s in new.snapshot()["sources"] if s["id"] == chosen["id"])
    assert Path(updated["target"]).is_relative_to(Path(targets.tv.root))
    assert Path(updated["target"]).exists() and not Path(chosen["target"]).exists()


def test_destination_offline_does_not_prevent_source_observation_or_other_routes(tmp_path):
    engine, source, targets, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    (Path(targets.tv.root) / ".media-volume").unlink()
    engine.scan("main", force=True)
    result = engine.scan("main", force=True)
    assert result["status"] == "complete"
    snapshot = engine.snapshot()
    assert len(snapshot["sources"]) == 4
    assert len([a for a in snapshot["artifacts"] if a["kind"] == "video"]) == 3
    blocked = next(s for s in snapshot["sources"] if s["path"] == "live-series.mkv")
    assert blocked["import_status"] == "blocked_destination" and blocked["missing_count"] == 0


def test_unknown_animation_requires_review_without_default_destination(tmp_path):
    engine, source, _, mappings = mixed_engine(tmp_path)
    mappings["live-movie.mkv"].animation = None
    (Path(source.root) / "live-movie.mkv").write_bytes(b"fixture")
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    row = engine.snapshot()["sources"][0]
    assert row["import_status"] == "review_required" and not engine.snapshot()["artifacts"]


def test_historical_target_ancestor_cannot_turn_scan_into_empty_authority(tmp_path):
    source, targets = fixture(tmp_path)
    with pytest.raises(ValueError, match="historical destination"):
        inventory(source, targets, historical_targets=[str(tmp_path)])


@pytest.mark.parametrize(
    "kind,animation", [("movie", False), ("tv", False), ("movie", True), ("tv", True)]
)
def test_mixed_tmdb_identity_type_and_animation_use_confirmed_metadata(tmp_path, kind, animation):
    import httpx
    import respx

    from seed_agent.media_import.metadata import Tmdb
    from seed_agent.media_import.routing import source_adapter

    source, _ = fixture(tmp_path)
    path = Path(source.root) / (
        "Exact.Show.2024.S01E01.mkv" if kind == "tv" else "Exact.Film.2024.mkv"
    )
    title = "Exact Show" if kind == "tv" else "Exact Film"
    with respx.mock:
        for search_kind in ["movie", "tv"]:
            item = {
                "id": 1,
                "original_title": title,
                "original_name": title,
                "release_date": "2024-01-01",
                "first_air_date": "2024-01-01",
            }
            respx.get("https://api.themoviedb.org/3/search/" + search_kind).mock(
                return_value=httpx.Response(
                    200, json={"results": [item] if search_kind == kind else []}
                )
            )
        respx.get(f"https://api.themoviedb.org/3/{kind}/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "genres": [{"id": 16 if animation else 18}],
                    "original_language": "ja" if not animation else "en",
                    "runtime": 90,
                },
            )
        )
        if kind == "tv":
            respx.get("https://api.themoviedb.org/3/tv/1/season/1/episode/1").mock(
                return_value=httpx.Response(
                    200, json={"season_number": 1, "episode_number": 1, "runtime": 45}
                )
            )
        mapping, _ = Tmdb("fixture").identify(path, source_adapter(source))
    assert mapping.media_type == kind and mapping.animation is animation
    assert mapping.classification_evidence == "tmdb_genres"


def test_same_title_movie_and_tv_metadata_stays_review_required(tmp_path):
    import httpx
    import respx

    from seed_agent.media_import.metadata import Tmdb
    from seed_agent.media_import.routing import source_adapter

    source, _ = fixture(tmp_path)
    with respx.mock:
        for kind in ["movie", "tv"]:
            respx.get("https://api.themoviedb.org/3/search/" + kind).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "results": [
                            {"id": 1, "original_title": "Same", "release_date": "2024-01-01"}
                        ]
                    },
                )
            )
        mapping, candidates = Tmdb("fixture").identify(
            Path(source.root) / "Same.2024.mkv", source_adapter(source)
        )
    assert mapping is None and len(candidates) == 2


def test_mixed_routes_enrichment_and_historical_cleanup_after_destination_change(tmp_path):
    from test_media_subtitles import FakeProvider

    from seed_agent.media_import.artwork import PosterJobs
    from seed_agent.media_import.subtitles.jobs import SubtitleJobs

    engine, source, targets, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    engine.config.subtitle_policy = "execute"
    engine.config.provider_interval_seconds = 0
    results = SubtitleJobs(engine, FakeProvider()).run()
    assert all(r["status"] == "satisfied" for r in results)

    class Posters:
        def fetch(self, mapping, locale):
            return (
                IMAGE_PAYLOAD,
                ".png",
                {
                    "provider": "tmdb",
                    "media_type": mapping["media_type"],
                    "tmdb_id": mapping["tmdb_id"],
                    "poster_path": "/fixture.png",
                },
            )

    assert len(PosterJobs(engine, Posters()).run()) == 4
    assert len(list(Path(source.root).rglob("poster.png"))) == 4
    old = next(s for s in engine.snapshot()["sources"] if s["path"] == "animated-movie.mkv")
    manual = Path(old["target"]).parent / "manual.txt"
    manual.write_text("preserve")
    new_animation = Path(source.root) / "new-animation"
    new_animation.mkdir()
    (new_animation / ".media-volume").write_text("target")
    targets.animation.root = str(new_animation)
    engine.config.reconcile_policy = "execute"
    (Path(source.root) / old["path"]).unlink()
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    assert not Path(old["target"]).exists()
    assert not (Path(old["target"]).parent / "poster.png").exists()
    assert manual.read_text() == "preserve"
    assert len(engine.snapshot()["sources"]) == 4  # old outputs never become new source generations


def test_late_publication_cannot_recover_after_manual_route_review(tmp_path, monkeypatch):
    engine, source, _, mappings = mixed_engine(tmp_path)
    (Path(source.root) / "live-movie.mkv").write_bytes(b"fixture")
    engine.scan("main", force=True)
    original = engine._link
    attempts = [0]

    def fail_second(*args, **kwargs):
        attempts[0] += 1
        if attempts[0] == 2:
            raise RuntimeError("simulated interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "_link", fail_second)
    engine.scan("main", force=True)
    row = engine.snapshot()["sources"][0]
    corrected = mappings["live-movie.mkv"].model_dump()
    corrected["animation"] = True
    engine.review(row["id"], corrected, fingerprint=row["fingerprint"], ready=True, repair=True)
    monkeypatch.setattr(engine, "_link", original)
    with engine.lease():
        engine.recover(engine.profile("main"))
    assert not list((Path(engine.config.destinations.movies.root)).rglob("*.mkv"))
    assert any(p["status"] == "conflict" for p in engine.snapshot()["publications"])


def test_disjoint_sources_share_show_poster_without_shared_deletion_authority(tmp_path):
    from seed_agent.media_import.artwork import PosterJobs

    engine, source, targets, mappings = mixed_engine(tmp_path)
    (Path(source.root) / "live-series.mkv").write_bytes(b"episode one")
    other = tmp_path / "other-source"
    other.mkdir()
    (other / ".media-volume").write_text("source")
    second = source.model_copy(update={"id": "second", "root": str(other)})
    engine.config.sources.append(second)
    mappings["second-episode.mkv"] = mappings["live-series.mkv"].model_copy(
        update={"episodes": [2]}
    )
    (other / "second-episode.mkv").write_bytes(b"episode two")
    for _ in range(2):
        engine.scan("main", force=True)
        engine.scan("second", force=True)

    class Posters:
        def fetch(self, mapping, locale):
            return (
                IMAGE_PAYLOAD,
                ".png",
                {
                    "provider": "tmdb",
                    "media_type": "tv",
                    "tmdb_id": 2,
                    "poster_path": "/fixture.png",
                },
            )

    PosterJobs(engine, Posters()).run()
    posters = list(Path(targets.tv.root).rglob("poster.png"))
    assert len(posters) == 1
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources r "
                "JOIN media_artifacts a ON a.id=r.artifact_id WHERE a.kind='poster'"
            ).fetchone()[0]
            == 2
        )
    engine.config.reconcile_policy = "execute"
    (Path(source.root) / "live-series.mkv").unlink()
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    assert posters[0].exists()
    (other / "second-episode.mkv").unlink()
    engine.scan("second", force=True)
    engine.scan("second", force=True)
    assert not posters[0].exists()


def test_late_metadata_does_not_overwrite_persisted_manual_classification(tmp_path):
    import json

    from seed_agent.media_import.metadata import Mapping

    engine, source, _, _ = mixed_engine(tmp_path)
    video = Path(source.root) / "live-movie.mkv"
    video.write_bytes(b"fixture")
    engine.scan("main", force=True)
    row = engine.snapshot()["sources"][0]
    corrected = Mapping(
        media_type="movie", animation=True, tmdb_id=33, original_title="Manual", year=2024
    )

    class Late:
        def identify(self, path, profile):
            with engine.store._connect() as conn:
                conn.execute(
                    "INSERT INTO media_review_decisions VALUES(?,?,?,?,1,?)",
                    (row["id"], row["fingerprint"], corrected.model_dump_json(), 1, engine.clock()),
                )
            return Mapping(
                media_type="movie", animation=False, tmdb_id=1, original_title="Late", year=2024
            ), []

    engine.metadata = Late()
    engine.scan("main", force=True)
    assert not engine.snapshot()["artifacts"]
    engine.scan("main", force=True)
    result = engine.snapshot()["sources"][0]
    assert json.loads(result["mapping_json"])["tmdb_id"] == 33
    assert result["animation"] is True


@pytest.mark.parametrize("fault", ["marker", "inode", "symlink", "missing"])
def test_imported_target_fault_is_visible_isolated_and_recovers(tmp_path, fault):
    engine, source, targets, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    root = Path(targets.tv.root)
    held = tmp_path / "held-tv-root"
    if fault == "marker":
        (root / ".media-volume").write_text("wrong")
    else:
        root.rename(held)
        if fault == "inode":
            root.mkdir()
            (root / ".media-volume").write_text("target")
        elif fault == "symlink":
            root.symlink_to(held, target_is_directory=True)
    engine.config.reconcile_policy = "execute"
    mappings["new-film.mkv"] = mappings["live-movie.mkv"].model_copy(
        update={"tmdb_id": 99, "original_title": "New Film"}
    )
    (Path(source.root) / "new-film.mkv").write_bytes(b"new film")
    for _ in range(2):
        assert engine.scan("main", force=True)["status"] == "complete"
    fresh = next(s for s in engine.snapshot()["sources"] if s["path"] == "new-film.mkv")
    assert fresh["import_status"] == "imported"
    health = engine.snapshot(limit=100)["domain_health"]
    assert any(h.get("root") == str(root) and h["status"] == "blocked" for h in health)
    if fault == "inode":
        assert not list(root.rglob("*.mkv"))
    if fault == "marker":
        (root / ".media-volume").write_text("target")
    else:
        if root.is_symlink():
            root.unlink()
        elif root.exists():
            (root / ".media-volume").unlink()
            root.rmdir()
        held.rename(root)
    assert engine.scan("main", force=True)["status"] == "complete"
    assert any(
        h.get("root") == str(root) and h["status"] == "healthy"
        for h in engine.snapshot(limit=100)["domain_health"]
    )


def test_subtitle_target_outage_spends_no_payload_and_due_recovers_without_refresh(tmp_path):
    from test_media_subtitles import FakeProvider

    from seed_agent.media_import.subtitles.jobs import SubtitleJobs

    engine, source, targets, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    engine.config.subtitle_policy = "execute"
    engine.config.provider_interval_seconds = 0
    marker = Path(targets.tv.root) / ".media-volume"
    marker.unlink()
    provider = FakeProvider()
    result = SubtitleJobs(engine, provider).run()
    assert [r["status"] for r in result].count("blocked_destination") == 1
    assert provider.downloads == 3
    marker.write_text("target")
    now = engine.clock()
    engine.clock = lambda: now + 61
    result = SubtitleJobs(engine, provider).run()
    assert len(result) == 1 and result[0]["status"] == "satisfied"
    assert provider.downloads == 4


def test_worker_cycles_continue_healthy_route_while_imported_target_is_unsafe(
    tmp_path, monkeypatch
):
    import yaml

    from seed_agent.config_views import load_view
    from seed_agent.media_import import worker

    engine, source, targets, mappings = mixed_engine(tmp_path)
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    engine.scan("main", force=True)
    engine.scan("main", force=True)
    engine.config.reconcile_policy = "execute"
    engine.config.interval_seconds = 1
    engine.config.state_path = str(engine.store.path)
    (Path(targets.tv.root) / ".media-volume").write_text("wrong")
    mappings["new-film.mkv"] = mappings["live-movie.mkv"].model_copy(
        update={"tmdb_id": 99, "original_title": "New Film"}
    )
    (Path(source.root) / "new-film.mkv").write_bytes(b"new film")
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_scan_runs SET completed=0")
    path = tmp_path / "worker-config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "deployment": {"source_id": "worker-fixture"},
                "media_import": engine.config.model_dump(mode="json"),
            }
        )
    )
    engine.config_view = load_view(path, "media")
    monkeypatch.setattr(worker, "build_engine", lambda *a, **k: (engine, tmp_path))
    worker.serve(path, max_cycles=3, poll_seconds=0.6)
    fresh = next(s for s in engine.snapshot()["sources"] if s["path"] == "new-film.mkv")
    assert fresh["import_status"] == "imported"
    assert engine.store.applied_status()["role"] == "media"
    assert any(
        h.get("root") == targets.tv.root and h["status"] == "blocked"
        for h in engine.snapshot(limit=100)["domain_health"]
    )


def test_mixed_cli_migration_rejected_with_backup_restore_path(tmp_path):
    import json

    import yaml
    from typer.testing import CliRunner

    from seed_agent import cli

    engine, _, _, _ = mixed_engine(tmp_path)
    engine.config.state_path = str(engine.store.path)
    path = tmp_path / "mixed-config.yaml"
    path.write_text(yaml.safe_dump({"media_import": engine.config.model_dump(mode="json")}))
    runner = CliRunner()
    for command in ["media-state-export", "media-state-import"]:
        args = [command, "--config", str(path), "--source", str(tmp_path / "not-read")]
        if command.endswith("export"):
            args += ["--output", str(tmp_path / "not-written")]
        result = runner.invoke(cli.app, args)
        assert result.exit_code != 0
        assert "Legacy-only" in result.output and "media-state-backup" in result.output
    backup = tmp_path / "mixed-backup.db"
    result = runner.invoke(
        cli.app, ["media-state-backup", "--config", str(path), "--output", str(backup)]
    )
    assert result.exit_code == 0 and json.loads(result.output)["valid"] is True
    result = runner.invoke(
        cli.app, ["media-state-restore", "--config", str(path), "--source", str(backup)]
    )
    assert result.exit_code == 0 and json.loads(result.output)["status"] == "preview"


def test_three_destination_default_routes_animation_films_to_movie(tmp_path):
    import os

    engine, source, old, mappings = mixed_engine(tmp_path)
    data = old.model_dump(exclude_none=True)
    animation = data.pop("animation")
    data["animated_tv"] = animation
    data["library_root"] = str(Path(old.movies.root).parent)
    targets = Destinations.model_validate(data)
    engine.config.destinations = targets
    for name in mappings:
        (Path(source.root) / name).write_bytes(name.encode())
    # Unknown/manual contents anywhere under Library are excluded before descent.
    unknown = Path(targets.library_root) / "Manual" / "unknown.mkv"
    unknown.parent.mkdir()
    unknown.write_bytes(b"preserve")
    for _ in range(2):
        assert engine.scan("main", force=True)["status"] == "complete"
    actual = {s["path"]: Path(s["target"]) for s in engine.snapshot()["sources"]}
    assert set(actual) == set(mappings)
    assert actual["animated-movie.mkv"].is_relative_to(Path(targets.movies.root))
    assert actual["animated-series.mkv"].is_relative_to(Path(targets.animated_tv.root))
    assert len(list(Path(targets.movies.root).rglob("*.mkv"))) == 2
    assert all(
        os.stat(path).st_ino == os.stat(Path(source.root) / name).st_ino
        for name, path in actual.items()
    )
    assert unknown.read_bytes() == b"preserve"
    # Persisted exclusions survive the output-parent configuration changing.
    changed = targets.model_copy(update={"library_root": None})
    engine.config.destinations = changed
    engine.scan("main", force=True)
    assert set(s["path"] for s in engine.snapshot()["sources"]) == set(mappings)


def test_destination_alias_requires_same_type_and_marker_policy(tmp_path):
    _, old = fixture(tmp_path)
    data = old.model_dump(exclude_none=True)
    data["animated_tv"] = data.pop("animation")
    data["animated_movies"] = data["movies"].copy()
    assert Destinations.model_validate(data).route("movie", True)[1].root == old.movies.root
    data["animated_movies"]["marker_value"] = "different"
    with pytest.raises(ValueError, match="disjoint"):
        Destinations.model_validate(data)
    data.pop("animated_movies")
    data["animated_tv"] = data["movies"].copy()
    with pytest.raises(ValueError, match="disjoint"):
        Destinations.model_validate(data)


def test_confirmed_tv_specials_keep_season_zero_despite_ova_movie_tokens(tmp_path):
    import httpx
    import respx

    from seed_agent.media_import.metadata import Tmdb
    from seed_agent.media_import.routing import source_adapter

    source, _ = fixture(tmp_path)
    path = Path(source.root) / "Exact.Show.2024.S00E01.OVA.Movie.mkv"
    with respx.mock:
        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        respx.get("https://api.themoviedb.org/3/search/tv").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"id": 42, "original_name": "Exact Show", "first_air_date": "2024-01-01"}
                    ]
                },
            )
        )
        respx.get("https://api.themoviedb.org/3/tv/42").mock(
            return_value=httpx.Response(200, json={"genres": [{"id": 16}]})
        )
        respx.get("https://api.themoviedb.org/3/tv/42/season/0/episode/1").mock(
            return_value=httpx.Response(
                200, json={"season_number": 0, "episode_number": 1, "runtime": 30}
            )
        )
        mapping, _ = Tmdb("fixture").identify(path, source_adapter(source))
    assert mapping.media_type == "tv"
    assert mapping.animation is True
    assert mapping.season == 0 and mapping.episodes == [1]


def test_config_legacy_outputs_excluded_before_walk_without_basename_collision(tmp_path):
    engine, source, targets, _ = mixed_engine(tmp_path)
    root = Path(source.root)
    legacy = root / "Movies"
    source.legacy_output_roots = [str(legacy), str(root / "TV"), str(root / "Anime")]
    for path in source.legacy_output_roots:
        output = Path(path)
        output.mkdir()
        (output / "old.mkv").write_bytes(b"old")
        # Walking or recognition beneath an output would fail; exclusion precedes both.
        (output / "unsafe-child").symlink_to(tmp_path, target_is_directory=True)
    legal = root / "movie/Collection/Movies"
    legal.mkdir(parents=True)
    (legal / "real.mkv").write_bytes(b"source")
    profile = engine.profiles()[0]
    assert (
        engine.profile_config(source.id)["source"]["legacy_output_roots"]
        == source.legacy_output_roots
    )
    assert set(engine.inventory(profile)) == {"movie/Collection/Movies/real.mkv"}
    with engine.store._connect() as conn:
        persisted = {r[0] for r in conn.execute("SELECT path FROM media_output_exclusions")}
    assert set(source.legacy_output_roots) <= persisted


def test_config_exclusions_survive_empty_restored_state_and_later_output_creation(tmp_path):
    from seed_agent.media_import.engine import Engine
    from seed_agent.media_import.maintenance import backup_media_database, restore_media_database
    from seed_agent.media_import.store import MediaStore

    engine, source, _, _ = mixed_engine(tmp_path)
    backup = tmp_path / "before-exclusions.db"
    assert backup_media_database(engine.store.path, backup)["valid"]
    root = Path(source.root)
    old = root / "TV"
    source.legacy_output_roots = [str(old)]
    profile = engine.profiles()[0]
    assert engine.inventory(profile) == {}  # Old output is not present yet.
    # Restore/rebuild a store with no historical exclusions: config still excludes it.
    restored = Engine(MediaStore(tmp_path / "restored.db"), engine.config)
    old.mkdir()
    (old / "must-not-identify.mkv").write_bytes(b"old output")
    assert restored.inventory(restored.profiles()[0]) == {}
    with restored.store._connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM media_output_exclusions WHERE path=?", (str(old),)
        ).fetchone()
    # An actual restore removes the DB record, but the current config restores the fence.
    assert restore_media_database(restored.store.path, backup, execute=True)["status"] == "restored"
    with restored.store._connect() as conn:
        assert not conn.execute("SELECT path FROM media_output_exclusions").fetchall()
    assert restored.inventory(restored.profiles()[0]) == {}
    # Removing the configured path later cannot erase already observed output history.
    source.legacy_output_roots = []
    assert restored.inventory(restored.profiles()[0]) == {}


def test_legacy_exclusions_validate_and_normalize_exact_absolute_paths(tmp_path):
    source, _ = fixture(tmp_path)
    data = source.model_dump()
    for bad in ["relative/TV", str(tmp_path), source.root, "/"]:
        with pytest.raises(ValueError, match="absolute|contain source"):
            Source.model_validate({**data, "legacy_output_roots": [bad]})
    path = str(Path(source.root) / "old/../TV")
    normalized = Source.model_validate({**data, "legacy_output_roots": [path, path]})
    assert normalized.legacy_output_roots == [str(Path(source.root) / "TV")]
