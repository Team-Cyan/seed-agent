"""Configured container identity is a precondition, never a permission repair."""

import os
import re


class RuntimeIdentityError(RuntimeError):
    """The caller has not completed the configured privilege transition."""


def verify_runtime_identity() -> None:
    """Fail before filesystem effects; standalone callers without a pair are unchanged.

    Real/effective/saved IDs are checked where available so a dropped-marker or
    an effective-only transition cannot stand in for the actual process identity.
    The shell entrypoint remains responsible for dropping groups/capabilities.
    """
    uid, gid = os.environ.get("PUID", ""), os.environ.get("PGID", "")
    if not uid and not gid:
        return
    if not re.fullmatch(r"[0-9]+", uid) or not re.fullmatch(r"[0-9]+", gid):
        raise RuntimeIdentityError("PUID and PGID must be configured together as numeric IDs")
    if len(uid) > 10 or len(gid) > 10 or max(int(uid), int(gid)) >= 2**32 - 1:
        raise RuntimeIdentityError("configured PUID/PGID are outside the supported ID range")
    expected_uid, expected_gid = int(uid), int(gid)
    uids = os.getresuid() if hasattr(os, "getresuid") else (os.getuid(), os.geteuid())
    gids = os.getresgid() if hasattr(os, "getresgid") else (os.getgid(), os.getegid())
    if any(value != expected_uid for value in uids) or any(
        value != expected_gid for value in gids
    ):
        raise RuntimeIdentityError("process identity differs from configured PUID/PGID")


def runtime_identity_observation() -> dict[str, int]:
    """Bounded diagnostics for the actual health process, independent of PID1."""
    verify_runtime_identity()
    return {"uid": os.geteuid(), "gid": os.getegid()}
