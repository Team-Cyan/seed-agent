from pathlib import Path

CURRENT_DOCS = (
    Path("README.md"),
    Path("docs/architecture.md"),
    Path("docs/ai/project-overview.md"),
)


def test_current_docs_match_implemented_extension_surface() -> None:
    content_by_path = {path: path.read_text(encoding="utf-8") for path in CURRENT_DOCS}
    combined = "\n".join(content_by_path.values())

    for path in (
        Path("src/seed_agent/downloaders/transmission.py"),
        Path("src/seed_agent/search/torznab.py"),
        Path("src/seed_agent/sources/letterboxd.py"),
        Path("src/seed_agent/sources/telegram.py"),
    ):
        assert path.exists()

    for term in (
        "Transmission",
        "Torznab",
        "Letterboxd",
        "Telegram",
        "min_free_disk_gb",
    ):
        assert term in combined

    stale_phrases = (
        "qBittorrent only",
        "qBittorrent is the only implemented downloader",
        "The only implemented downloader",
        "Transmission downloader | Planned",
        "Telegram | Parser skeleton",
    )
    for phrase in stale_phrases:
        for path, content in content_by_path.items():
            assert phrase not in content, f"{phrase!r} is stale in {path}"
