import json
import sqlite3
from pathlib import Path

import pytest
import yaml
from test_media_import import import_three
from test_media_import import media as media
from test_media_runtime import media_config

from seed_agent.config import atomic_write_text, load_config
from seed_agent.config_views import MediaConfigGuard, load_view
from seed_agent.maintenance import backup_sqlite_database, restore_sqlite_database
from seed_agent.media_import.maintenance import backup_media_database, restore_media_database
from seed_agent.media_import.migration import export_snapshot, import_snapshot
from seed_agent.media_import.store import MediaStore, bounded_lock
from seed_agent.state import StateStore


def test_seed_ignores_invalid_media_and_media_ignores_invalid_seed(tmp_path):
    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["media_import"] = {"profiles": "invalid no mounts"}
    config.write_text(yaml.safe_dump(raw))
    assert load_config(config).download_client is None
    with pytest.raises(ValueError):
        load_view(config, "media")
    raw["media_import"] = {"enabled": False}
    raw["download_client"] = {"invalid": "own seed section"}
    config.write_text(yaml.safe_dump(raw))
    assert not load_view(config, "media").config.media_import.enabled
    with pytest.raises(ValueError):
        load_config(config)


def test_revision_atomic_replacement_and_no_secret_value_digests(tmp_path):
    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["deployment"] = {"source_id": "fixture-deployment"}
    raw["media_import"]["opensubtitles_secret_ref"] = "local/secrets/subtitles.json"
    secrets = tmp_path / "local" / "secrets"
    secrets.mkdir(parents=True)
    secret = secrets / "subtitles.json"
    secret.write_text(json.dumps({"password": "first-private-value"}))
    atomic_write_text(config, yaml.safe_dump(raw))
    before = load_view(config, "media", require_identity=True)
    secret.write_text(json.dumps({"password": "second-private-value"}))
    after = load_view(config, "media", require_identity=True)
    assert before.full_revision == after.full_revision
    assert "private-value" not in json.dumps(after.observation())
    raw["pt_scoring"]["min_score_to_enqueue"] = 99
    atomic_write_text(config, yaml.safe_dump(raw))
    tracker_edit = load_view(config, "media")
    assert tracker_edit.full_revision != before.full_revision
    assert tracker_edit.effective_revision == before.effective_revision
    raw["media_import"]["interval_seconds"] = 77
    atomic_write_text(config, yaml.safe_dump(raw))
    assert load_view(config, "media").effective_revision != before.effective_revision


def test_worker_requires_explicit_config_source_and_invalid_schema_fails_common(tmp_path):
    config, _, _ = media_config(tmp_path)
    with pytest.raises(ValueError, match="source_id"):
        load_view(config, "media", require_identity=True)
    raw = yaml.safe_load(config.read_text())
    raw["deployment"] = {"source_id": "fixture", "schema_version": 99}
    config.write_text(yaml.safe_dump(raw))
    for role in ["seed", "media"]:
        with pytest.raises(ValueError):
            load_view(config, role)


def test_publication_guard_revocation_and_preview_never_upgrades(tmp_path):
    config, _, _ = media_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    raw["media_import"]["subtitle_policy"] = "execute"
    atomic_write_text(config, yaml.safe_dump(raw))
    view = load_view(config, "media")
    guard = MediaConfigGuard(view)
    guard.check("subtitle")
    raw["media_import"]["subtitle_policy"] = "preview"
    atomic_write_text(config, yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="rejected"):
        guard.check("subtitle")
    preview = MediaConfigGuard(load_view(config, "media"))
    raw["media_import"]["subtitle_policy"] = "execute"
    atomic_write_text(config, yaml.safe_dump(raw))
    with pytest.raises(ValueError):
        preview.check("subtitle")
    config.unlink()
    with pytest.raises(ValueError):
        guard.check("subtitle")


def test_seed_initialization_and_restore_never_touch_media_locks(tmp_path):
    seed = StateStore(tmp_path / "seed.db")
    media = MediaStore(tmp_path / "media.db")
    with seed._connect() as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'media_%'"
        ).fetchall()
    backup = tmp_path / "seed-backup.db"
    assert backup_sqlite_database(seed.path, backup)["valid"]
    with (
        bounded_lock(Path(str(media.path) + ".media.lock"), exclusive=True),
        bounded_lock(Path(str(media.path) + ".access.lock"), exclusive=True),
    ):
        seed.acquire_scheduler_lease("fixture")
        seed.release_scheduler_lease("fixture")
        assert restore_sqlite_database(seed.path, backup, execute=True)["status"] == "restored"
    assert not Path(str(seed.path) + ".media.lock").exists()


def test_media_backup_restore_has_own_epoch_and_seed_is_irrelevant(tmp_path):
    media = MediaStore(tmp_path / "media.db")
    seed = StateStore(tmp_path / "seed.db")
    before = media.epoch()
    backup = tmp_path / "media-backup.db"
    assert backup_media_database(media.path, backup)["valid"]
    with bounded_lock(Path(str(seed.path) + ".access.lock"), exclusive=True):
        assert restore_media_database(media.path, backup, execute=True)["status"] == "restored"
    assert media.epoch() != before
    with pytest.raises(ValueError, match="non-media"):
        MediaStore(seed.path)


def test_explicit_migration_preview_idempotent_and_original_preserved(media, tmp_path):
    import_three(media)
    engine, _, _, _ = media
    export = tmp_path / "export.json"
    target = tmp_path / "independent.db"
    profiles = engine.config.profiles
    before = engine.snapshot()
    result = export_snapshot(engine.store.path, profiles)
    assert result["status"] == "preview" and not export.exists() and not target.exists()
    export_snapshot(engine.store.path, profiles, output=export)
    assert import_snapshot(export, target, profiles)["status"] == "preview"
    assert not target.exists()
    assert import_snapshot(export, target, profiles, execute=True)["status"] == "imported"
    assert import_snapshot(export, target, profiles, execute=True)["status"] == "already_imported"
    with MediaStore(target)._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_artifacts").fetchone()[0] == 3
    assert engine.snapshot() == before


def test_migration_rejects_changed_owned_receipts_and_bad_manifest(media, tmp_path):
    import_three(media)
    engine, _, _, _ = media
    export = tmp_path / "export.json"
    profiles = engine.config.profiles
    export_snapshot(engine.store.path, profiles, output=export)
    wrapper = json.loads(export.read_text())
    wrapper["payload"]["counts"]["media_artifacts"] = 999
    export.write_text(json.dumps(wrapper))
    with pytest.raises(ValueError, match="digest"):
        import_snapshot(export, tmp_path / "new.db", profiles)
    row = engine.snapshot()["artifacts"][0]
    Path(row["path"]).unlink()
    Path(row["path"]).write_bytes(b"replacement")
    with pytest.raises(ValueError, match="receipt"):
        export_snapshot(engine.store.path, profiles)


def test_export_import_legacy_shared_seed_database_without_mutating_it(media, tmp_path):
    from seed_agent.media_import.migration import table_columns
    from seed_agent.media_import.schema import SCHEMA

    import_three(media)
    engine, _, _, _ = media
    legacy = StateStore(tmp_path / "legacy-seed.db")
    with engine.store._connect() as source, legacy._connect() as target:
        target.executescript(SCHEMA)
        for table, columns in table_columns().items():
            target.execute(f'DELETE FROM "{table}"')
            records = source.execute(f'SELECT * FROM "{table}"').fetchall()
            if records:
                target.executemany(
                    f'INSERT INTO "{table}" VALUES(' + ",".join("?" for _ in columns) + ")", records
                )
    export = tmp_path / "legacy-export.json"
    export_snapshot(legacy.path, engine.config.profiles, output=export)
    result = import_snapshot(
        export, tmp_path / "new-media.db", engine.config.profiles, execute=True
    )
    assert result["counts"]["media_artifacts"] == 3
    with legacy._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_artifacts").fetchone()[0] == 3
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='candidates'").fetchone()


def test_migration_interruption_rolls_back_and_retry_is_safe(media, tmp_path, monkeypatch):
    from contextlib import contextmanager

    import_three(media)
    engine, _, _, _ = media
    export = tmp_path / "migration-export.json"
    target = tmp_path / "new-media.db"
    export_snapshot(engine.store.path, engine.config.profiles, output=export)
    original = MediaStore._connect

    class FailInsert:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def executemany(self, sql, values):
            if "media_import_jobs" in sql:
                raise sqlite3.OperationalError("fixture interruption")
            return self.conn.executemany(sql, values)

    @contextmanager
    def connect(self, **kwargs):
        with original(self, **kwargs) as conn:
            yield FailInsert(conn) if self.path == target and not self._initializing else conn

    monkeypatch.setattr(MediaStore, "_connect", connect)
    with pytest.raises(sqlite3.OperationalError):
        import_snapshot(export, target, engine.config.profiles, execute=True)
    monkeypatch.setattr(MediaStore, "_connect", original)
    with MediaStore(target)._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_artifacts").fetchone()[0] == 0
    assert (
        import_snapshot(export, target, engine.config.profiles, execute=True)["status"]
        == "imported"
    )


def test_media_schema_inventory_matches_independent_store(tmp_path):
    from test_state_schema_inventory import _documented_sqlite_tables

    documented = _documented_sqlite_tables(Path("docs/operations/media-state-schema.md"))
    with MediaStore(tmp_path / "media.db")._connect() as conn:
        actual = {
            r[0]: [c[1] for c in conn.execute("PRAGMA table_info(" + r[0] + ")")]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert documented == actual


def test_seed_backup_preserves_exact_legacy_media_tables_but_rejects_modified(tmp_path):
    from seed_agent.maintenance import verify_sqlite_database
    from seed_agent.media_import.schema import SCHEMA

    seed = StateStore(tmp_path / "legacy.db")
    with seed._connect() as conn:
        conn.executescript(SCHEMA)
    backup = tmp_path / "legacy-backup.db"
    assert backup_sqlite_database(seed.path, backup)["valid"]
    assert restore_sqlite_database(seed.path, backup, execute=True)["status"] == "restored"
    with seed._connect() as conn:
        conn.execute("ALTER TABLE media_source_files ADD COLUMN unexpected TEXT")
    assert not verify_sqlite_database(seed.path)["valid"]


def test_applied_media_observation_contains_revision_and_restore_epoch(tmp_path):
    config, _, _ = media_config(tmp_path)
    view = load_view(config, "media")
    store = MediaStore(tmp_path / "applied.db")
    status = store.record_applied(view)
    assert status == store.applied_status()
    assert status["applied_revision"] == view.effective_revision
    assert status["state_epoch"] == store.epoch()
    assert status["role"] == "media"


def test_legacy_output_config_roundtrips_web_and_fences_worker_writes(tmp_path):
    from test_media_source_routing import mixed_engine

    from seed_agent.web.settings import (
        ConfigSectionDraft,
        config_revision,
        config_sections_payload,
        save_config_section,
    )

    engine, source, _, _ = mixed_engine(tmp_path)
    legacy = str(Path(source.root) / "Movies")
    source.legacy_output_roots = [legacy]
    config = tmp_path / "config.yaml"
    from test_web_settings import _write_minimal_config

    raw = yaml.safe_load(_write_minimal_config(tmp_path).read_text())
    raw.update(deployment={"source_id": "Media"}, media_import=engine.config.model_dump())
    config.write_text(yaml.safe_dump(raw))
    before = load_view(config, "media", require_identity=True)
    from seed_agent.media_import.runtime import build_engine

    with pytest.raises(FileNotFoundError):
        build_engine(config)
    assert not (tmp_path / ".media-import/state.db").exists()
    guard = MediaConfigGuard(before)
    section = config_sections_payload(load_config(config))["media_import"]
    assert section["sources"][0]["legacy_output_roots"] == [legacy]
    saved = save_config_section(
        config,
        ConfigSectionDraft(section="media_import", data=section, revision=config_revision(config)),
    )
    assert saved["sources"][0]["legacy_output_roots"] == [legacy]
    assert load_view(config, "media").effective_revision == before.effective_revision
    guard.check("import")
    section["sources"][0]["legacy_output_roots"].append(str(Path(source.root) / "TV"))
    save_config_section(
        config,
        ConfigSectionDraft(section="media_import", data=section, revision=config_revision(config)),
    )
    assert load_view(config, "media").effective_revision != before.effective_revision
    with pytest.raises(ValueError, match="rejected"):
        guard.check("import")
