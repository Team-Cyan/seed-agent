"""Fixed-origin authenticated API calls and bounded provider-owned payload transport."""

import json
import time
from urllib.parse import urljoin, urlparse

import httpx

from seed_agent.media_import.subtitles.provider import ProviderError, retry_seconds


class Transport:
    def __init__(self, origin, token, *, payload_hosts):
        self.origin, self.token = origin, token
        self.payload_hosts = set(payload_hosts)
        self.pacer = None
        self.last_headers = {}

    def request(
        self,
        url,
        *,
        params=None,
        api=False,
        limit=2_000_000,
        download_auth=False,
        before_request=None,
    ):
        deadline = time.monotonic() + 60
        payload_attempted = False
        if self.pacer:
            self.pacer()
        headers = {
            "Accept": "application/json" if api else "*/*",
            "User-Agent": "seed-agent subtitles",
        }
        if api:
            headers["Authorization"] = "Bearer " + self.token
        if download_auth:
            headers["X-API-Key"] = self.token
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            for hop in range(3):
                parsed = urlparse(url)
                allowed = {urlparse(self.origin).hostname} if api else self.payload_hosts
                if (
                    parsed.scheme != "https"
                    or parsed.hostname not in allowed
                    or parsed.username
                    or parsed.password
                    or parsed.port not in {None, 443}
                ):
                    raise ProviderError("terminal_failure", payload_attempted=payload_attempted)
                if not api and not payload_attempted:
                    if before_request:
                        before_request()
                    payload_attempted = True
                with client.stream("GET", url, params=params, headers=headers) as response:
                    self.last_headers = {
                        k.lower(): v
                        for k, v in response.headers.items()
                        if k.lower()
                        in {
                            "retry-after",
                            "x-ratelimit-limit",
                            "x-ratelimit-remaining",
                            "x-ratelimit-reset",
                        }
                    }
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if hop == 2:
                            raise ProviderError("retrying")
                        target = urljoin(str(response.url), response.headers.get("location", ""))
                        target_host = urlparse(target).hostname
                        # Auth never leaves its exact documented origin. A download
                        # redirect may reach only a configured provider payload host.
                        if target_host != parsed.hostname:
                            if api or target_host not in self.payload_hosts:
                                raise ProviderError("terminal_failure", payload_attempted=not api)
                            headers.pop("X-API-Key", None)
                        url, params = target, None
                        if self.pacer:
                            self.pacer()
                        continue
                    result = bytearray()
                    for chunk in response.iter_bytes():
                        result.extend(chunk)
                        if len(result) > limit or time.monotonic() >= deadline:
                            raise ProviderError("terminal_failure", payload_attempted=not api)
                    if response.status_code >= 400:
                        try:
                            details = json.loads(result)
                        except ValueError:
                            details = {}
                        error = details.get("error", {}) if isinstance(details, dict) else {}
                        code = error.get("code") if isinstance(error, dict) else None
                        message = (
                            str(error.get("message", "")).casefold()
                            if isinstance(error, dict)
                            else ""
                        )
                        if api and isinstance(details, dict) and details.get("status") == 30900:
                            return bytes(result)  # ASSRT's documented minute-limit API error.
                        if code in {
                            "quota_exceeded",
                            "daily_quota_exceeded",
                            "download_quota_exceeded",
                        } and ("daily" in message or "day" in message):
                            reset = self.last_headers.get("x-ratelimit-reset")
                            try:
                                delay = (
                                    max(1, int(float(reset) - time.time()))
                                    if float(reset) > time.time()
                                    else 86400
                                )
                            except TypeError, ValueError, OverflowError:
                                delay = 86400
                            raise ProviderError("daily_quota", delay, payload_attempted=not api)
                        if response.status_code == 429:
                            raise ProviderError(
                                "rate_limited",
                                retry_seconds(response.headers.get("retry-after")),
                                payload_attempted=not api,
                            )
                        if response.status_code in {401, 403}:
                            raise ProviderError("credentials_required", payload_attempted=not api)
                        raise ProviderError("retrying", payload_attempted=not api)
                    return bytes(result)
        raise ProviderError("retrying")

    def get(self, path, params=None):
        try:
            return json.loads(self.request(self.origin + path, params=params, api=True))
        except ProviderError:
            raise
        except httpx.HTTPError, ValueError:
            raise ProviderError("retrying", payload_attempted=False) from None

    def payload(self, url, *, authenticate=False, before_request=None):
        try:
            return self.request(url, download_auth=authenticate, before_request=before_request)
        except ProviderError:
            raise
        except httpx.HTTPError:
            raise ProviderError("retrying") from None
