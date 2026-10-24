from dataclasses import replace

import pytest
from test_media_import import media as media
from test_media_subtitles import PAYLOAD, FakeProvider, import_three

from seed_agent.media_import.config import MediaImportConfig
from seed_agent.media_import.subtitles.assrt import languages, source_release_bound
from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.languages import matches
from seed_agent.media_import.subtitles.pool import ProviderPool
from seed_agent.media_import.subtitles.provider import ProviderError
from seed_agent.media_import.subtitles.subdl import script


def test_explicit_generic_chinese_never_proves_script():
    assert script({"language": "ZH"}) == "zh"
    assert script({"language": "ZH_BG"}) == "zh"
    assert script({"language": "ZH", "comment": "Chinese (Simplified)"}) == "zh-Hans"
    assert script({"language": "ZH", "comment": "Chinese (Traditional)"}) == "zh-Hant"
    assert script({"language": "UNKNOWN", "name": "中国电影"}) == "unknown"
    assert languages({"lang": {"desc": "中文"}}) == ["zh"]
    assert languages({"lang": {}}) == ["unknown"]
    assert matches("zh", ["zh-Hans", "zh-Hant", "zh"])
    assert not matches("zh", ["zh-Hans", "zh-Hant"])
    assert not matches("unknown", ["zh"])


def test_assrt_title_only_cannot_bind_identity():
    mapping = {"media_type": "movie", "year": 1999, "original_title": "The Matrix"}
    source = {"original_release": "The.Matrix.1999.1080p.WEB-DL-GROUP.mkv"}
    assert source_release_bound("The.Matrix.1999.1080p.WEB-DL-GROUP", mapping, source)
    assert not source_release_bound("The Matrix 1999", mapping, source)
    assert not source_release_bound("The.Matrix.1999.1080p.WEB-DL-OTHER", mapping, source)


@pytest.mark.parametrize("names", [["assrt", "assrt"], ["other"]])
def test_provider_configuration_rejects_duplicate_or_unknown(names):
    with pytest.raises(ValueError):
        MediaImportConfig(subtitle_providers=[{"name": x} for x in names])


def test_one_payload_per_file_across_language_jobs(media):
    import_three(media)
    engine, _, _, _ = media
    engine.config.subtitle_policy = "execute"
    engine.config.profiles[0].languages = [["zh-Hans"], ["en"]]

    class Bilingual(FakeProvider):
        def search(self, mapping, source, languages):
            return [replace(super().search(mapping, source, languages)[0], language=languages[0])]

    provider = Bilingual()
    jobs = SubtitleJobs(engine, ProviderPool([provider]))
    result = jobs.run()
    assert provider.downloads == 3
    assert sum(r["status"] == "cycle_deferred" for r in result) == 3
    jobs.run(refresh=True)
    # Same bytes from another language/provider remain a single choice.
    assert provider.downloads == 6
    assert len(list(media[2].rglob("*.srt"))) == 3


def test_pre_payload_provider_failure_uses_other_provider(media):
    import_three(media)
    engine = media[0]
    engine.config.subtitle_policy = "execute"

    class Blocked(FakeProvider):
        name = "blocked"

        def download(self, candidate):
            raise ProviderError("daily_quota", 3600, payload_attempted=False)

    good = FakeProvider()
    pool = ProviderPool([Blocked(), good])
    result = SubtitleJobs(engine, pool).run()
    assert all(r["status"] == "satisfied" for r in result)
    assert good.downloads == 3
    assert pool.statuses["blocked"]["status"] == "daily_quota"


def test_invalid_payload_yields_to_next_candidate_next_cycle(media):
    import_three(media)
    engine = media[0]
    engine.config.subtitle_policy = "execute"

    class BrokenFirst(FakeProvider):
        def search(self, mapping, source, languages):
            base = super().search(mapping, source, languages)[0]
            return [replace(base, id="bad"), replace(base, id="good")]

        def download(self, candidate):
            self.downloads += 1
            return b"<html>error</html>" if candidate.id == "bad" else PAYLOAD

    provider = BrokenFirst()
    jobs = SubtitleJobs(engine, provider)
    assert all(r["status"] == "retrying" for r in jobs.run())
    assert provider.downloads == 3
    assert all(r["status"] == "satisfied" for r in jobs.run(refresh=True))
    assert provider.downloads == 6


def test_runtime_provider_config_keeps_missing_provider_local(tmp_path):
    import json

    from seed_agent.media_import.runtime import build_subtitle_provider
    from seed_agent.media_import.subtitles.pool import Unavailable
    from seed_agent.media_import.subtitles.subdl import Subdl

    secrets = tmp_path / "local" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "subdl.json").write_text(json.dumps({"api_key": "fixture"}))
    options = MediaImportConfig(
        subtitle_providers=[
            {"name": "assrt", "secret_ref": "local/secrets/missing.json"},
            {"name": "subdl", "secret_ref": "local/secrets/subdl.json"},
        ]
    )
    pool = build_subtitle_provider(options, tmp_path)
    assert isinstance(pool.providers[0], Unavailable)
    assert isinstance(pool.providers[1], Subdl)
    assert pool.priority("assrt") < pool.priority("subdl")


def test_removed_language_requirement_is_not_dispatched_after_config_change(media):
    import_three(media)
    engine = media[0]
    engine.config.profiles[0].languages = [["zh-Hans"], ["en"]]
    provider = FakeProvider()
    jobs = SubtitleJobs(engine, provider)
    jobs.run()
    engine.config.profiles[0].languages = [["zh-Hans"]]
    before = provider.calls
    result = jobs.run(refresh=True)
    assert len(result) == 3
    assert provider.calls - before == 3
