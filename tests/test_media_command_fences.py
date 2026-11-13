import json
from contextlib import contextmanager

import pytest
from test_media_runtime import media_config

from seed_agent.media_import import commands
from seed_agent.media_import.runtime import build_engine
from seed_agent.media_import.worker import process_one


@pytest.fixture
def fenced(tmp_path):
    config, _, _ = media_config(tmp_path)
    engine, _ = build_engine(config)
    with engine.store._connect() as conn:
        for sid, path in [("first", "a.mkv"), ("parent", "b.mkv")]:
            conn.execute(
                "INSERT INTO media_source_files(id,profile,path,generation,fingerprint,"
                "first_seen,last_seen,stable_count,status,original_release) "
                "VALUES(?, 'movie', ?, 1, ?, 0, 0, 2, 'ready', ?)",
                (sid, path, "fp-" + sid, path),
            )
    sources = [
        dict(source_id=sid, generation=1, fingerprint="fp-" + sid) for sid in ("first", "parent")
    ]
    return config, engine.store, sources


def test_replacement_before_atomic_submission_rejects_without_command(fenced):
    config, store, expected = fenced
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO media_source_files(id,profile,path,generation,fingerprint,"
            "first_seen,last_seen,stable_count,status,original_release) "
            "VALUES('replacement','movie','b.mkv',2,'new',0,0,2,'ready','b')"
        )
    with pytest.raises(ValueError, match="source baseline changed"):
        commands.submit(config, "scan", expected_sources=expected)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_commands").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["fingerprint", "missing", "generation"])
def test_worker_rejects_source_changed_after_insert(fenced, change):
    config, store, expected = fenced
    queued = commands.submit(config, "scan", expected_sources=expected)
    with store._connect() as conn:
        if change == "fingerprint":
            conn.execute("UPDATE media_source_files SET fingerprint='different' WHERE id='parent'")
        elif change == "missing":
            conn.execute("UPDATE media_source_files SET missing_count=1 WHERE id='parent'")
        else:
            conn.execute(
                "INSERT INTO media_source_files(id,profile,path,generation,fingerprint,"
                "first_seen,last_seen,stable_count,status,original_release) "
                "VALUES('next','movie','b.mkv',2,'new',0,0,2,'ready','b')"
            )
    result = process_one(config)
    assert result["status"] == "failed"
    assert commands.status(config, queued["command_id"])[0]["result"]["error_type"] == "ValueError"


def test_baseline_borrows_transaction_and_coalesces(fenced, monkeypatch):
    config, store, expected = fenced
    view, _ = commands.command_store(config)
    monkeypatch.setattr(commands, "command_store", lambda path: (view, store))
    original_connect = store._connect
    original_baseline = commands.baseline

    def checked_baseline(store_arg, action, payload, *, connection=None):
        assert connection is not None and connection.in_transaction
        return original_baseline(store_arg, action, payload, connection=connection)

    monkeypatch.setattr(commands, "baseline", checked_baseline)
    opens = []

    @contextmanager
    def counted(*args, **kwargs):
        opens.append(1)
        with original_connect(*args, **kwargs) as conn:
            yield conn

    monkeypatch.setattr(store, "_connect", counted)
    first = commands.submit(config, "scan", expected_sources=expected)
    assert len(opens) == 1
    second = commands.submit(config, "scan", expected_sources=list(reversed(expected)))
    assert len(opens) == 2
    assert second["coalesced"] and second["command_id"] == first["command_id"]
    with original_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        payload = json.loads(conn.execute("SELECT payload_json FROM media_commands").fetchone()[0])
        monkeypatch.setattr(store, "_connect", lambda: pytest.fail("unexpected second connection"))
        assert original_baseline(store, "scan", payload, connection=conn) == payload["_baseline"]
        assert "_expected_sources" not in payload


@pytest.mark.parametrize(
    "expected",
    [
        [],
        [{}],
        [{"source_id": "x", "generation": True, "fingerprint": "f"}],
        [{"source_id": "x", "generation": 1, "fingerprint": "f"}] * 2,
        [{"source_id": "x", "generation": 1, "fingerprint": "f", "extra": 1}],
        [{"source_id": str(i), "generation": 1, "fingerprint": "f"} for i in range(7)],
    ],
)
def test_invalid_source_fences_rejected(fenced, expected):
    config, _, _ = fenced
    with pytest.raises(ValueError):
        commands.submit(config, "scan", expected_sources=expected)


def test_unchanged_source_fences_allow_worker_command(fenced):
    config, _, expected = fenced
    queued = commands.submit(config, "scan", expected_sources=expected)
    result = process_one(config)
    assert result["command_id"] == queued["command_id"]
    assert result["status"] == "complete"


def reviewed_context(config, store):
    view, _ = commands.command_store(config)
    return {
        "source_id": view.source_id,
        "config_revision": view.effective_revision,
        "epoch": store.epoch(),
    }


@pytest.mark.parametrize("field", ["source_id", "config_revision", "epoch"])
def test_stale_reviewed_context_rejected_before_queue(fenced, field):
    config, store, expected = fenced
    context = reviewed_context(config, store)
    if field == "source_id":
        context[field] += "-old"
    else:
        context[field] = ("0" if context[field][0] != "0" else "1") + context[field][1:]
    with pytest.raises(ValueError, match="expected media"):
        commands.submit(config, "scan", expected_sources=expected, expected_context=context)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_commands").fetchone()[0] == 0


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"source_id": "", "config_revision": "0" * 64, "epoch": "0" * 32},
        {"source_id": "x", "config_revision": "g" * 64, "epoch": "0" * 32},
        {"source_id": "x", "config_revision": "0" * 64, "epoch": "0" * 31},
        {"source_id": "x", "config_revision": "0" * 64, "epoch": "0" * 32, "extra": 1},
    ],
)
def test_invalid_reviewed_context_rejected(fenced, context):
    config, _, _ = fenced
    with pytest.raises(ValueError, match="invalid expected media context"):
        commands.submit(config, "scan", expected_context=context)


def test_context_pinned_before_config_changes_and_worker_rejects(fenced, monkeypatch):
    import yaml

    config, store, sources = fenced
    context = reviewed_context(config, store)
    original = commands.command_store

    def load_then_change(path):
        view, result_store = original(path)
        raw = yaml.safe_load(config.read_text())
        raw["media_import"]["subtitle_policy"] = "execute"
        config.write_text(yaml.safe_dump(raw))
        return view, result_store

    monkeypatch.setattr(commands, "command_store", load_then_change)
    queued = commands.submit(config, "scan", expected_sources=sources, expected_context=context)
    monkeypatch.setattr(commands, "command_store", original)
    assert process_one(config)["status"] == "failed"
    assert commands.status(config, queued["command_id"])[0]["result"]["error_type"] == "ValueError"
