import json
from pathlib import Path

from typer.testing import CliRunner

from seed_agent.actions.intent import add_intent
from seed_agent.models import Discount, IntentState, RankedRelease, ReleaseCandidate
from seed_agent.state import StateStore


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
mode: balanced
sites:
  - name: demo-free
    type: nexusphp
    enabled: true
    rss_url: https://tracker.example/rss.php
    cookie_ref: null
discovery:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  max_seeders: 80
  allow_hr: false
scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5
downloader:
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
  budget_pools:
    - name: downloads
      max_size_tib: 10
  secret_ref: null
cleanup:
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
        score=95 if not confirmation_required else 80,
        confidence=0.95 if not confirmation_required else 0.8,
        accepted=not confirmation_required,
        confirmation_required=confirmation_required,
        reasons=["title tokens matched"],
        risks=[] if not confirmation_required else ["resolution missing"],
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
    assert downloader.calls == []
    row = store.get_intent(intent.intent_id)
    assert row is not None
    assert row["state"] == IntentState.NORMALIZED.value
    assert "passkey=secret" not in result.output


def test_intent_enqueue_execute_uses_confirmed_release_and_updates_state(
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
    store.update_intent_state(
        intent.intent_id,
        IntentState.CONFIRMED,
        selected_release_id=ranked.release.release_id,
    )

    result = CliRunner().invoke(
        cli.app,
        ["intent-enqueue", intent.intent_id, "--config", str(config_path), "--execute"],
    )

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["execute"] is True
    assert payload["intent"]["state"] == IntentState.ENQUEUED.value
    assert downloader.calls == [
        (
            ranked.release.download_url,
            "seed",
            ["seed-agent", "seed"],
        )
    ]
    row = store.get_intent(intent.intent_id)
    assert row is not None
    assert row["state"] == IntentState.ENQUEUED.value
    assert row["selected_release_id"] == ranked.release.release_id
    audit = (tmp_path / ".seed-agent" / "audit.jsonl").read_text(encoding="utf-8")
    assert "qb.enqueue" in audit


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
