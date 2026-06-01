from __future__ import annotations

from pathlib import Path

from seed_agent.web.app import _content_type_for


def test_static_image_content_types_are_browser_renderable() -> None:
    assert _content_type_for(Path("favicon.svg")) == "image/svg+xml"
    assert _content_type_for(Path("seed-agent-icon.png")) == "image/png"
