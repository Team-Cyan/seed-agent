from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

FILES = (
    "VERSION",
    "Dockerfile",
    "pyproject.toml",
    "src/seed_agent/__init__.py",
    "uv.lock",
    "docs/operations/release-process.md",
    "tests/test_package_import.py",
)


def bump_version(root: Path, version: str) -> list[Path]:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must look like MAJOR.MINOR.PATCH")

    replacements = {
        "VERSION": lambda _text: f"{version}\n",
        "Dockerfile": lambda text: _replace(
            text,
            r"ARG VERSION=\d+\.\d+\.\d+",
            f"ARG VERSION={version}",
            count=1,
        ),
        "pyproject.toml": lambda text: _replace(
            text,
            r'version = "\d+\.\d+\.\d+"',
            f'version = "{version}"',
            count=1,
        ),
        "src/seed_agent/__init__.py": lambda text: _replace(
            text,
            r'__version__ = "\d+\.\d+\.\d+"',
            f'__version__ = "{version}"',
            count=1,
        ),
        "uv.lock": lambda text: _replace_seed_agent_lock_version(text, version),
        "docs/operations/release-process.md": lambda text: _replace(
            text,
            r"The current release line is `\d+\.\d+\.\d+`\.",
            f"The current release line is `{version}`.",
            count=1,
        ),
        "tests/test_package_import.py": lambda text: _replace(
            text,
            r'assert __version__ == "\d+\.\d+\.\d+"',
            f'assert __version__ == "{version}"',
            count=1,
        ),
    }

    changed = []
    for relative in FILES:
        path = root / relative
        original = path.read_text(encoding="utf-8")
        updated = replacements[relative](original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def _replace(text: str, pattern: str, replacement: str, *, count: int) -> str:
    updated, changed = re.subn(pattern, replacement, text, count=count, flags=re.MULTILINE)
    if changed != count:
        raise ValueError(f"expected {count} replacement for {pattern!r}, got {changed}")
    return updated


def _replace_seed_agent_lock_version(text: str, version: str) -> str:
    pattern = r'(\[\[package\]\]\nname = "seed-agent"\nversion = ")\d+\.\d+\.\d+(")'
    return _replace(text, pattern, rf"\g<1>{version}\2", count=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize seed-agent version files.")
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    changed = bump_version(args.root, args.version)
    for path in changed:
        print(path.relative_to(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
