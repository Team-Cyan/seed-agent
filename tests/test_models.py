from seed_agent.models import Discount, TorrentCandidate


def test_candidate_normalizes_discount_and_stable_id() -> None:
    candidate = TorrentCandidate(
        site="demo",
        title="Example Free Torrent",
        source_url="https://tracker.example/details.php?id=42&passkey=secret",
        download_url="https://tracker.example/download.php?id=42&passkey=secret",
        size_bytes=10_000,
        seeders=10,
        leechers=20,
        discount="FREE",
        left_time_minutes=180,
        hr=False,
    )

    assert candidate.discount == Discount.FREE
    assert candidate.stable_id == "demo:https://tracker.example/details.php?id=42"
