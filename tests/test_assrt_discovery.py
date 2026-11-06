from seed_agent.media_import.subtitles.assrt import Assrt, subtitles

RELEASE = "夜王.2026.1080p.WEB-DL-GROUP.mkv"
MAPPING = {
    "media_type": "movie",
    "year": 2026,
    "tmdb_id": 123,
    "localized_title": "夜王",
    "original_title": "Night King",
    "english_title": "Night King",
}
SOURCE = {"original_release": RELEASE}


def item(sid, release="Unrelated.2026.1080p.WEB-DL", language="langchs"):
    return {"id": sid, "videoname": release, "lang": {"langlist": {language: True}}}


def provider_with(respond):
    provider = Assrt({"token": "fixture"})
    provider.check_quota = lambda: None
    calls = []

    def api(path, params):
        assert path == "/sub/search"
        calls.append(params)
        return {"sub": {"subs": respond(params)}}

    provider.api = api
    return provider, calls


def test_irrelevant_nonempty_results_continue_to_alias_and_keep_identity_barrier():
    provider, calls = provider_with(
        lambda p: [item(1)] if p["q"] != "夜王 2026" else [item(2, RELEASE)]
    )
    result = provider.search(MAPPING, SOURCE, ["zh-Hans"])
    assert [c.id for c in result] == ["1", "2"]
    assert result[0].tmdb_id is None and result[0].identity_basis == "unverified_title"
    assert result[1].tmdb_id == 123 and result[1].identity_basis == "exact_source_release"
    assert [c["q"] for c in calls] == [RELEASE[:-4], RELEASE[:-4], "夜王 2026"]
    assert [c.get("no_muxer") for c in calls] == [None, 1, None]
    assert all(c["cnt"] == 15 for c in calls)


def test_deduplicates_ids_and_queries_and_fetches_only_one_full_page():
    def respond(params):
        if params["pos"] == 15:
            return [item(1), item(99)]
        return [item(i) for i in range(1, 16)]

    provider, calls = provider_with(respond)
    result = provider.search(MAPPING, SOURCE, ["zh-Hans"])
    assert [c.id for c in result] == [str(i) for i in range(1, 16)] + ["99"]
    assert len(calls) == 5
    assert [c["pos"] for c in calls] == [0, 0, 0, 0, 15]
    assert len(calls) <= 6


def test_tv_alias_uses_episode_and_wrong_language_does_not_stop_search():
    mapping = MAPPING | {"media_type": "tv", "season": 1, "episodes": [2]}
    release = "夜王.S01E02.1080p.WEB-DL-GROUP.mkv"
    provider, calls = provider_with(
        lambda p: [item(1, release, "langeng")] if p["pos"] == 0 else []
    )
    result = provider.search(mapping, {"original_release": release}, ["zh-Hans"])
    assert result == []
    assert [c["q"] for c in calls] == [
        release[:-4],
        release[:-4],
        "夜王 S01E02",
        "Night King S01E02",
    ]
    assert [c.get("no_muxer") for c in calls] == [None, 1, None, None]


def test_short_release_skipped_but_two_han_title_query_meets_minimum():
    provider, calls = provider_with(lambda p: [])
    assert provider.search(MAPPING, {"original_release": "夜王.mkv"}, ["zh"]) == []
    assert calls[0]["q"] == "夜王 2026"
    assert all(len(c["q"]) >= 3 for c in calls)


def test_detail_parser_retains_existing_five_item_limit():
    body = {"sub": {"subs": [item(i) for i in range(15)]}}
    assert len(subtitles(body)) == 5
    assert len(subtitles(body, limit=15)) == 15


def test_nonempty_undocumented_rows_never_become_empty_corpus():
    import pytest

    from seed_agent.media_import.subtitles.provider import ProviderError

    # A live response also contained internal fileid/m_* rows, without the
    # documented subtitle id. Do not reinterpret those as safe download IDs.
    provider, calls = provider_with(lambda p: [{"fileid": 123, "m_videoname": "other"}])
    with pytest.raises(ProviderError, match="retrying") as error:
        provider.search(MAPPING, SOURCE, ["zh"])
    assert error.value.evidence["exception_type"] == "AssrtSchemaError"
    assert not error.value.payload_attempted and len(calls) <= 6
