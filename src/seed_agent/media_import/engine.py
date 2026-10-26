"""Restart-safe inventory, review, hardlink import and exact owned-output reconciliation."""

import fcntl
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx

from seed_agent.media_import import filesystem as fs
from seed_agent.media_import import roots
from seed_agent.media_import.metadata import Mapping, probe, render
from seed_agent.media_import.routing import apply_descriptor, effective_profile, source_adapter

VIDEO = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov", ".webm"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def rows(conn, sql, args=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args)]


class Engine:
    def __init__(
        self, store, config, *, metadata=None, media_probe=probe, clock=time.time, config_guard=None
    ):
        self.store, self.config = store, config
        self.metadata, self.probe, self.clock = metadata, media_probe, clock
        self.config_guard = config_guard
        self.store_epoch = store.epoch()

    def write_gate(self, kind):
        if self.store.epoch() != self.store_epoch:
            raise ValueError("media restore epoch changed; stale writer fenced")
        if self.config_guard is not None:
            self.config_guard.check(kind)

    def _link(self, *args, kind="import"):
        self.write_gate(kind)
        fs.link(*args)

    def _unlink(self, *args, kind="import"):
        self.write_gate(kind)
        fs.unlink(*args)

    @contextmanager
    def lease(self):
        # One cross-process lock covers all profile writers, including enrichment finalization.
        path = self.store.path.with_suffix(self.store.path.suffix + ".media.lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.store.epoch() != self.store_epoch:
                raise ValueError("media restore epoch changed; stale operation fenced")
            yield
        finally:
            os.close(fd)

    def event(self, conn, source, event, payload):
        conn.execute(
            "INSERT INTO media_events(source_id,event,created,payload_json) VALUES(?,?,?,?)",
            (source, event, self.clock(), encode(payload)),
        )

    def profile(self, name):
        return next(p for p in self.profiles() if p.name == name)

    def profiles(self):
        return self.config.profiles or [source_adapter(s) for s in self.config.sources]

    def profile_config(self, name):
        source = self.profile(name).model_dump(mode="json")
        if self.config.sources:
            source["legacy_output_roots"] = next(
                s.legacy_output_roots for s in self.config.sources if s.id == name
            )
        return {
            "source": source,
            "destinations": self.config.destinations.model_dump(mode="json")
            if self.config.destinations
            else None,
        }

    def for_mapping(self, p, mapping):
        return effective_profile(p, mapping, self.config.destinations)

    def describe(self, p):
        revision = self.configuration_revision()
        descriptor = roots.describe(
            p, route=p._route_id if p._mixed else "legacy:" + p.name, revision=revision
        )
        with self.store._connect() as conn:
            history = conn.execute(
                "SELECT descriptor_json FROM media_artifact_roots UNION "
                "SELECT descriptor_json FROM media_plan_routes UNION "
                "SELECT descriptor_json FROM media_directory_roots"
            ).fetchall()
        if any(
            value["root"] == descriptor["root"] and value["identity"] != descriptor["identity"]
            for (encoded,) in history
            for value in [json.loads(encoded)]
        ):
            raise roots.DestinationUnavailable(
                "destination root identity changed; explicit migration required"
            )
        return descriptor

    def configuration_revision(self):
        from seed_agent.config_views import revision

        return (
            self.config_guard.view.effective_revision
            if self.config_guard
            else revision(self.config.model_dump(mode="json"))
        )

    def for_plan(self, p, source_id):
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT r.descriptor_json FROM media_plan_routes r JOIN media_import_jobs j "
                "ON j.source_id=r.source_id AND j.revision=r.revision WHERE r.source_id=?",
                (source_id,),
            ).fetchone()
        if not row:
            raise ValueError("plan lacks historical destination; explicit migration required")
        return apply_descriptor(p, json.loads(row[0]))

    def artifact_root(self, artifact):
        with self.store._connect() as conn:
            descriptor = roots.artifact(conn, artifact["id"])
        return roots.validate(descriptor, artifact["path"])

    def publication_fence(self, conn, source_id):
        value = rows(
            conn,
            "SELECT s.generation,s.fingerprint,j.revision,j.target,j.mapping_json,"
            "d.revision AS review_revision "
            "FROM media_source_files s JOIN media_import_jobs j ON j.source_id=s.id "
            "LEFT JOIN media_review_decisions d ON d.source_id=s.id WHERE s.id=?",
            (source_id,),
        )
        if not value:
            raise ValueError("publication source plan missing")
        return {
            **value[0],
            "epoch": self.store_epoch,
            "config_revision": self.configuration_revision(),
        }

    def record_publication_fence(self, conn, artifact_id, source_id):
        conn.execute(
            "INSERT INTO media_publication_fences VALUES(?,?)",
            (artifact_id, encode(self.publication_fence(conn, source_id))),
        )

    def same_scan_identity(self, p, old, new):
        if p._mixed:
            value = json.loads(old)
            if (
                isinstance(value, list)
                and len(value) == 2
                and all(isinstance(v, str) for v in value)
            ):
                old = encode(value[0])  # explicit legacy source/target observation adapter
        return old == new

    def record_health(self, scope, key, payload):
        import hashlib

        role = scope + ":" + hashlib.sha256(key.encode()).hexdigest()[:24]
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO media_runtime_status SELECT ?,? WHERE EXISTS "
                "(SELECT 1 FROM media_control WHERE epoch=?) ON CONFLICT(role) "
                "DO UPDATE SET payload_json=excluded.payload_json",
                (role, encode({**payload, "observed_at": self.clock()}), self.store_epoch),
            )

    def target_health(self, descriptor, status, error=None):
        self.record_health(
            "destination",
            descriptor["root"] + ":" + descriptor.get("route", ""),
            {
                "root": descriptor["root"],
                "route": descriptor.get("route"),
                "status": status,
                "error_type": type(error).__name__ if error else None,
                "reason": str(error)[:200] if error else None,
            },
        )

    def health(self, p):
        # Pure validation: callers may hold a short SQLite transaction. Health
        # observations are persisted at application boundaries, never via a nested writer.
        try:
            source_identity = fs.root_health(Path(p.source_root), p.marker, p.marker_value)
        except (OSError, ValueError) as exc:
            raise roots.SourceUnavailable(str(exc)) from exc
        descriptor = p._historical_descriptor
        target_identity = None
        if not p._source_only:
            if descriptor:
                roots.validate(descriptor)
            else:
                descriptor = self.describe(p)
            target_identity = descriptor["identity"]
        observed = encode(source_identity if p._mixed else [source_identity, target_identity])
        with self.store._connect() as conn:
            prior = rows(
                conn,
                "SELECT root_identity FROM media_scan_runs WHERE profile=? "
                "AND status='complete' ORDER BY id DESC LIMIT 1",
                (p.name,),
            )
        if prior and not self.same_scan_identity(p, prior[0]["root_identity"], observed):
            raise roots.SourceUnavailable(
                "source/profile root identity changed; operator review required"
            )
        return observed

    def scan(self, name, *, force=False):
        p = self.profile(name)
        with self.lease():
            with self.store._connect() as conn:
                recent = rows(
                    conn,
                    "SELECT * FROM media_scan_runs WHERE profile=? "
                    "AND status='complete' ORDER BY id DESC LIMIT 1",
                    (name,),
                )
                if (
                    not force
                    and recent
                    and self.clock() - recent[0]["completed"] < self.config.interval_seconds
                ):
                    return {"profile": name, "status": "not_due"}
                run = conn.execute(
                    "INSERT INTO media_scan_runs(profile,started,status) VALUES(?,?,'running')",
                    (name, self.clock()),
                ).lastrowid
            try:
                root_id = self.health(p)
                inventory = self.inventory(p)
                if self.health(p) != root_id:
                    raise ValueError("root changed during inventory")
                self.publish(p, run, root_id, inventory)
            except (OSError, ValueError) as exc:
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_scan_runs SET status='failed',completed=?,error=? WHERE id=?",
                        (self.clock(), type(exc).__name__ + ": " + str(exc), run),
                    )
                return {"profile": name, "status": "failed", "error": str(exc)}
            self.recover(p)
            self.process_pending(p)
            self.reconcile(p)
            return {"profile": name, "status": "complete", "count": len(inventory), "run_id": run}

    def process_pending(self, p):
        with self.store._connect() as conn:
            cursor = conn.execute(
                "SELECT source_id FROM media_work_cursor WHERE profile=?", (p.name,)
            ).fetchone()
            after = cursor[0] if cursor else ""
            sources = rows(
                conn,
                "SELECT * FROM media_source_files WHERE profile=? "
                "AND missing_count=0 AND status!='removed' AND id>? ORDER BY id LIMIT ?",
                (p.name, after, self.config.work_batch_size),
            )
            if not sources and after:
                sources = rows(
                    conn,
                    "SELECT * FROM media_source_files WHERE profile=? "
                    "AND missing_count=0 AND status!='removed' ORDER BY id LIMIT ?",
                    (p.name, self.config.work_batch_size),
                )
        for source in sources:
            self.process_source(p, source)
            with self.store._connect() as conn:
                conn.execute(
                    "INSERT INTO media_work_cursor VALUES(?,?) ON CONFLICT(profile) "
                    "DO UPDATE SET source_id=excluded.source_id",
                    (p.name, source["id"]),
                )

    def process_source(self, p, source):
        try:
            self.plan_import(p, source)
        except httpx.HTTPError:
            self.job_error(source, "metadata provider unavailable", status="retrying")
        except (OSError, ValueError, RuntimeError) as exc:
            self.job_error(source, str(exc))

    def inventory(self, p):
        if p._mixed:
            from seed_agent.media_import.sources import inventory

            with self.store._connect() as conn:
                history = [
                    json.loads(r[0])["root"]
                    for r in conn.execute(
                        "SELECT descriptor_json FROM media_artifact_roots UNION "
                        "SELECT descriptor_json FROM media_plan_routes UNION "
                        "SELECT descriptor_json FROM media_directory_roots"
                    )
                ]
            from seed_agent.media_import.routing import validate_sources

            validate_sources(self.config.sources, self.config.destinations)
            source = next(s for s in self.config.sources if s.id == p.name)
            current = [
                str(Path(value).resolve())
                for value in [
                    *self.config.destinations.exclusion_roots(),
                    *(p for s in self.config.sources for p in s.legacy_output_roots),
                ]
            ]
            with self.store._connect() as conn:
                history.extend(
                    r[0] for r in conn.execute("SELECT path FROM media_output_exclusions")
                )
            root = Path(source.root).resolve()
            if any(
                root == Path(value).resolve() or Path(value).resolve() in root.parents
                for value in [*history, *current]
            ):
                raise ValueError(
                    "historical destination contains source; explicit migration review required"
                )
            with self.store._connect() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO media_output_exclusions VALUES(?)",
                    [(value,) for value in current],
                )
            return inventory(
                source,
                self.config.destinations,
                historical_targets=[*history, *current],
                max_files=self.config.max_inventory_files,
                timeout=self.config.inventory_timeout_seconds,
            )
        root = Path(p.source_root)
        result = {}
        deadline = time.monotonic() + self.config.inventory_timeout_seconds

        def onerror(error):
            raise error

        for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            if time.monotonic() >= deadline:
                raise ValueError("inventory time budget exceeded; incomplete scan")
            # Symlink directories are rejected rather than silently yielding a partial inventory.
            for d in dirs:
                if (Path(directory) / d).is_symlink():
                    raise ValueError("symlink directory in source root")
            dirs[:] = sorted(d for d in dirs if d not in p.exclude_dirs)
            for name in sorted(files):
                if time.monotonic() >= deadline:
                    raise ValueError("inventory time budget exceeded; incomplete scan")
                path = Path(directory) / name
                if path.suffix.lower() in VIDEO:
                    if len(result) >= self.config.max_inventory_files:
                        raise ValueError("inventory file budget exceeded; incomplete scan")
                    result[str(path.relative_to(root))] = fs.fingerprint(path)
        return result

    def publish(self, p, run, root_id, inventory):
        now = self.clock()
        items = list(inventory.items())
        for start in range(0, len(items), 250):
            with self.store._connect() as conn:
                conn.executemany(
                    "INSERT INTO media_inventory_stage VALUES(?,?,?)",
                    [(run, path, fp) for path, fp in items[start : start + 250]],
                )
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT COUNT(*) FROM media_inventory_stage WHERE run_id=?", (run,)
            ).fetchone()[0] != len(inventory):
                raise ValueError("incomplete staged inventory")
            previous = rows(
                conn,
                "SELECT * FROM media_scan_runs WHERE profile=? AND status='complete' "
                "ORDER BY id DESC LIMIT 1",
                (p.name,),
            )
            if previous and not self.same_scan_identity(p, previous[0]["root_identity"], root_id):
                raise ValueError("root identity changed; operator investigation required")
            existing = rows(
                conn,
                "SELECT * FROM media_source_files WHERE profile=?",
                (p.name,),
            )
            latest = {}
            for row in existing:
                if (
                    row["path"] not in latest
                    or row["generation"] > latest[row["path"]]["generation"]
                ):
                    latest[row["path"]] = row
            seen = set()
            for path, fp in inventory.items():
                old = latest.get(path)
                if old and old["fingerprint"] == fp and old["status"] != "removed":
                    source_id = old["id"]
                    conn.execute(
                        "UPDATE media_source_files SET last_seen=?,stable_count=stable_count+1,"
                        "missing_since=NULL,missing_count=0 WHERE id=?",
                        (now, source_id),
                    )
                else:
                    # Rename requires a unique exact full fingerprint in this complete snapshot.
                    aliases = [
                        r
                        for r in existing
                        if r["status"] != "removed"
                        and r["fingerprint"] == fp
                        and r["path"] not in inventory
                        and r["id"] not in seen
                    ]
                    if len(aliases) == 1 and sum(v == fp for v in inventory.values()) == 1:
                        source_id = aliases[0]["id"]
                        conn.execute(
                            "UPDATE media_source_files SET path=?,last_seen=?,missing_since=NULL,"
                            "missing_count=0,stable_count=stable_count+1 WHERE id=?",
                            (path, now, source_id),
                        )
                        self.event(conn, source_id, "source_relocated", {"path": path})
                    else:
                        source_id = uuid.uuid4().hex
                        generation = (old["generation"] + 1) if old else 1
                        if old and old["status"] != "removed":
                            conn.execute(
                                "UPDATE media_source_files SET status='changed' WHERE id=?",
                                (old["id"],),
                            )
                        conn.execute(
                            "INSERT INTO media_source_files(id,profile,path,generation,fingerprint,"
                            "first_seen,last_seen,stable_count,status,original_release) "
                            "VALUES(?,?,?,?,?,?,?,1,?,?)",
                            (
                                source_id,
                                p.name,
                                path,
                                generation,
                                fp,
                                now,
                                now,
                                "changed" if old and old["status"] != "removed" else "stabilizing",
                                Path(path).name,
                            ),
                        )
                seen.add(source_id)
            for old in existing:
                if old["id"] not in seen and old["status"] != "removed":
                    conn.execute(
                        "UPDATE media_source_files SET missing_since=COALESCE(missing_since,?),"
                        "missing_count=missing_count+1,status=CASE WHEN status='changed' THEN "
                        "'changed' ELSE 'missing_pending' END WHERE id=?",
                        (now, old["id"]),
                    )
            conn.execute(
                "UPDATE media_scan_runs SET completed=?,status='complete',root_identity=?,count=? "
                "WHERE id=?",
                (now, root_id, len(inventory), run),
            )
            conn.execute("DELETE FROM media_inventory_stage WHERE run_id=?", (run,))

    def job_error(self, source, error, *, status="conflict"):
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO media_import_jobs(source_id,revision,status,error,updated) "
                "VALUES(?,1,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                "status=excluded.status,error=excluded.error,updated=excluded.updated",
                (source["id"], status, error, self.clock()),
            )

    def plan_import(self, p, source):
        sid = source["id"]
        path = Path(p.source_root) / source["path"]
        with self.store._connect() as conn:
            decisions = rows(conn, "SELECT * FROM media_review_decisions WHERE source_id=?", (sid,))
            jobs = rows(conn, "SELECT * FROM media_import_jobs WHERE source_id=?", (sid,))
        decision = (
            decisions[0]
            if decisions and decisions[0]["fingerprint"] == source["fingerprint"]
            else None
        )
        job = jobs[0] if jobs else None
        if job and job["status"] == "imported":
            p = self.for_plan(p, sid)
            if Path(job["target"]).exists() and self.config.import_policy == "execute":
                self.retire_old(p, source, job["target"])
            if not Path(job["target"]).exists():
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_import_jobs SET status='target_missing' WHERE source_id=?",
                        (sid,),
                    )
            return
        if job and job["status"] == "target_missing":
            return
        if source["stable_count"] < 2 or self.clock() - path.stat().st_mtime < p.min_age_seconds:
            return
        ready = (
            "completed_folder"
            if p.readiness == "completed_folder"
            else ("operator" if decision and decision["ready"] else "completion_unverified")
        )
        with self.store._connect() as conn:
            conn.execute("UPDATE media_source_files SET readiness=? WHERE id=?", (ready, sid))
        if ready == "completion_unverified":
            return
        if fs.fingerprint(path) != source["fingerprint"]:
            raise ValueError("source changed before planning")
        media = json.loads(source["probe_json"]) if source["probe_json"] else self.probe(path)
        mapping = Mapping.model_validate_json(decision["mapping_json"]) if decision else None
        candidates = []
        if mapping is None and job and job["mapping_json"]:
            mapping = Mapping.model_validate_json(job["mapping_json"])
        with self.store._connect() as conn:
            predecessors = rows(
                conn,
                "SELECT s.id FROM media_source_files s JOIN media_artifact_sources r "
                "ON r.source_id=s.id JOIN media_artifacts a ON a.id=r.artifact_id "
                "WHERE s.profile=? AND s.path=? AND s.id!=? AND a.status='active'",
                (p.name, source["path"], source["id"]),
            )
        replacement_needs_review = bool(predecessors and decision is None)
        if replacement_needs_review:
            mapping = None
        if mapping is None and self.metadata and not replacement_needs_review:
            mapping, candidates = self.metadata.identify(path, p)
        if (
            p._mixed
            and mapping
            and (mapping.media_type not in {"movie", "tv"} or mapping.animation is None)
        ):
            candidates = [
                {
                    **mapping.model_dump(),
                    "reason": "content type/animation classification requires review",
                }
            ]
            mapping = None
        destination_error = None
        destination = None
        if mapping:
            p = self.for_mapping(p, mapping)
            target = render(mapping, p, path.suffix.lower())
            try:
                destination = self.describe(p)
            except (OSError, ValueError) as exc:
                destination_error = type(exc).__name__
        if fs.fingerprint(path) != source["fingerprint"]:
            raise ValueError("source changed during metadata resolution")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current_decisions = rows(
                conn, "SELECT * FROM media_review_decisions WHERE source_id=?", (sid,)
            )
            current_decision = (
                current_decisions[0]
                if current_decisions
                and current_decisions[0]["fingerprint"] == source["fingerprint"]
                else None
            )

            def decision_key(value):
                return (
                    tuple(value[k] for k in ["fingerprint", "revision", "mapping_json", "ready"])
                    if value
                    else None
                )

            if decision_key(current_decision) != decision_key(decision):
                raise ValueError("manual review changed during metadata resolution; retry")
            conn.execute(
                "UPDATE media_source_files SET probe_json=?,status=? WHERE id=?",
                (encode(media), "ready" if mapping else "review_required", sid),
            )
            if not mapping:
                conn.execute(
                    "INSERT INTO media_import_jobs(source_id,revision,status,error,updated) "
                    "VALUES(?,1,'review_required',?,?) ON CONFLICT(source_id) DO UPDATE SET "
                    "status='review_required',error=excluded.error",
                    (sid, encode({"candidates": candidates}), self.clock()),
                )
                return
            revision = decision["revision"] if decision else (job["revision"] if job else 1)
            conn.execute(
                "INSERT INTO "
                "media_import_jobs(source_id,revision,status,mapping_json,target,updated) "
                "VALUES(?,?,'planned',?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                "revision=excluded.revision,status='planned',mapping_json=excluded.mapping_json,"
                "target=excluded.target,error=NULL,updated=excluded.updated",
                (sid, revision, mapping.model_dump_json(), str(target), self.clock()),
            )
            if destination is None:
                conn.execute(
                    "UPDATE media_import_jobs SET status='blocked_destination',error=? "
                    "WHERE source_id=?",
                    (destination_error, sid),
                )
                return
            conn.execute(
                "INSERT INTO media_plan_routes VALUES(?,?,?) ON CONFLICT(source_id,revision) "
                "DO UPDATE SET descriptor_json=excluded.descriptor_json",
                (sid, revision, encode(destination)),
            )
            if (
                mapping.reference_duration
                and abs(media["duration"] - mapping.reference_duration) > 600
            ):
                self.event(
                    conn,
                    sid,
                    "possible_alternate_cut",
                    {
                        "measured": media["duration"],
                        "reference": mapping.reference_duration,
                        "provenance": "tmdb",
                    },
                )
        if self.config.import_policy == "execute":
            self.execute_link(p, source, target)
            if decision and predecessors:
                with self.store._connect() as conn:
                    for predecessor in predecessors:
                        conn.execute(
                            "INSERT OR IGNORE INTO media_artifact_sources "
                            "SELECT artifact_id,? FROM media_artifact_sources WHERE source_id=?",
                            (sid, predecessor["id"]),
                        )
                        conn.execute(
                            "UPDATE media_source_files SET status='removed' WHERE id=?",
                            (predecessor["id"],),
                        )
                        self.event(conn, sid, "replacement_predecessor_retirement", predecessor)
            # Repair switches only after verified creation. Shared sidecars require review.
            self.retire_old(p, source, str(target))

    def mkdirs(self, p, parent):
        root = Path(p.target_root)
        current = root
        for part in parent.relative_to(root).parts:
            current /= part
            try:
                with fs.parent_fd(root, current) as (fd, name):
                    self.write_gate("import")
                    os.mkdir(name, dir_fd=fd)
            except FileExistsError:
                fs.identity(current)
            else:
                with self.store._connect() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO media_owned_directories VALUES(?,?,?)",
                        (str(current), p.name, fs.identity(current)),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO media_directory_roots VALUES(?,?)",
                        (str(current), encode(self.describe(p))),
                    )

    def execute_link(self, p, source, target):
        p = self.for_plan(p, source["id"])
        self.write_gate("import")
        self.health(p)
        path = Path(p.source_root) / source["path"]
        root = Path(p.target_root)
        if fs.fingerprint(path) != source["fingerprint"]:
            raise ValueError("source fingerprint changed before link")
        self.mkdirs(p, target.parent)
        with self.store._connect() as conn:
            existing = rows(
                conn,
                "SELECT * FROM media_artifacts WHERE path=? AND status='active'",
                (str(target),),
            )
        if target.exists() or target.is_symlink():
            expected = fs.receipt(Path(p.source_root), path)
            actual = fs.receipt(root, target)
            if expected != actual:
                raise ValueError("destination occupied by different content; no overwrite")
            if existing and existing[0]["status"] == "active":
                aid = existing[0]["id"]
                self.artifact_root(existing[0])
            else:
                aid = uuid.uuid4().hex
                with self.store._connect() as conn:
                    conn.execute(
                        "INSERT INTO media_artifacts VALUES(?,?,?,?,0,'active',?,?)",
                        (aid, str(target), p.name, "video", encode(actual), self.clock()),
                    )
                    roots.record_artifact(conn, aid, p._historical_descriptor)
            self.finish_link(source, aid, target)
            return
        if existing:
            with self.store._connect() as conn:
                conn.execute(
                    "UPDATE media_artifacts SET status='target_missing' WHERE id=?",
                    (existing[0]["id"],),
                )
        aid = uuid.uuid4().hex
        temp = target.parent / (".media-link-" + aid)
        receipt = fs.receipt(Path(p.source_root), path)
        # Intent exists before the very first filesystem mutation. It includes exact temp identity.
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO media_artifacts VALUES(?,?,?,?,1,'publishing',?,?)",
                (aid, str(target), p.name, "video", encode(receipt), self.clock()),
            )
            roots.record_artifact(conn, aid, p._historical_descriptor)
            conn.execute(
                "INSERT INTO media_publications VALUES(?,?,?,?,?,'pending')",
                (aid, source["id"], str(temp), str(target), encode(receipt)),
            )
            self.record_publication_fence(conn, aid, source["id"])
        self._link(Path(p.source_root), path, root, temp)
        if fs.fingerprint(path) != source["fingerprint"] or fs.receipt(root, temp) != receipt:
            raise ValueError("source changed during temporary link")
        self.write_gate("import")
        self._link(root, temp, root, target)
        if fs.receipt(root, target) != receipt or fs.fingerprint(path) != source["fingerprint"]:
            raise ValueError("source changed during publication")
        self.finish_link(source, aid, target, receipt)
        self._unlink(root, temp, receipt)
        with self.store._connect() as conn:
            conn.execute("UPDATE media_publications SET status='done' WHERE artifact_id=?", (aid,))

    def finish_link(self, source, aid, target, receipt=None):
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if receipt:
                conn.execute(
                    "UPDATE media_artifacts SET status='active',receipt_json=? WHERE id=?",
                    (encode(receipt), aid),
                )
            conn.execute(
                "INSERT OR IGNORE INTO media_artifact_sources VALUES(?,?)", (aid, source["id"])
            )
            conn.execute(
                "UPDATE media_import_jobs SET status='imported',target=? WHERE source_id=?",
                (str(target), source["id"]),
            )
            conn.execute(
                "UPDATE media_source_files SET status='imported' WHERE id=?", (source["id"],)
            )
            self.event(conn, source["id"], "video_imported", {"artifact": aid})

    def recover(self, p):
        with self.store._connect() as conn:
            pending = rows(
                conn,
                "SELECT u.*,a.kind,a.status AS artifact_status FROM media_publications u "
                "JOIN media_artifacts a ON a.id=u.artifact_id WHERE a.profile=? "
                "AND u.status='pending'",
                (p.name,),
            )
        for item in pending:
            policy = (
                self.config.import_policy
                if item["kind"] in {"video", "poster"}
                else self.config.subtitle_policy
            )
            if policy != "execute":
                continue
            try:
                self.recover_publication(p, item)
            except (OSError, ValueError) as exc:
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_publications SET status='conflict' WHERE artifact_id=?",
                        (item["artifact_id"],),
                    )
                    self.event(
                        conn,
                        item["source_id"],
                        "publication_recovery_conflict",
                        {
                            "artifact": item["artifact_id"],
                            "temporary": item["temporary"],
                            "target": item["target"],
                            "error": str(exc),
                        },
                    )

    def recover_publication(self, p, item):
        with self.store._connect() as conn:
            p = apply_descriptor(p, roots.artifact(conn, item["artifact_id"]))
            prior = conn.execute(
                "SELECT payload_json FROM media_publication_fences WHERE artifact_id=?",
                (item["artifact_id"],),
            ).fetchone()
            if not prior or json.loads(prior[0]) != self.publication_fence(conn, item["source_id"]):
                raise ValueError("publication source/plan/route/config/restore baseline changed")
        roots.validate(p._historical_descriptor, item["target"])
        kind = "import" if item["kind"] in {"video", "poster"} else "subtitle"
        self.write_gate(kind)
        root = Path(p.target_root)
        temp, target = Path(item["temporary"]), Path(item["target"])
        receipt = json.loads(item["receipt_json"])
        if "dev" not in receipt:
            if not temp.exists():
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_artifacts SET status='removed' WHERE id=?",
                        (item["artifact_id"],),
                    )
                    conn.execute(
                        "UPDATE media_publications SET status='done' WHERE artifact_id=?",
                        (item["artifact_id"],),
                    )
                return
            actual = fs.receipt(root, temp, digest=True)
            if actual["digest"] != receipt["digest"] or actual["size"] != receipt["size"]:
                raise ValueError(
                    "partial payload publication requires review; recorded intent retained"
                )
            receipt = actual
            with self.store._connect() as conn:
                conn.execute(
                    "UPDATE media_publications SET receipt_json=? WHERE artifact_id=?",
                    (encode(receipt), item["artifact_id"]),
                )
                conn.execute(
                    "UPDATE media_artifacts SET receipt_json=? WHERE id=?",
                    (encode(receipt), item["artifact_id"]),
                )
        with self.store._connect() as conn:
            sources = rows(
                conn, "SELECT * FROM media_source_files WHERE id=?", (item["source_id"],)
            )
        source = sources[0] if sources else None
        if item["kind"] == "poster":
            from seed_agent.media_import.artwork import poster_parent

            with self.store._connect() as conn:
                current = rows(
                    conn,
                    "SELECT mapping_json,target,status FROM media_import_jobs WHERE source_id=?",
                    (item["source_id"],),
                )
            if (
                not current
                or not current[0]["mapping_json"]
                or current[0]["status"] != "imported"
                or poster_parent(json.loads(current[0]["mapping_json"]), current[0]["target"])
                != target.parent
            ):
                raise ValueError("poster mapping changed before recovery")
        valid = False
        try:
            valid = bool(
                source
                and not source["missing_count"]
                and fs.fingerprint(Path(p.source_root) / source["path"]) == source["fingerprint"]
            )
        except FileNotFoundError:
            pass
        if item["artifact_status"] == "active":
            if temp.exists() or temp.is_symlink():
                self._unlink(root, temp, receipt, kind=kind)
        elif not valid:
            # Source gone: clean only exact recorded temporary/final receipts.
            if temp.exists() or temp.is_symlink():
                if (
                    target.exists()
                    and fs.receipt(root, target, digest="digest" in receipt) == receipt
                ):
                    self._unlink(root, target, receipt, kind=kind)
                self._unlink(root, temp, receipt, kind=kind)
            with self.store._connect() as conn:
                conn.execute(
                    "UPDATE media_artifacts SET status='removed' WHERE id=?",
                    (item["artifact_id"],),
                )
        else:
            if not temp.exists():
                if target.exists() or item["kind"] != "video":
                    raise ValueError("publication requires review: missing temporary witness")
                self._link(
                    Path(p.source_root), Path(p.source_root) / source["path"], root, temp, kind=kind
                )
            if fs.receipt(root, temp, digest="digest" in receipt) != receipt:
                raise ValueError("publication temporary changed")
            if not target.exists():
                self._link(root, temp, root, target, kind=kind)
            if fs.receipt(root, target, digest="digest" in receipt) != receipt:
                raise ValueError("publication target conflict")
            if item["kind"] == "video":
                self.finish_link(source, item["artifact_id"], target, receipt)
            else:
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_artifacts SET status='active' WHERE id=?",
                        (item["artifact_id"],),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO media_artifact_sources VALUES(?,?)",
                        (item["artifact_id"], source["id"]),
                    )
            self._unlink(root, temp, receipt, kind=kind)
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE media_publications SET status='done' WHERE artifact_id=?",
                (item["artifact_id"],),
            )

    def retire_old(self, p, source, new_target):
        self.write_gate("import")
        self.health(p)
        if fs.fingerprint(Path(p.source_root) / source["path"]) != source["fingerprint"]:
            raise ValueError("repair source generation changed; preserve old output")
        with self.store._connect() as conn:
            current = rows(
                conn,
                "SELECT j.*,s.generation,s.fingerprint,s.missing_count FROM "
                "media_import_jobs j JOIN media_source_files s ON s.id=j.source_id "
                "WHERE j.source_id=?",
                (source["id"],),
            )
            decision = rows(
                conn, "SELECT * FROM media_review_decisions WHERE source_id=?", (source["id"],)
            )
            target_receipts = rows(
                conn,
                "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
                "ON r.artifact_id=a.id WHERE r.source_id=? AND a.path=? "
                "AND a.status='active' AND a.kind='video'",
                (source["id"], new_target),
            )
        if (
            not current
            or current[0]["missing_count"]
            or current[0]["target"] != new_target
            or current[0]["fingerprint"] != source["fingerprint"]
            or current[0]["generation"] != source["generation"]
            or (decision and decision[0]["revision"] != current[0]["revision"])
        ):
            raise ValueError("repair revision changed; preserve old output")
        if len(target_receipts) != 1 or fs.receipt(
            Path(p.target_root), Path(new_target)
        ) != json.loads(target_receipts[0]["receipt_json"]):
            raise ValueError("new repair target receipt changed; preserve old output")
        with self.store._connect() as conn:
            old = rows(
                conn,
                "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
                "ON r.artifact_id=a.id WHERE r.source_id=? AND a.path!=? AND "
                "a.status IN ('active','retiring')",
                (source["id"], new_target),
            )
        with self.store._connect() as conn:
            invalidated = rows(
                conn,
                "SELECT id FROM media_subtitle_jobs WHERE source_id=? AND status='mapping_review'",
                (source["id"],),
            )
        for artifact in old:
            if artifact["kind"] == "poster":
                from seed_agent.media_import.artwork import poster_parent

                mapping = json.loads(current[0]["mapping_json"])
                if Path(artifact["path"]).parent == poster_parent(mapping, new_target):
                    continue
            # Reassociate same-identity sidecars only; work/episode/cut changes re-search.
            if (
                artifact["kind"] != "video"
                and not invalidated
                and Path(artifact["path"]).parent == Path(new_target).parent
            ):
                continue
            with self.store._connect() as conn:
                supports = rows(
                    conn,
                    "SELECT r.source_id FROM media_artifact_sources r JOIN media_source_files s "
                    "ON s.id=r.source_id WHERE r.artifact_id=? AND r.source_id!=? "
                    "AND s.status!='removed'",
                    (artifact["id"], source["id"]),
                )
            if artifact["owned"] and not supports:
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_artifacts SET status='retiring' WHERE id=?", (artifact["id"],)
                    )
                old_path = Path(artifact["path"])
                if old_path.exists() or old_path.is_symlink():
                    self.write_gate("import")
                    self._unlink(
                        self.artifact_root(artifact), old_path, json.loads(artifact["receipt_json"])
                    )
                elif artifact["status"] != "retiring":
                    raise ValueError("old repair artifact disappeared before retirement intent")
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_artifacts SET status='retired' WHERE id=?", (artifact["id"],)
                    )
                    self.event(conn, source["id"], "repair_old_retired", {"path": artifact["path"]})
            with self.store._connect() as conn:
                conn.execute(
                    "DELETE FROM media_artifact_sources WHERE artifact_id=? AND source_id=?",
                    (artifact["id"], source["id"]),
                )
                conn.execute(
                    "UPDATE media_subtitle_jobs SET status='missing',next_attempt=?,payload_json=? "
                    "WHERE source_id=?",
                    (self.clock(), encode({"downloaded": [], "digests": []}), source["id"]),
                )
        self.prune_dirs(p)

    def review(self, source_id, mapping, *, fingerprint, ready=False, repair=False):
        if type(ready) is not bool or type(repair) is not bool:
            raise ValueError("ready and repair must be explicit booleans")
        chosen = Mapping.model_validate(mapping)
        with self.lease(), self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source = rows(conn, "SELECT * FROM media_source_files WHERE id=?", (source_id,))
            if not source or source[0]["fingerprint"] != fingerprint or source[0]["missing_count"]:
                raise ValueError("stale source review")
            p = self.profile(source[0]["profile"])
            if fs.fingerprint(Path(p.source_root) / source[0]["path"]) != fingerprint:
                raise ValueError("source replaced during review")
            old = rows(conn, "SELECT * FROM media_import_jobs WHERE source_id=?", (source_id,))
            prior_decision = rows(
                conn, "SELECT revision FROM media_review_decisions WHERE source_id=?", (source_id,)
            )
            revision = (
                max(
                    old[0]["revision"] if old else 0,
                    prior_decision[0]["revision"] if prior_decision else 0,
                )
                + 1
            )
            p = self.for_mapping(p, chosen)
            target = render(chosen, p, Path(source[0]["path"]).suffix)
            old_mapping = json.loads(old[0]["mapping_json"] or "{}") if old else {}
            keys = ["media_type", "animation", "tmdb_id", "season", "episodes", "edition"]
            if old_mapping and any(old_mapping.get(k) != chosen.model_dump().get(k) for k in keys):
                conn.execute(
                    "UPDATE media_subtitle_jobs SET status='mapping_review',payload_json=?,"
                    "claim_token=NULL,next_attempt=? WHERE source_id=?",
                    (encode({"downloaded": [], "digests": []}), self.clock(), source_id),
                )
            conn.execute(
                "INSERT INTO media_review_decisions VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(source_id) DO UPDATE SET fingerprint=excluded.fingerprint,"
                ""
                ""
                "mapping_json=excluded.mapping_json,ready=excluded.ready,revision=excluded.revision,"
                "updated=excluded.updated",
                (
                    source_id,
                    fingerprint,
                    chosen.model_dump_json(),
                    int(ready),
                    revision,
                    self.clock(),
                ),
            )
            conn.execute(
                "UPDATE media_import_jobs SET status='reviewed' WHERE source_id=?", (source_id,)
            )
            self.event(conn, source_id, "review_saved", {"revision": revision, "repair": repair})
            return {
                "source_id": source_id,
                "old_target": old[0]["target"] if old else None,
                "new_target": str(target),
                "revision": revision,
            }

    def series_preview(self, source_id, mapping):
        chosen = Mapping.model_validate(mapping)
        with self.lease(), self.store._connect() as conn:
            source_rows = rows(
                conn,
                "SELECT s.*,j.mapping_json FROM media_source_files s JOIN "
                "media_import_jobs j ON j.source_id=s.id WHERE s.id=?",
                (source_id,),
            )
            if not source_rows:
                raise ValueError("source has no mapped series")
            current = source_rows[0]
            old = json.loads(current["mapping_json"])
            if old["media_type"] == "movie" or chosen.media_type == "movie":
                raise ValueError("series scope requires TV/anime")
            candidates = rows(
                conn,
                "SELECT s.*,j.mapping_json,j.target,j.revision,d.revision AS decision_revision,"
                "d.mapping_json AS decision_mapping FROM media_source_files s JOIN "
                "media_import_jobs j ON j.source_id=s.id LEFT JOIN media_review_decisions d "
                "ON d.source_id=s.id WHERE s.profile=? "
                "AND s.missing_count=0 AND s.status!='removed'",
                (current["profile"],),
            )
            manifest = []
            for source in candidates:
                original = json.loads(source["mapping_json"] or "{}")
                if (
                    original.get("tmdb_id") != old["tmdb_id"]
                    or original.get("media_type") == "movie"
                ):
                    continue
                value = chosen.model_copy(
                    update={
                        "season": original.get("season"),
                        "episodes": original.get("episodes", []),
                    }
                )
                target = render(
                    value,
                    self.for_mapping(self.profile(source["profile"]), value),
                    Path(source["path"]).suffix,
                )
                manifest.append(
                    {
                        "source_id": source["id"],
                        "fingerprint": source["fingerprint"],
                        "mapping": value.model_dump(),
                        "old_target": source["target"],
                        "new_target": str(target),
                        "baseline": {
                            key: source[key]
                            for key in [
                                "mapping_json",
                                "target",
                                "revision",
                                "decision_revision",
                                "decision_mapping",
                            ]
                        },
                    }
                )
            payload = {
                "profile": current["profile"],
                "series_id": old["tmdb_id"],
                "profile_config": self.profile_config(current["profile"]),
                "manifest": manifest,
            }
            cursor = conn.execute(
                "INSERT INTO media_events(source_id,event,created,payload_json) "
                "VALUES(?,'series_review_preview',?,?)",
                (source_id, self.clock(), encode(payload)),
            )
            return {"preview_id": cursor.lastrowid, **payload}

    def series_apply(self, preview_id):
        with self.lease(), self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            preview = rows(
                conn,
                "SELECT * FROM media_events WHERE id=? AND event='series_review_preview'",
                (preview_id,),
            )
            if not preview:
                raise ValueError("unknown series preview")
            data = json.loads(preview[0]["payload_json"])
            if self.profile_config(data["profile"]) != data["profile_config"]:
                raise ValueError("series naming/profile configuration changed; preview again")
            current = rows(
                conn,
                "SELECT s.*,j.mapping_json,j.target,j.revision,d.revision AS decision_revision,"
                "d.mapping_json AS decision_mapping FROM media_source_files s "
                "JOIN media_import_jobs j "
                "ON j.source_id=s.id LEFT JOIN media_review_decisions d ON d.source_id=s.id "
                "WHERE s.profile=? AND s.missing_count=0 AND "
                "s.status!='removed'",
                (data["profile"],),
            )
            scoped = {
                s["id"]: s
                for s in current
                if json.loads(s["mapping_json"] or "{}").get("tmdb_id") == data["series_id"]
            }
            if set(scoped) != {item["source_id"] for item in data["manifest"]}:
                raise ValueError("series file set changed; preview again")
            for item in data["manifest"]:
                source = scoped[item["source_id"]]
                p = self.profile(source["profile"])
                self.health(p)
                if any(source[key] != value for key, value in item["baseline"].items()):
                    raise ValueError("series mapping/revision changed; preview again")
                if (
                    source["fingerprint"] != item["fingerprint"]
                    or fs.fingerprint(Path(p.source_root) / source["path"]) != item["fingerprint"]
                ):
                    raise ValueError("series source changed; preview again")
                job = rows(
                    conn,
                    "SELECT revision FROM media_import_jobs WHERE source_id=?",
                    (source["id"],),
                )[0]
                if any(
                    json.loads(source["mapping_json"] or "{}").get(key) != item["mapping"].get(key)
                    for key in [
                        "media_type",
                        "animation",
                        "tmdb_id",
                        "season",
                        "episodes",
                        "edition",
                    ]
                ):
                    conn.execute(
                        "UPDATE media_subtitle_jobs SET status='mapping_review',payload_json=?,"
                        "claim_token=NULL,next_attempt=? WHERE source_id=?",
                        (encode({"downloaded": [], "digests": []}), self.clock(), source["id"]),
                    )
                conn.execute(
                    "INSERT INTO media_review_decisions VALUES(?,?,?,0,?,?) "
                    "ON CONFLICT(source_id) DO UPDATE SET mapping_json=excluded.mapping_json,"
                    "revision=excluded.revision,updated=excluded.updated",
                    (
                        source["id"],
                        source["fingerprint"],
                        encode(item["mapping"]),
                        max(job["revision"], source["decision_revision"] or 0) + 1,
                        self.clock(),
                    ),
                )
                conn.execute(
                    "UPDATE media_import_jobs SET status='reviewed' WHERE source_id=?",
                    (source["id"],),
                )
            self.event(
                conn, preview[0]["source_id"], "series_review_saved", {"preview_id": preview_id}
            )
            return {"status": "saved", "manifest": data["manifest"]}

    def supporting_sources(self, sources):
        protected = []
        for source in sources:
            try:
                profile = self.profile(source["profile"])
            except StopIteration:
                protected.append(source)
                continue
            # Another source is authoritative until its own grace and health gates pass.
            if (
                not source["missing_count"]
                or source["status"] == "changed"
                or source["missing_count"] < profile.missing_scans
                or self.clock() - source["missing_since"] < profile.grace_seconds
            ):
                protected.append(source)
                continue
            self.health(profile)
            inventory = self.inventory(profile)
            if source["path"] in inventory or source["fingerprint"] in inventory.values():
                protected.append(source)
        return protected

    def reconcile(self, p):
        now = self.clock()
        with self.store._connect() as conn:
            sources = rows(
                conn,
                "SELECT * FROM media_source_files WHERE profile=? AND status!='removed'",
                (p.name,),
            )
        missing = [s for s in sources if s["missing_count"]]
        mass = len(missing) > p.max_cleanup_batch or (
            len(sources) > 2 and len(missing) / len(sources) > p.max_missing_fraction
        )
        for source in missing:
            if source["status"] == "changed" or source["path"] in self.inventory(p):
                continue
            if (
                source["missing_count"] < p.missing_scans
                or now - source["missing_since"] < p.grace_seconds
            ):
                continue
            with self.store._connect() as conn:
                artifacts = rows(
                    conn,
                    "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
                    "ON r.artifact_id=a.id WHERE r.source_id=? AND a.status IN "
                    "('active','deleting')",
                    (source["id"],),
                )
                manifest = []
                for a in artifacts:
                    support = rows(
                        conn,
                        "SELECT s.* FROM media_source_files s JOIN media_artifact_sources r "
                        "ON r.source_id=s.id WHERE r.artifact_id=? AND s.id!=? AND "
                        "s.status!='removed'",
                        (a["id"], source["id"]),
                    )
                    if not a["owned"] or self.supporting_sources(support):
                        continue
                    manifest.append(
                        {
                            "id": a["id"],
                            "path": a["path"],
                            "receipt": json.loads(a["receipt_json"]),
                            "destination": roots.artifact(conn, a["id"]),
                        }
                    )
                unfinished = rows(
                    conn,
                    "SELECT * FROM media_reconcile_actions WHERE source_id=? "
                    "AND status='executing' ORDER BY created DESC LIMIT 1",
                    (source["id"],),
                )
                if unfinished:
                    action = unfinished[0]["id"]
                    manifest = json.loads(unfinished[0]["manifest_json"])
                else:
                    action = uuid.uuid5(uuid.NAMESPACE_URL, source["id"] + encode(manifest)).hex
                conn.execute(
                    "INSERT OR IGNORE INTO media_reconcile_actions VALUES(?,?,1,?,?,?,NULL)",
                    (
                        action,
                        source["id"],
                        encode(manifest),
                        "mass_review" if mass else "preview",
                        now,
                    ),
                )
            if self.config.reconcile_policy == "execute" and not mass:
                self.execute_cleanup(p, source, action, manifest)
        if self.config.reconcile_policy == "execute":
            self.prune_dirs(p, kind="reconcile")

    def execute_cleanup(self, p, source, action, manifest):
        self.write_gate("reconcile")
        self.health(p)
        path = Path(p.source_root) / source["path"]
        current_inventory = self.inventory(p)
        if (
            source["path"] in current_inventory
            or source["fingerprint"] in current_inventory.values()
            or path.exists()
            or path.is_symlink()
        ):
            return
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE media_subtitle_jobs SET status='cancelled' WHERE source_id=?",
                (source["id"],),
            )
            conn.execute(
                "UPDATE media_reconcile_actions SET status='executing' WHERE id=?", (action,)
            )
        outcomes = []
        for entry in manifest:
            try:
                self.health(p)
                if path.exists() or path.is_symlink():
                    raise ValueError("source returned")
                with self.store._connect() as conn:
                    support = rows(
                        conn,
                        "SELECT s.* FROM media_source_files s JOIN media_artifact_sources r "
                        "ON r.source_id=s.id WHERE r.artifact_id=? AND s.id!=? AND "
                        "s.status!='removed'",
                        (entry["id"], source["id"]),
                    )
                    if self.supporting_sources(support):
                        raise ValueError("artifact has another supporting source")
                    conn.execute(
                        "UPDATE media_artifacts SET status='deleting' WHERE id=?", (entry["id"],)
                    )
                target = Path(entry["path"])
                with self.store._connect() as conn:
                    descriptor = roots.artifact(conn, entry["id"])
                if descriptor != entry.get("destination"):
                    raise ValueError("cleanup historical destination changed; preview again")
                target_root = roots.validate(descriptor, target)
                if target.exists() or target.is_symlink():
                    self.write_gate("reconcile")
                    self._unlink(target_root, target, entry["receipt"], kind="reconcile")
                with self.store._connect() as conn:
                    conn.execute(
                        "UPDATE media_artifacts SET status='removed' WHERE id=?", (entry["id"],)
                    )
                    self.event(conn, source["id"], "artifact_removed", entry)
                outcomes.append({"path": entry["path"], "status": "removed"})
            except (OSError, ValueError) as exc:
                outcomes.append({"path": entry["path"], "status": "conflict", "error": str(exc)})
        status = "conflict" if any(o["status"] == "conflict" for o in outcomes) else "removed"
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE media_reconcile_actions SET status=?,result_json=? WHERE id=?",
                (status, encode(outcomes), action),
            )
            if status == "removed":
                conn.execute(
                    "UPDATE media_source_files SET status='removed' WHERE id=?", (source["id"],)
                )
        self.prune_dirs(p, kind="reconcile")

    def prune_dirs(self, p, *, kind="import"):
        import errno

        with self.store._connect() as conn:
            directories = rows(
                conn,
                "SELECT d.*,r.descriptor_json FROM media_owned_directories d "
                "JOIN media_directory_roots r ON r.path=d.path WHERE d.profile=?",
                (p.name,),
            )
        failed = set()
        for row in sorted(directories, key=lambda d: len(Path(d["path"]).parts), reverse=True):
            path = Path(row["path"])
            descriptor = json.loads(row["descriptor_json"])
            key = (descriptor["root"], descriptor.get("route"))
            if key in failed:
                continue
            try:
                root = roots.validate(descriptor, path)
            except (OSError, ValueError) as exc:
                self.target_health(descriptor, "blocked", exc)
                failed.add(key)
                continue
            self.target_health(descriptor, "healthy")
            if descriptor.get("subdir") and path == root / descriptor["subdir"]:
                continue
            try:
                if fs.identity(path) != row["identity"]:
                    raise ValueError("owned directory identity changed; preserve it")
            except (OSError, ValueError) as exc:
                self.record_health(
                    "directory",
                    str(path),
                    {
                        "path": str(path),
                        "root": str(root),
                        "status": "conflict",
                        "reason": str(exc)[:200],
                    },
                )
                continue
            try:
                with fs.parent_fd(root, path) as (fd, name):
                    self.write_gate(kind)
                    os.rmdir(name, dir_fd=fd)
                with self.store._connect() as conn:
                    conn.execute("DELETE FROM media_owned_directories WHERE path=?", (str(path),))
                    conn.execute("DELETE FROM media_directory_roots WHERE path=?", (str(path),))
            except OSError as exc:
                if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                    self.record_health(
                        "directory",
                        str(path),
                        {
                            "path": str(path),
                            "root": str(root),
                            "status": "conflict",
                            "reason": str(exc)[:200],
                        },
                    )

    def source_snapshot(self, conn, *, limit=None, offset=0):
        sources = rows(
            conn,
            "SELECT s.*,j.mapping_json,j.target,j.revision,j.error,j.status AS import_status,"
            "r.descriptor_json AS route_json,d.mapping_json AS review_mapping_json,d.ready AS "
            "review_ready,d.revision AS review_revision "
            "FROM media_source_files s LEFT JOIN media_import_jobs j ON j.source_id=s.id "
            "LEFT JOIN media_review_decisions d ON d.source_id=s.id AND "
            "d.fingerprint=s.fingerprint "
            "LEFT JOIN media_plan_routes r ON r.source_id=s.id AND r.revision=j.revision "
            "ORDER BY s.path,s.generation LIMIT ? OFFSET ?",
            (limit if limit is not None else -1, offset),
        )
        for source in sources:
            mapping = json.loads(source["mapping_json"] or "{}")
            source["content_type"] = (
                "movie" if mapping.get("media_type") == "movie" else ("tv" if mapping else None)
            )
            source["animation"] = mapping.get("animation")
            source["classification_evidence"] = mapping.get("classification_evidence")
            source["route"] = (
                json.loads(source["route_json"])["route"] if source["route_json"] else None
            )
            if source["review_mapping_json"]:
                mapping = Mapping.model_validate_json(source["review_mapping_json"])
                try:
                    source["review_target"] = str(
                        render(
                            mapping,
                            self.for_mapping(self.profile(source["profile"]), mapping),
                            Path(source["path"]).suffix,
                        )
                    )
                except ValueError, StopIteration:
                    source["review_error"] = "classification/route requires renewed review"
        return sources

    def snapshot(self, *, limit=None, offset=0):
        from seed_agent.media_import.artwork import PosterJobs

        if limit is not None:
            limit = min(250, max(1, int(limit)))
        offset = max(0, int(offset))
        with self.store._connect() as conn:
            sources = self.source_snapshot(conn, limit=limit, offset=offset)
            ids = [s["id"] for s in sources]
            placeholders = ",".join("?" for _ in ids) or "NULL"

            def related(table, column="source_id"):
                if limit is None:
                    return rows(conn, "SELECT * FROM " + table)
                return rows(conn, f"SELECT * FROM {table} WHERE {column} IN ({placeholders})", ids)

            refs = related("media_artifact_sources")
            aids = [r["artifact_id"] for r in refs]
            artifact_marks = ",".join("?" for _ in aids) or "NULL"
            return {
                "pagination": {
                    "offset": offset,
                    "limit": limit,
                    "total": conn.execute("SELECT COUNT(*) FROM media_source_files").fetchone()[0],
                },
                "profiles": [
                    {
                        "name": p.name,
                        "source_root": p.source_root,
                        "target_root": p.target_root,
                        "grace_seconds": p.grace_seconds,
                        "import_policy": self.config.import_policy,
                        "subtitle_policy": self.config.subtitle_policy,
                        "reconcile_policy": self.config.reconcile_policy,
                        "max_subtitles": p.max_subtitles,
                    }
                    for p in self.profiles()
                ],
                "destinations": self.config.destinations.model_dump(mode="json")
                if self.config.destinations
                else None,
                "sources": sources,
                "scans": rows(conn, "SELECT * FROM media_scan_runs ORDER BY id DESC LIMIT 100"),
                "artifacts": (
                    rows(
                        conn, f"SELECT * FROM media_artifacts WHERE id IN ({artifact_marks})", aids
                    )
                    if limit is not None
                    else rows(conn, "SELECT * FROM media_artifacts")
                ),
                "artifact_sources": refs,
                "publications": related("media_publications"),
                "subtitles": related("media_subtitle_jobs"),
                "cleanup": related("media_reconcile_actions"),
                "events": rows(conn, "SELECT * FROM media_events ORDER BY id DESC LIMIT 200"),
                **(
                    {
                        "posters": PosterJobs(self, None).status(limit=limit, offset=offset),
                        "domain_health": [
                            json.loads(r["payload_json"])
                            for r in rows(
                                conn,
                                "SELECT payload_json FROM media_runtime_status "
                                "WHERE role LIKE 'destination:%' "
                                "OR role LIKE 'source:%' OR role LIKE 'directory:%' "
                                "OR role LIKE 'provider:%' "
                                "ORDER BY json_extract(payload_json,'$.status')='healthy',"
                                "role LIMIT 250",
                            )
                        ],
                    }
                    if limit is not None
                    else {}
                ),
            }
