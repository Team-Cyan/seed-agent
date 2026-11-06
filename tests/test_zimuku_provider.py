# Reconstructed from public reference implementations; not captured live site HTML.
import httpx
import pytest

from seed_agent.media_import.subtitles.provider import Candidate, ProviderError
from seed_agent.media_import.subtitles.zimuku import Zimuku, _valid_url

MAPPING = {
    "media_type": "movie",
    "year": 2026,
    "tmdb_id": 123,
    "localized_title": "夜王",
    "original_title": "Night King",
}
RELEASE = "夜王.2026.1080p.WEB-DL-GROUP.mkv"
SOURCE = {"original_release": RELEASE}


def use_http(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(
        "seed_agent.media_import.subtitles.zimuku.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_search_bounded_deduplicated_identity_and_fps(monkeypatch):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/search":
            return httpx.Response(200, text='<a href="/subs/1.html">work</a>')
        if request.url.path == "/subs/1.html":
            return httpx.Response(
                200,
                text="<table><tbody>"
                + "".join(
                    f'<tr><td><a href="/detail/{i}.html" '
                    f'title="{RELEASE if i == 1 else "Other.2026"}">sub</a></td>'
                    '<td><img src="/img/china.png"></td></tr>'
                    for i in range(1, 9)
                )
                + "</tbody></table>",
            )
        release = RELEASE if request.url.path == "/detail/1.html" else "Other.2026.1080p.WEB-DL"
        return httpx.Response(
            200,
            text=f"<div>版本: {release}</div><div>语言: 简体</div>"
            "<div>帧率: 23.976 fps</div><div>IMDb: tt1234567</div>"
            '<a id="down1" href="/dld/1.html">download</a>',
        )

    use_http(monkeypatch, handler)
    provider = Zimuku()
    pacing = []
    provider.request_pacer = lambda: pacing.append(1)
    result = provider.search(MAPPING, SOURCE, ["zh-Hans"])
    assert len(requests) == len(pacing) == 8
    assert len(result) == 5 and result[0].tmdb_id == 123
    assert result[0].fps == 23.976 and result[0].imdb_id == "tt1234567"
    assert result[1].tmdb_id is None and result[1].imdb_id is None
    assert result[1].identity_basis == "unverified_title"


def test_challenge_unknown_and_true_empty(monkeypatch):
    response = ["<html>unexpected layout</html>"]
    use_http(monkeypatch, lambda request: httpx.Response(200, text=response[0]))
    provider = Zimuku()
    for html in ["<html>unexpected layout</html>", "<html>验证码</html>"]:
        response[0] = html
        with pytest.raises(ProviderError, match="retrying") as error:
            provider.search(MAPPING, SOURCE, ["zh"])
        assert not error.value.payload_attempted
    response[0] = "<h1>字幕库</h1><p>没有找到相关字幕</p>"
    assert provider.search(MAPPING, SOURCE, ["zh"]) == []


def test_redirect_host_security_and_rate_limit(monkeypatch):
    response = [httpx.Response(302, headers={"Location": "https://evil.test/path"})]
    use_http(monkeypatch, lambda request: response[0])
    provider = Zimuku()
    with pytest.raises(ProviderError, match="terminal_failure"):
        provider.search(MAPPING, SOURCE, ["zh"])
    response[0] = httpx.Response(429, headers={"Retry-After": "30"})
    with pytest.raises(ProviderError, match="rate_limited"):
        provider.search(MAPPING, SOURCE, ["zh"])
    assert not _valid_url("https://zimuku.org.evil.test/", {"zimuku.org"})
    assert not _valid_url("https://u:p@zimuku.org/", {"zimuku.org"})
    assert not _valid_url("https://zimuku.org:444/", {"zimuku.org"})


def test_download_resolves_fresh_allowed_link_and_restores_id(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path.startswith("/detail/"):
            return httpx.Response(
                200,
                text='<a id="down1" href="/dld/123.html">download</a>',
                headers={"Set-Cookie": "session=test; Path=/"},
            )
        if request.url.host == "zimuku.org":
            assert request.headers.get("cookie") == "session=test"
            assert request.headers.get("referer", "").endswith("/detail/123.html")
            return httpx.Response(
                200, text='<a href="https://s.zimuku.org/a.zip?sig=secret">get</a>'
            )
        return httpx.Response(200, content=b"PK\x03\x04fixture")

    use_http(monkeypatch, handler)
    provider = Zimuku()
    candidate = Candidate(id="123", language="zh")
    provider.restore_candidate(candidate)
    assert provider.download(candidate).startswith(b"PK")
    assert calls[0].endswith("/detail/123.html") and len(calls) == 3
    assert provider.available == {"123"}
    with pytest.raises(ProviderError, match="candidate_refresh_required"):
        provider.restore_candidate(Candidate(id="../secret", language="zh"))


def test_rar_rejected_before_payload(monkeypatch):
    use_http(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            text='<a id="down1" href="/dld/1.html">get</a>'
            if request.url.path.startswith("/detail/")
            else '<a href="https://s.zimuku.org/file.rar">get</a>',
        ),
    )
    provider = Zimuku()
    candidate = Candidate(id="1", language="zh")
    provider.restore_candidate(candidate)
    with pytest.raises(ProviderError, match="unsupported_archive") as error:
        provider.download(candidate)
    assert not error.value.payload_attempted


def test_redirects_consume_search_budget_and_pacing(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "/again"})

    use_http(monkeypatch, handler)
    provider = Zimuku()
    pacing = []
    provider.request_pacer = lambda: pacing.append(1)
    with pytest.raises(ProviderError, match="retrying"):
        provider.search(MAPPING, SOURCE, ["zh"])
    assert len(calls) == len(pacing) == 3


def test_payload_size_is_bounded(monkeypatch):
    use_http(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 2_000_001))
    provider = Zimuku()
    with pytest.raises(ProviderError, match="terminal_failure") as error:
        provider._get(
            "https://s.zimuku.org/file", stage="payload", hosts={"s.zimuku.org"}, payload=True
        )
    assert error.value.payload_attempted


def test_optional_runtime_registration_needs_no_secret_and_keeps_all_four(tmp_path):
    from seed_agent.media_import.config import MediaImportConfig
    from seed_agent.media_import.runtime import build_subtitle_provider
    from seed_agent.media_import.subtitles.pool import ProviderPool

    assert build_subtitle_provider(MediaImportConfig(), tmp_path) is None
    options = MediaImportConfig(
        subtitle_providers=[
            {"name": name} for name in ["opensubtitlescom", "assrt", "subdl", "zimuku"]
        ]
    )
    pool = build_subtitle_provider(options, tmp_path)
    assert len(pool.providers) == 4 and isinstance(pool.providers[-1], Zimuku)
    assert not hasattr(pool.providers[-1], "download_gate")
    with pytest.raises(ValueError, match="at most four"):
        ProviderPool([type("P", (), {"name": str(i)})() for i in range(5)])
    options.subtitle_providers[-1].enabled = False
    assert len(build_subtitle_provider(options, tmp_path).providers) == 3


@pytest.mark.parametrize(
    "content_type", ["text/html", "TEXT/HTML; charset=UTF-8", "application/xhtml+xml"]
)
def test_html_payload_is_explicit_failure_and_never_free_retry(monkeypatch, content_type):
    use_http(
        monkeypatch,
        lambda request: httpx.Response(
            200, text="<html>验证码</html>", headers={"Content-Type": content_type}
        ),
    )
    provider = Zimuku()
    with pytest.raises(ProviderError, match="retrying") as error:
        provider._get(
            "https://s.zimuku.org/file", stage="payload", hosts={"s.zimuku.org"}, payload=True
        )
    assert error.value.payload_attempted
    assert error.value.evidence["exception_type"] == "ZimukuHtmlPayloadError"


def test_http_404_is_not_empty_search(monkeypatch):
    use_http(monkeypatch, lambda request: httpx.Response(404, text="not found"))
    with pytest.raises(ProviderError, match="retrying") as error:
        Zimuku().search(MAPPING, SOURCE, ["zh"])
    assert error.value.evidence["http_status"] == 404
    assert not error.value.payload_attempted


def test_visible_title_and_ambiguous_language_icon(monkeypatch):
    def handler(request):
        if request.url.path == "/search":
            return httpx.Response(200, text='<a href="/subs/1.html">work</a>')
        if request.url.path == "/subs/1.html":
            return httpx.Response(
                200,
                text=(
                    f'<table><tr><td><a href="/detail/1.html"><b>{RELEASE}</b></a></td>'
                    '<td><img src="/img/jollyroger.png"></td></tr></table>'
                ),
            )
        return httpx.Response(200, text='<a id="down1" href="/dld/1.html">get</a>')

    use_http(monkeypatch, handler)
    result = Zimuku().search(MAPPING, SOURCE, ["zh-Hans"])
    assert result[0].release == RELEASE
    assert result[0].tmdb_id == 123
    assert result[0].language == "unknown"


def test_download_supports_observed_site_relative_link(monkeypatch):
    def handler(request):
        if request.url.path.startswith("/detail/"):
            return httpx.Response(200, text='<li class="dlsub"><a href="/dld/1.html">get</a></li>')
        if request.url.path.startswith("/dld/"):
            return httpx.Response(200, text='<a href="/download/file">get</a>')
        assert request.headers["referer"].endswith("/dld/1.html")
        return httpx.Response(200, content=b"PK\x03\x04fixture")

    use_http(monkeypatch, handler)
    provider = Zimuku()
    candidate = Candidate(id="1", language="zh")
    provider.restore_candidate(candidate)
    assert provider.download(candidate).startswith(b"PK")


@pytest.mark.parametrize("payload", [False, True])
def test_404_challenge_retains_status_and_attempt(monkeypatch, payload):
    use_http(
        monkeypatch,
        lambda request: httpx.Response(
            404, text="<html>验证码</html>", headers={"Content-Type": "text/html"}
        ),
    )
    with pytest.raises(ProviderError, match="retrying") as error:
        Zimuku()._get(
            "https://zimuku.org/download/1",
            stage="payload" if payload else "search",
            hosts={"zimuku.org"},
            payload=payload,
        )
    assert error.value.payload_attempted is payload
    assert error.value.evidence["http_status"] == 404
    assert error.value.evidence["exception_type"] == "ZimukuChallengeError"


@pytest.mark.parametrize("html", ["<div>" * 65, "<a></a>" * 1001, "<br>" * 10001])
def test_structural_html_limits_fail_before_unbounded_parser_growth(html):
    from seed_agent.media_import.subtitles.zimuku import _parse

    with pytest.raises(ProviderError, match="retrying") as error:
        _parse(html.encode(), "search")
    assert error.value.evidence["exception_type"] == "ZimukuLayoutError"
    assert not error.value.payload_attempted


def test_redirect_budget_preserves_already_parsed_candidates(monkeypatch):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/search":
            return httpx.Response(
                200, text="".join(f'<a href="/subs/{i}.html">work</a>' for i in range(1, 4))
            )
        if request.url.path.startswith("/subs/"):
            return httpx.Response(
                200,
                text="<table>"
                + "".join(
                    f'<tr><td><a href="/detail/{i}.html">{RELEASE}</a></td></tr>'
                    for i in range(1, 6)
                )
                + "</table>",
            )
        if request.url.path == "/detail/1.html":
            return httpx.Response(302, headers={"Location": "/detail/one"})
        return httpx.Response(
            200,
            text=f"<div>版本: {RELEASE}</div><div>语言: 简体</div>"
            '<a id="down1" href="/dld/1.html">download</a>',
        )

    use_http(monkeypatch, handler)
    result = Zimuku().search(MAPPING, SOURCE, ["zh-Hans"])
    assert len(requests) == 10
    assert [candidate.id for candidate in result] == ["1", "2", "3", "4"]
