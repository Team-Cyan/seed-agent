from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from seed_agent.observability import (
    JsonLogFormatter,
    RuntimeFileHandler,
    configure_logging,
    get_logger,
    log_context,
    log_event,
    safe_error_text,
)


@pytest.fixture(autouse=True)
def restore_logging():
    logger = logging.getLogger("seed_agent")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    yield
    for handler in logger.handlers[:]:
        if handler not in handlers:
            handler.close()
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def test_json_log_formatter_redacts_credentials_and_urls() -> None:
    record = logging.LogRecord(
        "seed_agent.search.mteam",
        logging.INFO,
        __file__,
        1,
        "mteam.intent_search.completed",
        (),
        None,
    )
    record.event = "mteam.intent_search.completed"
    record.details = {
        "api_key": "secret-api-key",
        "url": "https://tracker.example/path?token=secret-token",
        "release_count": 3,
    }

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["level"] == "info"
    assert payload["event"] == "mteam.intent_search.completed"
    assert payload["details"]["api_key"] == "<redacted>"
    assert "secret-token" not in json.dumps(payload)
    assert payload["details"]["release_count"] == 3


def test_level_gating_reconfiguration_and_stdout_contract(monkeypatch, capsys) -> None:
    logger = get_logger("test")
    configure_logging("INFO")
    log_event(logger, logging.DEBUG, "hidden")
    log_event(logger, logging.INFO, "visible")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["event"] == "visible"
    replacement = io.StringIO()
    monkeypatch.setattr("sys.stderr", replacement)
    configure_logging("DEBUG")
    log_event(logger, logging.DEBUG, "debug")
    assert len(replacement.getvalue().splitlines()) == 1
    assert json.loads(replacement.getvalue())["level"] == "debug"
    configure_logging("not-a-level")
    assert json.loads(replacement.getvalue().splitlines()[-1])["event"] == "logging.invalid_level"


def test_context_is_nested_and_thread_isolated(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    configure_logging("INFO", log_path=path)
    logger = get_logger("test")

    def emit(index):
        with log_context(request_id=str(index)):
            with log_context(intent_id=f"want-{index}"):
                log_event(logger, logging.INFO, "test", api_key="private-key")
            log_event(logger, logging.INFO, "outer")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(emit, range(8)))
    log_event(logger, logging.INFO, "outside")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 17
    for row in rows:
        if row["event"] == "test":
            assert row["details"]["intent_id"] == f"want-{row['details']['request_id']}"
            assert row["details"]["api_key"] == "<redacted>"
        elif row["event"] == "outer":
            assert "intent_id" not in row["details"]
        else:
            assert "details" not in row
    assert path.stat().st_mode & 0o777 == 0o600


def test_runtime_rotation_is_bounded_and_tail_merges_backups(tmp_path: Path) -> None:
    from seed_agent.observability import RUNTIME_LOG_NAME
    from seed_agent.web.app import _runtime_log_entries

    path = tmp_path / ".seed-agent" / RUNTIME_LOG_NAME
    handlers = [RuntimeFileHandler(path, max_bytes=1024) for _ in range(2)]
    for handler in handlers:
        handler.setFormatter(JsonLogFormatter())
    for index in range(50):
        record = logging.LogRecord("seed_agent.test", logging.INFO, __file__, 1,
                                   f"test.{index}", (), None)
        handlers[index % 2].handle(record)
    files = list(path.parent.glob("runtime-events.jsonl*"))
    assert len(files) == 5  # active, three backups, stable lock
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in files)
    assert all(item.stat().st_size <= 1024 for item in files)
    rows = _runtime_log_entries(tmp_path, limit=12)
    assert [row["title"] for row in rows] == [f"test.{index}" for index in range(49, 37, -1)]


def test_runtime_file_failure_does_not_break_operation(tmp_path: Path, capsys) -> None:
    blocked = tmp_path / "blocked"
    blocked.touch()
    configure_logging("INFO", log_path=blocked / "events.jsonl")
    for _ in range(2):
        log_event(get_logger("test"), logging.INFO, "still.running")
    rows = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert sum(row["event"] == "logging.file_unavailable" for row in rows) == 1
    assert sum(row["event"] == "still.running" for row in rows) == 2


def test_malformed_log_details_never_escape_or_expose_raw_record(tmp_path: Path, capsys) -> None:
    path = tmp_path / "events.jsonl"
    configure_logging("INFO", log_path=path)
    circular = {"api_key": "private-value"}
    circular["nested"] = circular

    class BrokenValue:
        def __str__(self):
            raise RuntimeError("private-value")

    log_event(get_logger("test"), logging.INFO, "circular", payload=circular)
    log_event(get_logger("test"), logging.INFO, "unprintable", payload=BrokenValue())
    log_event(get_logger("test"), logging.INFO, "healthy")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-value" not in captured.err
    assert "private-value" not in path.read_text()
    for text in (captured.err, path.read_text()):
        rows = [json.loads(line) for line in text.splitlines()]
        assert [row["event"] for row in rows] == [
            "logging.serialization_failed", "logging.serialization_failed", "healthy"
        ]
        assert rows[0]["details"]["error_type"] == "ValueError"
        assert rows[1]["details"]["error_type"] == "RuntimeError"


def test_oversized_event_name_cannot_exceed_runtime_file_limit(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    handler = RuntimeFileHandler(path, max_bytes=1024)
    handler.setFormatter(JsonLogFormatter())
    record = logging.LogRecord("seed_agent.test", logging.ERROR, __file__, 1, "x" * 8192, (), None)
    handler.handle(record)
    assert path.stat().st_size <= 1024
    row = json.loads(path.read_text())
    assert row["event"] == "logging.record_truncated"
    assert row["level"] == "error"


def test_runtime_file_can_encode_unpaired_surrogate(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    handler = RuntimeFileHandler(path)
    handler.setFormatter(JsonLogFormatter())
    record = logging.LogRecord("seed_agent.test", logging.INFO, __file__, 1, "surrogate", (), None)
    record.details = {"text": "bad unicode \ud800"}
    handler.handle(record)
    assert json.loads(path.read_text())["event"] == "surrogate"


def test_runtime_multiple_processes_append_complete_records(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    code = """
import logging, sys
from pathlib import Path
from seed_agent.observability import RuntimeFileHandler, JsonLogFormatter
handler = RuntimeFileHandler(Path(sys.argv[1]))
handler.setFormatter(JsonLogFormatter())
for index in range(40):
    handler.handle(logging.LogRecord('seed_agent.test', logging.INFO, '', 1,
                                    f'{sys.argv[2]}.{index}', (), None))
"""
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(
            lambda index: subprocess.run([sys.executable, "-c", code, str(path), str(index)],
                                         check=True, capture_output=True), range(3)))
    assert all(result.returncode == 0 for result in results)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 120
    assert len({row["event"] for row in rows}) == 120


def test_runtime_unreadable_tail_does_not_hide_other_sources(tmp_path: Path, monkeypatch) -> None:
    from seed_agent.web import app

    def unreadable(*args, **kwargs):
        raise PermissionError("private location")

    monkeypatch.setattr(app, "_tail_text_lines", unreadable)
    payload = app._logs_payload(tmp_path)
    assert payload["entries"][0]["level"] == "warning"
    assert payload["entries"][0]["title"] == "logging.read_unavailable"
    assert "private location" not in json.dumps(payload)


def test_exception_and_non_json_values_are_redacted() -> None:
    class SecretObject:
        def __str__(self):
            return "https://example.org/path?token=hidden"

    try:
        raise RuntimeError("Authorization: Bearer hidden-bearer")
    except RuntimeError:
        import sys
        record = logging.LogRecord("seed_agent.test", logging.ERROR, __file__, 1,
                                   "failed token=hidden-token", (), sys.exc_info())
    record.details = {"object": SecretObject(), "nested": [{"password": "hidden-password"}]}
    formatted = JsonLogFormatter().format(record)
    assert "hidden" not in formatted
    assert json.loads(formatted)["level"] == "error"


def test_validation_error_does_not_log_raw_secret_input() -> None:
    from pydantic import BaseModel, ValidationError

    class Draft(BaseModel):
        enabled: bool

    with pytest.raises(ValidationError) as caught:
        Draft(enabled={"api_key_value": "private-value"})
    text = safe_error_text(caught.value)
    assert "bool_type" in text
    assert "private-value" not in text
    assert "api_key_value" not in text


@pytest.mark.asyncio
async def test_search_failure_redacts_validation_input_at_the_first_log_boundary(
    tmp_path: Path, capsys,
) -> None:
    from pydantic import BaseModel, ValidationError

    from seed_agent.actions.intent import add_intent, search_intents_batch
    from seed_agent.config import IntentConfig, SearchConfig
    from seed_agent.state import StateStore

    class Response(BaseModel):
        enabled: bool

    class Provider:
        async def search(self, intent):
            Response.model_validate({"enabled": "private-input"})

    path = tmp_path / "events.jsonl"
    configure_logging("INFO", log_path=path)
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Example 2026", store)
    with pytest.raises(ValidationError):
        await search_intents_batch([intent], store, [Provider()], IntentConfig(),
                                   SearchConfig(), source="web")
    for text in (path.read_text(), capsys.readouterr().err):
        assert "private-input" not in text
        failure = next(json.loads(line) for line in text.splitlines()
                       if json.loads(line)["event"] == "intent.search_batch.failed")
        assert "validation failed" in failure["details"]["error"]
    assert store.list_want_search_runs() == []


def test_exception_summaries_and_runtime_status_omit_validation_input(monkeypatch) -> None:
    from pydantic import BaseModel, ValidationError

    from seed_agent import cli
    from seed_agent.actions import pt, qb

    class Draft(BaseModel):
        enabled: bool

    with pytest.raises(ValidationError) as caught:
        Draft.model_validate({"enabled": "private-input"})
    for summarize in (cli._runtime_error_summary, pt._runtime_error_summary, qb._error_summary):
        assert "private-input" not in summarize(caught.value)
        assert "validation failed" in summarize(caught.value)

    def fail_config(path):
        raise caught.value

    monkeypatch.setattr(cli, "load_config", fail_config)
    payload = cli._runtime_status_payload(
        Path("config.yaml"), heartbeat_file=None, max_staleness_minutes=5
    )
    assert payload["status"] == "config_error"
    assert "private-input" not in json.dumps(payload)
