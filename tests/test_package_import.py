import tomllib
from pathlib import Path

from seed_agent import __version__


def test_package_imports() -> None:
    assert __version__ == "0.6.0"


def test_release_version_sources_match() -> None:
    root = Path(__file__).resolve().parents[1]
    version_file = (root / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert version_file == __version__
    assert pyproject["project"]["version"] == version_file
