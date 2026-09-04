"""Safe, structured runtime logging for operators and container platforms.

Logs are intentionally emitted to stderr so CLI JSON on stdout remains a
machine-readable contract.  All event details pass through the same redaction
used by the durable audit log: credentials, authorization headers, query
tokens, and credential-bearing URL components are removed before emission.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from seed_agent.audit import redact_payload, redact_sensitive_text

LOGGER_NAMESPACE = "seed_agent"
DEFAULT_LOG_LEVEL = "INFO"
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
RUNTIME_LOG_NAME = "runtime-events.jsonl"
RUNTIME_LOG_MAX_BYTES = 2 * 1024 * 1024
RUNTIME_LOG_BACKUPS = 3
_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def safe_error_text(exc: Exception) -> str:
    """Validation exceptions embed raw input values; never persist those."""
    if isinstance(exc, ValidationError):
        kinds = sorted({item["type"] for item in exc.errors(include_input=False,
                                                          include_context=False,
                                                          include_url=False)})
        return f"validation failed ({exc.error_count()} errors): {', '.join(kinds)}"
    return redact_sensitive_text(str(exc))[:2000]


@contextmanager
def log_context(**details: Any):
    """Correlate nested sync/async work without leaking across request threads."""
    token = _context.set({**(_context.get() or {}), **details})
    try:
        yield
    finally:
        _context.reset(token)


class JsonLogFormatter(logging.Formatter):
    """Render one redacted JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        logger_name = record.name.removeprefix(f"{LOGGER_NAMESPACE}.")
        if logger_name == LOGGER_NAMESPACE:
            logger_name = "runtime"
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": logger_name,
            "event": str(getattr(record, "event", record.getMessage())),
        }
        details = getattr(record, "details", None)
        if isinstance(details, dict) and details:
            payload["details"] = details
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(self.formatException(record.exc_info))
        # Normalize non-JSON values before redaction, not afterwards.
        payload = json.loads(json.dumps(payload, default=str))
        return json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True)


class StderrHandler(logging.Handler):
    """Resolve stderr at emit time (CLI runners and embedders replace it)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(_format_or_fallback(self, record) + "\n")
            sys.stderr.flush()
        except OSError, ValueError:
            pass  # Logging must not turn a successful operation into a failure.


class RuntimeFileHandler(logging.Handler):
    """Bounded JSONL shared by Web and scheduler processes.

    Reopen on each append under a stable flock so rotations never leave another
    process writing to a renamed file. Durable decision audit is separate.
    """

    def __init__(self, path: Path, *, max_bytes: int = RUNTIME_LOG_MAX_BYTES) -> None:
        super().__init__()
        self.path = path
        self.max_bytes = max_bytes
        self._failed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = (_format_or_fallback(self, record) + "\n").encode(
                "utf-8", errors="backslashreplace"
            )
            if len(line) > self.max_bytes:
                # Event names and exception text can also be oversized. Do not
                # retain arbitrary fields when enforcing the whole-record cap.
                payload = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": record.levelname.lower(),
                    "logger": "runtime",
                    "event": "logging.record_truncated",
                    "details": {"original_bytes": len(line)},
                }
                line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
            with os.fdopen(lock_fd, "w") as lock:
                os.fchmod(lock.fileno(), 0o600)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                if self.path.exists() and self.path.stat().st_size + len(line) > self.max_bytes:
                    for index in range(RUNTIME_LOG_BACKUPS, 0, -1):
                        previous = self.path if index == 1 else Path(f"{self.path}.{index - 1}")
                        if previous.exists():
                            previous.replace(Path(f"{self.path}.{index}"))
                fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "ab") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(line)
                # Closing the stable lock releases the flock, including on error.
            self._failed = False
        except OSError:
            if not self._failed:
                self._failed = True
                # Avoid recursive logger invocation and never print raw records/errors.
                try:
                    sys.stderr.write(
                        json.dumps(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "level": "warning",
                                "logger": "runtime",
                                "event": "logging.file_unavailable",
                            }
                        )
                        + "\n"
                    )
                except OSError, ValueError:
                    pass


def _format_or_fallback(handler: logging.Handler, record: logging.LogRecord) -> str:
    """A malformed diagnostic must never interrupt search or a mutation.

    Do not use logging.handleError: it can print the raw record and its secrets.
    The fallback deliberately contains no original message, details, or repr.
    """
    try:
        return handler.format(record)
    except Exception as exc:
        return json.dumps({
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "warning",
            "logger": "runtime",
            "event": "logging.serialization_failed",
            "details": {"error_type": type(exc).__name__},
        })


def configure_logging(level: str | None = None, *, log_path: Path | None = None) -> None:
    """Configure package handlers idempotently, honoring ``SEED_AGENT_LOG_LEVEL``.

    Valid levels are DEBUG, INFO, WARNING, ERROR, and CRITICAL. An invalid
    value falls back to INFO rather than preventing the scheduler from starting.
    """
    requested = (level or os.environ.get("SEED_AGENT_LOG_LEVEL", DEFAULT_LOG_LEVEL)).upper()
    resolved = requested if requested in VALID_LOG_LEVELS else DEFAULT_LOG_LEVEL
    logger = logging.getLogger(LOGGER_NAMESPACE)
    logger.setLevel(getattr(logging, resolved))
    logger.propagate = False
    for handler in list(logger.handlers):
        if isinstance(handler, (StderrHandler, RuntimeFileHandler)):
            logger.removeHandler(handler)
            handler.close()
    handlers: list[logging.Handler] = [StderrHandler()]
    if log_path is not None:
        handlers.append(RuntimeFileHandler(log_path))
    for handler in handlers:
        handler.setLevel(getattr(logging, resolved))
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    if requested != resolved:
        log_event(
            logger,
            logging.WARNING,
            "logging.invalid_level",
            requested_level=requested,
            fallback_level=resolved,
        )


def get_logger(component: str) -> logging.Logger:
    """Return a namespaced logger without configuring global logging eagerly."""
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{component}")


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    /,
    **details: Any,
) -> None:
    """Emit a structured event with centralized redaction."""
    if logger.isEnabledFor(level):
        logger.log(
            level, event, extra={"event": event, "details": {**(_context.get() or {}), **details}}
        )
