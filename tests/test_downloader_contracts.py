from __future__ import annotations

from datetime import UTC, datetime

import pytest

from seed_agent.downloaders.base import Downloader
from seed_agent.downloaders.qbittorrent import QbittorrentClient
from seed_agent.downloaders.transmission import TransmissionClient
from seed_agent.models import ManagedTorrent


class InMemoryDownloader:
    def __init__(self) -> None:
        self.torrents: dict[str, ManagedTorrent] = {}
        self.paused: list[str] = []
        self.deleted: list[tuple[str, bool]] = []

    async def add_url(
        self,
        url: str,
        category: str,
        tags: list[str],
        *,
        paused: bool = False,
    ) -> str | None:
        torrent_hash = f"hash-{len(self.torrents) + 1}"
        self.torrents[torrent_hash] = ManagedTorrent(
            hash=torrent_hash,
            name=url.rsplit("/", 1)[-1],
            category=category,
            tags=set(tags),
            state="paused" if paused else "downloading",
            size_bytes=0,
            uploaded_bytes=0,
            downloaded_bytes=0,
            added_at=datetime.now(UTC),
        )
        return torrent_hash

    async def list_torrents(
        self,
        category: str | None = None,
        tags: set[str] | None = None,
    ) -> list[ManagedTorrent]:
        torrents = list(self.torrents.values())
        if category is not None:
            torrents = [torrent for torrent in torrents if torrent.category == category]
        if tags is not None:
            torrents = [torrent for torrent in torrents if tags.intersection(torrent.tags)]
        return torrents

    async def pause(self, hash: str) -> None:
        self.paused.append(hash)
        torrent = self.torrents[hash]
        self.torrents[hash] = torrent.model_copy(update={"state": "paused"})

    async def delete(self, hash: str, delete_files: bool) -> None:
        self.deleted.append((hash, delete_files))
        self.torrents.pop(hash, None)


def test_downloader_implementations_satisfy_runtime_protocol_shape() -> None:
    assert isinstance(QbittorrentClient("https://qb.example", "alice", "secret"), Downloader)
    assert isinstance(TransmissionClient("https://tr.example"), Downloader)


@pytest.mark.asyncio
async def test_downloader_contract_add_list_pause_and_delete_semantics() -> None:
    downloader = InMemoryDownloader()

    torrent_hash = await downloader.add_url(
        "https://tracker.example/download.php?id=1",
        category="seed",
        tags=["seed-agent", "seed"],
        paused=False,
    )

    assert torrent_hash == "hash-1"
    torrents = await downloader.list_torrents(category="seed", tags={"seed-agent"})
    assert [torrent.hash for torrent in torrents] == ["hash-1"]
    assert torrents[0].state == "downloading"

    await downloader.pause("hash-1")
    assert (await downloader.list_torrents())[0].state == "paused"
    assert downloader.paused == ["hash-1"]

    await downloader.delete("hash-1", delete_files=True)
    assert await downloader.list_torrents() == []
    assert downloader.deleted == [("hash-1", True)]
