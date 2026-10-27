"""Provider-isolated search and accounting; publication remains in the common domain core."""

import hashlib
import json
from dataclasses import replace

from seed_agent.media_import.subtitles.evidence import safe_evidence
from seed_agent.media_import.subtitles.provider import Candidate, ProviderError


class Unavailable:
    request_pacer = None

    def __init__(self, name):
        self.name = name

    def search(self, *args):
        raise ProviderError("credentials_required", payload_attempted=False)

    def download(self, *args):
        raise ProviderError("credentials_required", payload_attempted=False)


class ProviderPool:
    name = "multiple"
    request_pacer = (
        None  # Every child request uses its own persistent gate, not a shared pool cooldown.
    )
    managed = True

    def __init__(self, providers):
        self.providers = list(providers)[:3]
        if len({p.name for p in self.providers}) != len(self.providers):
            raise ValueError("duplicate subtitle provider")
        self.statuses = {}
        self.next_retry = None
        self.components = {}
        self.engine = None

    def bind(self, engine):
        from seed_agent.media_import.subtitles.jobs import SubtitleJobs

        self.engine = engine
        self.components = {p.name: SubtitleJobs(engine, p) for p in self.providers}

    def priority(self, name):
        return next((i for i, p in enumerate(self.providers) if p.name == name), 99)

    def record(self, p, status, error=None, *, evidence=None):
        summary = {
            "provider": p.name,
            "status": status,
            "error": error,
            "quota_per_minute": getattr(p, "quota_per_minute", None),
            "account_quota": getattr(p, "account_summary", None),
        }
        current = safe_evidence(evidence)
        if current:
            summary["observation"] = current
        prior = self.statuses.get(p.name, {})
        if self.engine:
            role = "provider:" + hashlib.sha256(p.name.encode()).hexdigest()[:24]
            with self.engine.store._connect() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM media_runtime_status WHERE role=?", (role,)
                ).fetchone()
            if row:
                prior = json.loads(row[0])
        for key in ("last_request", "last_response"):
            retained = safe_evidence(prior.get(key))
            if retained:
                summary[key] = retained
        response = safe_evidence(
            getattr(p, "last_response_evidence", {})
            or getattr(getattr(p, "http", None), "last_response_evidence", {})
        )
        if response and response.get("observed_at", 0) >= summary.get("last_response", {}).get(
            "observed_at", 0
        ):
            summary["last_response"] = response
        if current and current.get("origin") in {
            "http_response",
            "transport_failure",
            "adapter_failure",
            "provider_api",
        }:
            summary["last_request"] = current
        elif not current and response:
            summary["last_request"] = response
        self.statuses[p.name] = summary
        if self.engine:
            self.engine.record_health("provider", p.name, summary)

    def failed(self, p, error):
        self.record(p, error.status, error.status, evidence=error.evidence)
        self.next_retry = min(self.next_retry or error.retry_after, error.retry_after)
        download_only = error.evidence.get("origin") == "download_budget" or (
            error.status == "daily_quota"
            and error.evidence.get("stage") in {"download_link", "payload", "quota"}
        )
        existing_gate = (
            error.evidence.get("origin") == "persistent_gate"
            and error.evidence.get("stage") == "request"
        )
        if (
            not download_only
            and not existing_gate
            and error.status
            in {
                "quota",
                "daily_quota",
                "rate_limited",
                "retrying",
            }
        ):
            with self.engine.store._connect() as conn:
                if (
                    conn.execute("SELECT epoch FROM media_control WHERE id=1").fetchone()[0]
                    != self.engine.store_epoch
                ):
                    raise ValueError("stale provider response after restore")
                conn.execute(
                    "INSERT INTO media_provider_state VALUES(?,?,?) ON CONFLICT(provider) "
                    "DO UPDATE SET next_request=MAX(next_request,excluded.next_request),"
                    "status=CASE WHEN excluded.next_request>=next_request "
                    "THEN excluded.status ELSE status END",
                    (p.name, self.engine.clock() + error.retry_after, error.status),
                )

    def search(self, mapping, source, languages):
        output = []
        seen = set()
        failures = []
        healthy = False
        self.next_retry = None
        for p in self.providers:
            component = self.components[p.name]
            try:
                # Download allowance does not prohibit search. Child adapters
                # retain their own search quota/pacing; downloads still reserve
                # allowance before requesting any link or payload.
                if not hasattr(p, "request_pacer"):
                    component.pace()
                values = p.search(mapping, source, languages)[:100]
                healthy = True
                self.record(p, "available" if values else "no_result")
                for value in values:
                    if (
                        not isinstance(value, Candidate)
                        or not isinstance(value.id, str)
                        or len(value.id) > 200
                    ):
                        continue
                    key = (p.name, value.id, value.language, value.release)
                    if key in seen:
                        continue
                    seen.add(key)
                    output.append(
                        replace(
                            value, provider=p.name, origin_id=value.id, id=p.name + ":" + value.id
                        )
                    )
                    if len(output) >= 100:
                        return output
            except ProviderError as exc:
                failures.append(exc)
                self.failed(p, exc)
            except Exception as error:
                exc = ProviderError(
                    "retrying",
                    60,
                    payload_attempted=False,
                    evidence={
                        "origin": "adapter_failure",
                        "stage": "search",
                        "exception_type": type(error).__name__,
                    },
                )
                failures.append(exc)
                self.failed(p, exc)
        if not output and failures and not healthy:
            raise ProviderError(
                "providers_wait", min(e.retry_after for e in failures), payload_attempted=False
            )
        return output

    def download(self, candidate):
        p = next((p for p in self.providers if p.name == candidate.provider), None)
        if p is None:
            raise ProviderError("retrying", payload_attempted=False)
        component = self.components[p.name]
        try:
            if not hasattr(p, "request_pacer"):
                component.pace(wait=True)
            result = p.download(replace(candidate, id=candidate.origin_id or candidate.id))
            self.record(p, "available")
            return result
        except ProviderError as exc:
            self.failed(p, exc)
            raise
