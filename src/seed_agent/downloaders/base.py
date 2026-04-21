from __future__ import annotations

from typing import Protocol, runtime_checkable

from seed_agent.models import ManagedTorrent


@runtime_checkable
class Downloader(Protocol):
    async def add_url(self, url: str, category: str, tags: list[str]) -> str | None: ...

    async def list_torrents(
        self, category: str | None = None, tags: set[str] | None = None
    ) -> list[ManagedTorrent]: ...

    async def pause(self, hash: str) -> None: ...

    async def delete(self, hash: str, delete_files: bool) -> None: ...
