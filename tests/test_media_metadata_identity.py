from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from seed_agent.media_import.metadata import (
    Tmdb,
    ancillary_identity,
    identity_hints,
    identity_normalize,
)


def identify(monkeypatch, filename, records, extra=None, tmdb=None):
    calls = []
    responses = extra or {}

    def respond(request):
        endpoint = request.url.path.removeprefix("/3")
        calls.append((endpoint, dict(request.url.params)))
        if endpoint.startswith("/search/"):
            kind = endpoint.rsplit("/", 1)[1]
            query = request.url.params["query"]
            result = [r for r in records if r["kind"] == kind and query in r["queries"]]
            return httpx.Response(200, json={"results": [r["search"] for r in result]})
        if endpoint in responses:
            return httpx.Response(200, json=responses[endpoint])
        if endpoint.endswith("/alternative_titles"):
            return httpx.Response(200, json={"titles": [], "results": []})
        for record in records:
            if endpoint == f"/{record['kind']}/{record['search']['id']}":
                return httpx.Response(
                    200,
                    json={
                        "genres": [{"id": 18}],
                        "runtime": 110,
                        "external_ids": {"imdb_id": "tt1234567"},
                    },
                )
        return httpx.Response(404)

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(respond))
    )
    profile = SimpleNamespace(source_root="/media", locale="zh-CN", _mixed=True)
    mapping, candidates = (tmdb or Tmdb("fixture")).identify(Path(filename), profile)
    return mapping, candidates, calls


def record(title, year, *, queries=None, kind="movie", identity=1, local=None):
    return {
        "kind": kind,
        "queries": queries or [title],
        "search": {
            "id": identity,
            "original_title" if kind == "movie" else "original_name": title,
            "title" if kind == "movie" else "name": local or title,
            "release_date" if kind == "movie" else "first_air_date": f"{year}-01-01",
        },
    }


@pytest.mark.parametrize(
    "filename,title,year",
    [
        ("Detective.Chinatown.1900.2025.2160p.mkv", "Detective Chinatown 1900", 2025),
        ("Cold.War.1994.2026.2160p.mkv", "Cold War 1994", 2026),
        ("2001.A.Space.Odyssey.1968.1080p.mkv", "2001 A Space Odyssey", 1968),
    ],
)
def test_numbers_in_title_are_preserved_before_release_year(monkeypatch, filename, title, year):
    mapping, _, _ = identify(monkeypatch, "/media/movie/" + filename, [record(title, year)])
    assert mapping.original_title == title and mapping.year == year


@pytest.mark.parametrize(
    "filename,query",
    [
        ("[女浩克].She-Hulk.Attorney.at.Law.2022.S01E01.2160p.mkv", "She-Hulk Attorney at Law"),
        ("好东西.Her.Story.2024.2160p.mkv", "Her Story"),
        ("夜王.156分未删减.导演剪辑版.2026.1080p.mkv", "夜王"),
    ],
)
def test_bilingual_and_edition_hints_remain_separate(filename, query):
    queries, _, _ = identity_hints(Path("/media/movie/" + filename), "/media")
    assert query in queries and len(queries) <= 4
    assert "movie" not in queries


def test_accent_normalization_matches_without_fuzzy_guess(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/Joker.Folie.a.Deux.2024.mkv",
        [
            record("Joker: Folie à Deux", 2024, queries=["Joker Folie a Deux"]),
        ],
    )
    assert mapping.tmdb_id == 1


def test_latin_accent_folding_does_not_erase_japanese_voicing_or_cyrillic_letters():
    assert identity_normalize("Folie à Deux") == identity_normalize("Folie a Deux")
    assert identity_normalize("ガ") != identity_normalize("カ")
    assert identity_normalize("й") != identity_normalize("и")


def test_provider_confirmed_alternative_title_resolves_alias(monkeypatch):
    query = "Harry Potter and the Sorcerers Stone"
    mapping, candidates, _ = identify(
        monkeypatch,
        f"/media/{query}.2001.mkv",
        [
            record("Harry Potter and the Philosopher's Stone", 2001, queries=[query]),
        ],
        {
            "/movie/1/alternative_titles": {
                "titles": [
                    {"title": "Harry Potter and the Sorcerer's Stone"},
                ]
            }
        },
    )
    assert mapping.tmdb_id == 1 and mapping.original_title.endswith("Philosopher's Stone")
    assert candidates[0]["match_basis"] == "provider_alternative_title"


def test_similar_single_search_candidate_without_alias_is_not_confirmation(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/Almost.The.Same.2024.mkv",
        [
            record("Almost Same", 2024, queries=["Almost The Same"]),
        ],
    )
    assert mapping is None


def test_localized_bracket_title_can_resolve_when_combined_search_fails(monkeypatch):
    mapping, _, calls = identify(
        monkeypatch,
        "/media/[给阿嬷的情书].Dear.You.2026.mkv",
        [
            record("给阿嬷的情书", 2026, queries=["给阿嬷的情书"], local="给阿嬷的情书"),
        ],
    )
    assert mapping.original_title == "给阿嬷的情书"
    assert any(params.get("query") == "给阿嬷的情书" for _, params in calls)


def test_conflicting_bilingual_identities_remain_review_required(monkeypatch):
    mapping, candidates, _ = identify(
        monkeypatch,
        "/media/[另一部].Different.Movie.2024.mkv",
        [
            record("Different Movie", 2024),
            record("另一部", 2024, identity=2),
        ],
    )
    assert mapping is None and len([c for c in candidates if c["exact"]]) == 2


def test_bilingual_consensus_requires_official_alias_corroboration(monkeypatch):
    mapping, candidates, _ = identify(
        monkeypatch,
        "/media/[给阿嬷的情书].Dear.You.2026.mkv",
        [
            record("Dear You", 2026, identity=1),
            record("给阿嬷的情书", 2026, identity=2),
        ],
        {
            "/movie/2/translations": {
                "translations": [
                    {"iso_639_1": "en", "data": {"title": "Dear You"}},
                ]
            }
        },
    )
    assert mapping.tmdb_id == 2
    assert candidates[1]["match_basis"] == "provider_multilingual_title_consensus"


def test_explicit_episode_and_confirmed_numbering_excludes_movie_namesake(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/Severance.S01E01.mkv",
        [
            record("Severance", 2006, identity=1),
            record("Severance", 2022, identity=2, kind="tv"),
        ],
        {
            "/tv/2/season/1/episode/1": {
                "season_number": 1,
                "episode_number": 1,
                "runtime": 50,
            }
        },
    )
    assert mapping.media_type == "tv" and mapping.tmdb_id == 2


def test_explicit_episode_still_rejects_wrong_provider_numbering(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/Severance.S01E01.mkv",
        [
            record("Severance", 2022, kind="tv"),
        ],
        {
            "/tv/1/season/1/episode/1": {
                "season_number": 1,
                "episode_number": 2,
                "runtime": 50,
            }
        },
    )
    assert mapping is None


def test_alias_does_not_bypass_year_conflict(monkeypatch):
    mapping, _, calls = identify(
        monkeypatch,
        "/media/Alias.2020.mkv",
        [
            record("Other Name", 2025, queries=["Alias"]),
        ],
        {"/movie/1/alternative_titles": {"titles": [{"title": "Alias"}]}},
    )
    assert mapping is None
    assert not any(p.endswith("/alternative_titles") for p, _ in calls)


def test_known_movie_year_limits_search_without_filtering_tv_season_year(monkeypatch):
    mapping, _, calls = identify(monkeypatch, "/media/Film.2024.mkv", [record("Film", 2024)])
    assert mapping.year == 2024
    assert (
        next(p for endpoint, p in calls if endpoint == "/search/movie")["primary_release_year"]
        == "2024"
    )
    assert "first_air_date_year" not in next(p for endpoint, p in calls if endpoint == "/search/tv")


def test_tv_season_year_is_validated_but_series_root_keeps_first_air_year(monkeypatch):
    mapping, candidates, _ = identify(
        monkeypatch,
        "/media/What.If.S03E01.2024.mkv",
        [
            record("What If", 2021, kind="tv"),
        ],
        {
            "/tv/1/season/3": {"air_date": "2024-12-22"},
            "/tv/1/season/3/episode/1": {
                "season_number": 3,
                "episode_number": 1,
                "runtime": 30,
            },
        },
    )
    assert mapping.year == 2021 and mapping.season == 3 and mapping.episodes == [1]
    assert candidates[0]["year_basis"] == "provider_season_air_date"


def test_wrong_season_year_remains_unresolved(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/What.If.S03E01.2024.mkv",
        [
            record("What If", 2021, kind="tv"),
        ],
        {"/tv/1/season/3": {"air_date": "2023-01-01"}},
    )
    assert mapping is None


def test_namesake_without_requested_season_does_not_abort_correct_candidate(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/What.If.S03E01.2024.mkv",
        [
            record("What If", 2019, identity=1, kind="tv"),
            record("What If", 2021, identity=2, kind="tv"),
        ],
        {
            "/tv/2/season/3": {"air_date": "2024-12-22"},
            "/tv/2/season/3/episode/1": {
                "season_number": 3,
                "episode_number": 1,
                "runtime": 30,
            },
        },
    )
    assert mapping.tmdb_id == 2 and mapping.episodes == [1]


def test_namesake_tv_show_without_requested_episode_is_not_the_selected_work(monkeypatch):
    mapping, candidates, _ = identify(
        monkeypatch,
        "/media/The.Boys.S05E01.mkv",
        [
            record("The Boys", 1993, identity=1, kind="tv"),
            record("The Boys", 2019, identity=2, kind="tv"),
        ],
        {
            "/tv/2/season/5/episode/1": {
                "season_number": 5,
                "episode_number": 1,
                "runtime": 60,
            }
        },
    )
    assert mapping.tmdb_id == 2 and mapping.year == 2019
    assert candidates[1]["match_basis"] == "provider_episode_identity"


def test_two_tv_namesakes_with_the_same_confirmed_number_stay_ambiguous(monkeypatch):
    mapping, _, _ = identify(
        monkeypatch,
        "/media/The.Boys.S01E01.mkv",
        [
            record("The Boys", 1993, identity=1, kind="tv"),
            record("The Boys", 2019, identity=2, kind="tv"),
        ],
        {
            f"/tv/{i}/season/1/episode/1": {
                "season_number": 1,
                "episode_number": 1,
                "runtime": 60,
            }
            for i in [1, 2]
        },
    )
    assert mapping is None


def test_missing_episode_is_review_not_a_provider_availability_failure(monkeypatch):
    mapping, candidates, _ = identify(
        monkeypatch,
        "/media/Show.2024.S01E01.mkv",
        [
            record("Show", 2024, kind="tv"),
        ],
    )
    assert mapping is None and candidates[-1]["reason"] == "episode metadata unavailable"


@pytest.mark.parametrize(
    "filename",
    [
        "/media/Inland.Empire.2006.Extras-01.BDRip.1080p.mkv",
        "/media/Film.2024.sample.1080p.mkv",
        "/media/Film (2024)/Extras/Behind.the.Scenes.mkv",
    ],
)
def test_extras_do_not_become_primary_films_or_trigger_provider_calls(monkeypatch, filename):
    mapping, candidates, calls = identify(monkeypatch, filename, [])
    assert mapping is None and "ancillary" in candidates[0]["reason"]
    assert calls == []


def test_series_named_extras_is_not_mistaken_for_bonus_media():
    assert not ancillary_identity(Path("/media/Extras.2005.S01E01.mkv"), "/media")


def test_repeated_series_search_and_episode_details_use_bounded_cache(monkeypatch):
    tmdb = Tmdb("fixture")
    records = [record("Show", 2024, kind="tv")]
    extra = {
        "/tv/1/season/1/episode/1": {
            "season_number": 1,
            "episode_number": 1,
            "runtime": 30,
        }
    }
    mapping, _, first = identify(monkeypatch, "/media/Show.2024.S01E01.mkv", records, extra, tmdb)
    assert mapping.episodes == [1]
    # Restore the real constructor before installing another mock transport.
    monkeypatch.undo()
    mapping, _, second = identify(monkeypatch, "/media/Show.2024.S01E01.mkv", records, extra, tmdb)
    assert mapping.episodes == [1] and first and second == []
