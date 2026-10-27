"""Small allowlisted request evidence; never URLs, messages, credentials or bodies."""

import math
import re
import time
from email.utils import parsedate_to_datetime

ORIGINS = {
    "http_response",
    "transport_failure",
    "adapter_failure",
    "provider_api",
    "persistent_gate",
    "download_budget",
    "validation",
}
STAGES = {
    "account",
    "login",
    "search",
    "details",
    "download_link",
    "payload",
    "api",
    "request",
    "quota",
}


def safe_evidence(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    if value.get("origin") in ORIGINS:
        result["origin"] = value["origin"]
    if value.get("stage") in STAGES:
        result["stage"] = value["stage"]
    for name, lower, upper in [
        ("http_status", 100, 599),
        ("api_code", 0, 10**9),
        ("retry_delay_seconds", 0, 604800),
        ("retry_after_seconds", 0, 604800),
        ("rate_limit_reset_value", 0, 10**12),
        ("observed_at", 0, 10**12),
    ]:
        number = value.get(name)
        if type(number) in {int, float} and math.isfinite(number) and lower <= number <= upper:
            result[name] = number
    if type(value.get("retry_after_header_present")) is bool:
        result["retry_after_header_present"] = value["retry_after_header_present"]
    name = value.get("exception_type")
    if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        result["exception_type"] = name
    return result


def response_evidence(status, headers, stage):
    headers = {k.lower(): v for k, v in headers.items()}
    now = time.time()
    value = {
        "origin": "http_response",
        "stage": stage,
        "http_status": status,
        "observed_at": now,
        "retry_after_header_present": "retry-after" in headers,
    }
    raw = headers.get("retry-after")
    if raw is not None:
        try:
            delay = float(raw)
        except ValueError, TypeError:
            try:
                stamp = parsedate_to_datetime(raw)
                delay = max(0, stamp.timestamp() - now) if stamp.tzinfo is not None else None
            except ValueError, TypeError, OverflowError:
                delay = None
        value["retry_after_seconds"] = delay
    try:
        value["rate_limit_reset_value"] = float(headers.get("x-ratelimit-reset"))
    except ValueError, TypeError, OverflowError:
        pass
    return safe_evidence(value)
