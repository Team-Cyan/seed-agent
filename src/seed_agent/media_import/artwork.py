"""Bounded official TMDB posters and reference-owned movie/series publication."""

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from seed_agent.media_import import filesystem as fs
from seed_agent.media_import import roots
from seed_agent.media_import.engine import encode, rows

MAX_IMAGE = 5_000_000
JOB_PREFIX = "artwork:tmdb:job:"
CURSOR_PREFIX = "artwork:tmdb:cursor:"
PROVIDER_KEY = "artwork:tmdb:pause"


class PosterProviderFailure(Exception):
    """A provider adapter failed; its private exception text is not persisted."""


def poster_parent(mapping, video):
    video = Path(video)
    return video.parent if mapping["media_type"] == "movie" else video.parent.parent


class TmdbPosters:
    def __init__(self, token):
        self.token = token

    def fetch(self, mapping, locale):
        kind = "movie" if mapping["media_type"] == "movie" else "tv"
        # Only fixed official API/CDN origins; no credentials on the image client.
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            deadline = time.monotonic() + 60
            with client.stream(
                "GET",
                f"https://api.themoviedb.org/3/{kind}/{int(mapping['tmdb_id'])}",
                params={"language": locale},
                headers={"Authorization": "Bearer " + self.token},
            ) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 1_000_000 or time.monotonic() >= deadline:
                        raise ValueError("poster metadata exceeds byte/time limit")
            path = json.loads(data).get("poster_path")
            if not path:
                return None
            if not re.fullmatch(r"/[A-Za-z0-9_-]+\.(jpg|png)", path):
                raise ValueError("unsafe TMDB poster path")
            with client.stream("GET", "https://image.tmdb.org/t/p/w500" + path) as response:
                response.raise_for_status()
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_IMAGE or time.monotonic() >= deadline:
                        raise ValueError("poster exceeds byte/time limit")
        payload, extension = normalize_image(bytes(payload), Path(path).suffix)
        return (
            payload,
            extension,
            {
                "provider": "tmdb",
                "media_type": kind,
                "tmdb_id": mapping["tmdb_id"],
                "poster_path": path,
            },
        )


def normalize_image(payload, extension):
    # TMDB may negotiate WebP bytes even for a .jpg URL. Decode bounded raster
    # input and publish JPEG, never put WebP bytes into a misleading JPEG file.
    if len(payload) > MAX_IMAGE:
        raise ValueError("poster exceeds byte limit")
    webp = payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    if not (
        (extension == ".jpg" and payload.startswith(b"\xff\xd8\xff"))
        or (extension == ".png" and payload.startswith(b"\x89PNG\r\n\x1a\n"))
        or webp
    ):
        raise ValueError("poster is not a JPEG/PNG")
    with tempfile.TemporaryDirectory(prefix="seed-poster-") as directory:
        path = Path(directory) / ("poster.webp" if webp else "poster" + extension)
        path.write_bytes(payload)
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
        if len(result.stdout) > 100_000:
            raise ValueError("poster probe exceeds limit")
        streams = json.loads(result.stdout).get("streams", [])
        if len(streams) != 1 or streams[0].get("codec_name") not in {"mjpeg", "png", "webp"}:
            raise ValueError("unsupported poster image")
        if not all(1 <= streams[0].get(k, 0) <= 8000 for k in ["width", "height"]):
            raise ValueError("poster dimensions exceed limit")
        # A valid header does not prove the raster can be decoded in full.
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-xerror",
                "-threads",
                "1",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
        if webp:
            converted = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=10,
                check=True,
            ).stdout
            if len(converted) > MAX_IMAGE or not converted.startswith(b"\xff\xd8\xff"):
                raise ValueError("poster conversion failed/exceeds limit")
            return converted, ".jpg"
    return payload, extension


def validate_image(payload, extension):
    normalize_image(payload, extension)


class PosterJobs:
    def __init__(self, engine, provider):
        self.engine, self.provider = engine, provider

    def provider_pause(self):
        with self.engine.store._connect() as conn:
            prior = conn.execute(
                "SELECT status FROM media_provider_state WHERE provider=?", (PROVIDER_KEY,)
            ).fetchone()
        value = json.loads(prior[0]) if prior else {}
        return value if value.get("next_attempt", 0) > self.engine.clock() else None

    def status(self, *, profile=None, limit=100, offset=0):
        """Paginated persisted status; no filesystem, provider work or mutation."""
        with self.engine.store._connect() as conn:
            values = rows(
                conn,
                "SELECT status FROM media_provider_state WHERE provider LIKE ? "
                "AND (? IS NULL OR json_extract(status,'$.profile')=?) "
                "ORDER BY provider LIMIT ? OFFSET ?",
                (JOB_PREFIX + "%", profile, profile, max(0, min(500, limit)), max(0, offset)),
            )
        epoch = self.engine.store.epoch()
        return [
            {**value, "stale_epoch": value.get("epoch") != epoch}
            for v in values
            for value in [json.loads(v["status"])]
        ]

    def save(self, key, value, *, token=None):
        e = self.engine
        with e.store._connect() as conn:
            if token is not None:
                return bool(
                    conn.execute(
                        "UPDATE media_provider_state SET next_request=?,status=? WHERE provider=? "
                        "AND json_extract(status,'$.claim_token')=? AND EXISTS "
                        "(SELECT 1 FROM media_control WHERE epoch=?)",
                        (value["next_attempt"], encode(value), key, token, e.store_epoch),
                    ).rowcount
                )
            conn.execute(
                "INSERT INTO media_provider_state SELECT ?,?,? WHERE EXISTS "
                "(SELECT 1 FROM media_control WHERE epoch=?) ON CONFLICT(provider) "
                "DO UPDATE SET next_request=excluded.next_request,status=excluded.status",
                (key, value["next_attempt"], encode(value), e.store_epoch),
            )
        return True

    def run(self, *, profile=None, limit=10, refresh=False):
        """Worker-only batch. Refresh bypasses retry delay, never a live claim.

        The artwork namespace does not share pacing/download quota keys. Provider
        work runs outside SQLite transactions and the filesystem writer lease.
        """
        e = self.engine
        limit = max(0, min(50, limit))
        names = [p.name for p in e.profiles() if profile is None or p.name == profile]
        if not names or not limit:
            return []
        names_sql = ",".join("?" for _ in names)
        cursor_key = CURSOR_PREFIX + str(profile)
        with e.store._connect() as conn:
            sources = rows(
                conn,
                "SELECT s.*,j.target,j.revision,j.mapping_json FROM media_source_files s "
                "JOIN media_import_jobs j ON j.source_id=s.id WHERE s.status='imported' "
                "AND s.missing_count=0 AND j.status='imported' "
                f"AND s.profile IN ({names_sql}) ORDER BY s.id LIMIT ?",
                (*names, e.config.max_inventory_files + 1),
            )
            cursor = conn.execute(
                "SELECT status FROM media_provider_state WHERE provider=?", (cursor_key,)
            ).fetchone()
        if len(sources) > e.config.max_inventory_files:
            return [{"status": "coverage_pending", "error": "poster inventory budget exceeded"}]
        after = cursor[0] if cursor else ""
        ordered = [s for s in sources if s["id"] > after] + [s for s in sources if s["id"] <= after]
        result, checked = [], set()
        deadline = time.monotonic() + e.config.inventory_timeout_seconds
        for source in ordered:
            if len(checked) >= limit or time.monotonic() >= deadline:
                break
            mapping = json.loads(source["mapping_json"])
            parent = poster_parent(mapping, source["target"])
            if str(parent) in checked:
                continue
            checked.add(str(parent))
            key = JOB_PREFIX + hashlib.sha256(str(parent).encode()).hexdigest()
            support = [
                s
                for s in sources
                if poster_parent(json.loads(s["mapping_json"]), s["target"]) == parent
            ]
            value = {
                "id": key,
                "profile": source["profile"],
                "path": str(parent),
                "source_ids": [s["id"] for s in support],
                "status": "running",
                "epoch": e.store_epoch,
                "claim_token": None,
                "attempts": 0,
                "observed_at": e.clock(),
                "next_attempt": e.clock(),
            }
            token, p, skipped = None, None, False
            try:
                with e.lease():
                    p = e.for_plan(e.profile(source["profile"]), source["id"])
                    fences = self.validate_support(p, support)
                    if any(
                        (
                            json.loads(s["mapping_json"])["media_type"],
                            json.loads(s["mapping_json"])["tmdb_id"],
                        )
                        != (mapping["media_type"], mapping["tmdb_id"])
                        for s in support
                    ):
                        raise ValueError("shared poster has conflicting work identities")
                    with e.store._connect() as conn:
                        prior = conn.execute(
                            "SELECT status FROM media_provider_state WHERE provider=?", (key,)
                        ).fetchone()
                    prior = json.loads(prior[0]) if prior else {}
                    value["attempts"] = prior.get("attempts", 0)
                    if (
                        prior.get("epoch") == e.store_epoch
                        and prior.get("next_attempt", 0) > e.clock()
                    ):
                        if prior.get("status") == "running" or not refresh:
                            result.append(prior)
                            skipped = True
                            continue
                    if e.config.import_policy != "execute" or (
                        e.config_guard is not None and e.config_guard.modes["import"] != "execute"
                    ):
                        value["status"] = "preview"
                        continue
                    e.write_gate("import")
                    token = uuid.uuid4().hex
                    value.update(claim_token=token, next_attempt=e.clock() + 600)
                    self.save(key, value)
                with e.lease():
                    with e.store._connect() as conn:
                        pending = rows(
                            conn,
                            "SELECT u.*,a.kind,a.status AS artifact_status "
                            "FROM media_publications u "
                            "JOIN media_artifacts a ON a.id=u.artifact_id WHERE a.kind='poster' "
                            "AND a.path IN (?,?) AND u.status IN ('pending','conflict')",
                            (str(parent / "poster.jpg"), str(parent / "poster.png")),
                        )
                    for item in pending:
                        if item["status"] == "conflict":
                            raise ValueError("poster publication requires recovery review")
                        self.validate_support(p, support, fences)
                        e.recover_publication(p, item)
                existing = self.attach_existing(p, parent, mapping, support, fences=fences)
                if existing:
                    value.update(existing)
                elif self.provider is None:
                    value.update(status="credentials_required", next_attempt=e.clock() + 3600)
                else:
                    pause = self.provider_pause()
                    if pause:
                        value.update(status=pause["status"], next_attempt=pause["next_attempt"])
                        continue
                    value["attempts"] += 1
                    if not self.save(key, value, token=token):
                        raise ValueError("poster claim superseded before provider request")
                    try:
                        asset = self.provider.fetch(mapping, p.locale)
                    except httpx.HTTPError, ValueError, subprocess.SubprocessError:
                        raise
                    except Exception as exc:
                        raise PosterProviderFailure(type(exc).__name__) from exc
                    if asset is None:
                        value.update(status="missing", next_attempt=e.clock() + 86400)
                    else:
                        payload, extension, provenance = asset
                        value.update(
                            self.publish(
                                p,
                                source,
                                mapping,
                                support,
                                parent / ("poster" + extension),
                                payload,
                                provenance,
                                fences=fences,
                                claim=(key, token),
                            )
                        )
                if value["status"] in {"published", "owned", "existing_unowned"}:
                    value["next_attempt"] = e.clock()
                e.target_health(p._historical_descriptor, "healthy")
            except roots.DestinationUnavailable as exc:
                value.update(
                    status="blocked_destination",
                    error=type(exc).__name__,
                    next_attempt=e.clock() + 60,
                )
                if p:
                    e.target_health(p._historical_descriptor, "blocked", exc)
            except roots.SourceUnavailable as exc:
                value.update(
                    status="blocked_source", error=type(exc).__name__, next_attempt=e.clock() + 60
                )
                e.record_health(
                    "source",
                    source["profile"],
                    {"status": "blocked", "error_type": type(exc).__name__},
                )
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                delay = 300
                retry_after = exc.response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = parsedate_to_datetime(retry_after).timestamp() - e.clock()
                        except TypeError, ValueError, OverflowError:
                            delay = 300
                if not math.isfinite(delay):
                    delay = 300
                value.update(
                    status="rate_limited"
                    if code == 429
                    else ("credentials_required" if code in {401, 403} else "retrying"),
                    error="HTTP " + str(code),
                    next_attempt=e.clock() + max(60, delay),
                )
                if code in {401, 403, 429}:
                    self.save(
                        PROVIDER_KEY,
                        {
                            "status": value["status"],
                            "next_attempt": value["next_attempt"],
                        },
                    )
            except (httpx.RequestError, subprocess.SubprocessError, PosterProviderFailure) as exc:
                value.update(
                    status="retrying",
                    error=str(exc)
                    if isinstance(exc, PosterProviderFailure)
                    else type(exc).__name__,
                    next_attempt=e.clock() + 300,
                )
            except (OSError, ValueError) as exc:
                value.update(status="conflict", error=str(exc)[:200], next_attempt=e.clock() + 300)
            finally:
                if not skipped and value["status"] != "running":
                    value.update(claim_token=None, observed_at=e.clock())
                    if not self.save(key, value, token=token):
                        value["status"] = "superseded"
                    result.append(value)
                with e.store._connect() as conn:
                    conn.execute(
                        "INSERT INTO media_provider_state SELECT ?,0,? WHERE EXISTS "
                        "(SELECT 1 FROM media_control WHERE epoch=?) ON CONFLICT(provider) "
                        "DO UPDATE SET status=excluded.status",
                        (cursor_key, source["id"], e.store_epoch),
                    )
        return result

    def attach_existing(self, p, parent, mapping, support, *, fences=None):
        e = self.engine
        with e.lease():
            e.write_gate("import")
            e.health(p)
            for extension in [".jpg", ".png"]:
                target = parent / ("poster" + extension)
                if not target.exists() and not target.is_symlink():
                    continue
                with e.store._connect() as conn:
                    owned = rows(
                        conn,
                        "SELECT * FROM media_artifacts WHERE path=? AND kind='poster' "
                        "AND owned=1 AND status='active'",
                        (str(target),),
                    )
                    evidence = rows(
                        conn,
                        "SELECT payload_json FROM media_events WHERE event='poster_intent' "
                        "AND source_id=? ORDER BY id DESC LIMIT 100",
                        (support[0]["id"],),
                    )
                    # Shared show references may originate from a different episode.
                    if owned:
                        evidence = rows(
                            conn,
                            "SELECT payload_json FROM media_events WHERE event='poster_intent' "
                            "AND json_extract(payload_json,'$.artifact')=? LIMIT 1",
                            (owned[0]["id"],),
                        )
                    if not owned or not evidence:
                        return {"path": str(target), "status": "existing_unowned"}
                    e.artifact_root(owned[0])
                    provenance = json.loads(evidence[0]["payload_json"])
                    if (
                        provenance["tmdb_id"] != mapping["tmdb_id"]
                        or provenance["media_type"]
                        != ("movie" if mapping["media_type"] == "movie" else "tv")
                        or fs.receipt(Path(p.target_root), target, digest=True)
                        != json.loads(owned[0]["receipt_json"])
                    ):
                        raise ValueError("poster identity/receipt conflict")
                    self.validate_support(p, support, fences)
                    for source in support:
                        conn.execute(
                            "INSERT OR IGNORE INTO media_artifact_sources VALUES(?,?)",
                            (owned[0]["id"], source["id"]),
                        )
                return {"path": str(target), "status": "owned"}
        return None

    def publish(
        self, p, source, mapping, support, target, payload, provenance, *, fences=None, claim=None
    ):
        e = self.engine
        payload, extension = normalize_image(payload, target.suffix)
        target = target.with_suffix(extension)
        if (
            provenance.get("provider") != "tmdb"
            or provenance.get("tmdb_id") != mapping["tmdb_id"]
            or provenance.get("media_type") != mapping["media_type"]
        ):
            raise ValueError("poster provider identity mismatch")
        root = Path(p.target_root)
        with e.lease():
            e.write_gate("import")
            if e.config.import_policy != "execute":
                raise ValueError("poster execution policy changed")
            e.health(p)
            self.validate_support(p, support, fences)
            with e.store._connect() as conn:
                if claim:
                    current_claim = conn.execute(
                        "SELECT 1 FROM media_provider_state WHERE provider=? "
                        "AND json_extract(status,'$.claim_token')=? AND next_request>?",
                        (*claim, e.clock()),
                    ).fetchone()
                    if not current_claim:
                        raise ValueError("poster claim superseded/expired")
                live = rows(
                    conn,
                    "SELECT s.*,j.revision,j.target,j.mapping_json FROM media_source_files s "
                    "JOIN media_import_jobs j ON j.source_id=s.id WHERE s.id=?",
                    (source["id"],),
                )
            if (
                not live
                or live[0]["missing_count"]
                or live[0]["revision"] != source["revision"]
                or live[0]["target"] != source["target"]
                or live[0]["mapping_json"] != source["mapping_json"]
                or fs.fingerprint(Path(p.source_root) / source["path"]) != source["fingerprint"]
            ):
                raise ValueError("stale poster source/mapping")
            aid = uuid.uuid4().hex
            temp = target.parent / (".media-poster-" + aid)
            receipt = {"digest": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
            with e.store._connect() as conn:
                conn.execute(
                    "INSERT INTO media_artifacts VALUES(?,?,?,?,1,'publishing',?,?)",
                    (aid, str(target), p.name, "poster", encode(receipt), e.clock()),
                )
                roots.record_artifact(conn, aid, p._historical_descriptor)
                conn.execute(
                    "INSERT INTO media_publications VALUES(?,?,?,?,?,'pending')",
                    (aid, source["id"], str(temp), str(target), encode(receipt)),
                )
                e.record_publication_fence(conn, aid, source["id"])
                e.event(conn, source["id"], "poster_intent", {**provenance, "artifact": aid})
            with fs.parent_fd(root, temp) as (fd, name):
                out = os.open(
                    name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=fd
                )
                with os.fdopen(out, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            receipt = fs.receipt(root, temp, digest=True)
            with e.store._connect() as conn:
                conn.execute(
                    "UPDATE media_artifacts SET receipt_json=? WHERE id=?", (encode(receipt), aid)
                )
                conn.execute(
                    "UPDATE media_publications SET receipt_json=? WHERE artifact_id=?",
                    (encode(receipt), aid),
                )
            e._link(root, temp, root, target, kind="import")
            with e.store._connect() as conn:
                conn.execute("UPDATE media_artifacts SET status='active' WHERE id=?", (aid,))
                for item in support:
                    conn.execute(
                        "INSERT OR IGNORE INTO media_artifact_sources VALUES(?,?)",
                        (aid, item["id"]),
                    )
                e.event(conn, source["id"], "poster_published", {"artifact": aid, **provenance})
            e._unlink(root, temp, receipt, kind="import")
            with e.store._connect() as conn:
                conn.execute(
                    "UPDATE media_publications SET status='done' WHERE artifact_id=?", (aid,)
                )
        return {"path": str(target), "status": "published"}

    def validate_support(self, p, support, fences=None):
        e = self.engine
        baselines = {}
        for source in support:
            source_profile = e.for_plan(e.profile(source["profile"]), source["id"])
            e.health(source_profile)
            with e.store._connect() as conn:
                current = rows(
                    conn,
                    "SELECT s.fingerprint,s.missing_count,s.status,j.target,"
                    "j.revision,j.mapping_json,j.status AS job_status FROM media_source_files s "
                    "JOIN media_import_jobs j "
                    "ON j.source_id=s.id WHERE s.id=?",
                    (source["id"],),
                )
                videos = rows(
                    conn,
                    "SELECT a.receipt_json FROM media_artifacts a JOIN media_artifact_sources r "
                    "ON r.artifact_id=a.id WHERE r.source_id=? AND a.kind='video' "
                    "AND a.status='active' AND a.path=?",
                    (source["id"], source["target"]),
                )
            if (
                not current
                or current[0]["missing_count"]
                or current[0]["status"] != "imported"
                or current[0]["job_status"] != "imported"
                or current[0]["target"] != source["target"]
                or current[0]["revision"] != source["revision"]
                or current[0]["mapping_json"] != source["mapping_json"]
                or not videos
                or fs.fingerprint(Path(source_profile.source_root) / source["path"])
                != source["fingerprint"]
                or fs.receipt(Path(source_profile.target_root), Path(source["target"]))
                != json.loads(videos[0]["receipt_json"])
            ):
                raise ValueError("poster supporting source/video changed")
            with e.store._connect() as conn:
                baselines[source["id"]] = e.publication_fence(conn, source["id"])
            if fences is not None and baselines[source["id"]] != fences.get(source["id"]):
                raise ValueError("poster source/plan/review/config/restore baseline changed")
        return baselines
