from pathlib import Path

from seed_agent.audit import AuditLogger, redact_payload, redact_sensitive_text
from seed_agent.models import Decision


def test_redact_sensitive_text_masks_credentials_in_urls_and_assignments() -> None:
    value = "https://tracker.example/rss?passkey=abc&uid=12 password=hunter2"

    redacted = redact_sensitive_text(value)

    assert "abc" not in redacted
    assert "hunter2" not in redacted
    assert "uid=12" in redacted
    assert "<redacted>" in redacted


def test_redact_sensitive_text_masks_common_secret_fields() -> None:
    value = (
        "https://tracker.example/download?password=hunter2&passphrase=open-sesame"
        "&authkey=abc&token=def&id=42"
    )

    redacted = redact_sensitive_text(value)

    assert "hunter2" not in redacted
    assert "open-sesame" not in redacted
    assert "abc" not in redacted
    assert "def" not in redacted
    assert "id=42" in redacted
    assert redacted.count("<redacted>") >= 4


def test_redact_payload_masks_nested_strings_and_dict_values() -> None:
    payload = {
        "password": "hunter2",
        "nested": [
            "https://tracker.example/rss?passkey=abc&id=42",
            {"token": "def", "safe": "ok"},
        ],
    }

    redacted = redact_payload(payload)

    assert redacted == {
        "password": "<redacted>",
        "nested": [
            "https://tracker.example/rss?id=42",
            {"token": "<redacted>", "safe": "ok"},
        ],
    }


def test_audit_logger_writes_redacted_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "audit.jsonl"
    decision = Decision(
        action="upload",
        target_id="torrent-1",
        execute=True,
        reason="test",
        old_state={"cookie": "secret-cookie"},
        new_state={
            "url": "https://tracker.example/download.php?id=42&passkey=abc",
            "nested": {"password": "hunter2"},
        },
    )

    logger = AuditLogger(path)
    logger.write(decision)

    written = path.read_text(encoding="utf-8").splitlines()

    assert len(written) == 1
    assert "abc" not in written[0]
    assert "hunter2" not in written[0]
    assert "secret-cookie" not in written[0]
    assert "<redacted>" in written[0]
    assert '"action": "upload"' in written[0]
    assert '"new_state": {' in written[0]
