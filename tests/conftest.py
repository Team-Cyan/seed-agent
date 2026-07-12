from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_mteam_request_interval_for_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEED_AGENT_MTEAM_MIN_REQUEST_INTERVAL_SECONDS", "0")
