
import pytest
import yaml
from test_media_import import media as media
from test_media_subtitles import FakeProvider, import_three

from seed_agent.config import atomic_write_text
from seed_agent.media_import.commands import status, submit
from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.worker import process_one


def setup_command_config(media, tmp_path):
    import_three(media)
    engine = media[0]
    engine.config.subtitle_policy = "execute"
    engine.config.provider_interval_seconds = 1
    SubtitleJobs(engine).run(limit=0)
    with engine.store._connect() as conn:
        conn.execute("UPDATE media_subtitle_jobs SET next_attempt=?", (engine.clock() + 86400,))
    config = tmp_path / "config.yaml"
    raw = {"media_import": engine.config.model_dump(mode="json")}
    raw["media_import"]["state_path"] = str(engine.store.path)
    atomic_write_text(config, yaml.safe_dump(raw))
    return config, engine


def test_exact_target_command_refreshes_only_source_and_coalesces(media, tmp_path, monkeypatch):
    config, engine = setup_command_config(media, tmp_path)
    source = engine.snapshot()["sources"][0]
    body = {
        "source_id": source["id"],
        "generation": source["generation"],
        "fingerprint": source["fingerprint"],
    }
    before = {j["source_id"]: j["next_attempt"] for j in engine.snapshot()["subtitles"]}
    provider = FakeProvider()
    monkeypatch.setattr(
        "seed_agent.media_import.runtime.build_subtitle_provider", lambda *args: provider
    )
    first = submit(config, "subtitle-search", body, execute=True)
    assert (
        submit(config, "subtitle-search", body, execute=True)["command_id"] == first["command_id"]
    )
    assert process_one(config)["status"] == "complete"
    assert provider.calls == provider.downloads == 1
    for job in engine.snapshot()["subtitles"]:
        if job["source_id"] != source["id"]:
            assert job["next_attempt"] == before[job["source_id"]]
    assert status(config, first["command_id"])[0]["result"]["subtitles"][0]["status"] == "satisfied"


def test_target_preview_cannot_gain_payload_authority(media, tmp_path, monkeypatch):
    config, engine = setup_command_config(media, tmp_path)
    source = engine.snapshot()["sources"][0]
    provider = FakeProvider()
    monkeypatch.setattr(
        "seed_agent.media_import.runtime.build_subtitle_provider", lambda *args: provider
    )
    submit(
        config,
        "subtitle-search",
        {
            "source_id": source["id"],
            "generation": source["generation"],
            "fingerprint": source["fingerprint"],
        },
    )
    assert process_one(config)["status"] == "complete"
    assert provider.calls == 1 and provider.downloads == 0


def test_target_source_generation_and_plan_changes_reject_before_provider(
    media, tmp_path, monkeypatch
):
    config, engine = setup_command_config(media, tmp_path)
    source = engine.snapshot()["sources"][0]
    body = {
        "source_id": source["id"],
        "generation": source["generation"],
        "fingerprint": source["fingerprint"],
    }
    with pytest.raises(ValueError, match="baseline"):
        submit(config, "subtitle-search", {**body, "generation": 999}, execute=True)
    submit(config, "subtitle-search", body, execute=True)
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE media_import_jobs SET revision=revision+1 WHERE source_id=?", (source["id"],)
        )
    provider = FakeProvider()
    monkeypatch.setattr(
        "seed_agent.media_import.runtime.build_subtitle_provider", lambda *args: provider
    )
    assert process_one(config)["status"] == "failed" and provider.calls == 0


def test_target_replaced_video_spends_no_provider_request(media, tmp_path, monkeypatch):
    config, engine = setup_command_config(media, tmp_path)
    source = engine.snapshot()["sources"][0]
    submit(
        config,
        "subtitle-search",
        {
            "source_id": source["id"],
            "generation": source["generation"],
            "fingerprint": source["fingerprint"],
        },
        execute=True,
    )
    (media[1] / source["path"]).write_bytes(b"changed")
    provider = FakeProvider()
    monkeypatch.setattr(
        "seed_agent.media_import.runtime.build_subtitle_provider", lambda *args: provider
    )
    value = process_one(config)
    assert (
        value["status"] == "complete"
        and value["result"]["subtitles"][0]["status"] == "terminal_failure"
    )
    assert provider.calls == provider.downloads == 0
