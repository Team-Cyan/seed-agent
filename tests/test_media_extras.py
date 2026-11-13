import json
import os
import sqlite3
from pathlib import Path

import pytest

from seed_agent.media_import import extras
from seed_agent.media_import import filesystem as fs
from seed_agent.media_import.config import MediaImportConfig, Profile
from seed_agent.media_import.engine import Engine
from seed_agent.media_import.extra_migration import migrate_schema4
from seed_agent.media_import.metadata import Mapping
from seed_agent.media_import.schema import SCHEMA
from seed_agent.media_import.store import CONTROL_SCHEMA, MediaStore


@pytest.fixture
def setup_extra(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for root in (source, target):
        (root / ".media-volume").write_text("fixture")
    profile = Profile(
        name="movies",
        source_root=str(source),
        target_root=str(target),
        marker_value="fixture",
        target_marker_value="fixture",
        media_type="movie",
        min_age_seconds=0,
        readiness="completed_folder",
        completed_contract_acknowledged=True,
    )

    class Metadata:
        def identify(self, path, profile):
            return Mapping(media_type="movie", tmdb_id=1, original_title="Film", year=2020), []

    engine = Engine(
        MediaStore(tmp_path / "state.db"),
        MediaImportConfig(enabled=True, profiles=[profile], import_policy="execute"),
        metadata=Metadata(),
        media_probe=lambda _: {"duration": 1000, "fps": 24, "streams": []},
    )
    (source / "Film.mkv").write_bytes(b"movie")
    engine.scan("movies", force=True)
    engine.scan("movies", force=True)
    parent = engine.snapshot()["sources"][0]["id"]
    return engine, source, target, parent


def add_source(engine, source, name):
    path = source / name
    path.write_bytes(b"extra-" + name.encode())
    sid = name
    with engine.store._connect() as conn:
        conn.execute(
            "INSERT INTO media_source_files(id,profile,path,generation,fingerprint,first_seen,"
            "last_seen,stable_count,status,original_release) VALUES(?,?,?,?,?,0,0,2,?,?)",
            (sid, "movies", name, 1, fs.fingerprint(path), "review_required", name),
        )
    return sid


def test_six_extras_publish_without_film_matching_or_subtitles(setup_extra):
    engine, source, target, parent = setup_extra
    assert extras.parents(engine, "Film") == [{"source_id": parent, "title": "Film", "year": 2020}]
    assert extras.parents(engine, "unmatched") == []
    with pytest.raises(ValueError):
        extras.parents(engine, "x" * 101)
    for n in range(6):
        sid = add_source(engine, source, f"extra{n}.mkv")
        preview = extras.preview(
            engine,
            {
                "source_id": sid,
                "parent_source_id": parent,
                "filename": f"Featurette {n}.mkv",
                "completion_confirmed": True,
            },
        )
        engine.process_source(engine.profile("movies"), {"id": sid})
        result = extras.execute(engine, preview["preview_id"])
        assert os.path.samefile(source / sid, result["target"])
        engine.process_source(engine.profile("movies"), {"id": sid})
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_extra_attachments WHERE status='published'"
            ).fetchone()[0]
            == 6
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_import_jobs WHERE source_id LIKE 'extra%'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_subtitle_jobs WHERE source_id LIKE 'extra%'"
            ).fetchone()[0]
            == 0
        )
    assert len(list(target.rglob("Featurette *.mkv"))) == 6
    assert engine.snapshot()["source_progress"]["extras"] == 6
    assert engine.snapshot()["source_progress"]["extras_by_status"] == {"published": 6}


def test_stale_source_and_unknown_target_preserved(setup_extra):
    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "extra.mkv")
    req = {
        "source_id": sid,
        "parent_source_id": parent,
        "filename": "Extra.mkv",
        "completion_confirmed": True,
    }
    preview = extras.preview(engine, req)
    (source / sid).write_bytes(b"changed")
    with pytest.raises(ValueError):
        extras.execute(engine, preview["preview_id"])
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_source_files SET fingerprint=? WHERE id=?",
            (fs.fingerprint(source / sid), sid),
        )
    sid = add_source(engine, source, "extra2.mkv")
    req["source_id"] = sid
    preview = extras.preview(engine, req)
    target = Path(preview["projection"]["target"])
    target.parent.mkdir()
    target.write_bytes(b"unknown")
    with pytest.raises(ValueError):
        extras.execute(engine, preview["preview_id"])
    assert target.read_bytes() == b"unknown"


def test_explicit_schema4_migration(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + CONTROL_SCHEMA)
        conn.execute("INSERT INTO media_control VALUES(1,'old',4)")
    with pytest.raises(ValueError, match="explicit migration"):
        MediaStore(path)
    with pytest.raises(ValueError, match="epoch changed"):
        migrate_schema4(path, expected_epoch="wrong")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT epoch,schema_version FROM media_control").fetchone() == (
            "old",
            4,
        )
    migrate_schema4(path, expected_epoch="old")
    store = MediaStore(path, initialize=False)
    assert store.epoch() != "old"
    with store._connect() as conn:
        assert conn.execute("SELECT schema_version FROM media_control").fetchone() == (5,)


@pytest.mark.parametrize("crash_call", [1, 2, 3])
def test_recovery_at_filesystem_boundaries(setup_extra, monkeypatch, crash_call):
    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "extra.mkv")
    preview = extras.preview(
        engine,
        {
            "source_id": sid,
            "parent_source_id": parent,
            "filename": "Extra.mkv",
            "completion_confirmed": True,
        },
    )
    link, unlink = engine._link, engine._unlink
    calls = 0

    def interrupt(operation):
        def run(*args, **kwargs):
            nonlocal calls
            result = operation(*args, **kwargs)
            calls += 1
            if calls == crash_call:
                raise OSError("simulated interruption after filesystem mutation")
            return result

        return run

    monkeypatch.setattr(engine, "_link", interrupt(link))
    monkeypatch.setattr(engine, "_unlink", interrupt(unlink))
    with pytest.raises(OSError):
        extras.execute(engine, preview["preview_id"])
    monkeypatch.setattr(engine, "_link", link)
    monkeypatch.setattr(engine, "_unlink", unlink)
    with engine.lease():
        extras.recover(engine, engine.profile("movies"))
    with engine.store._connect() as conn:
        status = conn.execute(
            "SELECT status FROM media_extra_attachments WHERE source_id=?", (sid,)
        ).fetchone()[0]
    assert status == ("conflict" if crash_call in (1, 2) else "published")
    if crash_call != 1:
        assert os.path.samefile(source / sid, preview["projection"]["target"])
    if crash_call == 3:
        assert not list(Path(preview["projection"]["target"]).parent.glob(".media-extra-*"))


def test_recovery_fences_changed_config(setup_extra, monkeypatch):
    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "extra.mkv")
    preview = extras.preview(
        engine,
        {
            "source_id": sid,
            "parent_source_id": parent,
            "filename": "Extra.mkv",
            "completion_confirmed": True,
        },
    )
    original = engine._link

    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("interrupted")

    monkeypatch.setattr(engine, "_link", interrupt)
    with pytest.raises(OSError):
        extras.execute(engine, preview["preview_id"])
    monkeypatch.setattr(engine, "_link", original)
    engine.config.work_batch_size += 1
    with engine.lease():
        extras.recover(engine, engine.profile("movies"))
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM media_extra_attachments WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == "conflict"
        )
    assert not Path(preview["projection"]["target"]).exists()


@pytest.mark.parametrize("case", ["queued", "running", "publication", "claim"])
def test_migration_rejects_active_work_without_mutation(tmp_path, case):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + CONTROL_SCHEMA)
        conn.execute("INSERT INTO media_control VALUES(1,'old',4)")
        if case in ("queued", "running"):
            conn.execute(
                "INSERT INTO media_commands(id,coalesce_key,action,payload_json,config_source,"
                "config_revision,epoch,modes_json,status,created) "
                "VALUES('id','key','scan','{}','source','rev','old','{}',?,1)",
                (case,),
            )
        elif case == "publication":
            conn.execute(
                "INSERT INTO media_publications VALUES('a','s','tmp','target','{}','pending')"
            )
        else:
            conn.execute(
                "INSERT INTO media_subtitle_jobs(id,source_id,generation,requirement,status,"
                "next_attempt,first_attempt,payload_json,claim_token) "
                "VALUES('j','s',1,'zh','running',0,0,'{}','claim')"
            )
        before = list(conn.iterdump())
    with pytest.raises(ValueError, match="active media work"):
        migrate_schema4(path)
    with sqlite3.connect(path) as conn:
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize("status", ["satisfied", "missing", "review_required"])
def test_migration_preserves_finished_subtitle_claim_fences(tmp_path, status):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + CONTROL_SCHEMA)
        conn.execute("INSERT INTO media_control VALUES(1,'old',4)")
        conn.execute(
            "INSERT INTO media_subtitle_jobs(id,source_id,generation,requirement,status,"
            "next_attempt,first_attempt,payload_json,claim_token) "
            "VALUES('j','s',1,'zh',?,0,0,'{}','retained-fence')",
            (status,),
        )
    migrate_schema4(path, expected_epoch="old")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status,claim_token FROM media_subtitle_jobs").fetchone() == (
            status,
            "retained-fence",
        )


def test_same_inode_manual_target_race_is_not_adopted(setup_extra, monkeypatch):
    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "extra.mkv")
    request = {
        "source_id": sid,
        "parent_source_id": parent,
        "filename": "Extra.mkv",
        "completion_confirmed": True,
    }
    preview = extras.preview(engine, request)
    target = Path(preview["projection"]["target"])
    original = engine._link

    def raced(*args, **kwargs):
        result = original(*args, **kwargs)
        if not target.exists():
            os.link(source / sid, target)
        return result

    monkeypatch.setattr(engine, "_link", raced)
    with pytest.raises(ValueError, match="occupied"):
        extras.execute(engine, preview["preview_id"])
    monkeypatch.setattr(engine, "_link", original)
    with engine.lease():
        extras.recover(engine, engine.profile("movies"))
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM media_extra_attachments WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == "conflict"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == 0
        )
    assert os.path.samefile(source / sid, target)


@pytest.mark.parametrize("stage", ["pending", "temporary", "linked", "cleanup"])
def test_recovery_after_recorded_database_stages(setup_extra, monkeypatch, stage):
    from seed_agent.media_import import roots

    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "extra.mkv")
    preview = extras.preview(
        engine,
        {
            "source_id": sid,
            "parent_source_id": parent,
            "filename": "Extra.mkv",
            "completion_confirmed": True,
        },
    )
    original_link, original_unlink, original_record = (
        engine._link,
        engine._unlink,
        roots.record_artifact,
    )
    calls = 0

    def link(*args, **kwargs):
        nonlocal calls
        calls += 1
        if (stage == "pending" and calls == 1) or (stage == "temporary" and calls == 2):
            raise OSError("before link")
        return original_link(*args, **kwargs)

    def record(*args, **kwargs):
        if stage == "linked":
            raise OSError("during artifact transaction")
        return original_record(*args, **kwargs)

    def unlink(*args, **kwargs):
        if stage == "cleanup":
            raise OSError("before cleanup")
        return original_unlink(*args, **kwargs)

    monkeypatch.setattr(engine, "_link", link)
    monkeypatch.setattr(engine, "_unlink", unlink)
    monkeypatch.setattr(roots, "record_artifact", record)
    with pytest.raises(OSError):
        extras.execute(engine, preview["preview_id"])
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM media_extra_attachments WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == stage
        )
    monkeypatch.setattr(engine, "_link", original_link)
    monkeypatch.setattr(engine, "_unlink", original_unlink)
    monkeypatch.setattr(roots, "record_artifact", original_record)
    with engine.lease():
        extras.recover(engine, engine.profile("movies"))
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM media_extra_attachments WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == "published"
        )
    assert os.path.samefile(source / sid, preview["projection"]["target"])


def test_same_inode_manual_temporary_is_not_adopted(setup_extra, monkeypatch):
    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "extra.mkv")
    preview = extras.preview(
        engine,
        {
            "source_id": sid,
            "parent_source_id": parent,
            "filename": "Extra.mkv",
            "completion_confirmed": True,
        },
    )
    original = engine._link

    def raced(*args, **kwargs):
        os.link(source / sid, args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "_link", raced)
    with pytest.raises(FileExistsError):
        extras.execute(engine, preview["preview_id"])
    monkeypatch.setattr(engine, "_link", original)
    with engine.lease():
        extras.recover(engine, engine.profile("movies"))
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM media_extra_attachments WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == "conflict"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_artifact_sources WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == 0
        )
    assert not Path(preview["projection"]["target"]).exists()


def test_idle_yields_to_new_queue_after_source_cursor_is_saved(setup_extra, monkeypatch):
    engine, source, _, _ = setup_extra
    add_source(engine, source, "a.mkv")
    add_source(engine, source, "b.mkv")
    processed = []

    def arrived(profile, item):
        processed.append(item["id"])
        with engine.store._connect() as conn:
            conn.execute(
                "INSERT INTO media_commands(id,coalesce_key,action,payload_json,config_source,"
                "config_revision,epoch,modes_json,status,created) "
                "VALUES('queued','k','scan','{}','s','r','e','{}','queued',0)"
            )

    monkeypatch.setattr(engine, "process_source", arrived)

    def queued():
        with engine.store._connect() as conn:
            return bool(
                conn.execute("SELECT 1 FROM media_commands WHERE status='queued'").fetchone()
            )

    with engine.lease():
        assert engine.process_pending(engine.profile("movies"), should_yield=queued)
    assert len(processed) == 1
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT source_id FROM media_work_cursor WHERE profile='movies'"
            ).fetchone()[0]
            == processed[0]
        )
        conn.execute("UPDATE media_commands SET status='complete' WHERE id='queued'")
    monkeypatch.setattr(
        engine, "process_source", lambda profile, item: processed.append(item["id"])
    )
    with engine.lease():
        engine.process_pending(engine.profile("movies"), should_yield=queued)
    assert processed[1] != processed[0]


def test_idle_yields_only_after_complete_inventory_commit(setup_extra):
    engine, source, _, _ = setup_extra
    (source / "new.mkv").write_bytes(b"new")
    result = engine.scan("movies", force=True, should_yield=lambda: True)
    assert result["status"] == "yielded"
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT status FROM media_scan_runs WHERE id=?", (result["run_id"],)
            ).fetchone()[0]
            == "complete"
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM media_source_files WHERE path='new.mkv'").fetchone()[
                0
            ]
            == 1
        )


def test_variant_switch_preserves_sources_and_retires_only_owned_video(setup_extra):
    from seed_agent.media_import import variants

    engine, source, _, parent = setup_extra
    sid = add_source(engine, source, "variant.mkv")
    with engine.store._connect() as conn:
        mapping = conn.execute(
            "SELECT mapping_json FROM media_import_jobs WHERE source_id=?", (parent,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO media_import_jobs VALUES(?,1,'planned',?,NULL,NULL,0)", (sid, mapping)
        )
        old_target = Path(
            conn.execute(
                "SELECT target FROM media_import_jobs WHERE source_id=?", (parent,)
            ).fetchone()[0]
        )
    unknown = old_target.parent / "manual.srt"
    unknown.write_text("manual")
    plan = variants.preview(engine, parent, sid, completion_confirmed=True)
    result = variants.execute(engine, plan["preview_id"])
    assert os.path.samefile(source / sid, result["target"])
    assert (source / "Film.mkv").exists() and (source / sid).exists()
    assert not old_target.exists() and unknown.read_text() == "manual"
    assert ".source-" in Path(result["target"]).name
    with engine.store._connect() as conn:
        assert conn.execute(
            "SELECT source_id,revision FROM media_variant_selections"
        ).fetchone() == (sid, 2)
        assert (
            conn.execute("SELECT status FROM media_source_files WHERE id=?", (parent,)).fetchone()[
                0
            ]
            == "retained_not_selected"
        )
        assert conn.execute("SELECT status FROM media_variant_switches").fetchone()[0] == "done"


def setup_variant(engine, source, parent):
    sid = add_source(engine, source, "variant.mkv")
    with engine.store._connect() as conn:
        mapping = conn.execute(
            "SELECT mapping_json FROM media_import_jobs WHERE source_id=?", (parent,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO media_import_jobs VALUES(?,1,'planned',?,NULL,NULL,0)", (sid, mapping)
        )
    return sid


def test_variant_can_switch_back(setup_extra):
    from seed_agent.media_import import variants

    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    first = variants.preview(engine, parent, sid, completion_confirmed=True)
    variants.execute(engine, first["preview_id"])
    second = variants.preview(engine, sid, parent, completion_confirmed=True)
    result = variants.execute(engine, second["preview_id"])
    assert os.path.samefile(source / "Film.mkv", result["target"])
    with engine.store._connect() as conn:
        assert conn.execute(
            "SELECT source_id,revision FROM media_variant_selections"
        ).fetchone() == (parent, 3)
        assert (
            conn.execute("SELECT status FROM media_source_files WHERE id=?", (sid,)).fetchone()[0]
            == "retained_not_selected"
        )


@pytest.mark.parametrize(
    "kind,call",
    [("link", 1), ("link", 2), ("link", 3), ("unlink", 1), ("unlink", 2), ("unlink", 3)],
)
def test_variant_recovery_at_filesystem_boundaries(setup_extra, monkeypatch, kind, call):
    from seed_agent.media_import import variants

    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    preview = variants.preview(engine, parent, sid, completion_confirmed=True)
    original = engine._link if kind == "link" else engine._unlink
    count = 0

    def interrupt(*args, **kwargs):
        nonlocal count
        result = original(*args, **kwargs)
        count += 1
        if count == call:
            raise OSError("interrupted after mutation")
        return result

    monkeypatch.setattr(engine, "_" + kind, interrupt)
    with pytest.raises(OSError):
        variants.execute(engine, preview["preview_id"])
    monkeypatch.setattr(engine, "_" + kind, original)
    with engine.lease():
        variants.recover(engine)
    with engine.store._connect() as conn:
        state = conn.execute("SELECT status FROM media_variant_switches").fetchone()[0]
    assert state == ("conflict" if kind == "link" else "done")
    assert (source / "Film.mkv").exists() and (source / sid).exists()


def test_variant_fences_late_subtitle_and_retires_owned_sidecar(setup_extra):
    from seed_agent.media_import import variants
    from seed_agent.media_import.engine import encode

    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    with engine.store._connect() as conn:
        old = Path(
            conn.execute(
                "SELECT target FROM media_import_jobs WHERE source_id=?", (parent,)
            ).fetchone()[0]
        )
        descriptor = conn.execute(
            "SELECT descriptor_json FROM media_artifact_roots r "
            "JOIN media_artifact_sources s ON s.artifact_id=r.artifact_id WHERE s.source_id=?",
            (parent,),
        ).fetchone()[0]
        subtitle = old.with_suffix(".zh.srt")
        subtitle.write_text("owned subtitle")
        receipt = fs.receipt(Path(json.loads(descriptor)["root"]), subtitle, digest=True)
        conn.execute(
            "INSERT INTO media_artifacts VALUES('sub',?,'movies','subtitle',1,'active',?,0)",
            (str(subtitle), encode(receipt)),
        )
        conn.execute("INSERT INTO media_artifact_roots VALUES('sub',?)", (descriptor,))
        conn.execute("INSERT INTO media_artifact_sources VALUES('sub',?)", (parent,))
        conn.execute(
            "INSERT INTO media_subtitle_jobs(id,source_id,generation,requirement,status,"
            "next_attempt,first_attempt,payload_json,claim_token) "
            "VALUES('job',?,1,'zh','running',0,0,'{}','oldclaim')",
            (parent,),
        )
    preview = variants.preview(engine, parent, sid, completion_confirmed=True)
    with engine.store._connect() as conn:
        before = engine.publication_fence(conn, parent)
    variants.execute(engine, preview["preview_id"])
    assert not subtitle.exists()
    with engine.store._connect() as conn:
        assert engine.publication_fence(conn, parent) != before
        assert tuple(
            conn.execute(
                "SELECT status,claim_token FROM media_subtitle_jobs WHERE id='job'"
            ).fetchone()
        ) == ("cancelled", None)


def test_variant_unknown_same_inode_target_and_stale_source_are_preserved(setup_extra):
    from seed_agent.media_import import variants

    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    plan = variants.preview(engine, parent, sid, completion_confirmed=True)
    target = Path(plan["projection"]["target"])
    os.link(source / sid, target)
    with pytest.raises(ValueError, match="unknown variant"):
        variants.execute(engine, plan["preview_id"])
    assert os.path.samefile(source / sid, target)
    with engine.store._connect() as conn:
        assert (
            conn.execute("SELECT source_id FROM media_variant_selections").fetchone()[0] == parent
        )


def test_backup_validation_rejects_stale_and_accepts_exact(tmp_path):
    import hashlib
    import shutil

    path, backup = tmp_path / "old.db", tmp_path / "backup.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + CONTROL_SCHEMA)
        conn.execute("INSERT INTO media_control VALUES(1,'old',4)")
    shutil.copyfile(path, backup)
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO media_output_exclusions VALUES('/changed')")
    with pytest.raises(ValueError, match="logical contents differ"):
        migrate_schema4(path, expected_epoch="old", backup=backup, expected_backup_sha256=digest)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT epoch,schema_version FROM media_control").fetchone() == (
            "old",
            4,
        )
        conn.execute("DELETE FROM media_output_exclusions")
    with pytest.raises(ValueError, match="SHA-256"):
        migrate_schema4(path, expected_epoch="old", backup=backup, expected_backup_sha256="0" * 64)
    migrate_schema4(path, expected_epoch="old", backup=backup, expected_backup_sha256=digest)
    assert MediaStore(path, initialize=False).epoch() != "old"


@pytest.mark.parametrize(
    "extra_schema",
    [
        "CREATE VIEW unexpected AS SELECT * FROM media_control",
        "CREATE TRIGGER unexpected AFTER INSERT ON media_output_exclusions BEGIN SELECT 1; END",
    ],
)
def test_backup_rejects_views_and_triggers_without_changing_current(tmp_path, extra_schema):
    import hashlib
    import shutil

    path, backup = tmp_path / "old.db", tmp_path / "backup.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + CONTROL_SCHEMA)
        conn.execute("INSERT INTO media_control VALUES(1,'old',4)")
    shutil.copyfile(path, backup)
    with sqlite3.connect(backup) as saved:
        saved.execute(extra_schema)
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="backup views/triggers"):
        migrate_schema4(path, expected_epoch="old", backup=backup, expected_backup_sha256=digest)
    assert path.read_bytes() == before


def test_variant_confirmation_sets_only_selected_source_readiness(setup_extra):
    from seed_agent.media_import import variants

    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_source_files SET readiness='completion_unverified' WHERE id=?", (sid,)
        )
    plan = variants.preview(engine, parent, sid, completion_confirmed=True)
    variants.execute(engine, plan["preview_id"])
    with engine.store._connect() as conn:
        assert (
            conn.execute("SELECT readiness FROM media_source_files WHERE id=?", (sid,)).fetchone()[
                0
            ]
            == "operator"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_events WHERE source_id=? "
                "AND event='variant_completion_confirmed'",
                (sid,),
            ).fetchone()[0]
            == 1
        )
    assert (
        next(x for x in engine.snapshot()["sources"] if x["id"] == sid)["progress_reason"]
        == "imported"
    )


def test_late_subtitle_and_poster_responses_are_rejected(setup_extra, monkeypatch):
    from seed_agent.media_import import artwork, variants
    from seed_agent.media_import.subtitles.jobs import SubtitleJobs
    from seed_agent.media_import.subtitles.provider import Candidate

    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    with engine.store._connect(row_factory=sqlite3.Row) as conn:
        old = dict(
            conn.execute(
                "SELECT s.*,j.revision,j.target,j.mapping_json FROM media_source_files s "
                "JOIN media_import_jobs j ON j.source_id=s.id WHERE s.id=?",
                (parent,),
            ).fetchone()
        )
        conn.execute(
            "INSERT INTO media_subtitle_jobs(id,source_id,generation,requirement,status,"
            "next_attempt,first_attempt,payload_json,claim_token,plan_revision,target) "
            "VALUES('late',?,1,'zh','running',0,0,'{}','token',?,?)",
            (parent, old["revision"], old["target"]),
        )
    plan = variants.preview(engine, parent, sid, completion_confirmed=True)
    with engine.store._connect() as conn:
        fence = engine.publication_fence(conn, parent)
    profile = engine.for_plan(engine.profile(old["profile"]), parent)
    job = {
        "id": "late",
        "source_id": parent,
        "profile": old["profile"],
        "claim_token": "token",
        "generation": old["generation"],
        "target": old["target"],
        "plan_revision": old["revision"],
        "fingerprint": old["fingerprint"],
    }
    variants.execute(engine, plan["preview_id"])
    with pytest.raises(ValueError, match="fenced"):
        SubtitleJobs(engine).publish(
            job, Candidate(id="late", language="zh", provider="fixture"), b"payload", "srt"
        )
    monkeypatch.setattr(artwork, "normalize_image", lambda payload, ext: (b"image", ".jpg"))
    target = Path(old["target"]).parent / "poster.jpg"
    mapping = json.loads(old["mapping_json"])
    with pytest.raises(ValueError, match="supporting source"):
        artwork.PosterJobs(engine, None).publish(
            profile,
            old,
            mapping,
            [old],
            target,
            b"image",
            {
                "provider": "tmdb",
                "tmdb_id": mapping["tmdb_id"],
                "media_type": mapping["media_type"],
            },
            fences={parent: fence},
        )
    assert not target.exists()


@pytest.mark.parametrize("change", ["config", "epoch", "source", "root"])
def test_variant_switch_rejects_stale_baselines(setup_extra, change):
    from seed_agent.media_import import variants

    engine, source, target, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    plan = variants.preview(engine, parent, sid, completion_confirmed=True)
    if change == "config":
        engine.config.work_batch_size += 1
    elif change == "epoch":
        with engine.store._connect() as conn:
            conn.execute("UPDATE media_control SET epoch='different'")
    elif change == "source":
        (source / sid).write_bytes(b"changed")
    else:
        target.rename(target.with_name("old-target"))
        target.mkdir()
        (target / ".media-volume").write_text("fixture")
    with pytest.raises((ValueError, OSError)):
        variants.execute(engine, plan["preview_id"])
    with engine.store._connect() as conn:
        assert (
            conn.execute("SELECT source_id FROM media_variant_selections").fetchone()[0] == parent
        )
    assert (source / "Film.mkv").exists() and (source / sid).exists()


def test_completion_confirmation_without_mapping_or_provider(setup_extra, monkeypatch):
    from seed_agent.media_import.completion import confirm

    engine, source, _, _ = setup_extra
    engine.config.profiles[0].readiness = "manual"
    sid = add_source(engine, source, "unknown.mkv")
    fingerprint = fs.fingerprint(source / sid)
    calls = []
    original = engine.metadata.identify
    monkeypatch.setattr(
        engine.metadata, "identify", lambda *args: (calls.append(1), original(*args))[1]
    )
    result = confirm(engine, sid, 1, fingerprint, completion_confirmed=True)
    assert result["readiness"] == "operator" and not calls
    with engine.store._connect(row_factory=sqlite3.Row) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_import_jobs WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == 0
        )
        row = dict(conn.execute("SELECT * FROM media_source_files WHERE id=?", (sid,)).fetchone())
    engine.process_source(engine.profile("movies"), row)
    assert calls == [1]


def test_completion_rejects_unstable_and_replaced_source(setup_extra):
    from seed_agent.media_import.completion import confirm

    engine, source, _, _ = setup_extra
    sid = add_source(engine, source, "unknown.mkv")
    fingerprint = fs.fingerprint(source / sid)
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_source_files SET stable_count=1 WHERE id=?", (sid,))
    with pytest.raises(ValueError, match="unstable"):
        confirm(engine, sid, 1, fingerprint, completion_confirmed=True)
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_source_files SET stable_count=2 WHERE id=?", (sid,))
    (source / sid).write_bytes(b"replaced")
    with pytest.raises(ValueError, match="fingerprint"):
        confirm(engine, sid, 1, fingerprint, completion_confirmed=True)
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM media_completion_reviews WHERE source_id=?", (sid,)
            ).fetchone()[0]
            == 0
        )


def test_completion_fact_not_inherited_by_new_generation(setup_extra, monkeypatch):
    from seed_agent.media_import.completion import confirm

    engine, source, _, _ = setup_extra
    engine.config.profiles[0].readiness = "manual"
    sid = add_source(engine, source, "unknown.mkv")
    confirm(engine, sid, 1, fs.fingerprint(source / sid), completion_confirmed=True)
    (source / sid).write_bytes(b"new generation")
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_source_files SET status='changed' WHERE id=?", (sid,))
        conn.execute(
            "INSERT INTO media_source_files(id,profile,path,generation,fingerprint,first_seen,"
            "last_seen,stable_count,status,original_release) "
            "VALUES('new','movies',?,2,?,0,0,2,'ready',?)",
            (sid, fs.fingerprint(source / sid), sid),
        )
    monkeypatch.setattr(
        engine.metadata, "identify", lambda *args: pytest.fail("completion must not transfer")
    )
    with engine.store._connect(row_factory=sqlite3.Row) as conn:
        current = dict(conn.execute("SELECT * FROM media_source_files WHERE id='new'").fetchone())
    engine.process_source(engine.profile("movies"), current)
    with engine.store._connect() as conn:
        assert (
            conn.execute("SELECT readiness FROM media_source_files WHERE id='new'").fetchone()[0]
            == "completion_unverified"
        )
