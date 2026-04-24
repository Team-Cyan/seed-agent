from __future__ import annotations

from pathlib import Path

import pytest

from seed_agent.audit import AuditLogger
from seed_agent.config import CategoryPolicyConfig
from seed_agent.models import ScoreBreakdown, TorrentCandidate


def _candidate(**overrides: object) -> TorrentCandidate:
    data: dict[str, object] = {
        "site": "demo-free",
        "title": "High Confidence Torrent",
        "source_url": "https://tracker.example/details.php?id=1",
        "download_url": "https://tracker.example/download.php?id=1&passkey=secret",
        "size_bytes": 10 * 1024 * 1024 * 1024,
        "seeders": 20,
        "leechers": 30,
        "discount": "free",
        "left_time_minutes": 240,
        "hr": False,
    }
    data.update(overrides)
    return TorrentCandidate(**data)


def _scored(**overrides: object) -> ScoreBreakdown:
    candidate = overrides.pop("candidate", _candidate())
    data: dict[str, object] = {
        "candidate_id": candidate.stable_id,
        "score": 95,
        "accepted": True,
        "reasons": ["discount free accepted", "leechers strong"],
        "candidate": candidate,
    }
    data.update(overrides)
    return ScoreBreakdown(**data)


def _policy(**overrides: object) -> CategoryPolicyConfig:
    data: dict[str, object] = {
        "name": "seed",
        "mode": "mutable",
        "budget_pool": "downloads",
        "delete_enabled": True,
        "over_budget_behavior": "add_paused",
        "tags": ["seed-agent", "seed"],
    }
    data.update(overrides)
    return CategoryPolicyConfig(**data)


class DummyDownloader:
    def __init__(self, torrent_hash: str | None = None) -> None:
        self.torrent_hash = torrent_hash
        self.calls: list[tuple[str, str, list[str], bool]] = []

    async def add_url(
        self, url: str, category: str, tags: list[str], *, paused: bool = False
    ) -> str | None:
        self.calls.append((url, category, tags, paused))
        return self.torrent_hash


class FailingSecondDownloader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add_url(
        self, url: str, category: str, tags: list[str], *, paused: bool = False
    ) -> str | None:
        self.calls.append(url)
        if len(self.calls) == 2:
            raise RuntimeError("qB add failed")
        return "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.asyncio
async def test_dry_run_accepted_candidate_skips_downloader_and_returns_execute_false() -> None:
    from seed_agent.actions.qb import enqueue_candidates

    downloader = DummyDownloader(torrent_hash="deadbeef")

    decisions = await enqueue_candidates(
        [_scored()],
        downloader,
        _policy(),
        execute=False,
    )

    assert downloader.calls == []
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.action == "qb.enqueue"
    assert decision.execute is False
    assert decision.rollback == "Delete torrent from qBittorrent if enqueue was accidental"
    assert decision.new_state["download_url"] == _scored().candidate.download_url
    assert "passkey=secret" not in decision.reason
    assert _scored().candidate.download_url not in decision.reason


@pytest.mark.asyncio
async def test_execute_accepted_candidate_calls_downloader_and_records_hash() -> None:
    from seed_agent.actions.qb import enqueue_candidates

    downloader = DummyDownloader(torrent_hash="0123456789abcdef0123456789abcdef01234567")

    decisions = await enqueue_candidates(
        [_scored()],
        downloader,
        _policy(),
        execute=True,
    )

    assert downloader.calls == [
        (
            _scored().candidate.download_url,
            "seed",
            ["seed-agent", "seed"],
            False,
        )
    ]
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.execute is True
    assert decision.new_state["torrent_hash"] == "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.asyncio
async def test_rejected_candidate_does_not_call_downloader() -> None:
    from seed_agent.actions.qb import enqueue_candidates

    downloader = DummyDownloader()

    decisions = await enqueue_candidates(
        [_scored(accepted=False, score=11, reasons=["rejected"])],
        downloader,
        _policy(),
        execute=True,
    )

    assert downloader.calls == []
    assert decisions == []


@pytest.mark.asyncio
async def test_execute_batch_failure_carries_prior_enqueue_decisions() -> None:
    from seed_agent.actions.qb import MutationBatchError, enqueue_candidates

    first = _scored(candidate=_candidate(title="First", source_url="https://tracker.example/a"))
    second = _scored(candidate=_candidate(title="Second", source_url="https://tracker.example/b"))
    downloader = FailingSecondDownloader()

    with pytest.raises(MutationBatchError) as raised:
        await enqueue_candidates(
            [first, second],
            downloader,
            _policy(),
            execute=True,
        )

    decisions = raised.value.decisions
    assert [decision.action for decision in decisions] == ["qb.enqueue", "qb.enqueue.failed"]
    assert decisions[0].target_id == first.candidate_id
    assert decisions[1].target_id == second.candidate_id
    assert "qB add failed" in decisions[1].reason


@pytest.mark.asyncio
async def test_audit_logger_redacts_decision_with_download_url_passkey(tmp_path: Path) -> None:
    from seed_agent.actions.qb import enqueue_candidates

    downloader = DummyDownloader()
    decisions = await enqueue_candidates(
        [_scored()],
        downloader,
        _policy(),
        execute=False,
    )

    path = tmp_path / "audit.jsonl"
    AuditLogger(path).write(decisions[0])

    written = path.read_text(encoding="utf-8")
    assert "passkey=secret" not in written
    assert "download.php?id=1" in written


@pytest.mark.asyncio
async def test_downloader_exception_propagates() -> None:
    from seed_agent.actions.qb import MutationBatchError, enqueue_candidates

    class FailingDownloader:
        async def add_url(
            self, url: str, category: str, tags: list[str], *, paused: bool = False
        ) -> str | None:
            raise RuntimeError("network down")

    with pytest.raises(MutationBatchError) as raised:
        await enqueue_candidates(
            [_scored()],
            FailingDownloader(),
            _policy(),
            execute=True,
        )

    assert "network down" in raised.value.decisions[0].reason


@pytest.mark.asyncio
async def test_execute_accepted_candidate_adds_paused_when_pool_is_over_budget() -> None:
    from seed_agent.actions.qb import enqueue_candidates

    downloader = DummyDownloader(torrent_hash="0123456789abcdef0123456789abcdef01234567")

    decisions = await enqueue_candidates(
        [_scored()],
        downloader,
        _policy(),
        execute=True,
        paused=True,
    )

    assert downloader.calls == [
        (
            _scored().candidate.download_url,
            "seed",
            ["seed-agent", "seed"],
            True,
        )
    ]
    assert decisions[0].new_state["paused"] is True
