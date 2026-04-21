from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from seed_agent.downloaders.qbittorrent import QbittorrentClient, QbittorrentError
from seed_agent.models import ManagedTorrent


@pytest.mark.asyncio
@respx.mock
async def test_add_url_logs_in_and_posts_category_tags_url() -> None:
    login_route = respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    add_route = respx.post("https://qb.example/api/v2/torrents/add").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    client = QbittorrentClient("https://qb.example", "alice", "secret")

    result = await client.add_url(
        "https://tracker.example/download.php?id=42",
        category="pt-auto",
        tags=["seed-agent", "pt-auto"],
    )

    assert result is None
    assert login_route.called
    assert add_route.called
    payload = parse_qs(add_route.calls[0].request.content.decode())
    assert payload == {
        "urls": ["https://tracker.example/download.php?id=42"],
        "category": ["pt-auto"],
        "tags": ["seed-agent,pt-auto"],
    }


@pytest.mark.asyncio
@respx.mock
async def test_add_url_fails_on_failure_body() -> None:
    respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    respx.post("https://qb.example/api/v2/torrents/add").mock(
        return_value=httpx.Response(200, text="Fails.")
    )
    client = QbittorrentClient("https://qb.example", "alice", "secret")

    with pytest.raises(QbittorrentError) as exc_info:
        await client.add_url(
            "https://tracker.example/download.php?id=42&passkey=secret",
            category="pt-auto",
            tags=["seed-agent"],
        )

    message = str(exc_info.value)
    assert "add torrent failed" in message
    assert "download.php?id=42" not in message
    assert "passkey=secret" not in message


@pytest.mark.asyncio
@respx.mock
async def test_list_torrents_converts_rows_into_managed_torrents() -> None:
    respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    respx.get("https://qb.example/api/v2/torrents/info").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "hash": "abcd1234",
                    "name": "Example Torrent",
                    "category": "pt-auto",
                    "tags": "seed-agent, pt-auto",
                    "state": "uploading",
                    "size": 123456,
                    "uploaded": 654321,
                    "uploaded_session": 111,
                    "downloaded": 123,
                    "added_on": 1700000000,
                    "completion_on": 1700000100,
                    "last_activity": 1700000200,
                    "save_path": "/mnt/data",
                }
            ],
        )
    )
    client = QbittorrentClient("https://qb.example", "alice", "secret")

    torrents = await client.list_torrents(category="pt-auto", tags={"seed-agent"})

    assert torrents == [
        ManagedTorrent(
            hash="abcd1234",
            name="Example Torrent",
            category="pt-auto",
            tags={"seed-agent", "pt-auto"},
            state="uploading",
            size_bytes=123456,
            uploaded_bytes=654321,
            downloaded_bytes=123,
            added_at=datetime.fromtimestamp(1700000000, tz=UTC),
            completed_at=datetime.fromtimestamp(1700000100, tz=UTC),
            last_activity_at=datetime.fromtimestamp(1700000200, tz=UTC),
            save_path="/mnt/data",
            metadata={
                "uploaded_session_bytes": 111,
            },
        )
    ]


@pytest.mark.asyncio
@respx.mock
async def test_pause_posts_hashes() -> None:
    respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    pause_route = respx.post("https://qb.example/api/v2/torrents/stop").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    client = QbittorrentClient("https://qb.example", "alice", "secret")

    await client.pause("abcd1234")

    assert pause_route.called
    payload = parse_qs(pause_route.calls[0].request.content.decode())
    assert payload == {"hashes": ["abcd1234"]}


@pytest.mark.asyncio
@respx.mock
async def test_delete_posts_hashes_and_delete_files() -> None:
    respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    delete_route = respx.post("https://qb.example/api/v2/torrents/delete").mock(
        return_value=httpx.Response(200, text="Ok.")
    )
    client = QbittorrentClient("https://qb.example", "alice", "secret")

    await client.delete("abcd1234", delete_files=True)

    assert delete_route.called
    payload = parse_qs(delete_route.calls[0].request.content.decode())
    assert payload == {"hashes": ["abcd1234"], "deleteFiles": ["true"]}


@pytest.mark.asyncio
@respx.mock
async def test_login_failure_raises_clear_exception() -> None:
    respx.post("https://qb.example/api/v2/auth/login").mock(
        return_value=httpx.Response(403, text="Forbidden")
    )
    client = QbittorrentClient("https://qb.example", "alice", "secret")

    with pytest.raises(QbittorrentError, match="login failed"):
        await client.add_url(
            "https://tracker.example/download.php?id=42",
            category="pt-auto",
            tags=[],
        )
