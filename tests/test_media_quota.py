from datetime import UTC, datetime

import pytest

from seed_agent.media_import.store import MediaStore
from seed_agent.media_import.subtitles.provider import ProviderError
from seed_agent.media_import.subtitles.quota import DownloadBudget, quota_evidence


def test_provider_reset_uses_utc_or_duration_never_local_midnight():
    now = datetime(2026, 10, 23, 15, tzinfo=UTC).timestamp()
    assert quota_evidence(
        {"remaining": "0", "requests": 5, "reset_time_utc": "2026-10-24 01:00:00"}, now
    ) == {
        "remaining": 0,
        "requests": 5,
        "reset_at": datetime(2026, 10, 24, 1, tzinfo=UTC).timestamp(),
    }
    assert quota_evidence({"reset_time": "01:30:00"}, now)["reset_at"] == now + 5400
    assert quota_evidence({"reset_time": "invalid"}, now)["reset_at"] == now + 86400


def test_last_permitted_link_and_payload_failure_still_exhaust_budget(tmp_path):
    store = MediaStore(tmp_path / "media.db")
    now = [1000]
    budget = DownloadBudget(store, "fixture", clock=lambda: now[0])
    budget.reserve()
    budget.observe({"remaining": 1, "reset_time": "01:00:00"})
    budget.reserve()
    budget.observe({"remaining": 0, "reset_time": "01:00:00"})
    # Payload retrieval may fail here; known link allowance stays consumed.
    restarted = DownloadBudget(store, "fixture", clock=lambda: now[0])
    with pytest.raises(ProviderError, match="daily_quota"):
        restarted.reserve()
    now[0] += 3601
    restarted.reserve()  # exactly one probe after service reset
    with pytest.raises(ProviderError, match="daily_quota"):
        budget.reserve()


def test_response_lost_reservation_is_shared_and_durable(tmp_path):
    store = MediaStore(tmp_path / "media.db")
    budget = DownloadBudget(store, "fixture", clock=lambda: 1000)
    budget.reserve()
    competing = DownloadBudget(store, "fixture", clock=lambda: 1001)
    with pytest.raises(ProviderError) as caught:
        competing.reserve()
    assert caught.value.status == "daily_quota"
    assert caught.value.retry_after == 86399
    budget.observe({"remaining": 3})
    competing.reserve()
    # Old delayed evidence cannot release a different in-flight reservation.
    assert budget.observe({"remaining": 99}) is None
    with pytest.raises(ProviderError):
        budget.reserve()


def test_restore_cannot_refund_downloads_after_snapshot(tmp_path):
    from seed_agent.media_import.maintenance import backup_media_database, restore_media_database

    store = MediaStore(tmp_path / "media.db")
    backup = tmp_path / "before-download.db"
    backup_media_database(store.path, backup)
    budget = DownloadBudget(store, "fixture", clock=lambda: 1000)
    budget.reserve()
    budget.observe({"remaining": 0})
    restore_media_database(store.path, backup, execute=True)
    with pytest.raises(ProviderError, match="superseded"):
        budget.check()
    with pytest.raises(ProviderError, match="daily_quota"):
        DownloadBudget(store, "fixture", clock=lambda: 1000).check()


def test_account_evidence_cannot_refund_reserved_or_spent_allowance(tmp_path):
    store = MediaStore(tmp_path / "media.db")
    budget = DownloadBudget(store, "subdl", clock=lambda: 1000)
    budget.sync({"remaining": 2, "reset_time": "01:00:00"})
    budget.reserve()
    assert budget.sync({"remaining": 2, "reset_time": "01:00:00"}) is None
    assert budget.observe({"remaining": 2, "reset_time": "01:00:00"})["remaining"] == 1
    restarted = DownloadBudget(store, "subdl", clock=lambda: 1000)
    assert restarted.sync({"remaining": 99, "reset_time": "01:00:00"})["remaining"] == 1
    restarted.reserve()
    restarted.observe({"remaining": 99, "reset_time": "01:00:00"})
    with pytest.raises(ProviderError, match="daily_quota"):
        budget.reserve()


def test_account_and_download_observations_after_restore_do_not_write(tmp_path):
    store = MediaStore(tmp_path / "media.db")
    budget = DownloadBudget(store, "subdl", clock=lambda: 1000)
    budget.reserve()
    with store._connect() as conn:
        conn.execute("UPDATE media_control SET epoch='new-epoch'")
    assert budget.sync({"remaining": 99}) is None
    assert budget.observe({"remaining": 99}) is None
    with pytest.raises(ProviderError, match="superseded"):
        budget.reserve()
    with pytest.raises(ProviderError, match="daily_quota"):
        DownloadBudget(store, "subdl", clock=lambda: 1000).reserve()
