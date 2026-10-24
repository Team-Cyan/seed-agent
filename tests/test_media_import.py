import os
from pathlib import Path

import pytest

from seed_agent.media_import.config import MediaImportConfig, Profile
from seed_agent.media_import.engine import Engine
from seed_agent.media_import.metadata import Mapping
from seed_agent.media_import.store import MediaStore


@pytest.fixture
def media(tmp_path):
    source, target = tmp_path / "source", tmp_path / "library"
    source.mkdir()
    target.mkdir()
    for root in [source, target]:
        (root / ".media-volume").write_text("fixture")
    p = Profile(
        name="tv",
        source_root=str(source),
        target_root=str(target),
        marker_value="fixture",
        target_marker_value="fixture",
        media_type="tv",
        min_age_seconds=0,
        readiness="completed_folder",
        completed_contract_acknowledged=True,
        grace_seconds=0,
    )
    config = MediaImportConfig(enabled=True, profiles=[p], import_policy="execute")

    class Metadata:
        calls = 0

        def identify(self, path, profile):
            self.calls += 1
            season = int(path.stem[-1])
            return Mapping(
                media_type="tv",
                tmdb_id=12,
                original_title="Example",
                year=2024,
                season=season,
                episodes=[1],
            ), []

    metadata = Metadata()
    store = MediaStore(tmp_path / "state.db")
    engine = Engine(
        store,
        config,
        metadata=metadata,
        media_probe=lambda p: {"duration": 1000, "fps": 24, "streams": []},
    )
    return engine, source, target, metadata


def import_three(media):
    engine, source, target, metadata = media
    for season in range(1, 4):
        (source / f"Episode{season}.mkv").write_bytes(b"fixture" + bytes([season]))
    engine.scan("tv", force=True)
    result = engine.scan("tv", force=True)
    assert result["status"] == "complete"
    assert all(s["import_status"] == "imported" for s in engine.snapshot()["sources"])


def test_three_seasons_restart_idempotent(media):
    import_three(media)
    engine, source, target, metadata = media
    for i in range(1, 4):
        dest = (
            target
            / "Example (2024) {tmdb-12}"
            / f"Season {i:02d}"
            / f"Example (2024) - S{i:02d}E01.mkv"
        )
        assert os.path.samefile(source / f"Episode{i}.mkv", dest)
    assert metadata.calls == 3
    engine.scan("tv", force=True)
    assert metadata.calls == 3
    assert len(engine.snapshot()["artifacts"]) == 3


def test_mirror_exact_and_manual_survives(media):
    import_three(media)
    engine, source, target, _ = media
    target1 = Path(engine.snapshot()["sources"][0]["target"])
    manual = target1.parent / "manual.txt"
    manual.write_text("keep")
    (source / "Episode1.mkv").unlink()
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    snapshot = engine.snapshot()
    assert len(snapshot["cleanup"]) == 1
    assert target1.exists()  # preview default
    engine.config.reconcile_policy = "execute"
    engine.scan("tv", force=True)
    assert not target1.exists()
    assert manual.exists()
    assert len(list(target.rglob("*.mkv"))) == 2


def test_outage_and_replaced_marker_do_not_count(media):
    import_three(media)
    engine, source, _, _ = media
    (source / "Episode1.mkv").unlink()
    (source / ".media-volume").write_text("other mount")
    assert engine.scan("tv", force=True)["status"] == "failed"
    assert all(s["missing_count"] == 0 for s in engine.snapshot()["sources"])


def test_manual_readiness_and_review_replan(media):
    engine, source, target, _ = media
    engine.config.profiles[0].readiness = "manual"
    path = source / "Episode1.mkv"
    path.write_bytes(b"fixture")
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    row = engine.snapshot()["sources"][0]
    assert row["readiness"] == "completion_unverified"
    assert not list(target.rglob("*.mkv"))
    mapping = Mapping(
        media_type="tv", tmdb_id=99, original_title="Original", year=2020, season=2, episodes=[3]
    )
    plan = engine.review(
        row["id"], mapping.model_dump(), fingerprint=row["fingerprint"], ready=True
    )
    assert "Season 02" in plan["new_target"]
    engine.scan("tv", force=True)
    assert Path(engine.snapshot()["sources"][0]["target"]).exists()


def test_rename_cancels_missing(media):
    import_three(media)
    engine, source, _, _ = media
    before = engine.snapshot()["sources"][0]
    (source / before["path"]).rename(source / "relocated.mkv")
    engine.scan("tv", force=True)
    after = next(s for s in engine.snapshot()["sources"] if s["id"] == before["id"])
    assert after["path"] == "relocated.mkv"
    assert after["missing_count"] == 0


def test_modified_target_preserved(media):
    import_three(media)
    engine, source, _, _ = media
    row = engine.snapshot()["sources"][0]
    target = Path(row["target"])
    target.unlink()
    target.write_bytes(b"manual replacement")
    (source / row["path"]).unlink()
    engine.config.reconcile_policy = "execute"
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert target.read_bytes() == b"manual replacement"
    assert engine.snapshot()["cleanup"][-1]["status"] == "conflict"


def test_root_overlap_rejected(tmp_path):
    with pytest.raises(ValueError, match="disjoint"):
        Profile(
            name="x",
            source_root=str(tmp_path),
            target_root=str(tmp_path / "out"),
            marker_value="x",
            target_marker_value="x",
        )


def test_inventory_symlink_fails_without_missing(media):
    import_three(media)
    engine, source, target, _ = media
    (source / "unsafe").symlink_to(target, target_is_directory=True)
    assert engine.scan("tv", force=True)["status"] == "failed"
    assert all(s["missing_count"] == 0 for s in engine.snapshot()["sources"])


def test_unowned_same_inode_never_acquires_deletion_authority(media):
    engine, source, target, _ = media
    path = source / "Episode1.mkv"
    path.write_bytes(b"fixture")
    dest = target / "Example (2024) {tmdb-12}" / "Season 01" / "Example (2024) - S01E01.mkv"
    dest.parent.mkdir(parents=True)
    os.link(path, dest)
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert engine.snapshot()["artifacts"][0]["owned"] == 0
    path.unlink()
    engine.config.reconcile_policy = "execute"
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert dest.exists()


def test_removed_path_redownload_keeps_history(media):
    import_three(media)
    engine, source, target, _ = media
    row = engine.snapshot()["sources"][0]
    (source / row["path"]).unlink()
    engine.config.reconcile_policy = "execute"
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    (source / row["path"]).write_bytes(b"new source generation")
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    history = [s for s in engine.snapshot()["sources"] if s["path"] == row["path"]]
    assert [s["generation"] for s in history] == [1, 2]
    assert history[0]["status"] == "removed"
    assert history[1]["import_status"] == "imported"
    assert len(engine.snapshot()["artifacts"]) == 4


def test_repair_preview_restart_execute_retires_published_output(media):
    import_three(media)
    engine, source, target, _ = media
    row = engine.snapshot()["sources"][0]
    old = Path(row["target"])
    mapping = Mapping(
        media_type="tv", tmdb_id=55, original_title="Correct", year=2023, season=1, episodes=[1]
    )
    engine.review(row["id"], mapping.model_dump(), fingerprint=row["fingerprint"], ready=True)
    engine.config.import_policy = "preview"
    engine.scan("tv", force=True)
    assert old.exists()
    restarted = Engine(engine.store, engine.config, media_probe=engine.probe)
    restarted.config.import_policy = "execute"
    restarted.scan("tv", force=True)
    assert not old.exists()
    assert any("Correct" in str(p) for p in target.rglob("*.mkv"))


@pytest.mark.parametrize("point", ["after_temporary_link", "after_receipt_commit"])
def test_publication_crash_recovery_temp_is_accounted(media, monkeypatch, point):
    from seed_agent.media_import import filesystem as fs

    engine, source, target, _ = media
    (source / "Episode1.mkv").write_bytes(b"fixture")
    engine.scan("tv", force=True)
    original_link = fs.link
    original_finish = engine.finish_link

    class Crash(BaseException):
        pass

    if point == "after_temporary_link":

        def crash_link(*args):
            original_link(*args)
            if ".media-link-" in str(args[-1]):
                raise Crash()

        monkeypatch.setattr(fs, "link", crash_link)
    else:

        def crash_finish(*args, **kwargs):
            original_finish(*args, **kwargs)
            raise Crash()

        monkeypatch.setattr(engine, "finish_link", crash_finish)
    with pytest.raises(Crash):
        engine.scan("tv", force=True)
    assert len(list(target.rglob(".media-link-*"))) == 1
    monkeypatch.setattr(fs, "link", original_link)
    monkeypatch.setattr(engine, "finish_link", original_finish)
    engine.scan("tv", force=True)
    assert not list(target.rglob(".media-link-*"))
    assert engine.snapshot()["sources"][0]["import_status"] == "imported"


def test_repair_finish_crash_recovers_old_retirement(media, monkeypatch):
    import_three(media)
    engine, _, target, _ = media
    row = engine.snapshot()["sources"][0]
    old = Path(row["target"])
    mapping = Mapping(
        media_type="tv", tmdb_id=55, original_title="Correct", year=2023, season=1, episodes=[1]
    )
    engine.review(row["id"], mapping.model_dump(), fingerprint=row["fingerprint"], ready=True)
    original = engine.finish_link

    class Crash(BaseException):
        pass

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash()

    monkeypatch.setattr(engine, "finish_link", crash)
    with pytest.raises(Crash):
        engine.scan("tv", force=True)
    monkeypatch.setattr(engine, "finish_link", original)
    engine.scan("tv", force=True)
    assert not old.exists()
    assert len(list(target.rglob("*.mkv"))) == 3


@pytest.mark.parametrize("replacement", ["file", "symlink"])
def test_repair_recovery_revalidates_new_target_before_retiring_old(
    media, monkeypatch, replacement
):
    import_three(media)
    engine, source, target, _ = media
    row = engine.snapshot()["sources"][0]
    old = Path(row["target"])
    mapping = Mapping(
        media_type="tv", tmdb_id=55, original_title="Correct", year=2023, season=1, episodes=[1]
    )
    engine.review(row["id"], mapping.model_dump(), fingerprint=row["fingerprint"], ready=True)
    original = engine.finish_link

    class Crash(BaseException):
        pass

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash()

    monkeypatch.setattr(engine, "finish_link", crash)
    with pytest.raises(Crash):
        engine.scan("tv", force=True)
    monkeypatch.setattr(engine, "finish_link", original)
    new = Path(next(s for s in engine.snapshot()["sources"] if s["id"] == row["id"])["target"])
    new.unlink()
    if replacement == "file":
        new.write_bytes(b"unrelated replacement")
    else:
        new.symlink_to(source / "Episode2.mkv")
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert old.exists()
    assert (
        next(s for s in engine.snapshot()["sources"] if s["id"] == row["id"])["import_status"]
        == "conflict"
    )


def test_series_scope_preview_and_stale_file_set(media):
    import_three(media)
    engine, source, _, _ = media
    row = engine.snapshot()["sources"][0]
    mapping = Mapping(
        media_type="tv",
        tmdb_id=42,
        original_title="Correct series",
        year=2022,
        season=1,
        episodes=[1],
    )
    preview = engine.series_preview(row["id"], mapping.model_dump())
    assert len(preview["manifest"]) == 3
    assert {i["mapping"]["season"] for i in preview["manifest"]} == {1, 2, 3}
    (source / "Episode1.mkv").write_bytes(b"replaced")
    with pytest.raises(ValueError, match="changed"):
        engine.series_apply(preview["preview_id"])
    assert not any(s["import_status"] == "reviewed" for s in engine.snapshot()["sources"])


def test_series_scope_saved_replans_every_season(media):
    import_three(media)
    engine, _, target, _ = media
    row = engine.snapshot()["sources"][0]
    mapping = Mapping(
        media_type="tv",
        tmdb_id=42,
        original_title="Correct series",
        year=2022,
        season=1,
        episodes=[1],
    )
    preview = engine.series_preview(row["id"], mapping.model_dump())
    engine.series_apply(preview["preview_id"])
    engine.scan("tv", force=True)
    assert len(list(target.rglob("*.mkv"))) == 3
    assert all("Correct series" in s["target"] for s in engine.snapshot()["sources"])


def test_shared_artifact_support_and_final_removal(media):
    engine, source, target, metadata = media
    (source / "Episode1.mkv").write_bytes(b"fixture")
    os.link(source / "Episode1.mkv", source / "Alias1.mkv")
    engine.config.profiles[0].max_missing_fraction = 1
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert len(engine.snapshot()["artifacts"]) == 1
    engine.config.reconcile_policy = "execute"
    (source / "Episode1.mkv").unlink()
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert len(list(target.rglob("*.mkv"))) == 1
    (source / "Alias1.mkv").unlink()
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert not list(target.rglob("*.mkv"))


def test_mass_disappearance_pauses_and_root_replacement_cannot_count(media):
    import_three(media)
    engine, source, target, _ = media
    engine.config.reconcile_policy = "execute"
    for path in source.glob("*.mkv"):
        path.unlink()
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert len(list(target.rglob("*.mkv"))) == 3
    assert all(a["status"] == "mass_review" for a in engine.snapshot()["cleanup"])
    old = source.with_name("detached")
    source.rename(old)
    source.mkdir()
    (source / ".media-volume").write_text("fixture")
    before = [s["missing_count"] for s in engine.snapshot()["sources"]]
    assert engine.scan("tv", force=True)["status"] == "failed"
    assert [s["missing_count"] for s in engine.snapshot()["sources"]] == before


def test_exdev_never_copies_or_symlinks(media, monkeypatch):
    import errno

    from seed_agent.media_import import filesystem as fs

    engine, source, target, _ = media
    (source / "Episode1.mkv").write_bytes(b"fixture")
    engine.scan("tv", force=True)

    def exdev(*args):
        raise OSError(errno.EXDEV, "cross-device hardlink blocked")

    monkeypatch.setattr(fs, "link", exdev)
    engine.scan("tv", force=True)
    assert not list(target.rglob("*.mkv"))
    assert engine.snapshot()["sources"][0]["import_status"] == "conflict"


def test_retirement_unlink_then_crash_is_idempotent(media, monkeypatch):
    from seed_agent.media_import import filesystem as fs

    import_three(media)
    engine, _, _, _ = media
    row = engine.snapshot()["sources"][0]
    old = Path(row["target"])
    mapping = Mapping(
        media_type="tv", tmdb_id=55, original_title="Correct", year=2023, season=1, episodes=[1]
    )
    engine.review(row["id"], mapping.model_dump(), fingerprint=row["fingerprint"], ready=True)
    original = fs.unlink

    class Crash(BaseException):
        pass

    def crash(root, path, receipt):
        original(root, path, receipt)
        if path == old:
            raise Crash()

    monkeypatch.setattr(fs, "unlink", crash)
    with pytest.raises(Crash):
        engine.scan("tv", force=True)
    monkeypatch.setattr(fs, "unlink", original)
    engine.scan("tv", force=True)
    assert not old.exists()
    assert (
        next(a for a in engine.snapshot()["artifacts"] if a["path"] == str(old))["status"]
        == "retired"
    )


def test_target_missing_requires_explicit_repair(media):
    import_three(media)
    engine, _, _, _ = media
    row = engine.snapshot()["sources"][0]
    target = Path(row["target"])
    target.unlink()
    engine.scan("tv", force=True)
    assert not target.exists()
    assert (
        next(s for s in engine.snapshot()["sources"] if s["id"] == row["id"])["import_status"]
        == "target_missing"
    )
    mapping = __import__("json").loads(row["mapping_json"])
    engine.review(row["id"], mapping, fingerprint=row["fingerprint"], ready=True, repair=True)
    engine.scan("tv", force=True)
    assert target.exists()


def test_source_replacement_invalidates_override_and_preserves_until_corrected(media):
    import_three(media)
    engine, source, target, _ = media
    row = engine.snapshot()["sources"][0]
    old = Path(row["target"])
    (source / row["path"]).unlink()
    (source / row["path"]).write_bytes(b"new replacement")
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    new = next(
        s for s in engine.snapshot()["sources"] if s["path"] == row["path"] and s["generation"] == 2
    )
    assert new["import_status"] == "review_required"
    assert old.exists()
    mapping = Mapping(
        media_type="tv", tmdb_id=55, original_title="Correct", year=2023, season=1, episodes=[1]
    )
    engine.review(new["id"], mapping.model_dump(), fingerprint=new["fingerprint"], ready=True)
    engine.scan("tv", force=True)
    assert not old.exists()
    assert len(list(target.rglob("*.mkv"))) == 3


def test_populated_media_state_backup_restore_includes_all_receipts(media):
    from seed_agent.media_import.maintenance import (
        backup_media_database,
        restore_media_database,
        verify_media_database,
    )

    import_three(media)
    engine, _, _, _ = media
    before = engine.snapshot()
    backup = engine.store.path.with_name("backup.db")
    assert backup_media_database(engine.store.path, backup)["valid"]
    with engine.store._connect() as conn:
        conn.execute("DELETE FROM media_artifact_sources")
    assert restore_media_database(engine.store.path, backup, execute=True)["status"] == "restored"
    assert engine.snapshot() == before
    assert verify_media_database(engine.store.path)["schema_version"] == 4


def test_partial_inventory_failure_never_publishes_missing(media, monkeypatch):
    import_three(media)
    engine, _, target, _ = media

    def partial(*args, **kwargs):
        yield args[0], [], []
        raise PermissionError("fixture traversal interrupted")

    monkeypatch.setattr(os, "walk", partial)
    assert engine.scan("tv", force=True)["status"] == "failed"
    assert all(s["missing_count"] == 0 for s in engine.snapshot()["sources"])
    assert len(list(target.rglob("*.mkv"))) == 3


def test_source_disappears_during_link_does_not_publish(media, monkeypatch):
    from seed_agent.media_import import filesystem as fs

    engine, source, target, _ = media
    path = source / "Episode1.mkv"
    path.write_bytes(b"fixture")
    engine.scan("tv", force=True)
    original = fs.link

    def disappearing(*args):
        original(*args)
        if str(args[-1]).find(".media-link-") >= 0:
            path.unlink()

    monkeypatch.setattr(fs, "link", disappearing)
    engine.scan("tv", force=True)
    monkeypatch.setattr(fs, "link", original)
    engine.scan("tv", force=True)
    assert not list(target.rglob("*.mkv"))
    assert not list(target.rglob(".media-link-*"))


def test_cleanup_unlink_then_database_crash_recovers(media, monkeypatch):
    from seed_agent.media_import import filesystem as fs

    import_three(media)
    engine, source, target, _ = media
    row = engine.snapshot()["sources"][0]
    path = Path(row["target"])
    (source / row["path"]).unlink()
    engine.scan("tv", force=True)
    engine.config.reconcile_policy = "execute"
    original = fs.unlink

    class Crash(BaseException):
        pass

    def crash(root, current, receipt):
        original(root, current, receipt)
        if current == path:
            raise Crash()

    monkeypatch.setattr(fs, "unlink", crash)
    with pytest.raises(Crash):
        engine.scan("tv", force=True)
    monkeypatch.setattr(fs, "unlink", original)
    engine.scan("tv", force=True)
    assert not path.exists()
    assert len(list(target.rglob("*.mkv"))) == 2
    assert (
        next(s for s in engine.snapshot()["sources"] if s["id"] == row["id"])["status"] == "removed"
    )


def test_excluded_incomplete_and_duration_do_not_invent_edition(media):
    engine, source, target, metadata = media
    directory = source / "incomplete"
    directory.mkdir()
    (directory / "Episode9.mkv").write_bytes(b"pending")
    (source / "Episode1.mkv").write_bytes(b"fixture")
    original = metadata.identify

    def identify(path, profile):
        mapping, candidates = original(path, profile)
        mapping.reference_duration = 1
        return mapping, candidates

    metadata.identify = identify
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    assert len(engine.snapshot()["sources"]) == 1
    assert all("{edition-" not in str(p) for p in target.rglob("*"))
    assert any(e["event"] == "possible_alternate_cut" for e in engine.snapshot()["events"])


@pytest.mark.parametrize("apply_intervening_review", [False, True])
def test_series_preview_cannot_overwrite_newer_episode_review(media, apply_intervening_review):
    import_three(media)
    engine, _, _, _ = media
    row = engine.snapshot()["sources"][0]
    mapping = __import__("json").loads(row["mapping_json"])
    mapping["original_title"] = "Series Fix"
    preview = engine.series_preview(row["id"], mapping)
    corrected = __import__("json").loads(row["mapping_json"])
    corrected["episodes"] = [99]
    engine.review(row["id"], corrected, fingerprint=row["fingerprint"], ready=True)
    if apply_intervening_review:
        engine.scan("tv", force=True)
    with pytest.raises(ValueError, match="mapping/revision changed"):
        engine.series_apply(preview["preview_id"])
    engine.scan("tv", force=True)
    assert next(s for s in engine.snapshot()["sources"] if s["id"] == row["id"])[
        "review_target"
    ].endswith("S01E99.mkv")


def test_series_preview_binds_naming_configuration(media):
    import_three(media)
    engine, _, _, _ = media
    row = engine.snapshot()["sources"][0]
    preview = engine.series_preview(row["id"], __import__("json").loads(row["mapping_json"]))
    engine.config.profiles[0].title_policy = "localized"
    with pytest.raises(ValueError, match="configuration changed"):
        engine.series_apply(preview["preview_id"])


def test_metadata_timeout_is_retryable_and_does_not_block_reconciliation(media):
    import httpx

    import_three(media)
    engine, source, target, metadata = media
    engine.config.reconcile_policy = "execute"
    (source / "Episode3.mkv").unlink()
    (source / "Episode4.mkv").write_bytes(b"new metadata lookup")
    original = metadata.identify

    def fail(path, profile):
        if path.name == "Episode4.mkv":
            raise httpx.ReadTimeout("synthetic metadata failure")
        return original(path, profile)

    metadata.identify = fail
    engine.scan("tv", force=True)
    engine.scan("tv", force=True)
    state = engine.snapshot()
    assert (
        next(s for s in state["sources"] if s["path"] == "Episode4.mkv")["import_status"]
        == "retrying"
    )
    assert next(s for s in state["sources"] if s["path"] == "Episode3.mkv")["status"] == "removed"
    assert len(list(target.rglob("*.mkv"))) == 2
