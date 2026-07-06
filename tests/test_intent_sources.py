import json
from datetime import UTC, datetime
from pathlib import Path

from seed_agent.models import IntentSource
from seed_agent.sources.douban import (
    build_douban_wish_url,
    fetch_douban_wanted_user,
    parse_douban_wish_html,
    read_douban_wanted,
)
from seed_agent.sources.file_inbox import read_file_inbox
from seed_agent.sources.imdb import parse_imdb_watchlist_csv, parse_imdb_watchlist_html
from seed_agent.sources.letterboxd import parse_letterboxd_watchlist_csv
from seed_agent.sources.telegram import parse_telegram_update, poll_telegram_updates
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


def test_telegram_polling_reads_updates_and_filters_allowed_chats() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_fetcher(bot_token: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((bot_token, params))
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 42,
                        "date": 1776816000,
                        "chat": {"id": 12345, "type": "private"},
                        "text": "download Inception 2010 1080p",
                    },
                },
                {
                    "update_id": 101,
                    "message": {
                        "message_id": 43,
                        "date": 1776816001,
                        "chat": {"id": 99999, "type": "private"},
                        "text": "ignore me",
                    },
                },
            ],
        }

    events = poll_telegram_updates(
        bot_token="secret-token",
        offset=100,
        timeout_seconds=3,
        allowed_chat_ids={"12345"},
        fetcher=fake_fetcher,
    )

    assert calls == [("secret-token", {"timeout": 3, "offset": 100})]
    assert len(events) == 1
    assert events[0].source == IntentSource.TELEGRAM
    assert events[0].source_event_id == "telegram:12345:42"
    assert events[0].metadata["chat_id"] == "12345"
    assert "secret-token" not in str(events[0].metadata)


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
    assert events[0].metadata["media_type"] == "movie"
    assert events[0].metadata["external_ids"] == {"douban": "1292052"}


def test_douban_wanted_parses_public_wish_html() -> None:
    html = """
    <div class="item comment-item" data-cid="4243074934">
      <div class="info">
        <li class="title">
          <a href="https://movie.douban.com/subject/26799731/">
            <em>请以你的名字呼唤我 / Call Me by Your Name</em>
             / 以你的名字呼唤我(港/台)
          </a>
        </li>
        <li class="intro">2017-01-22(圣丹斯电影节) / 意大利 / 美国</li>
        <li><span class="date">2024-07-14</span></li>
      </div>
    </div>
    """

    events = parse_douban_wish_html(html, user_name="LancerC")

    assert len(events) == 1
    assert events[0].source == IntentSource.DOUBAN_WANTED
    assert events[0].raw_text == "请以你的名字呼唤我 Call Me by Your Name 2017"
    assert events[0].source_event_id == "douban:26799731"
    assert events[0].metadata["source_adapter"] == "douban_wanted_public"
    assert events[0].metadata["douban_user_name"] == "LancerC"
    assert events[0].metadata["url"] == "https://movie.douban.com/subject/26799731/"
    assert events[0].metadata["media_type"] == "movie"
    assert events[0].metadata["external_ids"] == {"douban": "26799731"}
    assert events[0].metadata["douban_wish_date"] == "2024-07-14"
    assert events[0].requested_at == datetime(2024, 7, 14, tzinfo=UTC)


def test_douban_wanted_infers_anime_and_show_media_types() -> None:
    html = """
    <div class="item comment-item">
      <div class="info">
        <li class="title"><a href="https://movie.douban.com/subject/35797709/"><em>葬送的芙莉莲</em></a></li>
        <li class="intro">2023-09-29(日本) / 日本 / 动画 / 奇幻</li>
        <li><span class="date">2025-01-02</span></li>
      </div>
    </div>
    <div class="item comment-item">
      <div class="info">
        <li class="title"><a href="https://movie.douban.com/subject/34812928/"><em>漫长的季节</em></a></li>
        <li class="intro">2023-04-22(中国大陆) / 中国大陆 / 剧情 / 家庭 / 犯罪 / 12集</li>
      </div>
    </div>
    """

    events = parse_douban_wish_html(html, user_name="LancerC")

    assert [event.metadata["media_type"] for event in events] == ["anime", "tv"]


def test_douban_wanted_fetches_configured_user_pages() -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return """
        <div class="item comment-item">
          <li class="title">
            <a href="https://movie.douban.com/subject/35391267/"><em>暴风</em></a>
          </li>
          <li class="intro">2023-04-14(中国大陆) / 剧情</li>
        </div>
        """

    events = fetch_douban_wanted_user(
        "LancerC",
        max_pages=2,
        fetcher=fake_fetch,
        enrich_subjects=False,
    )

    assert calls == [
        "https://movie.douban.com/people/LancerC/wish?start=0",
        "https://movie.douban.com/people/LancerC/wish?start=15",
    ]
    assert [event.raw_text for event in events] == ["暴风 2023"]


def test_douban_wanted_fetches_subject_page_to_refine_tv_media_type() -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        if "/subject/33404425/" in url:
            return "<title>隐秘的角落 - 电视剧 - 豆瓣</title>"
        return """
        <div class="item comment-item">
          <div class="info">
            <li class="title"><a href="https://movie.douban.com/subject/33404425/"><em>隐秘的角落</em></a></li>
            <li class="intro">2020-06-16(中国大陆) / 中国大陆 / 50分钟 / 剧情</li>
          </div>
        </div>
        """

    events = fetch_douban_wanted_user("LancerC", max_pages=1, fetcher=fake_fetch)

    assert events[0].metadata["media_type"] == "tv"
    assert calls == [
        "https://movie.douban.com/people/LancerC/wish?start=0",
        "https://m.douban.com/movie/subject/33404425/",
    ]


def test_douban_wanted_enriches_subject_imdb_id() -> None:
    def fake_fetch(url: str) -> str:
        if "/subject/1292052/" in url:
            return "<title>肖申克的救赎 - 电影 - 豆瓣</title><span>IMDb: tt0111161</span>"
        return """
        <div class="item comment-item">
          <div class="info">
            <li class="title"><a href="https://movie.douban.com/subject/1292052/"><em>肖申克的救赎</em></a></li>
            <li class="intro">1994-09-10(多伦多电影节) / 美国 / 剧情</li>
          </div>
        </div>
        """

    events = fetch_douban_wanted_user("LancerC", max_pages=1, fetcher=fake_fetch)

    assert events[0].metadata["external_ids"] == {
        "douban": "1292052",
        "imdb": "tt0111161",
    }


def test_imdb_watchlist_parses_csv_export() -> None:
    csv_text = "\n".join(
        [
            "Position,Const,Created,Modified,Description,Title,URL,Title Type,"
            "IMDb Rating,Runtime (mins),Year,Genres",
            "1,tt5726616,2025-01-03,2025-01-03,,Call Me by Your Name,"
            "https://www.imdb.com/title/tt5726616/,movie,7.8,132,2017,Drama",
            "2,tt0388629,2025-01-04,2025-01-04,,One Piece,"
            "https://www.imdb.com/title/tt0388629/,tvSeries,9.0,24,1999,Animation",
        ]
    )

    events = parse_imdb_watchlist_csv(csv_text, source_config_id="imdb-weekend", label="周末清单")

    assert [event.source for event in events] == [
        IntentSource.IMDB_WATCHLIST,
        IntentSource.IMDB_WATCHLIST,
    ]
    assert events[0].source_event_id == "imdb:tt5726616"
    assert events[0].raw_text == "Call Me by Your Name 2017"
    assert events[0].metadata["media_type"] == "movie"
    assert events[0].metadata["external_ids"] == {"imdb": "tt5726616"}
    assert events[0].metadata["source_config_id"] == "imdb-weekend"
    assert events[0].metadata["source_label"] == "IMDb-周末清单"
    assert events[0].requested_at == datetime(2025, 1, 3, tzinfo=UTC)
    assert events[1].metadata["media_type"] == "anime"


def test_imdb_watchlist_parses_public_html_fixture() -> None:
    html = """
    <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "items": [
              {
                "title": {
                  "id": "tt0111161",
                  "titleText": {"text": "The Shawshank Redemption"},
                  "releaseYear": {"year": 1994},
                  "titleType": {"id": "movie"}
                },
                "created": "2025-02-01"
              }
            ]
          }
        }
      }
    </script>
    """

    events = parse_imdb_watchlist_html(html, source_config_id="imdb-classics", label="经典")

    assert len(events) == 1
    assert events[0].source_event_id == "imdb:tt0111161"
    assert events[0].raw_text == "The Shawshank Redemption 1994"
    assert events[0].metadata["external_ids"] == {"imdb": "tt0111161"}
    assert events[0].metadata["source_label"] == "IMDb-经典"


def test_letterboxd_watchlist_parses_csv_export() -> None:
    csv_text = "\n".join(
        [
            "Date,Name,Year,Letterboxd URI",
            "2025-02-01,The Substance,2024,https://boxd.it/Fy0G",
            "2025-02-02,No Year Movie,,https://boxd.it/demo",
        ]
    )

    events = parse_letterboxd_watchlist_csv(
        csv_text,
        source_config_id="letterboxd-watchlist",
        label="Watchlist",
    )

    assert [event.source for event in events] == [
        IntentSource.LETTERBOXD,
        IntentSource.LETTERBOXD,
    ]
    assert events[0].raw_text == "The Substance 2024"
    assert events[0].source_event_id == "letterboxd:https://boxd.it/Fy0G"
    assert events[0].metadata["media_type"] == "movie"
    assert events[0].metadata["url"] == "https://boxd.it/Fy0G"
    assert events[0].metadata["source_config_id"] == "letterboxd-watchlist"
    assert events[0].metadata["source_label"] == "Letterboxd-Watchlist"
    assert events[0].requested_at == datetime(2025, 2, 1, tzinfo=UTC)
    assert events[1].raw_text == "No Year Movie"


def test_build_douban_wish_url_accepts_profile_url_or_user_name() -> None:
    assert build_douban_wish_url("LancerC", start=15) == (
        "https://movie.douban.com/people/LancerC/wish?start=15"
    )
    assert build_douban_wish_url("https://www.douban.com/people/LancerC/", start=0) == (
        "https://movie.douban.com/people/LancerC/wish?start=0"
    )
