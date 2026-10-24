"""Bounded recursive source traversal excludes all output subtrees before descent."""

import os
import time
from pathlib import Path

from seed_agent.media_import import filesystem as fs


def inventory(source, destinations, *, historical_targets=(), max_files=20000, timeout=60):
    root = Path(source.root)
    observed = fs.root_health(root, source.marker, source.marker_value)
    outputs = [
        Path(p).resolve()
        for p in [*destinations.exclusion_roots(), *source.legacy_output_roots, *historical_targets]
    ]
    if any(root.resolve() == p or p in root.resolve().parents for p in outputs):
        raise ValueError(
            "historical destination contains source; explicit migration review required"
        )
    deadline = time.monotonic() + timeout
    result = {}

    def excluded(path):
        return any(path == p or p in path.parents for p in outputs)

    def onerror(error):
        raise error

    from seed_agent.media_import.engine import VIDEO

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        if time.monotonic() >= deadline:
            raise TimeoutError("source inventory time budget exceeded")
        kept = []
        for name in sorted(dirs):
            path = Path(directory) / name
            # Lexical and canonical paths both exclude known outputs, even when
            # their mounts are unavailable or replaced by symlinks.
            if name in source.exclude_dirs or excluded(path.absolute()) or excluded(path.resolve()):
                continue
            if path.is_symlink():
                raise ValueError("symlink directory in source")
            kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            if time.monotonic() >= deadline:
                raise TimeoutError("source inventory time budget exceeded")
            path = Path(directory) / name
            if path.suffix.lower() not in VIDEO:
                continue
            if len(result) >= max_files:
                raise ValueError("source inventory file budget exceeded")
            result[str(path.relative_to(root))] = fs.fingerprint(path)
    if fs.root_health(root, source.marker, source.marker_value) != observed:
        raise ValueError("source root changed during inventory")
    return result
