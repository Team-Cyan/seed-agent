"""Experimental opt-in HTML source; current site parsing/download is unverified."""

import re
import time
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from seed_agent.media_import.subtitles.assrt import source_release_bound
from seed_agent.media_import.subtitles.evidence import response_evidence
from seed_agent.media_import.subtitles.languages import matches as language_matches
from seed_agent.media_import.subtitles.provider import Candidate, ProviderError, retry_seconds

_SITE_HOSTS = {"zimuku.org", "srtku.com"}
_PAYLOAD_HOST = "s.zimuku.org"
_ID = re.compile(r"[0-9]{1,12}\Z")


def _valid_url(url, hosts):
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in hosts
            and not parsed.username
            and not parsed.password
            and parsed.port in {None, 443}
        )
    except ValueError:
        return False


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.hidden = 0
        self.rows = []
        self.row = None
        self.stack = []
        self.anchors = []
        self.node_count = 0
        self.row_anchor = None

    def handle_starttag(self, tag, attrs):
        self.node_count += 1
        if self.node_count > 10000 or len(self.stack) >= 64:
            raise ValueError("HTML structural bound exceeded")
        if tag == "a" and len(self.anchors) >= 1000:
            raise ValueError("HTML anchor bound exceeded")
        attrs = dict(attrs)
        if tag == "tr":
            self.row = {"links": [], "languages": []}
            self.rows.append(self.row)
        if tag == "img" and self.row is not None:
            self.row["languages"].append(
                " ".join(attrs.get(k, "") for k in ("title", "alt", "src"))
            )
        if tag == "a":
            self.anchors.append((attrs, tuple(self.stack)))
            if self.row is not None:
                self.row["links"].append(attrs)
                self.row_anchor = attrs
                attrs["_text"] = ""
        if tag not in {"img", "br", "input", "meta", "link", "hr"}:
            self.stack.append((tag, attrs))
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "tr", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")
        if tag == "a":
            self.links.append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "a":
            self.row_anchor = None
        if tag == "tr":
            self.row = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "li", "tr", "td", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.row_anchor is not None:
                self.row_anchor["_text"] += data

    @property
    def text(self):
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def _parse(data, stage):
    try:
        html = data.decode("utf-8")
        page = _Page()
        page.feed(html)
    except UnicodeError, ValueError:
        raise ProviderError(
            "retrying",
            payload_attempted=False,
            evidence={
                "origin": "adapter_failure",
                "stage": stage,
                "exception_type": "ZimukuLayoutError",
            },
        ) from None
    if re.search(r"captcha|验证码|人机验证|verify you are human|cloudflare|verifyimg", html, re.I):
        raise ProviderError(
            "retrying",
            payload_attempted=False,
            evidence={
                "origin": "adapter_failure",
                "stage": stage,
                "exception_type": "ZimukuChallengeError",
            },
        )
    if re.search(r"请先登录|登录后|login required", page.text, re.I):
        raise ProviderError(
            "credentials_required",
            payload_attempted=False,
            evidence={"origin": "adapter_failure", "stage": stage},
        )
    return page


def _field(text, names):
    match = re.search(r"(?im)^\s*(?:" + names + r")\s*[:：]\s*([^\n]+)", text)
    return match.group(1).strip() if match else ""


def _layout(stage):
    return ProviderError(
        "retrying",
        payload_attempted=False,
        evidence={
            "origin": "adapter_failure",
            "stage": stage,
            "exception_type": "ZimukuLayoutError",
        },
    )


def _download_anchor(attrs, parents):
    return attrs.get("id") == "down1" or any(
        tag == "li" and "dlsub" in parent.get("class", "").split() for tag, parent in parents
    )


class Zimuku:
    name = "zimuku"
    min_interval_seconds = 5
    request_pacer = None

    def __init__(self, credentials=None):
        self.available = set()
        self.last_response_evidence = {}

    def _get(self, url, *, stage, hosts, budget=None, payload=False, client=None, referer=None):
        if client is None:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                return self._get(
                    url,
                    stage=stage,
                    hosts=hosts,
                    budget=budget,
                    payload=payload,
                    client=client,
                    referer=referer,
                )
        deadline = time.monotonic() + 60
        attempted = False
        try:
            if client:
                for hop in range(3):
                    if not _valid_url(url, hosts):
                        raise ProviderError("terminal_failure", payload_attempted=attempted)
                    if budget is not None:
                        if budget[0] <= 0:
                            raise ProviderError(
                                "retrying",
                                payload_attempted=False,
                                evidence={
                                    "origin": "adapter_failure",
                                    "stage": stage,
                                    "exception_type": "ZimukuRequestBudgetError",
                                },
                            )
                        budget[0] -= 1
                    if self.request_pacer:
                        self.request_pacer()
                    if payload and not attempted:
                        attempted = True
                    with client.stream(
                        "GET",
                        url,
                        headers={
                            "User-Agent": "seed-agent subtitles",
                            **({"Referer": referer} if referer else {}),
                        },
                    ) as response:
                        self.last_response_evidence = response_evidence(
                            response.status_code, response.headers, stage
                        )
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if hop == 2 or not response.headers.get("location"):
                                raise ProviderError("retrying", payload_attempted=attempted)
                            referer, url = url, urljoin(url, response.headers["location"])
                            continue
                        if response.status_code == 429:
                            raise ProviderError(
                                "rate_limited",
                                retry_seconds(response.headers.get("retry-after")),
                                payload_attempted=attempted,
                                evidence=self.last_response_evidence,
                            )
                        if response.status_code in {401, 403}:
                            raise ProviderError(
                                "credentials_required"
                                if response.status_code == 401
                                else "retrying",
                                payload_attempted=attempted,
                                evidence=self.last_response_evidence,
                            )
                        if response.status_code == 404 and any(
                            mime in response.headers.get("content-type", "").casefold()
                            for mime in ("text/html", "application/xhtml+xml")
                        ):
                            error_body = bytearray()
                            for chunk in response.iter_bytes():
                                error_body.extend(chunk)
                                if len(error_body) > 2_000_000 or time.monotonic() >= deadline:
                                    raise ProviderError(
                                        "terminal_failure", payload_attempted=attempted
                                    )
                            if re.search(
                                r"captcha|验证码|人机验证|verify you are human|"
                                r"cloudflare|verifyimg",
                                error_body.decode("utf-8", errors="replace"),
                                re.I,
                            ):
                                raise ProviderError(
                                    "retrying",
                                    payload_attempted=attempted,
                                    evidence={
                                        **self.last_response_evidence,
                                        "exception_type": "ZimukuChallengeError",
                                    },
                                )
                        if response.status_code >= 400:
                            raise ProviderError(
                                "retrying",
                                payload_attempted=attempted,
                                evidence=self.last_response_evidence,
                            )
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > 2_000_000 or time.monotonic() >= deadline:
                                raise ProviderError("terminal_failure", payload_attempted=attempted)
                        if payload and any(
                            mime in response.headers.get("content-type", "").casefold()
                            for mime in ["text/html", "application/xhtml+xml"]
                        ):
                            raise ProviderError(
                                "retrying",
                                payload_attempted=True,
                                evidence={
                                    "origin": "adapter_failure",
                                    "stage": stage,
                                    "exception_type": "ZimukuHtmlPayloadError",
                                },
                            )
                        return bytes(content)
        except httpx.HTTPError as exc:
            raise ProviderError(
                "retrying",
                payload_attempted=attempted,
                evidence={
                    "origin": "transport_failure",
                    "stage": stage,
                    "exception_type": type(exc).__name__,
                },
            ) from None
        raise ProviderError("retrying", payload_attempted=attempted)

    def search(self, mapping, source, languages_requested):
        queries = []
        for key in ("localized_title", "original_title", "english_title"):
            title = mapping.get(key)
            if (
                isinstance(title, str)
                and title.strip()
                and title.strip().casefold() not in {q.casefold() for q in queries}
            ):
                queries.append(title.strip())
        if not queries:
            raise ProviderError("retrying", payload_attempted=False)
        budget = [10]  # two searches, three works, five details, including redirects
        works = {}
        entries = {}
        output = []
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            for query in queries[:2]:
                url = "https://zimuku.org/search?" + urlencode({"q": query, "chost": "zimuku.org"})
                page = _parse(
                    self._get(url, stage="search", hosts=_SITE_HOSTS, budget=budget, client=client),
                    "search",
                )
                links = []
                for link in page.links:
                    absolute = urljoin(url, link)
                    if _valid_url(absolute, _SITE_HOSTS) and re.fullmatch(
                        r"/subs/[0-9]{1,12}\.html", urlsplit(absolute).path
                    ):
                        links.append(absolute)
                        works.setdefault(absolute, url)
                if not links and not (
                    "字幕库" in page.text
                    and re.search(
                        r"没有找到|未找到|无搜索结果|没有相关字幕|no results found", page.text, re.I
                    )
                ):
                    raise _layout("search")
            for url, referer in list(works.items())[:3]:
                page = _parse(
                    self._get(
                        url,
                        stage="details",
                        hosts=_SITE_HOSTS,
                        budget=budget,
                        client=client,
                        referer=referer,
                    ),
                    "details",
                )
                found = False
                for row in page.rows:
                    for link in row["links"]:
                        absolute = urljoin(url, link.get("href", ""))
                        match = re.fullmatch(
                            r"/detail/([0-9]{1,12})\.html", urlsplit(absolute).path
                        )
                        if match and _valid_url(absolute, _SITE_HOSTS):
                            found = True
                            entries.setdefault(
                                match[1],
                                (
                                    absolute,
                                    url,
                                    (
                                        link.get("title", "").strip()
                                        or link.get("_text", "").strip()
                                    )[:512],
                                    " ".join(row["languages"]),
                                ),
                            )
                if not found:
                    raise _layout("details")
            for sid, (url, referer, row_release, language_text) in list(entries.items())[:5]:
                try:
                    page = _parse(
                        self._get(
                            url,
                            stage="details",
                            hosts=_SITE_HOSTS,
                            budget=budget,
                            client=client,
                            referer=referer,
                        ),
                        "details",
                    )
                except ProviderError as exc:
                    if output and exc.evidence.get("exception_type") == "ZimukuRequestBudgetError":
                        break
                    raise
                release = (_field(page.text, r"版本|影片版本|release") or row_release)[:512]
                language_text += " " + _field(page.text, r"语言|字幕语言|language")
                fps_text = _field(page.text, r"帧率|fps")
                imdb_text = _field(page.text, r"IMDb|IMDb链接|IMDb编号")
                if not any(_download_anchor(a, parents) for a, parents in page.anchors):
                    raise _layout("details")
                simplified = bool(
                    re.search(
                        r"简体|簡體|\bchs\b|(?:^|/)china(?:\.[a-z]+)?(?:\s|$)", language_text, re.I
                    )
                )
                traditional = bool(
                    re.search(
                        r"繁体|繁體|\bcht\b|(?:^|/)hongkong(?:\.[a-z]+)?(?:\s|$)",
                        language_text,
                        re.I,
                    )
                )
                language = (
                    "zh"
                    if simplified and traditional
                    else "zh-Hans"
                    if simplified
                    else "zh-Hant"
                    if traditional
                    else "zh"
                    if re.search(r"中文|汉语|漢語|chinese", language_text, re.I)
                    else "en"
                    if re.search(
                        r"英文|英语|english",
                        language_text,
                        re.I,
                    )
                    else "unknown"
                )
                if not language_matches(language, languages_requested) and language not in {
                    "zh",
                    "unknown",
                }:
                    continue
                fps_match = re.fullmatch(
                    r"\s*(\d{1,3}(?:\.\d{1,3})?)\s*(?:fps)?\s*", fps_text, re.I
                )
                fps = float(fps_match[1]) if fps_match and 0 < float(fps_match[1]) <= 240 else None
                imdb_match = re.search(r"\btt\d{5,12}\b", imdb_text, re.I)
                bound = bool(release and source_release_bound(release, mapping, source))
                self.available.add(sid)
                output.append(
                    Candidate(
                        id=sid,
                        provider=self.name,
                        language=language,
                        release=release,
                        fps=fps,
                        imdb_id=imdb_match[0].lower() if imdb_match and bound else None,
                        tmdb_id=mapping["tmdb_id"] if bound else None,
                        season=mapping.get("season") if bound else None,
                        episodes=tuple(mapping.get("episodes", [])) if bound else (),
                        identity_basis="exact_source_release" if bound else "unverified_title",
                    )
                )
        return output

    def restore_candidate(self, candidate):
        if not _ID.fullmatch(candidate.id):
            raise ProviderError("candidate_refresh_required", 60, payload_attempted=False)
        self.available.add(candidate.id)

    def download(self, candidate):
        if candidate.id not in self.available or not _ID.fullmatch(candidate.id):
            raise ProviderError("candidate_refresh_required", 60, payload_attempted=False)
        detail = f"https://zimuku.org/detail/{candidate.id}.html"
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            page = _parse(
                self._get(detail, stage="details", hosts=_SITE_HOSTS, client=client), "details"
            )
            links = [
                urljoin(detail, a.get("href", ""))
                for a, parents in page.anchors
                if _download_anchor(a, parents)
            ]
            links = [
                link
                for link in links
                if _valid_url(link, _SITE_HOSTS)
                and re.fullmatch(r"/dld/[0-9]{1,12}\.html", urlsplit(link).path)
            ]
            if not links:
                raise _layout("details")
            url = links[0]
            page = _parse(
                self._get(
                    url, stage="download_link", hosts=_SITE_HOSTS, client=client, referer=detail
                ),
                "download_link",
            )
            links = [
                urljoin(url, link)
                for link in page.links
                if _valid_url(urljoin(url, link), {_PAYLOAD_HOST})
                or (
                    _valid_url(urljoin(url, link), {"zimuku.org"})
                    and urlsplit(urljoin(url, link)).path.startswith("/download/")
                )
            ]
            if not links:
                raise _layout("download_link")
            if urlsplit(links[0]).path.lower().endswith(".rar"):
                raise ProviderError("unsupported_archive", payload_attempted=False)
            return self._get(
                links[0],
                stage="payload",
                hosts={_PAYLOAD_HOST, "zimuku.org"},
                payload=True,
                client=client,
                referer=url,
            )
