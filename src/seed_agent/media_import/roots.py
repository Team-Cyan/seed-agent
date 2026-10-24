"""Historical target authority is a verified descriptor, never today's route lookup."""

import json
from pathlib import Path

from seed_agent.media_import import filesystem as fs


class DestinationUnavailable(ValueError):
    """A target mount/marker/identity is not safe; do not spend provider allowance."""


class SourceUnavailable(ValueError):
    """A source mount cannot currently establish its authoritative identity."""


def describe(profile, *, route, revision):
    root = Path(profile.target_root)
    marker = getattr(profile, "target_marker", None) or profile.marker
    try:
        identity = fs.root_health(root, marker, profile.target_marker_value)
    except (OSError, ValueError) as exc:
        raise DestinationUnavailable(str(exc)) from exc
    return {
        "root": str(root),
        "marker": marker,
        "marker_value": profile.target_marker_value,
        "identity": identity,
        "route": route,
        "subdir": getattr(profile, "_route_subdir", ""),
        "config_revision": revision,
    }


def validate(descriptor, path=None):
    root = Path(descriptor["root"])
    try:
        actual = fs.root_health(root, descriptor["marker"], descriptor["marker_value"])
    except (OSError, ValueError) as exc:
        raise DestinationUnavailable(str(exc)) from exc
    if actual != descriptor["identity"]:
        raise DestinationUnavailable("historical destination identity changed")
    if path is not None:
        path = Path(path)
        if path == root or not path.is_relative_to(root) or ".." in path.parts:
            raise ValueError("artifact escapes historical destination")
        subdir = descriptor.get("subdir", "")
        if subdir and not path.is_relative_to(root / subdir):
            raise ValueError("artifact escapes historical route subtree")
    return root


def record_artifact(conn, artifact_id, descriptor):
    conn.execute(
        "INSERT INTO media_artifact_roots VALUES(?,?)",
        (artifact_id, json.dumps(descriptor, sort_keys=True)),
    )


def artifact(conn, artifact_id):
    row = conn.execute(
        "SELECT descriptor_json FROM media_artifact_roots WHERE artifact_id=?", (artifact_id,)
    ).fetchone()
    if not row:
        raise ValueError(
            "artifact lacks historical destination authority; explicit migration required"
        )
    return json.loads(row[0])
