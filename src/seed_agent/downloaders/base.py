from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from seed_agent.models import ManagedTorrent


@dataclass(frozen=True)
class DownloaderStatus:
    free_space_bytes: int | None = None


@runtime_checkable
class Downloader(Protocol):
    async def add_url(
        self,
        url: str,
        category: str,
        tags: list[str],
        *,
        paused: bool = False,
    ) -> str | None: ...

    async def list_torrents(
        self, category: str | None = None, tags: set[str] | None = None
    ) -> list[ManagedTorrent]: ...

    async def pause(self, hash: str) -> None: ...

    async def delete(self, hash: str, delete_files: bool) -> None: ...


@runtime_checkable
class DownloaderStatusProvider(Protocol):
    async def get_status(self) -> DownloaderStatus: ...
