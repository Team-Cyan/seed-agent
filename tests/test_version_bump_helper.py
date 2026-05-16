from __future__ import annotations

import importlib.util
from pathlib import Path


def load_bump_module():
    script_path = Path("scripts/bump_version.py")
    spec = importlib.util.spec_from_file_location("bump_version", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bump_version_updates_release_metadata(tmp_path: Path) -> None:
    for relative in (
        "VERSION",
        "pyproject.toml",
        "src/seed_agent/__init__.py",
        "uv.lock",
        "docs/operations/release-process.md",
        "tests/test_package_import.py",
    ):
        source = Path(relative)
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    module = load_bump_module()
    changed = module.bump_version(tmp_path, "1.2.3")

    assert {path.relative_to(tmp_path).as_posix() for path in changed} == {
        "VERSION",
        "pyproject.toml",
        "src/seed_agent/__init__.py",
        "uv.lock",
        "docs/operations/release-process.md",
        "tests/test_package_import.py",
    }
    assert (tmp_path / "VERSION").read_text(encoding="utf-8") == "1.2.3\n"
    assert 'version = "1.2.3"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '__version__ = "1.2.3"' in (tmp_path / "src/seed_agent/__init__.py").read_text(
        encoding="utf-8",
    )
    assert 'name = "seed-agent"\nversion = "1.2.3"' in (tmp_path / "uv.lock").read_text(
        encoding="utf-8",
    )
    assert "The current release line is `1.2.3`." in (
        tmp_path / "docs/operations/release-process.md"
    ).read_text(encoding="utf-8")
    assert 'assert __version__ == "1.2.3"' in (
        tmp_path / "tests/test_package_import.py"
    ).read_text(encoding="utf-8")
