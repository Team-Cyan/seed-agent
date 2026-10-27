import json
from dataclasses import replace

from test_media_import import media as media
from test_media_subtitles import PAYLOAD, FakeProvider, import_three

from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.pool import ProviderPool
from seed_agent.media_import.subtitles.provider import ProviderError


def embedded(media):
    import_three(media)
    engine = media[0]
    with engine.store._connect() as conn:
        rows = conn.execute("SELECT id,probe_json FROM media_source_files").fetchall()
        for sid, raw in rows:
            probe = json.loads(raw)
            probe["streams"] = [{"codec_type": "subtitle", "tags": {"language": "zh-cn"}}]
            conn.execute(
                "UPDATE media_source_files SET probe_json=? WHERE id=?", (json.dumps(probe), sid)
            )
    engine.config.subtitle_policy = "execute"
    return engine


class NoResult(FakeProvider):
    name = "opensubtitlescom"

    def search(self, *args):
        self.calls += 1
        if self.error:
            raise self.error
        return []


def state(engine, source_id=None):
    values = engine.snapshot()["subtitles"]
    row = next(
        j
        for j in values
        if (j["attempts"] > 0 if source_id is None else j["source_id"] == source_id)
    )
    return row, json.loads(row["payload_json"])


def test_embedded_coverage_never_becomes_external_search_or_download_success(media):
    engine = embedded(media)
    provider = NoResult()
    SubtitleJobs(engine, ProviderPool([provider])).run(limit=1)
    row, data = state(engine)
    assert row["status"] == "satisfied"  # retained legacy aggregate for compatibility
    assert data["coverage_state"] == "present" and data["external_state"] == "missing"
    assert data["external_count"] == 0 and data["downloaded"] == []
    assert data["search_state"] == "complete" and data["search_outcome"] == "no_result"
    assert data["last_search_at"] > 0 and provider.calls == 1 and provider.downloads == 0


def test_partial_retry_revisits_only_due_provider_and_never_invents_search_time(media):
    engine = embedded(media)
    now = [1000.0]
    engine.clock = lambda: now[0]
    healthy = NoResult()
    waiting = NoResult()
    waiting.name = "subdl"
    waiting.error = ProviderError("retrying", 3600)
    jobs = SubtitleJobs(engine, ProviderPool([healthy, waiting]))
    first = jobs.run(limit=1)[0]
    sid = next(j["source_id"] for j in engine.snapshot()["subtitles"] if j["id"] == first["id"])
    row, data = state(engine, sid)
    assert data["search_state"] == "partial" and data["search_outcome"] == "no_result"
    assert row["next_attempt"] < 1000 + engine.config.subtitle_refresh_seconds
    assert healthy.calls == waiting.calls == 1
    last = data["last_search_at"]
    original_gate = None
    with engine.store._connect() as conn:
        original_gate = conn.execute(
            "SELECT next_request FROM media_provider_state WHERE provider='subdl'"
        ).fetchone()[0]
        conn.execute("UPDATE media_subtitle_jobs SET next_attempt=1060 WHERE source_id=?", (sid,))
    now[0] = 1060
    # New orchestration objects reconstruct per-file provider history from SQLite.
    SubtitleJobs(engine, ProviderPool([healthy, waiting])).run(source_id=sid, limit=1)
    row, data = state(engine, sid)
    assert healthy.calls == waiting.calls == 1
    assert data["last_search_at"] == last and data["last_search_attempt_at"] == 1060
    assert row["next_attempt"] >= 4600
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT next_request FROM media_provider_state WHERE provider='subdl'"
            ).fetchone()[0]
            == original_gate
        )
    now[0] = 4602
    waiting.error = None
    SubtitleJobs(engine, ProviderPool([healthy, waiting])).run(source_id=sid, limit=1)
    assert healthy.calls == 1 and waiting.calls == 2
    assert state(engine, sid)[1]["search_state"] == "complete"


def test_only_gate_observation_does_not_count_as_a_completed_search(media):
    engine = embedded(media)
    provider = NoResult()
    provider.error = ProviderError("retrying", 3600)
    jobs = SubtitleJobs(engine, ProviderPool([provider]))
    first = jobs.run(limit=1)[0]
    row = next(j for j in engine.snapshot()["subtitles"] if j["id"] == first["id"])
    data = json.loads(row["payload_json"])
    assert data["search_state"] == "waiting" and "last_search_at" not in data
    before = provider.calls
    jobs = SubtitleJobs(engine, ProviderPool([provider]))
    jobs.run(refresh=True, source_id=row["source_id"], limit=1)
    assert provider.calls == before and "last_search_at" not in state(engine, row["source_id"])[1]


def test_legacy_upgrade_is_bounded_once_and_does_not_reset_provider_allowance(media):
    engine = embedded(media)
    jobs = SubtitleJobs(engine, ProviderPool([NoResult()]))
    jobs.run(limit=0)
    with engine.store._connect() as conn:
        for jid, raw in conn.execute("SELECT id,payload_json FROM media_subtitle_jobs").fetchall():
            data = json.loads(raw)
            data.pop("discovery_version")
            data.update(coverage_satisfied=True)
            conn.execute(
                "UPDATE media_subtitle_jobs SET status='satisfied',attempts=1,"
                "next_attempt=?,payload_json=? WHERE id=?",
                (engine.clock() + 86400, json.dumps(data), jid),
            )
        deadline = engine.clock() + 3600
        conn.execute(
            "INSERT INTO media_provider_state VALUES('opensubtitlescom',?,'retrying')", (deadline,)
        )
    provider = NoResult()
    SubtitleJobs(engine, ProviderPool([provider])).run(limit=1)
    assert provider.calls == 0
    assert all(
        json.loads(j["payload_json"])["discovery_version"] == 1
        for j in engine.snapshot()["subtitles"]
    )
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT next_request FROM media_provider_state WHERE provider='opensubtitlescom'"
            ).fetchone()[0]
            == deadline
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM media_events WHERE event='subtitle_discovery_state_upgraded'"
            ).fetchone()[0]
            == 3
        )
    SubtitleJobs(engine, ProviderPool([provider])).run(limit=1)
    with engine.store._connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM media_events WHERE event='subtitle_discovery_state_upgraded'"
            ).fetchone()[0]
            == 3
        )


def test_compatible_alternatives_continue_to_shared_cap_without_daily_wait(media):
    engine = embedded(media)
    engine.config.profiles[0].max_subtitles = 3
    now = [1000.0]
    engine.clock = lambda: now[0]

    class Choices(FakeProvider):
        def search(self, *args):
            base = super().search(*args)[0]
            return [replace(base, id=str(i)) for i in range(5)]

        def download(self, candidate):
            self.downloads += 1
            return PAYLOAD + b"choice " + candidate.id.encode() + b"\n"

    provider = Choices()
    sid = engine.snapshot()["sources"][0]["id"]
    for expected in range(1, 4):
        result = SubtitleJobs(engine, ProviderPool([provider])).run(source_id=sid, limit=1)
        assert len(result) == 1 and provider.downloads == expected
        row, data = state(engine, sid)
        assert data["external_count"] == expected
        if expected < 3:
            assert row["next_attempt"] <= now[0] + 60
        now[0] += 61
    assert len(list(media[2].rglob("*.srt"))) == 3
    assert provider.calls == 1  # later download turns consume the fenced result cache
    assert SubtitleJobs(engine, ProviderPool([provider])).run(source_id=sid, limit=1) == []


def test_rejection_reasons_distinguish_identity_version_and_language(media):
    engine = embedded(media)

    class Mixed(FakeProvider):
        def search(self, *args):
            c = super().search(*args)[0]
            return [
                replace(c, id="wrong", tmdb_id=999),
                replace(c, id="version", release="different encode"),
                replace(c, id="language", language="en"),
            ]

    SubtitleJobs(engine, Mixed()).run(limit=1)
    _, data = state(engine)
    assert data["candidate_reason_counts"] == {
        "work_id_conflict": 1,
        "version_unproven": 1,
        "language_mismatch": 1,
    }
    assert data["search_outcome"] == "version_review" and data["downloaded"] == []


def test_candidate_cache_survives_provider_reconstruction_and_refreshes_only_if_required(media):
    engine = embedded(media)
    now = [1000.0]
    engine.clock = lambda: now[0]
    sid = engine.snapshot()["sources"][0]["id"]
    searches = []
    downloads = []

    class Expiring(FakeProvider):
        name = "subdl"

        def __init__(self):
            self.available = set()

        def search(self, *args):
            searches.append(now[0])
            base = super().search(*args)[0]
            self.available = {"a", "b"}
            return [replace(base, id="a"), replace(base, id="b")]

        def restore_candidate(self, candidate):
            if candidate.id not in self.available:
                raise ProviderError("candidate_refresh_required", 60, payload_attempted=False)

        def download(self, candidate):
            downloads.append(candidate.id)
            return PAYLOAD + candidate.id.encode() + b"\n"

    SubtitleJobs(engine, ProviderPool([Expiring()])).run(source_id=sid, limit=1)
    assert len(searches) == len(downloads) == 1
    now[0] += 61
    SubtitleJobs(engine, ProviderPool([Expiring()])).run(source_id=sid, limit=1)
    assert len(searches) == len(downloads) == 1
    row, data = state(engine, sid)
    assert data["provider_search"]["subdl"]["refresh_required"]
    assert row["next_attempt"] <= now[0] + 60
    now[0] += 61
    SubtitleJobs(engine, ProviderPool([Expiring()])).run(source_id=sid, limit=1)
    assert len(searches) == len(downloads) == 2


def test_cached_available_choices_download_across_fresh_provider_objects_without_research(media):
    engine = embedded(media)
    now = [1000.0]
    engine.clock = lambda: now[0]
    sid = engine.snapshot()["sources"][0]["id"]
    searches = []
    downloads = []
    restores = []

    class Durable(FakeProvider):
        def search(self, *args):
            searches.append(now[0])
            c = super().search(*args)[0]
            return [replace(c, id="a"), replace(c, id="b")]

        def restore_candidate(self, candidate):
            restores.append(candidate.id)

        def download(self, candidate):
            downloads.append(candidate.id)
            return PAYLOAD + candidate.id.encode() + b"\n"

    for _ in range(2):
        SubtitleJobs(engine, ProviderPool([Durable()])).run(source_id=sid, limit=1)
        now[0] += 61
    assert len(searches) == 1 and len(downloads) == len(restores) == 2
    assert len(set(downloads)) == 2 and state(engine, sid)[1]["external_count"] == 2


def test_pending_cached_choice_uses_real_download_retry_not_daily_search_refresh(media):
    engine = embedded(media)
    now = [1000.0]
    engine.clock = lambda: now[0]
    sid = engine.snapshot()["sources"][0]["id"]
    searches = []
    downloads = []

    class Temporary(FakeProvider):
        name = "opensubtitlescom"

        def search(self, *args):
            searches.append(now[0])
            return super().search(*args)

        def download(self, candidate):
            if now[0] < 4600:
                raise ProviderError(
                    "daily_quota",
                    3600,
                    payload_attempted=False,
                    evidence={"origin": "download_budget", "stage": "quota"},
                )
            downloads.append(candidate.id)
            return PAYLOAD

    SubtitleJobs(engine, ProviderPool([Temporary()])).run(source_id=sid, limit=1)
    row, data = state(engine, sid)
    assert row["next_attempt"] <= 4600 and data["download_retry_at"]["opensubtitlescom"] == 4600
    now[0] = 4601
    SubtitleJobs(engine, ProviderPool([Temporary()])).run(source_id=sid, limit=1)
    assert len(searches) == len(downloads) == 1
