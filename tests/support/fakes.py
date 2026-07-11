from __future__ import annotations

from seed_agent.downloaders.base import DownloaderStatus
from seed_agent.models import ManagedTorrent, ReleaseCandidate


class RecordingDownloader:
    def __init__(
        self,
        torrents: list[ManagedTorrent] | None = None,
        *,
        free_space_bytes: int | None = None,
    ) -> None:
        self.torrents = {torrent.hash: torrent for torrent in torrents or []}
        self.free_space_bytes = free_space_bytes
        self.added: list[dict[str, object]] = []
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
        self.added.append(
            {"url": url, "category": category, "tags": tags, "paused": paused}
        )
        return f"fake-{len(self.added)}"

    async def list_torrents(
        self,
        category: str | None = None,
        tags: set[str] | None = None,
    ) -> list[ManagedTorrent]:
        torrents = list(self.torrents.values())
        if category is not None:
            torrents = [torrent for torrent in torrents if torrent.category == category]
        if tags:
            torrents = [torrent for torrent in torrents if tags.intersection(torrent.tags)]
        return torrents

    async def pause(self, hash: str) -> None:
        self.paused.append(hash)

    async def delete(self, hash: str, delete_files: bool) -> None:
        self.deleted.append((hash, delete_files))
        self.torrents.pop(hash, None)

    async def get_status(self) -> DownloaderStatus:
        return DownloaderStatus(free_space_bytes=self.free_space_bytes)


class StaticSearchProvider:
    def __init__(self, releases: list[ReleaseCandidate]) -> None:
        self.releases = releases
        self.queries: list[str] = []

    async def search(self, intent) -> list[ReleaseCandidate]:
        self.queries.append(intent.intent_id)
        return self.releases
