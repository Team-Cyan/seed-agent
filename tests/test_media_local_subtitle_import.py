import hashlib
import os
from types import SimpleNamespace

import pytest
from test_media_import import media as media
from test_media_subtitles import PAYLOAD, import_three

from seed_agent.media_import.subtitles.local_import import LocalSubtitleImport


def stage(engine, data):
    digest = hashlib.sha256(data).hexdigest()
    inbox = engine.store.path.parent / "subtitle-inbox"
    inbox.mkdir(exist_ok=True)
    (inbox / f"{digest}.srt").write_bytes(data)
    return digest


@pytest.fixture
def local(media):
    import_three(media)
    engine, _, target, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config_view = SimpleNamespace(effective_revision="a" * 64)
    source = engine.snapshot()["sources"][0]
    digest = stage(engine, PAYLOAD)
    request = {
        "source_id": source["id"],
        "generation": source["generation"],
        "fingerprint": source["fingerprint"],
        "payload_sha256": digest,
        "language": "zh-Hans",
        "kind": "full",
        "provenance": {
            "provider": "manual",
            "reference": "fixture",
            "original_sha256": digest,
            "transformation": {"kind": "none"},
        },
    }
    return engine, target, LocalSubtitleImport(engine), request


def approval(request, preview):
    return {**request, "preview_id": preview["preview_id"], "compatibility_acknowledged": True}


def test_preview_publish_deduplicate_and_cap(local):
    engine, target, importer, request = local
    preview = importer.run(request)
    assert preview["status"] == "preview" and not preview["published"]
    assert not list(target.rglob("*.srt"))
    result = importer.run(approval(request, preview), execute=True)
    assert result["status"] == "published" and len(list(target.rglob("*.srt"))) == 1
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM media_artifacts a JOIN media_artifact_sources r "
                "ON a.id=r.artifact_id WHERE a.kind='subtitle' AND a.owned=1 "
                "AND a.status='active' AND r.source_id=?",
                (request["source_id"],),
            ).fetchone()[0]
            == 1
        )
    assert importer.run(approval(request, preview), execute=True)["status"] == "already_present"
    engine.config.profiles[0].max_subtitles = 1
    second = stage(engine, PAYLOAD + b"different\n")
    new = {
        **request,
        "payload_sha256": second,
        "provenance": {**request["provenance"], "original_sha256": second},
    }
    reviewed = importer.run(new)
    assert importer.run(approval(new, reviewed), execute=True)["status"] == "limit_reached"
    assert len(list(target.rglob("*.srt"))) == 1


def test_preview_and_explicit_approval_required(local):
    engine, target, importer, request = local
    with pytest.raises(ValueError, match="preview"):
        importer.run(request, execute=True)
    preview = importer.run(request)
    with pytest.raises(ValueError, match="acknowledgment"):
        importer.run({**request, "preview_id": preview["preview_id"]}, execute=True)
    with pytest.raises(ValueError, match="preview"):
        importer.run(
            {**approval(request, preview), "preview_id": preview["preview_id"] + 100}, execute=True
        )
    engine.config.subtitle_policy = "preview"
    with pytest.raises(ValueError, match="policy"):
        importer.run(approval(request, preview), execute=True)
    assert not list(target.rglob("*.srt"))


@pytest.mark.parametrize(
    "change", ["generation", "fingerprint", "revision", "target", "epoch", "config"]
)
def test_preview_binding_rejects_changed_baseline(local, change):
    engine, target, importer, request = local
    preview = importer.run(request)
    if change in {"generation", "fingerprint"}:
        with engine.store._connect() as conn:
            if change == "generation":
                conn.execute(
                    "UPDATE media_source_files SET generation=generation+1 WHERE id=?",
                    (request["source_id"],),
                )
            else:
                conn.execute(
                    "UPDATE media_source_files SET fingerprint='[1,2,3,4]' WHERE id=?",
                    (request["source_id"],),
                )
    elif change in {"revision", "target"}:
        with engine.store._connect() as conn:
            if change == "revision":
                conn.execute(
                    "UPDATE media_import_jobs SET revision=revision+1 WHERE source_id=?",
                    (request["source_id"],),
                )
            else:
                conn.execute(
                    "UPDATE media_import_jobs SET target=target || '.changed' WHERE source_id=?",
                    (request["source_id"],),
                )
    elif change == "epoch":
        engine.store_epoch = "changed"
    else:
        engine.config_view.effective_revision = "b" * 64
    with pytest.raises((ValueError, OSError)):
        importer.run(approval(request, preview), execute=True)
    assert not list(target.rglob("*.srt"))


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hash", "archive"])
def test_reject_unsafe_staged_input(local, kind):
    engine, target, importer, request = local
    path = engine.store.path.parent / "subtitle-inbox" / (request["payload_sha256"] + ".srt")
    if kind == "symlink":
        path.unlink()
        path.symlink_to(engine.store.path)
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif kind == "hash":
        path.write_bytes(PAYLOAD + b"changed")
    else:
        digest = stage(engine, b"PK\x03\x04not-an-srt")
        request = {
            **request,
            "payload_sha256": digest,
            "provenance": {**request["provenance"], "original_sha256": digest},
        }
    with pytest.raises((ValueError, OSError)):
        importer.run(request)
    assert not list(target.rglob("*.srt"))


@pytest.mark.parametrize(
    "field,value",
    [("language", "en"), ("language", "zh-cn"), ("kind", "forced"), ("kind", "other")],
)
def test_profile_and_explicit_language_kind(local, field, value):
    _, target, importer, request = local
    with pytest.raises(ValueError):
        importer.run({**request, field: value})
    assert not list(target.rglob("*.srt"))


def test_precomputed_transform_proof_and_fps(local):
    engine, target, importer, request = local
    transformed = PAYLOAD.replace(b"00:00:01,000", b"00:00:02,000").replace(
        b"00:00:03,000", b"00:00:06,000"
    )
    digest = stage(engine, transformed)
    proof = {
        "kind": "precomputed_time_scale",
        "numerator": 2,
        "denominator": 1,
        "source_fps": 24,
        "evidence_sha256": "a" * 64,
    }
    revised = {
        **request,
        "payload_sha256": digest,
        "provenance": {**request["provenance"], "transformation": proof},
    }
    preview = importer.run(revised)
    assert preview["automatic_retiming"] is False
    assert importer.run(approval(revised, preview), execute=True)["status"] == "published"
    assert list(target.rglob("*.srt"))[0].read_bytes() == transformed
    with pytest.raises(ValueError, match="FPS"):
        importer.run(
            {
                **revised,
                "provenance": {
                    **revised["provenance"],
                    "transformation": {**proof, "source_fps": 25},
                },
            }
        )
    wrong = stage(engine, transformed.replace(b"00:00:06,000", b"00:00:07,000"))
    with pytest.raises(ValueError, match="timing proof"):
        importer.run({**revised, "payload_sha256": wrong})


def test_cli_worker_preview_then_execute_and_reject_changed_staging(local, tmp_path, monkeypatch):
    import json

    import yaml
    from test_web_settings import _write_minimal_config
    from typer.testing import CliRunner

    from seed_agent import cli
    from seed_agent.config_views import load_view
    from seed_agent.media_import import worker

    engine, target, _, request = local
    config = _write_minimal_config(tmp_path)
    raw = yaml.safe_load(config.read_text())
    engine.config.provider_interval_seconds = 1
    raw["media_import"] = engine.config.model_dump(mode="json")
    raw["media_import"]["state_path"] = str(engine.store.path)
    raw["media_import"]["subtitle_policy"] = "execute"
    config.write_text(yaml.safe_dump(raw))
    engine.config_view = load_view(config, "media")
    monkeypatch.setattr(worker, "build_engine", lambda *args, **kwargs: (engine, None))
    with engine.store._connect() as conn:
        before = conn.execute("SELECT * FROM media_provider_state ORDER BY provider").fetchall()
    request_path = tmp_path / "request.json"

    def queue(body, execute=False):
        request_path.write_text(json.dumps(body))
        args = ["media-subtitle-import", "--request", str(request_path), "--config", str(config)]
        if execute:
            args.append("--execute")
        outcome = CliRunner().invoke(cli.app, args)
        assert outcome.exit_code == 0, (outcome.output, outcome.exception)
        queued = json.loads(outcome.output)
        assert queued["status"] == "queued"
        return queued["command_id"]

    preview_command = queue(request)
    preview = worker.process_one(config)
    assert preview["command_id"] == preview_command and preview["status"] == "complete"
    assert preview["result"]["status"] == "preview"
    assert not list(target.rglob("*.srt"))
    approved = approval(request, preview["result"])
    execute_command = queue(approved, execute=True)
    result = worker.process_one(config)
    assert result["command_id"] == execute_command and result["status"] == "complete"
    assert result["result"]["status"] == "published"
    assert len(list(target.rglob("*.srt"))) == 1
    with engine.store._connect() as conn:
        assert (
            conn.execute("SELECT * FROM media_provider_state ORDER BY provider").fetchall()
            == before
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM media_artifacts WHERE kind='subtitle' AND status='active'"
            ).fetchone()[0]
            == 1
        )

    second_digest = stage(engine, PAYLOAD + b"second\n")
    second = {
        **request,
        "payload_sha256": second_digest,
        "provenance": {**request["provenance"], "original_sha256": second_digest},
    }
    queue(second)
    second_preview = worker.process_one(config)
    assert second_preview["status"] == "complete"
    queue(approval(second, second_preview["result"]), execute=True)
    (engine.store.path.parent / "subtitle-inbox" / (second_digest + ".srt")).write_bytes(b"changed")
    assert worker.process_one(config)["status"] == "failed"
    assert len(list(target.rglob("*.srt"))) == 1
