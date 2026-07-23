import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.actions.intent import add_intent
from seed_agent.models import Discount, IntentState, RankedRelease, ReleaseCandidate
from seed_agent.state import StateStore


def _write_config(
    tmp_path: Path,
    *,
    discovery_extra: str = "",
    downloader_extra: str = "",
) -> Path:
    path = tmp_path / "config.yaml"
    discovery_block = discovery_extra if discovery_extra else ""
    path.write_text(
        f"""
mode: balanced
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
pt_filters:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  target_seed_leecher_ratio: 10
  allow_hr: false
{discovery_block}\
pt_scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
download_client:
  type: qbittorrent
  target: unraid-qb
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: ["seed-agent", "seed"]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: ["seed-agent", "movie"]
    - name: tv
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: ["seed-agent", "tv"]
  budget_pools:
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
  secret_ref: null
{downloader_extra}\
seed_cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
""",
        encoding="utf-8",
    )
    return path


def _ranked(
    intent_id: str,
    *,
    confirmation_required: bool = False,
    release_id: str = "demo-free:release-1",
    score: int | None = None,
) -> RankedRelease:
    return RankedRelease(
        intent_id=intent_id,
        release=ReleaseCandidate(
            release_id=release_id,
            site="demo-free",
            title="Inception 2010 1080p BluRay",
            source_url="https://tracker.example/details.php?id=1",
            download_url="https://tracker.example/download.php?id=1&passkey=secret",
            size_bytes=12 * 1024 * 1024 * 1024,
            seeders=30,
            leechers=8,
            discount=Discount.FREE,
        ),
        score=score if score is not None else (95 if not confirmation_required else 80),
        confidence=0.95 if not confirmation_required else 0.8,
        accepted=not confirmation_required,
        confirmation_required=confirmation_required,
        reasons=["title tokens matched"],
        risks=[] if not confirmation_required else ["resolution missing"],
    )


def _mteam_deferred_ranked(intent_id: str) -> RankedRelease:
    return RankedRelease(
        intent_id=intent_id,
        release=ReleaseCandidate(
            release_id="mt:https://kp.m-team.cc/detail/26799731",
            site="mt",
            title="Call Me by Your Name 2017 2160p BluRay REMUX",
            source_url="https://kp.m-team.cc/detail/26799731",
            download_url="mteam-api://torrent/26799731",
            size_bytes=66 * 1024**3,
            seeders=12,
            leechers=3,
            discount=Discount.NORMAL,
            metadata={
                "mteam_torrent_id": "26799731",
                "download_url_source": "mteam_api_deferred",
            },
        ),
        score=96,
        confidence=0.96,
        accepted=True,
        confirmation_required=False,
        reasons=["required keyword matched: Remux"],
        risks=[],
    )


def _json_output(result) -> dict[str, object]:
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
    return parsed


class _DummyDownloader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[str]]] = []

    async def add_url(
        self, url: str, category: str, tags: list[str], *, paused: bool = False
    ) -> str | None:
        self.calls.append((url, category, tags))
        return "0123456789abcdef0123456789abcdef01234567"

    async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
        return []


def test_intent_enqueue_dry_run_does_not_touch_downloader_or_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["command"] == "intent-enqueue"
    assert payload["execute"] is False
    assert payload["enqueued"] == 1
    assert payload["decisions"][0]["execute"] is False
    assert payload["runtime_activity"]["managed_count"] == 0
    assert downloader.calls == []
    row = store.get_intent(intent.intent_id)
    assert row is not None
    assert row["state"] == IntentState.NORMALIZED.value
    assert "passkey=secret" not in result.output


def test_intent_enqueue_dry_run_preserves_score_above_100(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    store.save_ranked_releases([_ranked(intent.intent_id, score=120)])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert _json_output(result)["decisions"][0]["action"] == "qb.enqueue"
    assert downloader.calls == []


def test_intent_enqueue_dry_run_reports_runtime_activity_when_qb_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    class FakeDownloader(_DummyDownloader):
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="abcd1234",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="uploading",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=10 * 1024**3,
                    downloaded_bytes=8 * 1024**3,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"upspeed_bps": 2 * 1024**2, "dlspeed_bps": 0, "amount_left_bytes": 0},
                )
            ]

    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: FakeDownloader())

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["runtime_activity"]["managed_count"] == 1
    assert payload["runtime_activity"]["active_upload_count"] == 1
    assert payload["default_pool_usage"]["over_budget"] is False
    assert payload["enqueue_paused_by_pool_policy"] is False


def test_intent_enqueue_dry_run_reports_pause_reasons_when_runtime_gate_exceeded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli
    from seed_agent.models import ManagedTorrent

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, discovery_extra="  max_active_downloads: 0\n")
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    class FakeDownloader(_DummyDownloader):
        async def list_torrents(self, category: str | None = None, tags: set[str] | None = None):
            return [
                ManagedTorrent(
                    hash="abcd1234",
                    name="Managed Torrent",
                    category="seed",
                    tags={"seed-agent", "seed"},
                    state="downloading",
                    size_bytes=10 * 1024**3,
                    uploaded_bytes=10 * 1024**3,
                    downloaded_bytes=8 * 1024**3,
                    added_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                    metadata={"upspeed_bps": 0, "dlspeed_bps": 1024, "amount_left_bytes": 1},
                )
            ]

    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: FakeDownloader())

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert payload["enqueue_blocked_reasons"] == ["active downloads 1 >= max 0"]
    assert payload["decisions"][0]["action"] == "qb.enqueue.rejected"


def test_intent_enqueue_execute_can_select_release_id_and_updates_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    ranked = _ranked(intent.intent_id, confirmation_required=True)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        [
            "intent-enqueue",
            intent.intent_id,
            "--config",
            str(config_path),
            "--release-id",
            ranked.release.release_id,
            "--execute",
        ],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["execute"] is True
    assert payload["intent"]["state"] == IntentState.ENQUEUED.value
    assert downloader.calls == [
        (
            ranked.release.download_url,
            "movie",
            ["seed-agent", "movie"],
        )
    ]
    row = store.get_intent(intent.intent_id)
    assert row is not None
    assert row["state"] == IntentState.ENQUEUED.value
    assert row["selected_release_id"] == ranked.release.release_id
    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "qb.enqueue" in audit


def test_intent_enqueue_execute_is_idempotent_across_repeated_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    first = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )
    second = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert len(downloader.calls) == 1
    second_payload = _json_output(second)
    assert second_payload["enqueued"] == 0
    assert second_payload["decisions"][0]["action"] == "qb.enqueue.skip"
    assert second_payload["decisions"][0]["reason"] == "already enqueued"


def test_intent_enqueue_projects_capacity_in_selected_media_pool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "_maybe_build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "    - name: media\n      max_size_tib: 10",
            "    - name: media\n      max_size_tib: 0.01",
        ),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent(
        "Inception 2010 1080p",
        store,
        metadata={"media_type": "movie"},
    )
    store.save_ranked_releases([_ranked(intent.intent_id)])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["enqueue_paused_by_pool_policy"] is False
    assert payload["enqueue_blocked_by_runtime_gate"] is True
    assert payload["enqueue_blocked_reasons"][0].startswith(
        "budget pool media projected usage"
    )
    assert payload["decisions"][0]["new_state"]["category"] == "movie"
    assert payload["decisions"][0]["new_state"]["rejected"] is True


def test_intent_enqueue_rejects_unknown_release_id(tmp_path: Path, monkeypatch) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    store.save_ranked_releases([_ranked(intent.intent_id)])

    result = CliRunner().invoke(
        cli.app,
        [
            "intent-enqueue",
            intent.intent_id,
            "--config",
            str(config_path),
            "--release-id",
            "missing",
        ],
    )

    assert result.exit_code != 0
    assert "unknown release for intent: missing" in result.output


def test_intent_enqueue_routes_movie_intent_to_movie_category(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent(
        "Call Me by Your Name 2017 Remux",
        store,
        metadata={"media_type": "movie"},
    )
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    assert downloader.calls == [
        (
            ranked.release.download_url,
            "movie",
            ["seed-agent", "movie"],
        )
    ]


def test_intent_enqueue_routes_show_intent_to_tv_category(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("show Severance 2022 S01", store)
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    assert downloader.calls == [
        (
            ranked.release.download_url,
            "tv",
            ["seed-agent", "tv"],
        )
    ]


def test_intent_enqueue_uses_downloader_media_category_map_for_anime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)
    config_path = _write_config(
        tmp_path,
        downloader_extra="""
  media_category_map:
    anime: movie
""",
    )
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent(
        "葬送的芙莉莲 2023",
        store,
        metadata={"media_type": "anime"},
    )
    ranked = _ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    assert downloader.calls == [
        (
            ranked.release.download_url,
            "movie",
            ["seed-agent", "movie"],
        )
    ]


def test_intent_enqueue_execute_resolves_mteam_deferred_download_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)

    async def fake_resolve_release(release, **kwargs):
        assert kwargs["api_key"] == "secret-api-key"
        return release.model_copy(
            update={
                "download_url": "https://dl.m-team.example/26799731?passkey=secret",
                "metadata": {
                    **release.metadata,
                    "download_url_source": "mteam_api",
                },
            }
        )

    monkeypatch.setattr(cli, "resolve_mteam_release_download_url", fake_resolve_release)
    config_path = _write_config(tmp_path)
    (tmp_path / "local" / "secrets").mkdir(parents=True)
    (tmp_path / "local" / "secrets" / "mt.api-key").write_text(
        "secret-api-key",
        encoding="utf-8",
    )
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            """
tracker_sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
""",
            """
tracker_sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.example/fallback
    discovery_mode: api
    api_key_ref: local/secrets/mt.api-key
    api_discovery:
      mode: movie
      only_free: false
""",
        ),
        encoding="utf-8",
    )
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Call Me by Your Name 2017 Remux", store)
    ranked = _mteam_deferred_ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    assert downloader.calls == [
        (
            "https://dl.m-team.example/26799731?passkey=secret",
            "movie",
            ["seed-agent", "movie"],
        )
    ]
    rows = store.list_release_candidates(intent.intent_id)
    stored = json.loads(str(rows[0]["release_json"]))
    assert stored["release"]["metadata"]["download_url_source"] == "mteam_api"
    assert "passkey=secret" not in result.output


def test_want_list_enqueue_allows_non_free_release_when_pt_flow_is_free_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    downloader = _DummyDownloader()
    monkeypatch.setattr(cli, "build_downloader", lambda config: downloader)

    async def resolve_release(release):
        return release.model_copy(
            update={
                "download_url": "https://dl.m-team.example/non-free",
                "metadata": {
                    **release.metadata,
                    "download_url_source": "mteam_api",
                },
            }
        )

    monkeypatch.setattr(
        cli,
        "_build_release_download_resolver",
        lambda config: resolve_release,
    )
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Call Me by Your Name 2017 Remux", store)
    ranked = _mteam_deferred_ranked(intent.intent_id)
    store.save_ranked_releases([ranked])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    assert downloader.calls[0][1] == "movie"
    assert _json_output(result)["decisions"][0]["action"] == "qb.enqueue"


def test_intent_enqueue_requires_confirmation_for_ambiguous_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from seed_agent import cli

    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    store = StateStore(tmp_path / ".seed-agent" / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)
    store.save_ranked_releases([_ranked(intent.intent_id, confirmation_required=True)])

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path)],
    )

    assert result.exit_code != 0
    assert "intent requires confirmation before enqueue" in result.output
