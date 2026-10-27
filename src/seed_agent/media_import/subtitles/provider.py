"""Bounded provider contract; Subliminal supplies the OpenSubtitles.com search adapter."""

import time
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from seed_agent.media_import.subtitles.evidence import response_evidence, safe_evidence

_CACHE_LOCK = Lock()


class ProviderError(RuntimeError):
    def __init__(
        self, status="retrying", retry_after=3600, *, payload_attempted=True, evidence=None
    ):
        super().__init__(status)
        self.status, self.retry_after = status, retry_after
        self.payload_attempted = payload_attempted
        self.evidence = safe_evidence(evidence)
        if self.evidence:
            self.evidence.setdefault("observed_at", time.time())


@dataclass
class Candidate:
    id: str
    language: str
    tmdb_id: int | None = None
    imdb_id: str | None = None
    season: int | None = None
    episodes: tuple[int, ...] = ()
    release: str = ""
    edition: str | None = None
    fps: float | None = None
    hash_match: bool = False
    rating: float | None = None
    downloads: int | None = None
    trusted: bool = False
    kind: str = "full"
    file_id: int = 0
    format: str = "srt"
    match_basis: str = "needs_preview"
    provider: str | None = None
    identity_basis: str = "provider_ids"
    origin_id: str | None = None

    def payload(self):
        return asdict(self)


class Provider(Protocol):
    name: str

    def search(self, mapping: dict, source: dict, languages: list[str]) -> list[Candidate]: ...
    def download(self, candidate: Candidate) -> bytes: ...


class OpenSubtitles:
    name = "opensubtitlescom"

    def __init__(self, credentials: dict):
        from subliminal import region

        with _CACHE_LOCK:
            if not region.is_configured:
                region.configure("dogpile.cache.memory")
        from subliminal.providers.opensubtitlescom import (
            OpenSubtitlesComProvider,
            OpenSubtitlesComSubtitle,
        )

        class EvidenceSubtitle(OpenSubtitlesComSubtitle):
            @classmethod
            def from_response(cls, response, **kwargs):
                result = super().from_response(response, **kwargs)
                attributes = response.get("attributes", {})
                try:
                    result.provider_rating = float(attributes["ratings"])
                except KeyError, TypeError, ValueError:
                    result.provider_rating = None
                result.provider_trusted = attributes.get("from_trusted") in (True, 1, "1")
                return result

        self.adapter = OpenSubtitlesComProvider(
            username=credentials.get("username"),
            password=credentials.get("password"),
            apikey=credentials.get("api_key"),
            max_result_pages=1,
            timeout=20,
        )
        self.adapter.subtitle_class = EvidenceSubtitle
        self.request_pacer = None
        self.download_gate = None
        self.download_observer = None
        self.last_response_evidence = {}

    def initialize(self):
        self.adapter.initialize()
        request = self.adapter.session.request

        def bounded_request(method, url, **kwargs):
            deadline = time.monotonic() + 60
            segment = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            stage = {
                "login": "login",
                "subtitles": "search",
                "download": "download_link",
                "user": "account",
            }.get(segment, "api")
            kwargs["stream"] = True
            kwargs["allow_redirects"] = False
            for hop in range(4):
                if time.monotonic() >= deadline:
                    raise ProviderError("retrying")
                if self.request_pacer:
                    self.request_pacer()
                try:
                    response = request(method, url, **kwargs)
                except Exception as exc:
                    raise ProviderError(
                        evidence={
                            "origin": "transport_failure",
                            "stage": stage,
                            "exception_type": type(exc).__name__,
                        }
                    ) from None
                self.last_response_evidence = response_evidence(
                    response.status_code, response.headers, stage
                )
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                redirect = urljoin(url, response.headers.get("Location", ""))
                parsed = urlparse(redirect)
                response.close()
                if (
                    hop == 3
                    or parsed.scheme != "https"
                    or parsed.username
                    or parsed.password
                    or parsed.hostname not in {"api.opensubtitles.com", "vip-api.opensubtitles.com"}
                    or parsed.port not in {None, 443}
                ):
                    raise ProviderError("terminal_failure")
                url = redirect
                kwargs.pop("params", None)
                if response.status_code == 303 or (
                    response.status_code in {301, 302} and method.upper() == "POST"
                ):
                    method = "GET"
                    kwargs.pop("json", None)
                    kwargs.pop("data", None)
            if response.status_code == 429:
                response.close()
                raise ProviderError(
                    "rate_limited",
                    retry_seconds(response.headers.get("Retry-After")),
                    evidence=self.last_response_evidence,
                )
            content = bytearray()
            try:
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 2_000_000 or time.monotonic() >= deadline:
                        raise ProviderError("terminal_failure")
                response._content = bytes(content)
                response._content_consumed = True
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(
                    evidence={
                        "origin": "transport_failure",
                        "stage": stage,
                        "exception_type": type(exc).__name__,
                    }
                ) from None
            finally:
                response.close()
            try:
                details = response.json()
            except ValueError:
                details = {}
            message = (
                str(details.get("message", "")).casefold() if isinstance(details, dict) else ""
            )
            if response.status_code in {403, 406, 407} and (
                response.status_code == 407
                or any(
                    word in message
                    for word in ["quota", "download limit", "allowed downloads", "limit reached"]
                )
            ):
                from datetime import UTC, datetime

                from seed_agent.media_import.subtitles.quota import quota_evidence

                if response.headers.get("Retry-After") and not any(
                    details.get(k) for k in ["reset_time_utc", "reset_time"]
                ):
                    details["reset_time_utc"] = datetime.fromtimestamp(
                        time.time() + retry_seconds(response.headers["Retry-After"]), UTC
                    ).isoformat()
                if self.download_observer:
                    self.download_observer({**details, "remaining": 0})
                delay = quota_evidence(details, time.time())["reset_at"] - time.time()
                import math

                raise ProviderError(
                    "daily_quota", max(1, math.ceil(delay)), evidence=self.last_response_evidence
                )
            if response.status_code in {401, 403}:
                raise ProviderError("credentials_required", evidence=self.last_response_evidence)
            return response

        self.adapter.session.request = bounded_request

    def search(self, mapping, source, languages):
        from babelfish import Language

        from seed_agent.media_import.subtitles.languages import matches as language_matches

        requested_languages = set(languages) - {"zh"}
        if "zh" in languages:
            requested_languages.update({"zh-Hans", "zh-Hant"})
        requested = {
            Language.fromietf({"zh-Hans": "zh-CN", "zh-Hant": "zh-TW"}.get(x, x))
            for x in requested_languages
        }
        self.last_response_evidence = {}
        try:
            self.initialize()
            tv = mapping["media_type"] != "movie"
            # Multi-episode subtitles require explicit coverage not supplied by this provider.
            if tv and len(mapping["episodes"]) != 1:
                return []
            results = self.adapter.query(
                requested,
                moviehash=movie_hash(source),
                imdb_id=mapping.get("imdb_id") if not tv else None,
                show_imdb_id=mapping.get("imdb_id") if tv else None,
                tmdb_id=mapping["tmdb_id"] if not tv else None,
                show_tmdb_id=mapping["tmdb_id"] if tv else None,
                season=mapping.get("season"),
                episode=(mapping.get("episodes") or [None])[0],
                query=None,  # IDs only; never fall through to an unrelated title result.
            )
            candidates = []
            for sub in results[:100]:
                lang = str(sub.language)
                lang = {"zh-CN": "zh-Hans", "zh-TW": "zh-Hant"}.get(lang, lang)
                if not language_matches(lang, languages):
                    continue
                sid = sub.series_tmdb_id if tv else sub.movie_tmdb_id
                imdb = sub.series_imdb_id if tv else sub.movie_imdb_id
                candidates.append(
                    Candidate(
                        id=str(sub.id),
                        language=lang,
                        tmdb_id=int(sid) if sid else None,
                        imdb_id=imdb,
                        season=sub.series_season,
                        episodes=(sub.series_episode,) if sub.series_episode is not None else (),
                        release=sub.release or sub.file_name or "",
                        fps=sub.fps,
                        hash_match=sub.moviehash_match,
                        downloads=sub.download_count,
                        rating=getattr(sub, "provider_rating", None),
                        trusted=getattr(sub, "provider_trusted", False),
                        kind="forced"
                        if sub.foreign_only
                        else ("sdh" if sub.hearing_impaired else "full"),
                        file_id=sub.file_id,
                    )
                )
            return candidates
        except ProviderError:
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            evidence = {
                "origin": "adapter_failure",
                "stage": "search",
                "exception_type": type(exc).__name__,
            }
            if "auth" in name or "unauthorized" in name or "config" in name:
                raise ProviderError("credentials_required", evidence=evidence) from None
            if "limit" in name or "throttl" in name:
                raise ProviderError("quota", 86400, evidence=evidence) from None
            raise ProviderError(
                evidence={
                    "origin": "adapter_failure",
                    "stage": "search",
                    "exception_type": type(exc).__name__,
                }
            ) from None
        finally:
            self.adapter.terminate()

    def download(self, candidate):
        # Keep payload download streaming and bounded rather than using requests.content.
        link_attempted = False
        stage = "login"
        self.last_response_evidence = {}
        try:
            self.initialize()
            self.adapter.login()
            if self.download_gate:
                self.download_gate()
            link_attempted = True
            stage = "download_link"
            data = self.adapter.api_post(
                "download", {"file_id": candidate.file_id, "sub_format": "srt"}
            )
            if self.download_observer:
                self.download_observer(data)
            url = data.get("link", "")
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or not (
                    parsed.hostname == "opensubtitles.com"
                    or parsed.hostname.endswith(".opensubtitles.com")
                )
            ):
                raise ProviderError("terminal_failure")
            if self.request_pacer:
                self.request_pacer()
            deadline = time.monotonic() + 60
            stage = "payload"
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                with client.stream("GET", url) as response:
                    self.last_response_evidence = response_evidence(
                        response.status_code, response.headers, stage
                    )
                    if response.status_code == 429:
                        raise ProviderError(
                            "rate_limited",
                            retry_seconds(response.headers.get("retry-after")),
                            evidence=self.last_response_evidence,
                        )
                    response.raise_for_status()
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 2_000_000 or time.monotonic() >= deadline:
                            raise ProviderError("terminal_failure")
                    return bytes(payload)
        except ProviderError as exc:
            if not link_attempted:
                exc.payload_attempted = False
            elif not exc.payload_attempted:
                # A reserved/attempted link is never retried as a free pre-payload failure.
                exc.payload_attempted = True
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            evidence = {
                "origin": "transport_failure"
                if isinstance(exc, httpx.HTTPError)
                else "adapter_failure",
                "stage": stage,
                "exception_type": type(exc).__name__,
            }
            if "auth" in name or "unauthorized" in name:
                raise ProviderError(
                    "credentials_required", payload_attempted=link_attempted, evidence=evidence
                ) from None
            if "limit" in name or "throttl" in name:
                raise ProviderError(
                    "quota", 86400, payload_attempted=link_attempted, evidence=evidence
                ) from None
            raise ProviderError(payload_attempted=link_attempted, evidence=evidence) from None
        finally:
            self.adapter.terminate()


def retry_seconds(value):
    from datetime import UTC, datetime
    from email.utils import parsedate_to_datetime

    try:
        return max(1, min(86400, int(value)))
    except TypeError, ValueError:
        try:
            return max(
                1,
                min(86400, int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())),
            )
        except TypeError, ValueError, OverflowError:
            return 3600


def movie_hash(source):
    """OpenSubtitles 64-bit hash: exactly two 64KiB reads, with descriptor identity checks."""
    import json
    import os
    import struct
    from pathlib import Path

    from seed_agent.media_import.filesystem import parent_fd

    if not source.get("source_root") or not source.get("absolute_path"):
        return None
    with parent_fd(Path(source["source_root"]), Path(source["absolute_path"])) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            stat = os.fstat(stream.fileno())
            if (
                json.dumps([stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns])
                != source["fingerprint"]
            ):
                raise ValueError("source changed before subtitle hash")
            if stat.st_size < 131072:
                return None
            first = stream.read(65536)
            stream.seek(-65536, os.SEEK_END)
            last = stream.read(65536)
            after = os.fstat(stream.fileno())
            if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("source changed during subtitle hash")
    checksum = stat.st_size + sum(v[0] for v in struct.iter_unpack("<Q", first + last))
    return f"{checksum & 0xFFFFFFFFFFFFFFFF:016x}"
