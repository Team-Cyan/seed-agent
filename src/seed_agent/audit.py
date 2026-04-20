from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

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
KEY_VALUE_RE = re.compile(
    r"(?P<key>[A-Za-z0-9_.-]+)\s*(?P<sep>=|:)\s*(?P<value>[^\s&;,]+)"
)
URL_RE = re.compile(r"(?P<url>\bhttps?://[^\s<>'\"]+)")


def redact_sensitive_text(value: str) -> str:
    redacted = URL_RE.sub(_redact_url_match, value)
    return KEY_VALUE_RE.sub(_redact_assignment_match, redacted)


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        stripped = URL_RE.sub(_strip_url_match, value)
        return KEY_VALUE_RE.sub(_redact_assignment_match, stripped)
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
    return _redact_url(match.group("url"))


def _strip_url_match(match: re.Match[str]) -> str:
    return safe_url_identity(match.group("url"))


def _redact_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme:
        return value

    netloc = _safe_netloc(parts)
    if not parts.query:
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    query_parts = []
    for key, item_value in parse_qsl(parts.query, keep_blank_values=True):
        if _is_sensitive_key(key):
            query_parts.append((key, REDACTED))
        else:
            query_parts.append((key, item_value))
    query = "&".join(
        f"{quote_plus(key)}={REDACTED if item_value == REDACTED else quote_plus(item_value)}"
        for key, item_value in query_parts
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _safe_netloc(parts: Any) -> str:
    hostname = parts.hostname
    if hostname is None:
        return parts.netloc
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if parts.port is not None:
        return f"{hostname}:{parts.port}"
    return hostname


def _redact_assignment_match(match: re.Match[str]) -> str:
    key = match.group("key")
    sep = match.group("sep")
    value = match.group("value")
    if _is_sensitive_key(key):
        return f"{key}{sep}{REDACTED}"
    return f"{key}{sep}{value}"


def _is_sensitive_key(key: str) -> bool:
    lower_key = key.lower()
    if lower_key in SENSITIVE_QUERY_KEYS:
        return True
    key_parts = [part for part in re.split(r"[^a-z0-9]+", lower_key) if part]
    return any(part in SENSITIVE_TOKEN_KEYS for part in key_parts)
