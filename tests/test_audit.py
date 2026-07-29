import stat
from pathlib import Path

from seed_agent.audit import AuditLogger, redact_payload, redact_sensitive_text
from seed_agent.models import Decision


def test_redact_sensitive_text_masks_credentials_in_urls_and_assignments() -> None:
    value = "https://tracker.example/rss?passkey=abc&uid=12 password=hunter2"

    redacted = redact_sensitive_text(value)

    assert "abc" not in redacted
    assert "hunter2" not in redacted
    assert "uid=12" not in redacted
    assert "<redacted>" in redacted


def test_redact_sensitive_text_masks_nested_sensitive_assignments() -> None:
    assert "hunter2" not in redact_sensitive_text("note=password=hunter2")
    assert "hunter2" not in redact_sensitive_text("note: password=hunter2")


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


def test_redact_sensitive_text_preserves_closing_punctuation_after_url() -> None:
    value = "prefix (https://tracker.example/details.php?id=1&passkey=secret) suffix"

    redacted = redact_sensitive_text(value)

    assert "(https://tracker.example/details.php?id=1)" in redacted
    assert "%29" not in redacted
    assert "secret" not in redacted


def test_redact_sensitive_text_preserves_closing_bracket_after_url() -> None:
    value = "prefix [https://tracker.example/details.php?id=1&passkey=secret] suffix"

    redacted = redact_sensitive_text(value)

    assert "[https://tracker.example/details.php?id=1]" in redacted
    assert "%5D" not in redacted


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


def test_redact_payload_masks_api_key_fields_and_assignments() -> None:
    payload = {
        "api_key": "secret-api-key",
        "nested": {
            "apikey": "secret-compact-key",
            "message": "api_key=secret-inline-key auth_header=x-api-key",
            "url": "https://tracker.example/api?api_key=secret-query-key&id=42",
        },
    }

    redacted = redact_payload(payload)
    redacted_text = str(redacted)

    assert "secret-api-key" not in redacted_text
    assert "secret-compact-key" not in redacted_text
    assert "secret-inline-key" not in redacted_text
    assert "secret-query-key" not in redacted_text
    assert "auth_header=x-api-key" in redacted_text
    assert "id=42" in redacted_text


def test_redact_payload_masks_authorization_headers() -> None:
    redacted = redact_payload(
        {
            "Authorization": "Bearer secret-token",
            "Proxy-Authorization": "Basic secret-proxy",
        }
    )

    assert redacted == {
        "Authorization": "<redacted>",
        "Proxy-Authorization": "<redacted>",
    }


def test_redactors_mask_multiword_authorization_values_and_telegram_bot_urls() -> None:
    telegram_token = "123456:ABC-telegram-secret"
    bearer_token = "bearer-secret"
    basic_token = "YmFzaWMtc2VjcmV0"
    value = (
        f"Authorization: Bearer {bearer_token}; "
        f"Proxy-Authorization=Basic {basic_token}\n"
        f"https://api.telegram.org/bot{telegram_token}/getUpdates"
    )

    for redacted in (redact_sensitive_text(value), redact_payload(value)):
        assert telegram_token not in redacted
        assert bearer_token not in redacted
        assert basic_token not in redacted
        assert "https://api.telegram.org/bot<redacted>/getUpdates" in redacted
        assert redacted.count("<redacted>") >= 3


def test_authorization_redaction_preserves_following_media_metadata() -> None:
    value = "movie Secret Authorization: Bearer bearer-secret 2020 1080p"

    redacted = redact_sensitive_text(value)

    assert redacted == "movie Secret Authorization:<redacted> 2020 1080p"


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
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
