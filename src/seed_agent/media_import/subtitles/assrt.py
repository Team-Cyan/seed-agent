"""Original ASSRT API adapter; title-only identity and unknown Chinese script stay untrusted."""

import math
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from seed_agent.media_import.subtitles.http import Transport
from seed_agent.media_import.subtitles.languages import matches as language_matches
from seed_agent.media_import.subtitles.provider import Candidate, ProviderError


def normalized_release(value):
    if Path(value).suffix.lower() in {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov", ".webm"}:
        value = Path(value).stem
    return re.sub(r"[^\w]", "", value).casefold()


def source_release_bound(release, mapping, source):
    original = source["original_release"]

    # Only a full, identical release with title+technical evidence can bind the
    # already-confirmed source identity. A generic episode/title is never an ID.
    def norm(value):
        return re.sub(r"[\W_]", "", str(value)).casefold()

    aliases = [mapping.get(k) for k in ["original_title", "localized_title", "english_title"]]
    title = any(v and len(norm(v)) >= 3 and norm(v) in norm(original) for v in aliases)
    technical = bool(re.search(r"(?i)\b(?:720p|1080p|2160p|bluray|web[ ._-]?dl|hdtv)\b", original))
    same = normalized_release(release) == normalized_release(original)
    if mapping["media_type"] == "movie":
        numbering = str(mapping["year"]) in original
    else:
        token = re.search(r"(?i)S(\d{1,2})E(\d{1,3})(?:[-.]?E(\d{1,3}))?", original)
        numbering = bool(
            token
            and int(token[1]) == mapping["season"]
            and list(range(int(token[2]), int(token[3] or token[2]) + 1)) == mapping["episodes"]
        )
    return bool(same and title and technical and numbering and len(norm(original)) >= 20)


def languages(item):
    language = item.get("lang") or {}
    flags = language.get("langlist") or {}
    desc = str(language.get("desc") or "")
    result = []
    if flags.get("langchs") or re.search(r"简体|簡體|\bchs\b", desc, re.I):
        result.append("zh-Hans")
    if flags.get("langcht") or re.search(r"繁体|繁體|\bcht\b", desc, re.I):
        result.append("zh-Hant")
    if flags.get("langeng") or re.search(r"\benglish\b|英文", desc, re.I):
        result.append("en")
    if "zh-Hans" in result and "zh-Hant" in result:
        result = [v for v in result if v not in {"zh-Hans", "zh-Hant"}] + ["zh"]
    if not result and (flags.get("langchn") or re.search(r"中文|汉语|漢語|chinese", desc, re.I)):
        result = ["zh"]
    return result or ["unknown"]


def subtitles(body):
    values = body.get("sub", {}).get("subs")
    # The live API serializes an empty PHP collection as {}.
    if values == {} or values is None:
        return []
    if not isinstance(values, list):
        raise ProviderError("retrying", 60, payload_attempted=False)
    return values[:5]


class Assrt:
    name = "assrt"
    min_interval_seconds = 3
    request_pacer = None
    interval_observer = None

    def __init__(self, credentials):
        token = credentials.get("token")
        if not isinstance(token, str) or not token.strip():
            raise ProviderError("credentials_required", payload_attempted=False)
        self.http = Transport("https://api.assrt.net/v1", token, payload_hosts=())
        self.http.pacer = lambda: self.request_pacer() if self.request_pacer else None
        self.checked = 0
        self.quota_per_minute = None
        self.available = {}

    def api(self, path, params=None):
        body = self.http.get(path, params)
        code = body.get("status")
        if code == 0:
            return body
        if code in {1, 20001}:
            raise ProviderError("credentials_required", payload_attempted=False)
        if code == 30900:
            raise ProviderError("rate_limited", 60, payload_attempted=False)
        if code == 20900:
            return {"sub": {"subs": []}}
        raise ProviderError("retrying", 60, payload_attempted=False)

    def check_quota(self):
        if self.checked and time.monotonic() - self.checked < 60:
            return
        quota = self.api("/user/quota").get("user", {}).get("quota")
        if type(quota) is not int or quota <= 0:
            raise ProviderError("rate_limited", 60, payload_attempted=False)
        self.quota_per_minute = quota
        self.min_interval_seconds = max(3, math.ceil(60 / min(20, quota)))
        if self.interval_observer:
            self.interval_observer(self.min_interval_seconds)
        self.checked = time.monotonic()

    def search(self, mapping, source, languages_requested):
        self.check_quota()
        query = Path(source["original_release"]).stem
        items = subtitles(self.api("/sub/search", {"q": query, "cnt": 5, "pos": 0}))
        if not items:
            query = (
                (mapping.get("localized_title") or mapping["original_title"])
                + " "
                + str(mapping["year"])
            )
            if mapping["media_type"] != "movie":
                query += f" S{mapping['season']:02d}E{mapping['episodes'][0]:02d}"
            items = subtitles(self.api("/sub/search", {"q": query, "cnt": 5, "pos": 0}))
        output = []
        for item in items:
            sid = str(item.get("id", ""))
            if not re.fullmatch(r"\d{1,12}", sid):
                continue
            release = str(item.get("videoname") or "")[:512]
            bound = source_release_bound(release, mapping, source)
            self.available[sid] = True  # Never retain signed download URLs.
            for language in languages(item):
                if not language_matches(language, languages_requested) and language not in {
                    "zh",
                    "unknown",
                }:
                    continue
                output.append(
                    Candidate(
                        id=sid,
                        provider=self.name,
                        language=language,
                        tmdb_id=mapping["tmdb_id"] if bound else None,
                        season=mapping.get("season") if bound else None,
                        episodes=tuple(mapping.get("episodes", [])) if bound else (),
                        release=release,
                        identity_basis="exact_source_release" if bound else "unverified_title",
                        rating=item.get("vote_score")
                        if isinstance(item.get("vote_score"), (int, float))
                        else None,
                    )
                )
        return output

    def download(self, candidate):
        if candidate.id not in self.available:
            raise ProviderError("retrying", payload_attempted=False)
        items = subtitles(self.api("/sub/detail", {"id": candidate.id}))
        item = next((i for i in items if str(i.get("id")) == candidate.id), None)
        if not item:
            raise ProviderError("retrying", payload_attempted=False)
        files = item.get("filelist") or []
        if len(files) > 1:
            raise ProviderError("unsupported_archive", payload_attempted=False)
        chosen = files[0] if files else item
        filename = str(chosen.get("f") or chosen.get("filename") or "")
        if Path(filename).suffix.lower() not in {".srt", ".ass", ".vtt", ".zip"}:
            raise ProviderError("unsupported_archive", payload_attempted=False)
        parsed = urlparse(str(chosen.get("url") or ""))
        if (
            not parsed.hostname
            or not parsed.hostname.endswith(".assrt.net")
            or parsed.username
            or parsed.password
        ):
            raise ProviderError("terminal_failure", payload_attempted=False)
        # Old documented links use HTTP; try only authenticated TLS transport to
        # the same official host. Never fall back to plaintext or another domain.
        url = urlunparse(parsed._replace(scheme="https"))
        self.http.payload_hosts.add(parsed.hostname)
        return self.http.payload(url)
