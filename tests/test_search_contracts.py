from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from seed_agent.actions.intent import add_intent, search_intent
from seed_agent.models import Discount, ReleaseCandidate
from seed_agent.state import StateStore


def _release(**overrides: object) -> ReleaseCandidate:
    data: dict[str, object] = {
        "release_id": "demo:https://tracker.example/details.php?id=1",
        "site": "demo",
        "title": "Inception 2010 1080p BluRay",
        "source_url": "https://tracker.example/details.php?id=1",
        "download_url": "https://tracker.example/download.php?id=1&passkey=secret",
        "size_bytes": 12 * 1024**3,
        "seeders": 30,
        "leechers": 8,
        "discount": Discount.FREE,
    }
    data.update(overrides)
    return ReleaseCandidate(**data)


class StaticProvider:
    def __init__(self, releases: list[ReleaseCandidate]) -> None:
        self.releases = releases

    async def search(self, intent):
        return self.releases


class FailingProvider:
    async def search(self, intent):
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_search_provider_contract_returns_release_candidate_shape() -> None:
    provider = StaticProvider([_release()])

    releases = await provider.search(object())

    assert releases == [_release()]
    assert isinstance(releases[0], ReleaseCandidate)


@pytest.mark.asyncio
async def test_search_provider_contract_allows_empty_results() -> None:
    provider = StaticProvider([])

    assert await provider.search(object()) == []


@pytest.mark.asyncio
async def test_search_provider_contract_persists_releases_through_intent_loop(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent(
        "Inception 2010 1080p",
        store,
        requested_at=datetime(2026, 4, 22, tzinfo=UTC),
    )

    searched, ranked, decision = await search_intent(
        intent.intent_id,
        store,
        [StaticProvider([_release()])],
    )

    rows = store.list_release_candidates(intent.intent_id)
    assert searched.intent_id == intent.intent_id
    assert len(ranked) == 1
    assert decision.new_state["candidate_count"] == 1
    assert rows[0]["release_id"] == "demo:https://tracker.example/details.php?id=1"
    assert rows[0]["site"] == "demo"


@pytest.mark.asyncio
async def test_search_provider_contract_provider_errors_do_not_persist_partial_results(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state.db")
    intent, _ = add_intent("Inception 2010 1080p", store)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await search_intent(
            intent.intent_id,
            store,
            [StaticProvider([_release()]), FailingProvider()],
        )

    assert store.list_release_candidates(intent.intent_id) == []
