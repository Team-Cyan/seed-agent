from __future__ import annotations

from seed_agent.models import ManagedTorrent, ScoreBreakdown

GIB = 1024**3


def torrent_retention_quality_score(torrent: ManagedTorrent) -> float:
    """Higher means the existing torrent is more worth keeping."""

    return float(torrent_quality_evidence(torrent)["retention_quality_score"])


def torrent_quality_evidence(torrent: ManagedTorrent) -> dict[str, float | int | bool]:
    """Return stable, inspectable components used by retention and eviction ranking."""

    size_gib = max(torrent.size_bytes / GIB, 0.001)
    total_uploaded_gib = torrent.uploaded_bytes / GIB
    total_ratio = total_uploaded_gib / size_gib
    recent_1h_gib = _metadata_gib(torrent, "recent_upload_1h_gb")
    recent_24h_gib = _metadata_gib(torrent, "recent_upload_24h_gb")
    recent_gib = _metadata_gib(torrent, "recent_upload_gb", "upload_delta_gb")
    session_gib = _metadata_bytes_as_gib(torrent, "uploaded_session_bytes")
    upspeed_mib_s = _metadata_bytes_as_mib(torrent, "upspeed_bps")

    hourly_density = recent_1h_gib / size_gib
    daily_density = recent_24h_gib / size_gib
    recent_density = recent_gib / size_gib
    session_density = session_gib / size_gib

    retention_score = (
        hourly_density * 100.0
        + daily_density * 35.0
        + recent_density * 20.0
        + session_density * 6.0
        + total_ratio * 4.0
        + min(upspeed_mib_s, 20.0) * 0.1
    )
    evidence_points = sum(
        key in torrent.metadata
        for key in (
            "recent_upload_1h_gb",
            "recent_upload_24h_gb",
            "recent_upload_gb",
            "upload_delta_gb",
            "uploaded_session_bytes",
            "upspeed_bps",
        )
    )
    return {
        "size_gib": size_gib,
        "total_ratio": total_ratio,
        "hourly_density": hourly_density,
        "daily_density": daily_density,
        "recent_density": recent_density,
        "session_density": session_density,
        "upspeed_mib_s": upspeed_mib_s,
        "retention_quality_score": retention_score,
        "evidence_points": evidence_points,
        "evidence_sufficient": evidence_points >= 1,
    }


def torrent_eviction_pressure_score(torrent: ManagedTorrent) -> float:
    """Higher means the torrent should be considered earlier for deletion."""

    size_gib = torrent.size_bytes / GIB
    amount_left_gib = _metadata_bytes_as_gib(torrent, "amount_left_bytes")
    quality = torrent_retention_quality_score(torrent)
    stale_penalty = 3.0 if torrent.last_activity_at is None else 0.0
    incomplete_pressure = amount_left_gib * 0.03
    size_pressure = size_gib * 0.005
    error_pressure = _error_state_pressure(torrent)
    return error_pressure + stale_penalty + incomplete_pressure + size_pressure - quality


def torrent_eviction_evidence(torrent: ManagedTorrent) -> dict[str, float | int | bool]:
    quality = torrent_quality_evidence(torrent)
    amount_left_gib = _metadata_bytes_as_gib(torrent, "amount_left_bytes")
    stale_penalty = 3.0 if torrent.last_activity_at is None else 0.0
    incomplete_pressure = amount_left_gib * 0.03
    size_pressure = float(quality["size_gib"]) * 0.005
    error_pressure = _error_state_pressure(torrent)
    return {
        **quality,
        "amount_left_gib": amount_left_gib,
        "stale_penalty": stale_penalty,
        "incomplete_pressure": incomplete_pressure,
        "size_pressure": size_pressure,
        "error_pressure": error_pressure,
        "eviction_pressure_score": (
            error_pressure
            + stale_penalty
            + incomplete_pressure
            + size_pressure
            - float(quality["retention_quality_score"])
        ),
    }


def _error_state_pressure(torrent: ManagedTorrent) -> float:
    state = torrent.state.strip().lower()
    if state in {"error", "missingfiles", "unknown"}:
        return 1_000_000.0
    return 0.0


def candidate_value_score(item: ScoreBreakdown) -> float:
    """Higher means a discovered candidate deserves active download headroom first."""

    size_gib = item.candidate.size_bytes / GIB
    demand = item.candidate.leechers / max(item.candidate.seeders, 1)
    free_bonus = 2.0 if item.candidate.discount.value != "normal" else 0.0
    return float(item.score) + min(demand, 20.0) * 0.5 + free_bonus - size_gib * 0.01


def _metadata_gib(torrent: ManagedTorrent, *keys: str) -> float:
    for key in keys:
        value = torrent.metadata.get(key)
        if isinstance(value, int | float):
            return max(float(value), 0.0)
    return 0.0


def _metadata_bytes_as_gib(torrent: ManagedTorrent, key: str) -> float:
    value = torrent.metadata.get(key)
    if not isinstance(value, int | float):
        return 0.0
    return max(float(value), 0.0) / GIB


def _metadata_bytes_as_mib(torrent: ManagedTorrent, key: str) -> float:
    value = torrent.metadata.get(key)
    if not isinstance(value, int | float):
        return 0.0
    return max(float(value), 0.0) / 1024**2
