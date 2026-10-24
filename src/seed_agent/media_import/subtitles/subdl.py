"""SubDL v2 header-auth API; account-proven search and download limits stay separate."""

import re
import time
from urllib.parse import urlparse

from seed_agent.media_import.subtitles.http import Transport
from seed_agent.media_import.subtitles.languages import matches as language_matches
from seed_agent.media_import.subtitles.provider import Candidate, ProviderError
from seed_agent.media_import.subtitles.quota import quota_evidence


def script(item):
    code = str(item.get("language") or "").upper()
    evidence = (
        str(item.get("comment") or "")
        + " "
        + " ".join(
            re.findall(
                r"(?i)简体|簡體|繁体|繁體|\bchs\b|\bcht\b",
                str(item.get("name") or "") + " " + str(item.get("release_name") or ""),
            )
        )
    )
    simplified = bool(re.search(r"简体|簡體|\bsimplified\b|\bchs\b", evidence, re.I))
    traditional = bool(re.search(r"繁体|繁體|\btraditional\b|\bcht\b", evidence, re.I))
    if code == "EN":
        return "en"
    if code.startswith("ZH"):
        return (
            "zh-Hans"
            if simplified and not traditional
            else "zh-Hant"
            if traditional and not simplified
            else "zh"
        )
    return "unknown"


class Subdl:
    name = "subdl"
    request_pacer = None
    download_gate = None
    download_observer = None
    quota_observer = None
    min_interval_seconds = 2

    def __init__(self, credentials):
        key = credentials.get("api_key")
        if not isinstance(key, str) or not key.strip():
            raise ProviderError("credentials_required", payload_attempted=False)
        self.http = Transport("https://api.subdl.com", key, payload_hosts={"dl.subdl.com"})
        self.http.pacer = lambda: self.request_pacer() if self.request_pacer else None
        self.available = {}
        self.checked = 0
        self.account_summary = {}

    def account(self, *, after_download=False):
        body = self.http.get("/api/v2/me")
        usage = body.get("usage") or {}
        summary = {}
        for name in ["search", "downloads"]:
            value = usage.get(name) or {}
            summary[name] = {
                k: value[k]
                for k in ["remaining", "used", "limit", "reset_at", "period"]
                if k in value
            }
        self.account_summary = summary
        self.checked = time.monotonic()
        downloads = summary.get("downloads", {})
        if type(downloads.get("remaining")) is int:
            evidence = {
                "remaining": downloads["remaining"],
                "reset_time_utc": downloads.get("reset_at"),
            }
            observer = self.download_observer if after_download else self.quota_observer
            if observer:
                observer(evidence)
        return summary

    def search(self, mapping, source, languages):
        if not self.checked or time.monotonic() - self.checked >= 300:
            self.account()
        search = self.account_summary.get("search", {})
        if search.get("remaining") == 0:
            delay = (
                quota_evidence(
                    {"remaining": 0, "reset_time_utc": search.get("reset_at")}, time.time()
                )["reset_at"]
                - time.time()
            )
            raise ProviderError("daily_quota", max(1, int(delay)), payload_attempted=False)
        if mapping["media_type"] != "movie" and len(mapping.get("episodes", [])) != 1:
            return []
        params = {
            "tmdb_id": mapping["tmdb_id"],
            "type": "movie" if mapping["media_type"] == "movie" else "tv",
            "languages": ",".join(["ZH"] + (["EN"] if "en" in languages else [])),
            "subs_per_page": 30,
            "releases": 1,
            "comment": 1,
        }
        if mapping["media_type"] != "movie":
            params.update(season=mapping["season"], episode=mapping["episodes"][0], full_season=0)
        body = self.http.get("/api/v2/subtitles/search", params)
        if body.get("status") is False:
            raise ProviderError("retrying", payload_attempted=False)
        works = body.get("results", [])[:10]
        exact = [
            w
            for w in works
            if w.get("type") == params["type"] and str(w.get("tmdb_id")) == str(mapping["tmdb_id"])
        ]
        if len(exact) != 1 or not works or works[0] not in exact:
            return []
        output = []
        for item in body.get("subtitles", [])[:100]:
            if item.get("full_season"):
                continue
            url = str(item.get("url") or "")
            parsed = urlparse("https://dl.subdl.com" + url if url.startswith("/") else url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "dl.subdl.com"
                or not parsed.path.startswith("/subtitle/")
            ):
                continue
            sid = parsed.path.removeprefix("/subtitle/").strip("/")
            if not sid or len(sid) > 200:
                continue
            language = script(item)
            if not language_matches(language, languages) and language not in {"zh", "unknown"}:
                continue
            episodes = ()
            season = None
            if params["type"] == "tv":
                season = item.get("season")
                episode = item.get("episode") or item.get("episode_from")
                end = item.get("episode_end") or episode
                if type(season) is not int or type(episode) is not int or episode != end:
                    continue
                episodes = (episode,)
            self.available[sid] = parsed.geturl()  # ephemeral, never serialized in candidates/state
            releases = item.get("releases") or [item.get("release_name") or ""]
            if not isinstance(releases, list):
                releases = [str(releases)]
            try:
                fps = float(item["fps"]) if item.get("fps") else None
            except TypeError, ValueError:
                fps = None
            for release in releases[:5]:
                output.append(
                    Candidate(
                        id=sid,
                        provider=self.name,
                        language=language,
                        tmdb_id=mapping["tmdb_id"],
                        imdb_id=exact[0].get("imdb_id"),
                        season=season,
                        episodes=episodes,
                        release=str(release)[:512],
                        fps=fps,
                        kind="sdh" if item.get("hi") else "full",
                    )
                )
        return output

    def download(self, candidate):
        url = self.available.get(candidate.id)
        if not url:
            raise ProviderError("retrying", payload_attempted=False)
        try:
            return self.http.payload(url, authenticate=True, before_request=self.download_gate)
        finally:
            # Download-link/payload failure is not a refund. Missing account evidence
            # retains the conservative reservation instead of retrying blindly.
            try:
                self.account(after_download=True)
            except ProviderError:
                pass
