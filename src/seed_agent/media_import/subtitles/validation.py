"""Validate subtitle payloads without extraction or changes to source bytes."""

import io
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath

MAX_BYTES = 2_000_000


def normalized_release(value):
    """Ignore format/separators only; retain every identity/version token."""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"(?i)\.(?:mkv|mp4|avi|m4v|ts|mov|webm|srt|ass|ssa|vtt)$", "", value)
    return re.sub(r"[\W_]", "", value).casefold()


def validate(payload: bytes, *, duration: float) -> tuple[bytes, str]:
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("subtitle size out of bounds")
    if payload.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 5 or sum(i.file_size for i in entries) > MAX_BYTES:
                raise ValueError("archive bounds exceeded")
            for item in entries:
                p = PurePosixPath(item.filename)
                if (
                    p.is_absolute()
                    or ".." in p.parts
                    or "\\" in item.filename
                    or item.flag_bits & 1
                ):
                    raise ValueError("unsafe archive path/encryption")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("archive symlink")
                if item.compress_size and item.file_size / item.compress_size > 100:
                    raise ValueError("archive expansion ratio exceeded")
            subtitles = [
                i
                for i in entries
                if PurePosixPath(i.filename).suffix.lower() in {".srt", ".ass", ".vtt"}
            ]
            if len(subtitles) != 1:
                raise ValueError("ambiguous archive subtitle")
            payload = archive.read(subtitles[0])
    text = None
    for encoding in ["utf-8-sig", "utf-16", "gb18030", "big5"]:
        try:
            decoded = payload.decode(encoding)
            if "\x00" not in decoded:
                text = decoded
                break
        except UnicodeError:
            continue
    if text is None or re.search(r'(?i)<(?:html|!doctype|script)|"error"\s*:', text):
        raise ValueError("not a subtitle payload")
    fmt = (
        "ass"
        if "[Events]" in text and "[Script Info]" in text
        else ("vtt" if text.startswith("WEBVTT") else "srt")
    )
    timestamps = re.findall(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{2,3})", text)
    if len(timestamps) < 2:
        raise ValueError("subtitle contains no bounded timestamps")
    times = []
    for h, m, s, ms in timestamps:
        if int(m) > 59 or int(s) > 59:
            raise ValueError("invalid subtitle timestamp")
        times.append(
            int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / (100 if len(ms) == 2 else 1000)
        )
    if max(times) > duration + 120:
        raise ValueError("subtitle timing exceeds media; end time does not prove synchronization")
    if fmt in {"srt", "vtt"} and "-->" not in text:
        raise ValueError("invalid subtitle cue syntax")
    return text.replace("\r\n", "\n").encode("utf-8"), fmt


def compatible(candidate, mapping, source, profile):
    """Return evidence ordered before language/popularity; explicit mismatch always rejects."""
    if candidate.tmdb_id is not None and candidate.tmdb_id != mapping["tmdb_id"]:
        return None
    if candidate.imdb_id and mapping.get("imdb_id") and candidate.imdb_id != mapping["imdb_id"]:
        return None
    exact = candidate.tmdb_id == mapping["tmdb_id"] or (
        candidate.imdb_id and candidate.imdb_id == mapping.get("imdb_id")
    )
    if not exact:
        return None
    if mapping["media_type"] != "movie" and (
        candidate.season != mapping.get("season")
        or tuple(candidate.episodes) != tuple(mapping.get("episodes", []))
    ):
        return None
    if candidate.kind != profile.subtitle_kind:
        return None
    edition = mapping.get("edition")
    release = candidate.release.casefold()
    explicit = candidate.edition
    if not explicit:
        for token, label in [
            ("extended", "Extended"),
            ("unrated", "Unrated"),
            ("director's cut", "Director's Cut"),
        ]:
            if token in release:
                explicit = label
    if explicit and explicit != edition:
        return None
    if edition and explicit != edition and not candidate.hash_match:
        return None
    probe = source.get("probe", {})
    if candidate.fps and probe.get("fps") and abs(candidate.fps - probe["fps"]) > 0.1:
        return None

    release_match = bool(
        candidate.release
        and normalized_release(candidate.release) == normalized_release(source["original_release"])
    )
    # Work-only matches need operator preview; never auto-publish a random version.
    if not candidate.hash_match and not release_match:
        candidate.match_basis = "needs_preview"
        return (0, 0, candidate.rating or 0, candidate.downloads or 0)
    candidate.match_basis = "hash_matched" if candidate.hash_match else "release_matched"
    return (
        int(candidate.hash_match),
        int(release_match),
        int(bool(candidate.fps)),
        int(candidate.trusted),
        candidate.rating or 0,
        candidate.downloads or 0,
    )
