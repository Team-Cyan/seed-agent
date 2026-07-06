from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from seed_agent.downloaders.transmission import TransmissionClient, TransmissionError
from seed_agent.models import ManagedTorrent


@pytest.mark.asyncio
@respx.mock
async def test_transmission_add_url_retries_with_session_id_and_labels() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(409, headers={"X-Transmission-Session-Id": "sid-123"})
        return httpx.Response(
            200,
            json={
                "result": "success",
                "arguments": {
                    "torrent-added": {
                        "hashString": "0123456789abcdef0123456789abcdef01234567"
                    }
                },
            },
        )

    respx.post("https://tr.example/transmission/rpc").mock(side_effect=handler)
    client = TransmissionClient("https://tr.example", username="alice", password="secret")

    torrent_hash = await client.add_url(
        "https://tracker.example/download.php?id=42",
        category="seed",
        tags=["seed-agent"],
        paused=True,
    )

    assert torrent_hash == "0123456789abcdef0123456789abcdef01234567"
    assert len(calls) == 2
    assert calls[1].headers["X-Transmission-Session-Id"] == "sid-123"
    assert calls[1].headers["authorization"] == (
        "Basic " + base64.b64encode(b"alice:secret").decode()
    )
    payload = calls[1].content
    assert b'"method":"torrent-add"' in payload
    assert b'"paused":true' in payload
    assert b'"labels":["seed","seed-agent"]' in payload


@pytest.mark.asyncio
@respx.mock
async def test_transmission_list_torrents_maps_and_filters_labels() -> None:
    respx.post("https://tr.example/transmission/rpc").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": "success",
                "arguments": {
                    "torrents": [
                        {
                            "hashString": "abcd1234",
                            "name": "Example Torrent",
                            "labels": ["seed", "seed-agent"],
                            "status": 6,
                            "totalSize": 123456,
                            "uploadedEver": 654321,
                            "downloadedEver": 123,
                            "addedDate": 1700000000,
                            "doneDate": 1700000100,
                            "activityDate": 1700000200,
                            "downloadDir": "/mnt/downloads",
                            "rateUpload": 2048,
                            "rateDownload": 1024,
                            "leftUntilDone": 0,
                        },
                        {
                            "hashString": "ignored",
                            "name": "Ignored Torrent",
                            "labels": ["movie"],
                            "status": 4,
                            "totalSize": 1,
                            "uploadedEver": 0,
                            "downloadedEver": 0,
                            "addedDate": 1700000000,
                        },
                    ]
                },
            },
        )
    )
    client = TransmissionClient("https://tr.example")

    torrents = await client.list_torrents(category="seed", tags={"seed-agent"})

    assert torrents == [
        ManagedTorrent(
            hash="abcd1234",
            name="Example Torrent",
            category="seed",
            tags={"seed", "seed-agent"},
            state="seeding",
            size_bytes=123456,
            uploaded_bytes=654321,
            downloaded_bytes=123,
            added_at=datetime.fromtimestamp(1700000000, tz=UTC),
            completed_at=datetime.fromtimestamp(1700000100, tz=UTC),
            last_activity_at=datetime.fromtimestamp(1700000200, tz=UTC),
            save_path="/mnt/downloads",
            metadata={
                "transmission_labels": ["seed", "seed-agent"],
                "upspeed_bps": 2048,
                "dlspeed_bps": 1024,
                "amount_left_bytes": 0,
            },
        )
    ]


@pytest.mark.asyncio
@respx.mock
async def test_transmission_pause_and_delete_post_rpc_methods() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    respx.post("https://tr.example/transmission/rpc").mock(side_effect=handler)
    client = TransmissionClient("https://tr.example")

    await client.pause("abcd1234")
    await client.delete("abcd1234", delete_files=True)

    assert calls == [
        {"method": "torrent-stop", "arguments": {"ids": ["abcd1234"]}},
        {
            "method": "torrent-remove",
            "arguments": {"ids": ["abcd1234"], "delete-local-data": True},
        },
    ]


@pytest.mark.asyncio
@respx.mock
async def test_transmission_error_includes_rpc_result() -> None:
    respx.post("https://tr.example/transmission/rpc").mock(
        return_value=httpx.Response(
            200,
            json={"result": "invalid or corrupt torrent file", "arguments": {}},
        )
    )
    client = TransmissionClient("https://tr.example")

    with pytest.raises(TransmissionError, match="invalid or corrupt"):
        await client.add_url("https://tracker.example/bad.torrent", "seed", [])
