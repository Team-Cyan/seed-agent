import pytest
from pydantic import ValidationError

from seed_agent.models import Discount, TorrentCandidate, safe_url_identity


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


def test_candidate_rejects_unknown_discount_label() -> None:
    with pytest.raises(ValidationError, match="unknown discount label"):
        TorrentCandidate(
            site="demo",
            title="Example Torrent",
            source_url="https://tracker.example/details.php?id=42",
            download_url="https://tracker.example/download.php?id=42",
            size_bytes=10_000,
            seeders=10,
            leechers=20,
            discount="bogus",
            left_time_minutes=180,
            hr=False,
        )


def test_safe_url_identity_strips_pt_secret_keys_but_keeps_safe_params() -> None:
    url = (
        "https://tracker.example/details.php?id=42"
        "&authkey=secret"
        "&pass_key=secret"
        "&torrent_pass=secret"
        "&safe=value"
        "&key=keep"
    )

    identity = safe_url_identity(url)

    assert identity == "https://tracker.example/details.php?id=42&safe=value&key=keep"


def test_safe_url_identity_strips_explicit_password_query_keys() -> None:
    url = (
        "https://tracker.example/details.php?id=42"
        "&password=hunter2"
        "&passphrase=open-sesame"
        "&safe=value"
    )

    identity = safe_url_identity(url)

    assert identity == "https://tracker.example/details.php?id=42&safe=value"


def test_safe_url_identity_strips_common_secret_variants() -> None:
    url = "https://tracker.example/download.php?id=42&token=abc&sign=sig&hash=deadbeef"

    identity = safe_url_identity(url)

    assert identity == "https://tracker.example/download.php?id=42"


def test_safe_url_identity_preserves_safe_words_that_contain_secret_substrings() -> None:
    url = "https://tracker.example/details.php?id=42&bypass=1&compass=2&token=3"

    identity = safe_url_identity(url)

    assert identity == "https://tracker.example/details.php?id=42&bypass=1&compass=2"


def test_safe_url_identity_strips_userinfo_and_keeps_safe_parts() -> None:
    url = "https://user:pass@tracker.example/details.php?id=42"

    identity = safe_url_identity(url)

    assert identity == "https://tracker.example/details.php?id=42"


def test_safe_url_identity_strips_userinfo_and_preserves_port() -> None:
    url = "https://user:pass@tracker.example:8443/details.php?id=42&passkey=secret"

    identity = safe_url_identity(url)

    assert identity == "https://tracker.example:8443/details.php?id=42"
