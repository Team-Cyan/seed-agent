from __future__ import annotations

from pathlib import Path

from seed_agent.web.app import CANONICAL_ICON_NAME, _content_type_for, _static_asset_path


def test_static_image_content_types_are_browser_renderable() -> None:
    assert _content_type_for(Path(CANONICAL_ICON_NAME)) == "image/png"
    assert _static_asset_path(CANONICAL_ICON_NAME).is_file()


def test_icon_assets_have_one_editable_source_and_one_published_png() -> None:
    assets = Path("docs/assets")

    assert {path.name for path in assets.glob("*icon*")} == {"icon.svg", "icon.png"}
    assert not Path("src/seed_agent/web/static/favicon.svg").exists()
