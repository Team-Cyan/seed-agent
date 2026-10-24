from seed_agent.media_import.subtitles.assrt import Assrt
from seed_agent.media_import.subtitles.subdl import Subdl


def test_subdl_response_identity_language_release_and_quota_contract():
    provider = Subdl({"api_key": "fixture"})
    calls, observations, reservations = [], [], []
    provider.quota_observer = observations.append
    provider.download_observer = observations.append
    provider.download_gate = lambda: reservations.append(True)

    def payload(url, **kw):
        kw["before_request"]()
        return b"fixture"

    provider.http.payload = payload

    def get(path, params=None):
        calls.append((path, params))
        if path.endswith("/me"):
            return {
                "usage": {
                    "downloads": {"remaining": 7, "limit": 8, "reset_at": "2030-01-01T00:00:00Z"}
                }
            }
        assert "unpack" not in params
        assert params["languages"] == "ZH"
        return {
            "status": True,
            "results": [{"type": "movie", "tmdb_id": 603}],
            "subtitles": [
                {
                    "url": "/subtitle/123.zip",
                    "language": "ZH",
                    "comment": "Chinese (Simplified)",
                    "releases": ["release-a", "release-b"],
                }
            ],
        }

    provider.http.get = get
    values = provider.search({"media_type": "movie", "tmdb_id": 603}, {}, ["zh"])
    assert len(values) == 2
    assert all(c.language == "zh-Hans" and c.tmdb_id == 603 for c in values)
    assert all("https://" not in str(c.payload()) for c in values)
    assert provider.download(values[0]) == b"fixture"
    assert reservations == [True]
    assert len(observations) == 2
    assert observations[0]["remaining"] == 7


def test_subdl_wrong_work_or_episode_pack_is_rejected():
    provider = Subdl({"api_key": "fixture"})
    provider.checked = float("inf")
    provider.http.get = lambda *args: {
        "results": [{"type": "movie", "tmdb_id": 999}],
        "subtitles": [{"url": "/subtitle/123.zip", "language": "ZH"}],
    }
    assert provider.search({"media_type": "movie", "tmdb_id": 603}, {}, ["zh"]) == []
    provider.http.get = lambda *args: {
        "results": [{"type": "tv", "tmdb_id": 603}],
        "subtitles": [
            {
                "url": "/subtitle/123.zip",
                "language": "ZH",
                "season": 1,
                "episode": 1,
                "episode_end": 3,
            }
        ],
    }
    assert (
        provider.search(
            {"media_type": "tv", "tmdb_id": 603, "season": 1, "episodes": [1]}, {}, ["zh"]
        )
        == []
    )


def test_assrt_actual_minute_quota_and_full_release_binding():
    provider = Assrt({"token": "fixture"})
    intervals = []
    provider.interval_observer = intervals.append
    release = "The.Matrix.1999.1080p.WEB-DL-GROUP"
    provider.http.get = lambda path, params=None: (
        {"status": 0, "user": {"quota": 9}}
        if path.endswith("/quota")
        else {
            "status": 0,
            "sub": {
                "subs": [{"id": 123, "videoname": release, "lang": {"langlist": {"langchs": True}}}]
            },
        }
    )
    values = provider.search(
        {"media_type": "movie", "tmdb_id": 603, "year": 1999, "original_title": "The Matrix"},
        {"original_release": release + ".mkv"},
        ["zh-Hans"],
    )
    assert intervals == [7]
    assert provider.quota_per_minute == 9
    assert len(values) == 1
    assert values[0].tmdb_id == 603
    assert values[0].identity_basis == "exact_source_release"


def test_assrt_live_empty_collection_shape():
    from seed_agent.media_import.subtitles.assrt import subtitles

    assert subtitles({"sub": {"subs": {}}}) == []
