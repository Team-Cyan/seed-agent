from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityTagGroup:
    key: str
    label: str
    aliases: tuple[str, ...]


QUALITY_TAG_GROUPS: dict[str, QualityTagGroup] = {
    "remux": QualityTagGroup("remux", "Remux", ("remux",)),
    "bluray": QualityTagGroup(
        "bluray",
        "Blu-ray",
        ("blu ray", "blu-ray", "bluray", "blue ray", "blue-ray", "bdrip", "bd rip", "蓝光"),
    ),
    "uhd_bluray": QualityTagGroup(
        "uhd_bluray",
        "UHD Blu-ray",
        ("uhd blu ray", "uhd bluray", "uhd blue ray", "4k uhd", "ultra hd"),
    ),
    "webdl": QualityTagGroup("webdl", "WEB-DL", ("web dl", "web-dl", "webdl")),
    "webrip": QualityTagGroup("webrip", "WEBRip", ("web rip", "web-rip", "webrip")),
    "hdtv": QualityTagGroup("hdtv", "HDTV", ("hdtv", "hdtvrip")),
    "dolby_vision": QualityTagGroup(
        "dolby_vision",
        "Dolby Vision",
        ("dolby vision", "dovi", "do vi", "dv", "杜比视界"),
    ),
    "hdr10_plus": QualityTagGroup(
        "hdr10_plus",
        "HDR10+",
        ("hdr10+", "hdr 10+", "hdr10 plus", "hdr 10 plus"),
    ),
    "hdr10": QualityTagGroup("hdr10", "HDR10", ("hdr10", "hdr 10")),
    "hdr": QualityTagGroup("hdr", "HDR", ("hdr",)),
    "sdr": QualityTagGroup("sdr", "SDR", ("sdr",)),
    "2160p": QualityTagGroup("2160p", "2160p / 4K", ("2160p", "4k")),
    "1080p": QualityTagGroup("1080p", "1080p", ("1080p", "fhd")),
    "hevc": QualityTagGroup("hevc", "HEVC / H.265", ("hevc", "h265", "h 265", "h.265", "x265")),
    "avc": QualityTagGroup("avc", "AVC / H.264", ("avc", "h264", "h 264", "h.264", "x264")),
    "av1": QualityTagGroup("av1", "AV1", ("av1",)),
    "atmos": QualityTagGroup(
        "atmos",
        "Dolby Atmos",
        ("atmos", "dolby atmos", "杜比全景声"),
    ),
    "ddp": QualityTagGroup(
        "ddp",
        "DDP / E-AC3",
        ("ddp", "dd+", "eac3", "e ac3", "e-ac3", "e-ac-3", "dolby digital plus"),
    ),
    "truehd": QualityTagGroup("truehd", "TrueHD", ("truehd", "true hd", "dolby truehd")),
    "dts_hd_ma": QualityTagGroup(
        "dts_hd_ma",
        "DTS-HD MA",
        ("dts-hd ma", "dts hd ma", "dtshdma", "dts-hdma"),
    ),
    "dts_x": QualityTagGroup("dts_x", "DTS:X", ("dts:x", "dtsx", "dts x")),
    "aac": QualityTagGroup("aac", "AAC", ("aac",)),
    "flac": QualityTagGroup("flac", "FLAC", ("flac",)),
    "ass": QualityTagGroup("ass", "ASS subtitles", ("ass", "ssa", "特效字幕")),
}


def quality_tag_group_keys() -> set[str]:
    return set(QUALITY_TAG_GROUPS)


def matching_quality_tag_groups(texts: list[str]) -> list[QualityTagGroup]:
    normalized_texts = [_normalize_search_text(text) for text in texts if text.strip()]
    matched: list[QualityTagGroup] = []
    for group in QUALITY_TAG_GROUPS.values():
        if any(_group_matches_text(group, text) for text in normalized_texts):
            matched.append(group)
    return matched


def quality_tag_texts(title: str, metadata: dict[str, Any]) -> list[str]:
    texts = [title]
    for key in ("mteam_tags", "categories"):
        value = metadata.get(key)
        if isinstance(value, list):
            texts.extend(str(item) for item in value)
    raw_tags = metadata.get("mteam_raw_tags")
    if isinstance(raw_tags, dict):
        texts.extend(_flatten_tag_values(raw_tags.values()))
    return texts


def _flatten_tag_values(values: Any) -> list[str]:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(str(item) for item in value)
        elif value is not None:
            flattened.append(str(value))
    return flattened


def _group_matches_text(group: QualityTagGroup, text: str) -> bool:
    return any(_alias_matches_text(alias, text) for alias in group.aliases)


def _alias_matches_text(alias: str, text: str) -> bool:
    normalized_alias = _normalize_search_text(alias)
    if not normalized_alias:
        return False
    pattern = (
        r"(?<![a-z0-9+])"
        + re.escape(normalized_alias).replace(r"\ ", r"\s+")
        + r"(?![a-z0-9+])"
    )
    return re.search(pattern, text) is not None


def _normalize_search_text(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    normalized = re.sub(r"[\._\-/\[\]\(\)]+", " ", normalized)
    return " ".join(normalized.split())
