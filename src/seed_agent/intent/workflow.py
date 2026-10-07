"""Shared Want lifecycle, scheduling, and external identity boundaries."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from seed_agent.models import IntentState, ResourceIntent

SEARCHABLE_STATES = frozenset(
    {
        IntentState.RECEIVED,
        IntentState.NORMALIZED,
        IntentState.SEARCHED,
        IntentState.CONFIRMATION_REQUIRED,
    }
)


def want_searchable(state: str, selected_release_id: str | None = None) -> bool:
    return state in SEARCHABLE_STATES and not selected_release_id


def search_basis(intent: ResourceIntent) -> dict:
    """Only identity/matching inputs invalidate a search, not source refresh bookkeeping."""
    basis = intent.model_dump(
        include={
            "kind",
            "title",
            "year",
            "season",
            "episode",
            "resolution",
            "quality",
            "language",
        }
    )
    ids = intent.metadata.get("external_ids", {})
    basis["external_ids"] = (
        {
            provider: normalize_external_id(provider, value) or str(value)
            for provider, value in ids.items()
            if provider in {"douban", "imdb"}
        }
        if isinstance(ids, dict)
        else {}
    )
    for key in ("media_type", "kind", "title_aliases"):
        basis[key if key != "kind" else "source_kind"] = intent.metadata.get(key)
    return basis


def parse_search_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def next_search_at(
    progress: dict,
    *,
    now: datetime,
    mode: str = "daily",
    hour: int = 0,
) -> datetime:
    """History, rather than source-refresh timestamps, owns search cadence."""
    if mode == "manual":
        return now
    success = parse_search_time(progress.get("last_success_at"))
    due = datetime.min.replace(tzinfo=UTC)
    if success is not None and mode == "daily":
        local = success.astimezone(now.tzinfo)
        due = local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if due <= local:
            due += timedelta(days=1)
    # A failed batch remains pending without retrying a broken provider in a loop.
    if progress.get("last_status") in {"failed", "batch_aborted"}:
        attempted = parse_search_time(progress.get("last_attempt_at"))
        if attempted is not None:
            due = max(due, attempted + timedelta(minutes=30))
    backoff = parse_search_time(progress.get("backoff_until"))
    if backoff is not None:
        due = max(due, backoff)
    return due


def normalize_external_id(provider: str, value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith(("http://", "https://")):
        url = urlsplit(text)
        host = (url.hostname or "").lower()
        if provider == "douban" and host not in {"movie.douban.com", "m.douban.com"}:
            return None
        if provider == "imdb" and host not in {"imdb.com", "www.imdb.com", "m.imdb.com"}:
            return None
        parts = url.path.strip("/").split("/")
        marker = "subject" if provider == "douban" else "title"
        if marker not in parts or parts.index(marker) + 1 >= len(parts):
            return None
        text = parts[parts.index(marker) + 1]
    if provider == "douban" and text.isdigit():
        return text
    if provider == "imdb" and text.lower().startswith("tt") and text[2:].isdigit():
        return text.lower()
    return None
