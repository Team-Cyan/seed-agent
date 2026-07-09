from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from seed_agent.cli import (
    _backfill_title_key,
    _configured_site_for_inferred_tracker,
    _infer_tracker_site,
    _matching_mteam_candidates,
    _tracker_source_backfill_summary,
)
from seed_agent.config import SiteConfig
from seed_agent.models import Discount, ManagedTorrent, TorrentCandidate


def _torrent(
    *,
    name: str = "Jade.Deadly.Sins.Ep08.2026.2160p.WEB-DL.mkv",
    size_bytes: int = 10 * 1024**3,
    tags: set[str] | None = None,
    tracker: str | None = None,
) -> ManagedTorrent:
    metadata = {}
    if tracker is not None:
        metadata["tracker"] = tracker
    return ManagedTorrent(
        hash="a" * 40,
        name=name,
        category="seed",
        tags=tags or set(),
        state="stalledUP",
        size_bytes=size_bytes,
        uploaded_bytes=0,
        downloaded_bytes=size_bytes,
        added_at=datetime(2026, 7, 10, tzinfo=UTC),
        metadata=metadata,
    )


def _candidate(
    *,
    title: str = "Jade.Deadly.Sins.Ep08.2026.2160p.WEB-DL",
    size_bytes: int = 10 * 1024**3,
) -> TorrentCandidate:
    return TorrentCandidate(
        site="mteam",
        title=title,
        source_url="https://kp.m-team.cc/detail/1206094",
        download_url="https://kp.m-team.cc/download/1206094",
        size_bytes=size_bytes,
        seeders=10,
        leechers=2,
        discount=Discount.FREE,
    )


def test_infer_tracker_site_prefers_site_tag_and_supports_mteam_tracker_url() -> None:
    assert _infer_tracker_site(_torrent(tags={"site:mteam"})) == "mteam"
    assert _infer_tracker_site(_torrent(tags={"site:mt"})) == "mt"
    assert _infer_tracker_site(_torrent(tracker="https://tracker.m-team.cc/announce")) == "mt"


def test_configured_site_maps_legacy_mt_to_configured_mteam_site() -> None:
    config = SimpleNamespace(
        enabled_sites=[
            SiteConfig(
                name="mteam",
                type="mteam",
                rss_url="https://rss.m-team.cc/feed",
                api_key_ref="local/secrets/mteam-api-key.txt",
            )
        ]
    )

    site = _configured_site_for_inferred_tracker(config, "mt")

    assert site is not None
    assert site.name == "mteam"


def test_matching_mteam_candidates_requires_normalized_title_and_close_size() -> None:
    torrent = _torrent(size_bytes=10 * 1024**3)

    matches = _matching_mteam_candidates(
        torrent,
        [
            _candidate(size_bytes=10 * 1024**3 + 32 * 1024**2),
            _candidate(title="Other.Release.2026.2160p.WEB-DL"),
            _candidate(size_bytes=11 * 1024**3),
        ],
    )

    assert len(matches) == 1
    assert matches[0].title == "Jade.Deadly.Sins.Ep08.2026.2160p.WEB-DL"


def test_backfill_title_key_strips_common_file_suffixes() -> None:
    assert _backfill_title_key("Jade.Deadly.Sins.Ep08.2026.2160p.WEB-DL.mkv") == (
        "jade deadly sins ep08 2026 2160p web dl"
    )


def test_tracker_source_backfill_summary_counts_statuses_and_updates() -> None:
    assert _tracker_source_backfill_summary(
        [
            {"status": "matched", "updated": True},
            {"status": "matched", "updated": False},
            {"status": "skipped"},
        ]
    ) == {"matched": 2, "updated": 1, "skipped": 1}
