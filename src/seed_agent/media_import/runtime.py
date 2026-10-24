"""CLI, Web and scheduler share one media execution boundary."""

import json
from pathlib import Path

from seed_agent.config import resolve_runtime_secret_path
from seed_agent.config_views import MediaConfigGuard, load_view
from seed_agent.media_import.engine import Engine
from seed_agent.media_import.metadata import Tmdb
from seed_agent.media_import.store import MediaStore
from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.provider import OpenSubtitles


def media_state_path(view):
    root = view.workspace
    options = view.config.media_import
    path = Path(options.state_path)
    if not path.is_absolute():
        path = root / path
    if path.resolve() == (root / ".seed-agent" / "state.db").resolve():
        raise ValueError("media state must be independent from seed state")
    for profile in options.profiles:
        if path.resolve().is_relative_to(
            Path(profile.source_root).resolve()
        ) or path.resolve().is_relative_to(Path(profile.target_root).resolve()):
            raise ValueError("media state must be outside source/library roots")
    mixed_roots = [s.root for s in options.sources]
    if options.destinations:
        mixed_roots.extend(options.destinations.exclusion_roots())
    if any(path.resolve().is_relative_to(Path(value).resolve()) for value in mixed_roots):
        raise ValueError("media state must be outside source/library roots")
    return path


def build_engine(config_path: Path, *, read_only=False, initialize=False):
    view = load_view(config_path, "media")
    root = view.workspace
    options = view.config.media_import
    metadata = None
    if options.tmdb_secret_ref and not read_only:
        secret_path = resolve_runtime_secret_path(options.tmdb_secret_ref, root)
        if secret_path.is_file():
            secret = json.loads(secret_path.read_text())
            metadata = Tmdb(secret["token"])
    path = media_state_path(view)
    store = MediaStore(path, initialize=initialize, read_only=read_only)
    engine = Engine(store, options, metadata=metadata, config_guard=MediaConfigGuard(view))
    engine.config_view = view
    return engine, root


def run(config_path: Path, *, profile=None, force=False, subtitles=True, refresh=False):
    from seed_agent.media_import.commands import submit

    return submit(config_path, "subtitles" if refresh else "scan", {"profile": profile})


def run_engine(
    engine,
    config_path,
    *,
    profile=None,
    force=False,
    subtitles=True,
    refresh=False,
    scan=True,
    lifecycle=None,
):
    root = engine.config_view.workspace
    if not engine.config.enabled:
        return {"status": "disabled", "scans": []}
    if profile is not None and profile not in {p.name for p in engine.profiles()}:
        raise ValueError("unknown media profile")
    scans = []
    profiles = [p for p in engine.profiles() if profile is None or p.name == profile]
    for index, p in enumerate(profiles):
        if lifecycle:
            lifecycle.phase(
                "inventory-import",
                deadline_seconds=(
                    engine.config.inventory_timeout_seconds
                    + engine.config.work_batch_size * 180
                    + 120
                ),
                completed=index,
                total=len(profiles),
            )
        if scan:
            result = engine.scan(p.name, force=force)
            scans.append(result)
            if result["status"] == "not_due":
                with engine.lease():
                    engine.process_pending(p)
        if lifecycle:
            lifecycle.progress(completed=index + 1, total=len(profiles))
    from seed_agent.media_import.artwork import PosterJobs, TmdbPosters

    token = getattr(engine.metadata, "token", None)
    if lifecycle:
        lifecycle.phase("poster-batch", deadline_seconds=engine.config.work_batch_size * 180 + 60)
    poster_results = PosterJobs(engine, TmdbPosters(token) if token else None).run(
        profile=profile, limit=engine.config.work_batch_size
    )
    provider = build_subtitle_provider(engine.config, root) if subtitles else None
    subtitle_results = (
        SubtitleJobs(engine, provider).run(
            refresh=refresh,
            profile=profile,
            limit=engine.config.work_batch_size,
            on_job=(lambda: lifecycle.phase("subtitle-file", deadline_seconds=900))
            if lifecycle
            else None,
        )
        if subtitles
        else []
    )
    return {
        "status": "complete",
        "scans": scans,
        "posters": poster_results,
        "subtitles": subtitle_results,
    }


def build_subtitle_provider(options, root):
    from seed_agent.media_import.subtitles.assrt import Assrt
    from seed_agent.media_import.subtitles.pool import ProviderPool, Unavailable
    from seed_agent.media_import.subtitles.provider import ProviderError
    from seed_agent.media_import.subtitles.subdl import Subdl

    factories = {"opensubtitlescom": OpenSubtitles, "assrt": Assrt, "subdl": Subdl}
    configured = [(p.name, p.secret_ref) for p in options.subtitle_providers if p.enabled]
    if not options.subtitle_providers:
        if not options.opensubtitles_secret_ref:
            return None
        configured = [("opensubtitlescom", options.opensubtitles_secret_ref)]
    providers = []
    for name, ref in configured:
        try:
            path = resolve_runtime_secret_path(ref, root) if ref else None
            credentials = json.loads(path.read_text()) if path and path.is_file() else {}
            if not isinstance(credentials, dict):
                raise ValueError("invalid credentials")
            providers.append(factories[name](credentials))
        except OSError, ValueError, KeyError, ProviderError:
            providers.append(Unavailable(name))
    return ProviderPool(providers) if providers else None
