from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from seed_agent.actions.qb import prune_cold_torrents
from seed_agent.config import CategoryPolicyConfig, CleanupConfig
from seed_agent.downloaders.transmission import TransmissionClient, TransmissionError
from seed_agent.models import ManagedTorrent
from seed_agent.policies.category_policy import PoolUsage


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
                    "torrent-added": {"hashString": "0123456789abcdef0123456789abcdef01234567"}
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
async def test_transmission_category_resolution_requires_explicit_or_unique_policy_label() -> None:
    respx.post("https://tr.example/transmission/rpc").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": "success",
                "arguments": {
                    "torrents": [
                        {
                            "hashString": "ambiguous",
                            "name": "Ambiguous",
                            "labels": ["tv", "seed", "seed-agent"],
                            "status": 6,
                            "addedDate": 1700000000,
                        },
                        {
                            "hashString": "movie",
                            "name": "Movie",
                            "labels": ["movie", "mteam", "seed-agent"],
                            "status": 6,
                            "addedDate": 1700000000,
                        },
                        {
                            "hashString": "unknown",
                            "name": "Unknown",
                            "labels": ["archive", "seed-agent"],
                            "status": 6,
                            "addedDate": 1700000000,
                        },
                    ]
                },
            },
        )
    )
    client = TransmissionClient("https://tr.example")

    categorized = await client.list_torrents(known_policy_categories={"seed", "movie", "tv"})
    without_policy_context = await client.list_torrents()
    explicitly_requested = await client.list_torrents(
        category="tv",
        known_policy_categories={"seed", "movie", "tv"},
    )

    assert {torrent.hash: torrent.category for torrent in categorized} == {
        "ambiguous": None,
        "movie": "movie",
        "unknown": None,
    }
    assert all(torrent.category is None for torrent in without_policy_context)
    assert [(torrent.hash, torrent.category) for torrent in explicitly_requested] == [
        ("ambiguous", "tv")
    ]


@pytest.mark.asyncio
@respx.mock
async def test_transmission_emits_only_provable_cleanup_metadata() -> None:
    respx.post("https://tr.example/transmission/rpc").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": "success",
                "arguments": {
                    "torrents": [
                        {
                            "hashString": "protected",
                            "name": "Protected",
                            "labels": ["seed", "seed-agent", "H&R", "manual"],
                            "status": 6,
                            "addedDate": 1700000000,
                            "downloadDir": "/mnt/user/media/movies",
                        },
                        {
                            "hashString": "unproven",
                            "name": "Unproven",
                            "labels": ["seed", "seed-agent", "manual-copy"],
                            "status": 6,
                            "addedDate": 1700000000,
                            "downloadDir": "/mnt/user/downloads/movies.tmp",
                        },
                    ]
                },
            },
        )
    )
    client = TransmissionClient("https://tr.example")

    torrents = await client.list_torrents(category="seed")

    assert torrents[0].metadata["hr"] is True
    assert torrents[0].metadata["manual"] is True
    assert torrents[0].metadata["media_library"] is True
    assert "hr" not in torrents[1].metadata
    assert "manual" not in torrents[1].metadata
    assert "media_library" not in torrents[1].metadata


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
async def test_transmission_execute_prune_revalidates_requested_category() -> None:
    removed = False
    calls: list[str] = []
    torrent_row = {
        "hashString": "abcd1234",
        "name": "Cold Incomplete",
        "labels": ["seed", "seed-agent"],
        "status": 4,
        "totalSize": 10 * 1024**3,
        "uploadedEver": 0,
        "downloadedEver": 5 * 1024**3,
        "leftUntilDone": 5 * 1024**3,
        "addedDate": 1700000000,
        "activityDate": 1700000000,
        "downloadDir": "/mnt/downloads",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal removed
        payload = json.loads(request.content.decode())
        calls.append(payload["method"])
        if payload["method"] == "torrent-remove":
            removed = True
            return httpx.Response(200, json={"result": "success", "arguments": {}})
        return httpx.Response(
            200,
            json={
                "result": "success",
                "arguments": {"torrents": [] if removed else [torrent_row]},
            },
        )

    respx.post("https://tr.example/transmission/rpc").mock(side_effect=handler)
    client = TransmissionClient("https://tr.example")
    torrent = (await client.list_torrents(category="seed"))[0]

    decisions = await prune_cold_torrents(
        [torrent],
        client,
        CleanupConfig(
            cold_after_days=1,
            min_upload_delta_gb=1,
            protect_hr=True,
            protect_manual=True,
            protect_media_library=True,
            delete_after_no_upload_hours=1,
        ),
        CategoryPolicyConfig(
            name="seed",
            mode="mutable",
            budget_pool="downloads",
            delete_enabled=True,
            over_budget_behavior="add_paused",
            tags=["seed-agent", "seed"],
        ),
        execute=True,
        pool_usage=PoolUsage(
            pool_name="downloads",
            size_bytes=11 * 1024**4,
            max_size_bytes=10 * 1024**4,
        ),
    )

    assert decisions[0].action == "qb.cleanup.delete"
    assert "torrent-remove" in calls


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
