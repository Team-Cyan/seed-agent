import json
from datetime import UTC, datetime
from pathlib import Path

from seed_agent.models import IntentSource
from seed_agent.sources.douban import read_douban_wanted
from seed_agent.sources.file_inbox import read_file_inbox
from seed_agent.sources.telegram import parse_telegram_update
from seed_agent.sources.wechat_bridge import parse_wechat_bridge_event


def test_file_inbox_reads_jsonl_events_and_skips_invalid_lines(tmp_path: Path) -> None:
    inbox = tmp_path / "intents.jsonl"
    inbox.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "movie-1",
                        "text": "Inception 2010 1080p",
                        "requested_at": "2026-04-22T00:00:00+00:00",
                    }
                ),
                "not-json",
                json.dumps({"id": "missing-text"}),
                json.dumps({"event_id": "show-1", "message": "Severance S02E03"}),
            ]
        ),
        encoding="utf-8",
    )

    events = read_file_inbox(inbox)

    assert len(events) == 2
    assert events[0].source == IntentSource.FILE_INBOX
    assert events[0].raw_text == "Inception 2010 1080p"
    assert events[0].source_event_id == "movie-1"
    assert events[0].requested_at == datetime(2026, 4, 22, tzinfo=UTC)
    assert events[1].source_event_id == "show-1"


def test_telegram_parser_extracts_message_without_secret_fields() -> None:
    event = parse_telegram_update(
        {
            "update_id": 99,
            "message": {
                "message_id": 42,
                "date": 1776816000,
                "chat": {"id": 12345, "type": "private"},
                "text": "download Inception 2010 1080p",
            },
        }
    )

    assert event is not None
    assert event.source == IntentSource.TELEGRAM
    assert event.raw_text == "download Inception 2010 1080p"
    assert event.source_event_id == "telegram:12345:42"
    assert event.metadata["chat_id"] == "12345"
    assert "token" not in event.metadata


def test_telegram_parser_ignores_non_text_updates() -> None:
    assert parse_telegram_update({"update_id": 1, "message": {"photo": []}}) is None


def test_wechat_bridge_parser_extracts_message() -> None:
    event = parse_wechat_bridge_event(
        {
            "msg_id": "abc",
            "from_user": "alice",
            "content": "Foundation S03 2160p",
            "timestamp": 1776816000,
        }
    )

    assert event is not None
    assert event.source == IntentSource.WECHAT_BRIDGE
    assert event.raw_text == "Foundation S03 2160p"
    assert event.source_event_id == "wechat:abc"
    assert event.metadata["sender"] == "alice"


def test_douban_wanted_reads_local_export_shapes(tmp_path: Path) -> None:
    export = tmp_path / "douban.json"
    export.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "1292052",
                        "title": "The Shawshank Redemption",
                        "year": 1994,
                        "url": "https://movie.douban.com/subject/1292052/",
                        "type": "movie",
                    },
                    {"id": "missing-title"},
                ]
            }
        ),
        encoding="utf-8",
    )

    events = read_douban_wanted(export)

    assert len(events) == 1
    assert events[0].source == IntentSource.DOUBAN_WANTED
    assert events[0].raw_text == "The Shawshank Redemption 1994"
    assert events[0].source_event_id == "douban:1292052"
    assert events[0].metadata["kind"] == "movie"
