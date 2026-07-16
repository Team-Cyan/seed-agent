from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATH_PATTERNS = (
    ".env",
    ".env.*",
    ".seed-agent/*",
    "config/live-*.yaml",
    "config/live-*.yml",
    "local/inbox/*",
    "local/runtime/*",
    "local/secrets/*",
    "*.cookie",
    "*.db",
    "*.key",
    "*.pem",
    "*.sqlite",
    "*.sqlite3",
    "*.torrent",
    "audit.jsonl",
)

ALLOWED_LOCAL_MARKERS = {
    "local/inbox/.gitkeep",
    "local/secrets/.gitkeep",
}

CONTENT_RULES = (
    (
        "absolute user home path",
        re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    ),
    (
        "RFC1918 private IPv4 address",
        re.compile(
            rb"(?<![0-9])(?:10(?:\.[0-9]{1,3}){3}|192\.168(?:\.[0-9]{1,3}){2}|"
            rb"172\.(?:1[6-9]|2[0-9]|3[01])(?:\.[0-9]{1,3}){2})(?![0-9])"
        ),
    ),
    (
        "private key material",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "high-confidence access token",
        re.compile(
            rb"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
            rb"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,})"
        ),
    ),
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item.decode() for item in result.stdout.split(b"\0") if item]


def _forbidden_path(path: str) -> bool:
    if path in ALLOWED_LOCAL_MARKERS:
        return False
    if (
        path.startswith("config/")
        and path.endswith((".yaml", ".yml"))
        and path != "config/example.yaml"
        and not path.startswith("config/profiles/")
    ):
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in FORBIDDEN_PATH_PATTERNS)


def main() -> int:
    findings: list[str] = []
    for relative_path in _tracked_files():
        if _forbidden_path(relative_path):
            findings.append(f"{relative_path}: tracked private/runtime path")
            continue

        path = ROOT / relative_path
        try:
            content = path.read_bytes()
        except OSError as exc:
            findings.append(f"{relative_path}: cannot read tracked file: {exc}")
            continue
        if b"\0" in content:
            continue
        for label, pattern in CONTENT_RULES:
            match = pattern.search(content)
            if match is None:
                continue
            line = content.count(b"\n", 0, match.start()) + 1
            findings.append(f"{relative_path}:{line}: {label}")

    if findings:
        print("Public repository hygiene check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Public repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
