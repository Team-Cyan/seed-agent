"""Root-fenced descriptor-relative filesystem operations; never follow symlinks."""

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path


def fingerprint(path: Path) -> str:
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError("source must be a regular non-symlink file")
    return json.dumps([s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns])


def identity(path: Path) -> str:
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode):
        raise ValueError("root/directory must not be a symlink")
    return json.dumps([s.st_dev, s.st_ino])


def root_health(root: Path, marker: str, expected: str) -> str:
    # Reject symlinks in every ancestor, including the configured root itself.
    for p in [*reversed(root.parents), root]:
        identity(p)
    with parent_fd(root, root / marker) as (fd, name):
        mfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(mfd, "rb") as f:
            if f.read(4097).decode("utf-8").strip() != expected:
                raise ValueError("volume marker mismatch")
    return identity(root)


@contextmanager
def parent_fd(root: Path, path: Path):
    rel = path.relative_to(root)
    if not rel.parts or any(p in {"", ".", ".."} for p in rel.parts):
        raise ValueError("path escapes root")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in rel.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, rel.name
    finally:
        os.close(fd)


def receipt(root: Path, path: Path, *, digest=False) -> dict:
    with parent_fd(root, path) as (fd, name):
        item = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(item, "rb") as f:
            s = os.fstat(f.fileno())
            if not stat.S_ISREG(s.st_mode):
                raise ValueError("artifact not regular")
            result = {
                "dev": s.st_dev,
                "ino": s.st_ino,
                "size": s.st_size,
                "mtime_ns": s.st_mtime_ns,
            }
            if digest:
                h = hashlib.sha256()
                while chunk := f.read(65536):
                    h.update(chunk)
                result["digest"] = h.hexdigest()
            return result


def link(source_root: Path, source: Path, target_root: Path, target: Path):
    with parent_fd(source_root, source) as (sfd, src), parent_fd(target_root, target) as (tfd, dst):
        if not stat.S_ISREG(os.stat(src, dir_fd=sfd, follow_symlinks=False).st_mode):
            raise ValueError("unsafe source")
        os.link(src, dst, src_dir_fd=sfd, dst_dir_fd=tfd, follow_symlinks=False)


def unlink(root: Path, path: Path, expected: dict):
    actual = receipt(root, path, digest="digest" in expected)
    if actual != expected:
        raise ValueError("artifact identity/content changed")
    with parent_fd(root, path) as (fd, name):
        # Verify once more against the actual directory descriptor before unlink.
        s = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) != (
            expected["dev"],
            expected["ino"],
            expected["size"],
            expected["mtime_ns"],
        ):
            raise ValueError("artifact changed before unlink")
        os.unlink(name, dir_fd=fd)
