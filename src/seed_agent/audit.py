from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from seed_agent.models import Decision, safe_url_identity

REDACTED = "<redacted>"

SENSITIVE_QUERY_KEYS = {
    "passkey",
    "password",
    "passphrase",
    "token",
    "secret",
    "cookie",
    "rsskey",
    "authkey",
    "auth",
    "pass_key",
    "torrent_pass",
    "torrentpass",
    "download_key",
    "downloadkey",
    "secure",
    "signature",
    "sign",
    "hash",
}
SENSITIVE_TOKEN_KEYS = {"pass", "token", "secret", "auth", "cookie"}
URL_RE = re.compile(r"(?P<url>\bhttps?://[^\s<>'\"]+)")
SENSITIVE_ASSIGNMENT_RE = re.compile(
    rf"(?<![A-Za-z0-9_.-])(?P<key>{'|'.join(sorted(SENSITIVE_QUERY_KEYS))})"
    r"\s*(?P<sep>=|:)\s*(?P<value>[^\s&;,)\]}]+)",
    re.IGNORECASE,
)


def redact_sensitive_text(value: str) -> str:
    redacted = URL_RE.sub(_redact_url_match, value)
    return _redact_sensitive_assignments(redacted)


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        stripped = URL_RE.sub(_strip_url_match, value)
        return _redact_sensitive_assignments(stripped)
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive_key(key) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    return value


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, decision: Decision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = redact_payload(decision.model_dump(mode="json"))
        with self.path.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")


def _redact_url_match(match: re.Match[str]) -> str:
    url, suffix = _split_trailing_punctuation(match.group("url"))
    return f"{_redact_url(url)}{suffix}"


def _strip_url_match(match: re.Match[str]) -> str:
    url, suffix = _split_trailing_punctuation(match.group("url"))
    return f"{safe_url_identity(url)}{suffix}"


def _redact_url(value: str) -> str:
    return safe_url_identity(value)


def _redact_sensitive_assignments(value: str) -> str:
    previous = None
    current = value
    while current != previous:
        previous = current
        current = SENSITIVE_ASSIGNMENT_RE.sub(_redact_sensitive_assignment_match, current)
    return current


def _redact_sensitive_assignment_match(match: re.Match[str]) -> str:
    key = match.group("key")
    sep = match.group("sep")
    return f"{key}{sep}{REDACTED}"


def _split_trailing_punctuation(value: str) -> tuple[str, str]:
    suffix = ""
    core = value
    trailing_chars = ")]}.,;:!?\"'"
    while core and core[-1] in trailing_chars:
        suffix = core[-1] + suffix
        core = core[:-1]
    return core, suffix


def _is_sensitive_key(key: str) -> bool:
    lower_key = key.lower()
    if lower_key in SENSITIVE_QUERY_KEYS:
        return True
    key_parts = [part for part in re.split(r"[^a-z0-9]+", lower_key) if part]
    return any(part in SENSITIVE_TOKEN_KEYS for part in key_parts)
