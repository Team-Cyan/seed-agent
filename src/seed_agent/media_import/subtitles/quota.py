"""Persistent daily download allowance, separate from per-request pacing.

A download-link request can consume allowance before payload retrieval. Reserve
before sending it; missing/ambiguous responses retain a conservative 24h fence.
"""

import json
import math
import uuid
from datetime import UTC, datetime

from seed_agent.media_import.subtitles.provider import ProviderError

DAY = 86400


def quota_evidence(data, now):
    """Accept explicit provider UTC/offset reset or duration; never local midnight."""
    remaining = data.get("remaining")
    try:
        remaining = (
            int(remaining) if remaining is not None and not isinstance(remaining, bool) else None
        )
    except TypeError, ValueError, OverflowError:
        remaining = None
    if remaining is not None and remaining < 0:
        remaining = 0
    reset = None
    utc = data.get("reset_time_utc")
    try:
        if utc:
            parsed = datetime.fromisoformat(str(utc).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)  # field explicitly declares UTC
            reset = parsed.timestamp()
        elif data.get("reset_time"):
            value = str(data["reset_time"])
            if ":" in value and "T" not in value and "-" not in value:
                parts = value.split(":")
                if len(parts) == 3:
                    h, m, s = (float(part) for part in parts)
                    if 0 <= h <= 168 and 0 <= m < 60 and 0 <= s < 60:
                        reset = now + h * 3600 + m * 60 + s
            else:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    reset = parsed.timestamp()
    except ValueError, TypeError, OverflowError:
        reset = None
    # A stale/malformed service reset is not permission for a tight retry loop.
    if reset is None or not math.isfinite(reset) or reset <= now:
        reset = now + DAY
    requests = data.get("requests")
    return {
        "remaining": remaining,
        "requests": requests if isinstance(requests, int) and requests >= 0 else None,
        "reset_at": reset,
    }


class DownloadBudget:
    def __init__(self, store, provider, *, clock):
        self.store, self.clock = store, clock
        self.key = provider + ":download-budget"
        self.token = None
        self.epoch = store.epoch()

    def check(self):
        with self.store._connect() as conn:
            if (
                conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()[0]
                != self.epoch
            ):
                raise ProviderError("superseded", payload_attempted=False)
            row = conn.execute(
                "SELECT next_request,status FROM media_provider_state WHERE provider=?", (self.key,)
            ).fetchone()
        if row and row[0] > self.clock():
            remaining = json.loads(row[1]).get("remaining")
            if remaining is None or remaining <= 0:
                raise ProviderError(
                    "daily_quota", max(1, math.ceil(row[0] - self.clock())), payload_attempted=False
                )

    def reserve(self):
        now = self.clock()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if (
                conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()[0]
                != self.epoch
            ):
                raise ProviderError("superseded", payload_attempted=False)
            row = conn.execute(
                "SELECT next_request,status FROM media_provider_state WHERE provider=?", (self.key,)
            ).fetchone()
            state = json.loads(row[1]) if row else {}
            if row and row[0] > now:
                remaining = state.get("remaining")
                if remaining is None or remaining <= 0:
                    raise ProviderError(
                        "daily_quota", max(1, math.ceil(row[0] - now)), payload_attempted=False
                    )
                state["remaining"] = remaining - 1
                resume = row[0]
            else:
                # One probe when no evidence exists or a quota period has expired.
                state = {"remaining": None, "requests": None, "reservation": "uncertain"}
                resume = now + DAY
            state["reservation"] = "link_requested"
            state["reserved_remaining"] = state.get("remaining")
            state["remaining"] = None  # block concurrent links until this response is reconciled
            self.token = uuid.uuid4().hex
            state["token"] = self.token
            conn.execute(
                "INSERT INTO media_provider_state VALUES(?,?,?) ON CONFLICT(provider) "
                "DO UPDATE SET next_request=excluded.next_request,status=excluded.status",
                (self.key, resume, json.dumps(state, sort_keys=True)),
            )

    def observe(self, data):
        evidence = quota_evidence(data, self.clock())
        evidence["reservation"] = "provider_response"
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if (
                conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()[0]
                != self.epoch
            ):
                return None
            row = conn.execute(
                "SELECT status,next_request FROM media_provider_state WHERE provider=?", (self.key,)
            ).fetchone()
            if not row or json.loads(row[0]).get("token") != self.token:
                return None
            reserved = json.loads(row[0]).get("reserved_remaining")
            if reserved is not None and row[1] > self.clock() and evidence["remaining"] is not None:
                evidence["remaining"] = min(reserved, evidence["remaining"])
            conn.execute(
                "INSERT INTO media_provider_state VALUES(?,?,?) ON CONFLICT(provider) "
                "DO UPDATE SET next_request=excluded.next_request,status=excluded.status",
                (self.key, evidence["reset_at"], json.dumps(evidence, sort_keys=True)),
            )
        return evidence

    def sync(self, data):
        """Read-only account evidence cannot refund an active/uncertain reservation."""
        evidence = quota_evidence(data, self.clock())
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if (
                conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()[0]
                != self.epoch
            ):
                return None
            row = conn.execute(
                "SELECT status,next_request FROM media_provider_state WHERE provider=?", (self.key,)
            ).fetchone()
            if row and row[1] > self.clock():
                previous = json.loads(row[0])
                if (
                    previous.get("remaining") is None
                    or previous.get("reservation") == "restore_wait"
                ):
                    return None
                if evidence["remaining"] is not None:
                    evidence["remaining"] = min(evidence["remaining"], previous["remaining"])
            evidence["reservation"] = "account_response"
            conn.execute(
                "INSERT INTO media_provider_state VALUES(?,?,?) ON CONFLICT(provider) "
                "DO UPDATE SET next_request=excluded.next_request,status=excluded.status",
                (self.key, evidence["reset_at"], json.dumps(evidence, sort_keys=True)),
            )
        return evidence
