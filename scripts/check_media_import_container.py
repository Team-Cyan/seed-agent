"""Synthetic-only container acceptance. Never reads configured media or downloader credentials."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from seed_agent.media_import.config import MediaImportConfig, Profile
from seed_agent.media_import.engine import Engine
from seed_agent.media_import.metadata import Mapping
from seed_agent.media_import.store import MediaStore
from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.provider import Candidate


class Metadata:
    calls = 0

    def identify(self, path, profile):
        self.calls += 1
        return Mapping(
            media_type="tv",
            tmdb_id=12,
            original_title="Fixture",
            year=2024,
            season=int(path.stem[-1]),
            episodes=[1],
        ), []


class Subtitles:
    name = "fixture"

    def search(self, mapping, source, languages):
        return [
            Candidate(
                id=str(mapping["season"]),
                language="zh-Hans",
                tmdb_id=12,
                season=mapping["season"],
                episodes=(1,),
                hash_match=True,
            )
        ]

    def download(self, candidate):
        return b"1\n00:00:00,000 --> 00:00:00,900\nfixture\n"


def main():
    with tempfile.TemporaryDirectory(prefix="media-import-acceptance-") as directory:
        root = Path(directory)
        source, target = root / "completed", root / "library"
        source.mkdir()
        target.mkdir()
        for p in [source, target]:
            (p / ".media-volume").write_text("fixture")
        for season in range(1, 4):
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:r=25",
                    "-t",
                    "1",
                    "-c:v",
                    "mpeg4",
                    str(source / f"Season{season}.mkv"),
                ],
                check=True,
            )
        profile = Profile(
            name="tv",
            source_root=str(source),
            target_root=str(target),
            marker_value="fixture",
            target_marker_value="fixture",
            media_type="tv",
            readiness="completed_folder",
            completed_contract_acknowledged=True,
            min_age_seconds=0,
            grace_seconds=0,
        )
        config = MediaImportConfig(
            enabled=True,
            profiles=[profile],
            import_policy="execute",
            subtitle_policy="execute",
            reconcile_policy="preview",
        )
        config.provider_interval_seconds = 0
        metadata = Metadata()
        engine = Engine(MediaStore(root / "state.db"), config, metadata=metadata)
        engine.scan("tv", force=True)
        engine.scan("tv", force=True)
        assert len(list(target.rglob("*.mkv"))) == 3
        for item in engine.snapshot()["sources"]:
            assert os.path.samefile(source / item["path"], item["target"])
            assert json.loads(item["probe_json"])["duration"] > 0
        engine.scan("tv", force=True)
        assert metadata.calls == 3
        SubtitleJobs(engine, Subtitles()).run()
        assert len(list(target.rglob("*.srt"))) == 3
        first = engine.snapshot()["sources"][0]
        video = Path(first["target"])
        manual = video.parent / "manual.txt"
        manual.write_text("preserve")
        (source / first["path"]).unlink()
        engine.scan("tv", force=True)
        engine.scan("tv", force=True)
        assert video.exists() and engine.snapshot()["cleanup"]
        config.reconcile_policy = "execute"
        engine.scan("tv", force=True)
        assert not video.exists() and manual.exists()
        assert len(list(target.rglob("*.srt"))) == 2
        assert len(list(target.rglob("*.mkv"))) == 2
        before = [s["missing_count"] for s in engine.snapshot()["sources"]]
        (source / ".media-volume").write_text("wrong mount")
        assert engine.scan("tv", force=True)["status"] == "failed"
        assert before == [s["missing_count"] for s in engine.snapshot()["sources"]]
        print(
            json.dumps(
                {
                    "status": "passed",
                    "synthetic_seasons": 3,
                    "hardlink_receipts": 3,
                    "real_ffprobe": True,
                    "subtitle_publications": 3,
                    "remaining_videos": 2,
                    "remaining_subtitles": 2,
                    "manual_preserved": True,
                    "outage_fenced": True,
                }
            )
        )


if __name__ == "__main__":
    main()
