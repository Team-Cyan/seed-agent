"""Durable bounded discovery, independent coverage and source-generation-fenced publication."""

import hashlib
import json
import os
import time
import uuid
from collections import Counter
from pathlib import Path

from seed_agent.media_import import filesystem as fs
from seed_agent.media_import import roots
from seed_agent.media_import.engine import encode, rows
from seed_agent.media_import.subtitles.languages import (
    matches as language_matches,
)
from seed_agent.media_import.subtitles.languages import (
    normalize as language_normalize,
)
from seed_agent.media_import.subtitles.languages import (
    priority as language_priority,
)
from seed_agent.media_import.subtitles.provider import Candidate, ProviderError
from seed_agent.media_import.subtitles.validation import compatibility, validate


class SubtitleJobs:
    def __init__(self, engine, provider=None):
        self.engine, self.provider = engine, provider
        if provider is not None and hasattr(provider, "bind"):
            provider.bind(engine)
        if provider is not None and hasattr(provider, "request_pacer"):
            provider.request_pacer = lambda: self.pace(wait=True)
        if provider is not None and hasattr(provider, "download_gate"):
            from seed_agent.media_import.subtitles.quota import DownloadBudget

            self.budget = DownloadBudget(engine.store, provider.name, clock=engine.clock)
            provider.download_gate = self.budget.reserve
            provider.download_observer = self.budget.observe
            if hasattr(provider, "quota_observer"):
                provider.quota_observer = self.budget.sync
        if provider is not None and hasattr(provider, "interval_observer"):
            provider.interval_observer = self.defer_interval

    def inventory(self, source, p, *, deadline=None):
        coverage = []
        deadline = deadline or time.monotonic() + self.engine.config.inventory_timeout_seconds
        path = Path(p.source_root) / source["path"]
        probe = json.loads(source.get("probe_json") or "{}")
        for stream in probe.get("streams", []):
            if stream.get("codec_type") != "subtitle":
                continue
            lang = stream.get("tags", {}).get("language", "")
            # Generic zho/chi does not prove simplified/traditional script.
            lang = language_normalize(lang)
            flags = stream.get("disposition", {})
            kind = (
                "forced"
                if flags.get("forced")
                else ("sdh" if flags.get("hearing_impaired") else "full")
            )
            coverage.append({"language": lang, "kind": kind, "source": "embedded"})
        roots = [path]
        if source.get("target"):
            roots.append(Path(source["target"]))
        for video in roots:
            if not video.parent.is_dir():
                continue
            for item in video.parent.iterdir():
                if time.monotonic() >= deadline:
                    raise TimeoutError("subtitle coverage time budget exceeded")
                if not item.name.startswith(video.stem + ".") or item.suffix.lower() not in {
                    ".srt",
                    ".ass",
                    ".vtt",
                }:
                    continue
                if item.is_symlink() or not item.is_file():
                    continue
                tokens = item.name[len(video.stem) + 1 :].split(".")[:-1]
                lang = next(
                    (language_normalize(x) for x in tokens if language_normalize(x) != "unknown"),
                    "unknown",
                )
                kind = "forced" if "forced" in tokens else ("sdh" if "sdh" in tokens else "full")
                if item.stat().st_size > 2_000_000:
                    continue
                try:
                    validate(item.read_bytes(), duration=probe.get("duration", 0))
                except ValueError, OSError:
                    continue
                coverage.append(
                    {"language": lang, "kind": kind, "source": "sidecar", "path": str(item)}
                )
        return coverage

    def run(self, *, refresh=False, limit=10, profile=None, source_id=None, on_job=None):
        e, now = self.engine, self.engine.clock()
        self.payload_attempted_sources = set()
        names = [p.name for p in e.profiles() if profile is None or p.name == profile]
        if not names:
            return []
        lookahead = min(e.config.max_inventory_files, 50, max(1, limit) * 4)
        names_sql = ",".join("?" for _ in names)
        requirements_sql, requirements_args = [], []
        for name in names:
            groups = e.profile(name).languages
            requirements_sql.append(
                "(s.profile=? AND j.requirement IN (" + ",".join("?" for _ in groups) + "))"
            )
            requirements_args.extend([name, *(encode(group) for group in groups)])
        active_requirements = " OR ".join(requirements_sql)
        with e.lease(), e.store._connect() as conn:
            sources = rows(
                conn,
                "SELECT s.*,j.mapping_json,j.target FROM media_source_files s "
                "JOIN media_import_jobs j ON j.source_id=s.id WHERE s.missing_count=0 "
                "AND s.status='imported' AND j.status='imported' "
                f"AND s.profile IN ({names_sql}) AND (? IS NULL OR s.id=?)",
                (*names, source_id, source_id),
            )
            sources = [s for s in sources if profile is None or s["profile"] == profile]
            existing = {
                r[0]
                for r in conn.execute(
                    "SELECT j.id FROM media_subtitle_jobs j JOIN media_source_files s "
                    "ON s.id=j.source_id WHERE s.status='imported' AND s.missing_count=0 "
                    f"AND s.profile IN ({names_sql})",
                    names,
                )
            }
            for source in sources:
                p = e.profile(source["profile"])
                for requirement in p.languages:
                    jid = uuid.uuid5(uuid.NAMESPACE_URL, source["id"] + encode(requirement)).hex
                    if jid not in existing:
                        conn.execute(
                            "INSERT OR IGNORE INTO media_subtitle_jobs "
                            "(id,source_id,generation,requirement,status,attempts,"
                            "next_attempt,first_attempt,payload_json,error) "
                            "VALUES(?,?,?,?,?,0,?,?,?,NULL)",
                            (
                                jid,
                                source["id"],
                                source["generation"],
                                encode(requirement),
                                "missing",
                                now,
                                now,
                                encode(
                                    {
                                        "downloaded": [],
                                        "digests": [],
                                        "discovery_version": 1,
                                        "search_state": "not_searched",
                                        "external_state": "missing",
                                    }
                                ),
                            ),
                        )
                    if refresh:
                        conn.execute(
                            "UPDATE media_subtitle_jobs SET next_attempt=?,status='missing' "
                            "WHERE id=? AND status!='cancelled' AND (status!='running' OR "
                            "next_attempt<=?)",
                            (now, jid, now),
                        )
            if limit > 0:
                legacy = rows(
                    conn,
                    "SELECT j.id,j.source_id,j.generation,j.payload_json,j.next_attempt "
                    "FROM media_subtitle_jobs j "
                    "JOIN media_source_files s ON s.id=j.source_id "
                    "JOIN media_import_jobs i ON i.source_id=s.id "
                    "WHERE s.missing_count=0 AND s.status='imported' AND i.status='imported' "
                    "AND j.generation=s.generation "
                    "AND j.status NOT IN ('running','cancelled','terminal_failure') "
                    "AND json_extract(j.payload_json,'$.discovery_version') IS NULL "
                    f"AND s.profile IN ({names_sql}) AND (? IS NULL OR s.id=?) "
                    f"AND ({active_requirements}) "
                    "ORDER BY j.id LIMIT ?",
                    (*names, source_id, source_id, *requirements_args, lookahead),
                )
                for old in legacy:
                    upgraded = json.loads(old["payload_json"])
                    upgraded.update(
                        discovery_version=1,
                        search_state="legacy_unknown",
                        coverage_state="present"
                        if upgraded.get("coverage_satisfied")
                        else "missing",
                    )
                    changed = conn.execute(
                        "UPDATE media_subtitle_jobs SET payload_json=?,"
                        "next_attempt=MIN(next_attempt,?) "
                        "WHERE id=? AND payload_json=? "
                        "AND status NOT IN ('running','cancelled','terminal_failure')",
                        (encode(upgraded), now, old["id"], old["payload_json"]),
                    ).rowcount
                    if changed:
                        e.event(
                            conn,
                            old["source_id"],
                            "subtitle_discovery_state_upgraded",
                            {
                                "job_id": old["id"],
                                "generation": old["generation"],
                                "previous_next_attempt": old["next_attempt"],
                                "upgraded_at": now,
                            },
                        )
            due = rows(
                conn,
                "SELECT j.*,s.profile,s.path,s.fingerprint,s.original_release,s.probe_json,"
                "i.mapping_json,i.target AS planned_target,i.revision AS "
                "planned_revision FROM media_subtitle_jobs j "
                "JOIN media_source_files s ON s.id=j.source_id JOIN media_import_jobs i "
                "ON i.source_id=s.id WHERE s.missing_count=0 AND s.status='imported' "
                "AND i.status='imported' AND j.status NOT IN "
                "('cancelled','terminal_failure') AND j.next_attempt<=? "
                "AND (? IS NULL OR s.profile=?) "
                f"AND s.profile IN ({names_sql}) AND (? IS NULL OR s.id=?) "
                f"AND ({active_requirements}) "
                "ORDER BY CASE WHEN j.attempts=0 THEN 0 ELSE 1 END,"
                "COALESCE(json_extract(j.payload_json,'$.coverage_observed'),0),"
                "CASE WHEN j.status='satisfied' THEN 1 ELSE 0 END,j.next_attempt,j.id LIMIT ?",
                (
                    now,
                    profile,
                    profile,
                    *names,
                    source_id,
                    source_id,
                    *requirements_args,
                    lookahead,
                ),
            )
        due = [
            job
            for job in due
            if json.loads(job["requirement"]) in e.profile(job["profile"]).languages
        ]
        if limit <= 0:
            return []
        # Bound directory reads/writes separately from provider claims. Persisted
        # observation age rotates the lookahead across restarts; unseen/never-tried
        # jobs advance first. Missing coverage wins inside each finite window.
        # Never hold a SQLite transaction while inspecting sidecars.
        deadline = time.monotonic() + e.config.inventory_timeout_seconds
        classified = []
        with e.lease():
            for job in due:
                if time.monotonic() >= deadline:
                    return [
                        {"status": "coverage_pending", "error": "coverage time budget exceeded"}
                    ]
                job["refresh_search"] = refresh
                job["target"] = job.pop("planned_target")
                job["plan_revision"] = job.pop("planned_revision")
                data = json.loads(job["payload_json"])
                p = e.profile(job["profile"])
                try:
                    coverage = self.inventory(job, p, deadline=deadline)
                except OSError:
                    return [
                        {
                            "status": "coverage_pending",
                            "error": "coverage unavailable; no provider allowance spent",
                        }
                    ]
                covered = any(
                    language_matches(c["language"], json.loads(job["requirement"]))
                    and c["kind"] == p.subtitle_kind
                    for c in coverage
                )
                data.update(coverage=coverage, coverage_satisfied=covered, coverage_observed=now)
                prior = job["payload_json"]
                job["payload_json"] = encode(data)
                with e.store._connect() as conn:
                    changed = conn.execute(
                        "UPDATE media_subtitle_jobs SET payload_json=? "
                        "WHERE id=? AND payload_json=? AND next_attempt<=?",
                        (job["payload_json"], job["id"], prior, now),
                    ).rowcount
                if changed:
                    classified.append(job)
            classified.sort(
                key=lambda j: (
                    j["attempts"] > 0,
                    json.loads(j["payload_json"])["coverage_satisfied"],
                    e.profile(j["profile"]).languages.index(json.loads(j["requirement"])),
                    j["next_attempt"],
                    j["id"],
                )
            )
            due = []
            for job in classified[: min(50, limit)]:
                job["claim_token"] = uuid.uuid4().hex
                with e.store._connect() as conn:
                    changed = conn.execute(
                        "UPDATE media_subtitle_jobs SET status='running',next_attempt=?,"
                        "claim_token=?,"
                        "plan_revision=?,target=?,attempts=attempts+1 "
                        "WHERE id=? AND next_attempt<=?",
                        (
                            now + 600,
                            job["claim_token"],
                            job["plan_revision"],
                            job["target"],
                            job["id"],
                            now,
                        ),
                    ).rowcount
                if changed:
                    due.append(job)
        results = []
        for job in due:
            if on_job:
                on_job()
            results.append(self.process(job))
        return results

    @staticmethod
    def candidate_key(provider, candidate_id):
        return (
            candidate_id
            if candidate_id.startswith(provider + ":")
            else provider + ":" + candidate_id
        )

    def defer_interval(self, interval):
        with self.engine.store._connect() as conn:
            conn.execute(
                "UPDATE media_provider_state SET next_request=MAX(next_request,?) "
                "WHERE provider=? AND status='available' AND EXISTS "
                "(SELECT 1 FROM media_control WHERE epoch=?)",
                (
                    self.engine.clock() + max(1, interval),
                    self.provider.name,
                    self.engine.store_epoch,
                ),
            )

    def pace(self, *, wait=False):
        if not self.provider:
            return
        e = self.engine
        for _ in range(2):
            delay = 0
            with e.lease(), e.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = rows(
                    conn,
                    "SELECT * FROM media_provider_state WHERE provider=?",
                    (self.provider.name,),
                )
                if state and state[0]["next_request"] > e.clock():
                    delay = state[0]["next_request"] - e.clock()
                    if (
                        not wait
                        or delay > 10
                        or state[0]["status"] in {"quota", "rate_limited", "daily_quota"}
                    ):
                        raise ProviderError(
                            state[0]["status"]
                            if state[0]["status"] in {"quota", "rate_limited", "daily_quota"}
                            else "retrying",
                            max(1, int(delay) + 1),
                            payload_attempted=False,
                            evidence={
                                "origin": "persistent_gate",
                                "stage": "request",
                                "retry_delay_seconds": max(1, int(delay) + 1),
                            },
                        )
                else:
                    conn.execute(
                        "INSERT INTO media_provider_state VALUES(?,?,'available') "
                        "ON CONFLICT(provider) DO UPDATE SET "
                        "next_request=excluded.next_request,status='available'",
                        (
                            self.provider.name,
                            e.clock()
                            + max(
                                e.config.provider_interval_seconds,
                                getattr(self.provider, "min_interval_seconds", 0),
                            ),
                        ),
                    )
                    return
            # Never hold the filesystem/SQLite writer lock during network pacing.
            time.sleep(delay)
        raise ProviderError("retrying", e.config.provider_interval_seconds, payload_attempted=False)

    def reuse_local(self, job, coverage, data, all_digests):
        e = self.engine
        if e.config.subtitle_policy != "execute":
            return
        data.setdefault("local_published", [])
        data.setdefault("digests", [])
        duration = json.loads(job["probe_json"])["duration"]
        source_video = Path(e.profile(job["profile"]).source_root) / job["path"]
        profile = e.profile(job["profile"])
        maximum = profile.max_subtitles
        preferred = list(dict.fromkeys(lang for group in profile.languages for lang in group))
        ordered = sorted(
            coverage,
            key=lambda c: (
                preferred.index(c.get("language"))
                if c.get("language") in preferred
                else len(preferred)
            ),
        )
        for c in ordered:
            if (
                c.get("source") != "sidecar"
                or c.get("kind") != profile.subtitle_kind
                or not any(
                    language_matches(c.get("language"), group) for group in profile.languages
                )
            ):
                continue
            path = Path(c["path"])
            if path.parent != source_video.parent:
                continue
            if len(all_digests) >= maximum:
                break
            payload, fmt = validate(path.read_bytes(), duration=duration)
            digest = hashlib.sha256(payload).hexdigest()
            key = str(path) + ":" + digest
            if key in data["local_published"]:
                continue
            if digest in all_digests:
                continue
            candidate = Candidate(id=key, language=c["language"], kind=c["kind"])
            self.publish(job, candidate, payload, fmt, provider_name="local")
            data["digests"].append(digest)
            all_digests.add(digest)
            data["local_published"].append(key)
        for ext in [".jpg", ".png"]:
            path = source_video.with_suffix(ext)
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
                continue
            payload = path.read_bytes()
            if not (
                payload.startswith(b"\xff\xd8\xff") or payload.startswith(b"\x89PNG\r\n\x1a\n")
            ):
                continue
            key = str(path) + ":" + hashlib.sha256(payload).hexdigest()
            if key in data["local_published"]:
                continue
            self.publish(
                job,
                Candidate(id=key, language="und"),
                payload,
                ext[1:],
                provider_name="local",
                artifact_kind="artwork",
            )
            data["local_published"].append(key)

    def process(self, job):
        e = self.engine
        p = e.profile(job["profile"])
        source = {
            **job,
            "id": job["source_id"],
            "probe": json.loads(job["probe_json"] or "{}"),
            "source_root": p.source_root,
            "absolute_path": str(Path(p.source_root) / job["path"]),
        }
        mapping = json.loads(job["mapping_json"])
        requirement = json.loads(job["requirement"])
        data = json.loads(job["payload_json"])
        coverage = self.inventory(source, p)
        satisfied = any(
            language_matches(c["language"], requirement) and c["kind"] == p.subtitle_kind
            for c in coverage
        )
        data["coverage"] = coverage
        data["coverage_satisfied"] = satisfied
        data["coverage_state"] = "present" if satisfied else "missing"
        data.setdefault("discovery_version", 1)
        data.setdefault(
            "search_state",
            "legacy_unknown" if data.get("providers") or "candidates" in data else "not_searched",
        )
        data.setdefault("seen", list(data.get("downloaded", [])))
        data["provider"] = getattr(self.provider, "name", None)
        with e.store._connect() as conn:
            live_claim = rows(
                conn,
                "SELECT claim_token,next_attempt FROM media_subtitle_jobs WHERE id=?",
                (job["id"],),
            )
            published = rows(
                conn,
                "SELECT payload_json FROM media_events WHERE source_id=? "
                "AND event='subtitle_published' ORDER BY id DESC LIMIT 200",
                (job["source_id"],),
            )
            artifacts = rows(
                conn,
                "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
                "ON r.artifact_id=a.id WHERE r.source_id=? AND a.status='active' "
                "AND a.kind='subtitle'",
                (job["source_id"],),
            )
        if (
            not live_claim
            or live_claim[0]["claim_token"] != job["claim_token"]
            or live_claim[0]["next_attempt"] <= e.clock()
        ):
            return self.result(job, "superseded", data)
        active = {a["id"]: a for a in artifacts}
        all_digests = {json.loads(a["receipt_json"]).get("digest") for a in artifacts} - {None}
        # Old versions counted candidate IDs (including duplicate content) as
        # choices. Rebuild choice counts from active publication receipts; keep
        # candidate history separately so duplicates are not fetched again.
        data["downloaded"] = []
        data["digests"] = []
        for row in published:
            prior = json.loads(row["payload_json"])
            if prior.get("artifact") not in active or not language_matches(
                prior.get("candidate", {}).get("language"), requirement
            ):
                continue
            digest = json.loads(active[prior["artifact"]]["receipt_json"]).get("digest")
            unique = digest and digest not in data["digests"]
            if unique:
                data["digests"].append(digest)
            if prior.get("provider") not in {None, "local"}:
                key = self.candidate_key(prior["provider"], prior["candidate"]["id"])
                if key not in data["seen"]:
                    data["seen"].append(key)
                if unique and key not in data["downloaded"]:
                    data["downloaded"].append(key)
        candidates = []
        error = None
        delay = e.config.subtitle_refresh_seconds
        planned = None
        try:
            planned = e.for_plan(p, job["source_id"])
            e.health(
                planned
            )  # verify source + historical destination before any paid/provider work
            e.target_health(planned._historical_descriptor, "healthy")
            if fs.fingerprint(Path(source["absolute_path"])) != source["fingerprint"]:
                raise ValueError("subtitle source fingerprint changed")
            self.reuse_local(job, coverage, data, all_digests)
            all_digests.update(data["digests"])
            data["external_count"] = len(all_digests)
            data["external_state"] = "published" if all_digests else "missing"
            if len(all_digests) >= p.max_subtitles:
                data["choice_limit_reached"] = True
                status = "satisfied" if satisfied else "limit_reached"
                self.finish(job, status, data, e.config.subtitle_refresh_seconds)
                return self.result(job, status, data)
            if job["source_id"] in getattr(self, "payload_attempted_sources", set()):
                self.finish(job, "satisfied" if satisfied else "cycle_deferred", data, 60)
                return self.result(job, "satisfied" if satisfied else "cycle_deferred", data)
            if self.provider is None:
                raise ProviderError("credentials_required")
            if hasattr(self, "budget"):
                self.budget.check()
            if not hasattr(self.provider, "request_pacer"):
                self.pace()
            data["last_search_attempt_at"] = e.clock()
            source["_provider_search"] = data.get("provider_search", {})
            source["_force_search"] = job.get("refresh_search", False)
            source["_subtitle_candidates"] = data.get("candidates", []) + data.get(
                "unverified_candidates", []
            )
            candidates = self.provider.search(mapping, source, requirement)[:100]
            if getattr(self.provider, "search_performed", True):
                data["last_search_at"] = e.clock()
            provider_states = getattr(self.provider, "statuses", {})
            data["search_state"] = (
                "partial"
                if any(
                    v.get("status") not in {"available", "no_result"}
                    for v in provider_states.values()
                )
                else "complete"
            )
            ranked = []
            reasons = Counter()
            data["unverified_candidates"] = []
            for candidate in candidates:
                score, reason = compatibility(candidate, mapping, source, p)
                if score is not None and not language_matches(candidate.language, requirement):
                    reason = "language_mismatch"
                reasons[reason] += 1
                if score is not None and language_matches(candidate.language, requirement):
                    if candidate.id in data.get("operator_selected", []):
                        candidate.match_basis = "operator_confirmed"
                    ranked.append((score, candidate))
                elif candidate.tmdb_id is None and not candidate.imdb_id:
                    data["unverified_candidates"].append(candidate.payload())
            ranked.sort(
                key=lambda pair: (
                    *pair[0][:2],
                    -language_priority(pair[1].language, requirement),
                    *(pair[0][2:4] if len(pair[0]) == 6 else (0, 0)),
                    -self.provider.priority(pair[1].provider)
                    if hasattr(self.provider, "priority")
                    else 0,
                    *pair[0][-2:],
                ),
                reverse=True,
            )
            data["candidates"] = [{**c.payload(), "score": list(score)} for score, c in ranked]
            data["candidate_reason_counts"] = dict(reasons)
            data["candidate_reason_scope"] = "adapter_returned_candidates"
            data["search_outcome"] = (
                "no_result"
                if not candidates
                else "no_compatible"
                if not ranked
                else "version_review"
                if all(c.match_basis == "needs_preview" for _, c in ranked)
                else "candidates_available"
            )
            data.setdefault("downloaded", [])
            data.setdefault("digests", [])
            failed_providers = set()
            data["download_retry_at"] = {
                name: stamp
                for name, stamp in data.get("download_retry_at", {}).items()
                if stamp > e.clock()
            }
            data["candidate_failures"] = {
                k: v
                for k, v in data.get("candidate_failures", {}).items()
                if v.get("retry_until", 0) > e.clock()
            }
            for _score, candidate in ranked:
                if e.config.subtitle_policy != "execute" or len(all_digests) >= p.max_subtitles:
                    break
                key = self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                if (
                    key in data["seen"]
                    or key in data["downloaded"]
                    or candidate.match_basis == "needs_preview"
                    or key in data["candidate_failures"]
                    or candidate.provider in failed_providers
                ):
                    continue
                if (
                    data["download_retry_at"].get(candidate.provider or self.provider.name, 0)
                    > e.clock()
                ):
                    failed_providers.add(candidate.provider)
                    continue
                if not hasattr(self.provider, "request_pacer"):
                    self.pace(wait=True)
                self.payload_attempted_sources = getattr(self, "payload_attempted_sources", set())
                self.payload_attempted_sources.add(job["source_id"])
                try:
                    raw_payload = self.provider.download(candidate)
                except ProviderError as exc:
                    if not exc.payload_attempted:
                        self.payload_attempted_sources.discard(job["source_id"])
                        if getattr(self.provider, "managed", False):
                            failed_providers.add(candidate.provider)
                            data["download_retry_at"][candidate.provider or self.provider.name] = (
                                e.clock() + exc.retry_after
                            )
                            delay = min(delay, exc.retry_after)
                            error = exc.status
                            if exc.status == "candidate_refresh_required" and not data.get(
                                "external_count"
                            ):
                                data["external_state"] = "candidate_refresh_required"
                            continue
                    raise
                try:
                    payload, fmt = validate(raw_payload, duration=source["probe"]["duration"])
                except ValueError:
                    data["candidate_failures"][key] = {
                        "status": "invalid_payload",
                        "retry_until": e.clock() + 86400,
                    }
                    error, delay = "invalid_payload", 60
                    break
                digest = hashlib.sha256(payload).hexdigest()
                if digest in all_digests:
                    data["seen"].append(key)
                    # The link already consumed allowance even for duplicate bytes.
                    # Move to the next file instead of spending another link here.
                    break
                self.publish(job, candidate, payload, fmt)
                data["seen"].append(key)
                data["downloaded"].append(key)
                data["digests"].append(digest)
                all_digests.add(digest)
                data["external_count"] = len(all_digests)
                data["external_state"] = "published"
                data["coverage_satisfied"] = True
                data["coverage_state"] = "present"
                satisfied = True
                # Save per-payload receipts, not just at the end of a provider batch.
                self.finish(job, "satisfied", data, delay)
                # First cover each file once; alternatives use subsequent cycles.
                break
            data["pending_compatible_count"] = sum(
                candidate.match_basis != "needs_preview"
                and self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                not in data["seen"]
                and self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                not in data["downloaded"]
                and self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                not in data["candidate_failures"]
                and candidate.provider not in failed_providers
                for _, candidate in ranked
            )
            data["pending_download_retry_at"] = min(
                (
                    data["download_retry_at"][candidate.provider or self.provider.name]
                    for _, candidate in ranked
                    if candidate.match_basis != "needs_preview"
                    and self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                    not in data["seen"]
                    and self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                    not in data["downloaded"]
                    and self.candidate_key(candidate.provider or self.provider.name, candidate.id)
                    not in data["candidate_failures"]
                    and (candidate.provider or self.provider.name) in data["download_retry_at"]
                ),
                default=None,
            )
            if hasattr(self.provider, "search_history"):
                data["provider_search"] = self.provider.search_history
                retry = min(
                    (h["next_search_at"] for h in data["provider_search"].values()),
                    default=e.clock() + delay,
                )
                delay = max(60, retry - e.clock())
            if getattr(self.provider, "managed", False):
                data["providers"] = self.provider.statuses
                if self.provider.next_retry is not None:
                    delay = min(delay, self.provider.next_retry)
            status = (
                "satisfied"
                if satisfied
                else (
                    "providers_wait"
                    if failed_providers
                    else (
                        "retrying"
                        if error == "invalid_payload"
                        else ("review_required" if ranked else "missing")
                    )
                )
            )
        except roots.DestinationUnavailable as exc:
            status, error, delay = (
                "blocked_destination",
                "destination unavailable; ownership preserved",
                60,
            )
            if planned:
                e.target_health(planned._historical_descriptor, "blocked", exc)
        except roots.SourceUnavailable as exc:
            status, error, delay = "blocked_source", "source unavailable; ownership preserved", 60
            e.record_health(
                "source",
                p.name,
                {
                    "source_id": p.name,
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:200],
                },
            )
        except ProviderError as exc:
            status, error, delay = exc.status, exc.status, exc.retry_after
            if (
                data.get("last_search_attempt_at")
                and data.get("last_search_at", 0) < data["last_search_attempt_at"]
            ):
                data["search_state"] = "waiting"
                data["search_outcome"] = exc.status
            if (
                self.provider
                and not getattr(self.provider, "managed", False)
                and status in {"quota", "rate_limited", "daily_quota"}
            ):
                with e.lease(), e.store._connect() as conn:
                    conn.execute(
                        "INSERT INTO media_provider_state VALUES(?,?,?) "
                        "ON CONFLICT(provider) DO UPDATE SET "
                        "next_request=excluded.next_request,status=excluded.status",
                        (self.provider.name, e.clock() + delay, status),
                    )
        except (OSError, ValueError) as exc:
            status, error = "terminal_failure", str(exc)
        except Exception:
            status, error = "retrying", "provider failure"
        if status in {"retrying", "quota"}:
            delay = max(delay, min(86400, 60 * 2 ** min(job["attempts"], 10)))
            if (
                status == "retrying"
                and e.clock() - job["first_attempt"] > e.config.retry_horizon_seconds
            ):
                status = "terminal_failure"
        if getattr(self.provider, "managed", False):
            data["providers"] = self.provider.statuses
            if hasattr(self.provider, "search_history"):
                data["provider_search"] = self.provider.search_history
        if status == "satisfied":
            if (
                data.get("pending_compatible_count", 0)
                and data.get("external_count", 0) < p.max_subtitles
            ):
                delay = 60
            elif (
                data.get("pending_download_retry_at")
                and data.get("external_count", 0) < p.max_subtitles
            ):
                delay = max(60, data["pending_download_retry_at"] - e.clock())
            elif any(h.get("refresh_required") for h in data.get("provider_search", {}).values()):
                delay = max(
                    60,
                    min(
                        h["next_search_at"]
                        for h in data["provider_search"].values()
                        if h.get("refresh_required")
                    )
                    - e.clock(),
                )
            elif data.get("search_state") == "complete" or (
                data.get("external_count", 0) > 0 and not hasattr(self.provider, "search_history")
            ):
                delay = max(delay, e.config.subtitle_refresh_seconds)
            else:
                # Embedded coverage is not external acquisition. Resume incomplete
                # discovery under the real provider gate, with a bounded anti-spin floor.
                delay = max(60, delay)
        self.finish(job, status, data, delay, error)
        return self.result(job, status, data)

    @staticmethod
    def result(job, status, data):
        return {
            "id": job["id"],
            "status": status,
            "coverage_satisfied": data.get("coverage_satisfied", False),
            "external_state": data.get("external_state", "unknown"),
            "external_count": data.get("external_count"),
            "downloaded_count": len(data.get("downloaded", [])),
            "local_published_count": len(data.get("local_published", [])),
            "search_state": data.get("search_state", "not_searched"),
            "search_outcome": data.get("search_outcome"),
            "last_search_at": data.get("last_search_at"),
            "candidate_reason_counts": data.get("candidate_reason_counts", {}),
            "providers": {
                name: {
                    "status": value.get("status"),
                    "last_search_at": data.get("provider_search", {})
                    .get(name, {})
                    .get("last_search_at"),
                    "next_search_at": data.get("provider_search", {})
                    .get(name, {})
                    .get("next_search_at"),
                }
                for name, value in data.get("providers", {}).items()
            },
        }

    def select(self, job_id, candidate_id):
        e = self.engine
        with e.lease(), e.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            found = rows(
                conn,
                "SELECT j.*,i.revision AS current_revision,i.target AS current_target,"
                "s.profile,s.path,s.fingerprint,s.missing_count FROM media_subtitle_jobs j "
                "JOIN media_import_jobs i ON i.source_id=j.source_id "
                "JOIN media_source_files s ON s.id=j.source_id WHERE j.id=?",
                (job_id,),
            )
            if not found:
                raise ValueError("unknown subtitle job")
            job = found[0]
            p = e.profile(job["profile"])
            e.health(p)
            if (
                job["missing_count"]
                or job["plan_revision"] != job["current_revision"]
                or job["target"] != job["current_target"]
                or fs.fingerprint(Path(p.source_root) / job["path"]) != job["fingerprint"]
            ):
                raise ValueError("stale subtitle candidates; refresh first")
            data = json.loads(job["payload_json"])
            if not any(c["id"] == candidate_id for c in data.get("candidates", [])):
                raise ValueError("candidate absent or rejected by identity/version checks")
            data.setdefault("operator_selected", [])
            if candidate_id not in data["operator_selected"]:
                data["operator_selected"].append(candidate_id)
            data.get("provider_search", {}).pop(candidate_id.split(":", 1)[0], None)
            conn.execute(
                "UPDATE media_subtitle_jobs SET payload_json=?,status='missing',next_attempt=?,"
                "claim_token=NULL WHERE id=?",
                (encode(data), e.clock(), job_id),
            )
            e.event(
                conn,
                job["source_id"],
                "subtitle_candidate_confirmed",
                {"job_id": job_id, "candidate_id": candidate_id},
            )
            return {"status": "saved", "job_id": job_id, "candidate_id": candidate_id}

    def finish(self, job, status, data, delay, error=None):
        e = self.engine
        if e.store.epoch() != e.store_epoch:
            return
        with e.lease(), e.store._connect() as conn:
            conn.execute(
                "UPDATE media_subtitle_jobs SET status=?,next_attempt=?,payload_json=?,error=? "
                "WHERE id=? AND claim_token=? AND status!='cancelled' AND EXISTS ("
                "SELECT 1 FROM media_source_files s JOIN media_import_jobs i ON i.source_id=s.id "
                "WHERE s.id=media_subtitle_jobs.source_id AND s.missing_count=0 "
                "AND s.generation=media_subtitle_jobs.generation AND s.status='imported' "
                "AND i.status='imported' AND i.revision=? AND i.target=?)",
                (
                    status,
                    e.clock() + delay,
                    encode(data),
                    error,
                    job["id"],
                    job["claim_token"],
                    job["plan_revision"],
                    job["target"],
                ),
            )

    def publish(
        self, job, candidate, payload, fmt, *, provider_name=None, artifact_kind="subtitle"
    ):
        provider_name = provider_name or candidate.provider or self.provider.name
        e = self.engine
        p = e.for_plan(e.profile(job["profile"]), job["source_id"])
        root = Path(p.target_root)
        with e.lease():
            e.write_gate("subtitle")
            e.health(p)
            with e.store._connect() as conn:
                live = rows(
                    conn,
                    "SELECT s.*,j.status AS subtitle_status,j.claim_token,i.status AS "
                    "import_status,i.target,i.revision FROM "
                    "media_source_files s JOIN media_subtitle_jobs j ON j.source_id=s.id "
                    "JOIN media_import_jobs i ON i.source_id=s.id WHERE j.id=?",
                    (job["id"],),
                )
                if (
                    not live
                    or live[0]["missing_count"]
                    or live[0]["status"] != "imported"
                    or live[0]["subtitle_status"] == "cancelled"
                    or live[0]["import_status"] != "imported"
                    or live[0]["claim_token"] != job["claim_token"]
                ):
                    raise ValueError("subtitle generation fenced")
                source = live[0]
                if (
                    source["generation"] != job["generation"]
                    or source["target"] != job["target"]
                    or source["revision"] != job["plan_revision"]
                ):
                    raise ValueError("subtitle mapping changed")
                if fs.fingerprint(Path(p.source_root) / source["path"]) != job["fingerprint"]:
                    raise ValueError("source replaced before subtitle publication")
                video = rows(
                    conn,
                    "SELECT * FROM media_artifacts WHERE path=? AND status='active'",
                    (job["target"],),
                )
                if not video or fs.receipt(root, Path(job["target"])) != json.loads(
                    video[0]["receipt_json"]
                ):
                    raise ValueError("video artifact changed")
            # Plex descriptive label appears before supported language/forced suffixes.
            label = hashlib.sha256((provider_name + candidate.id).encode()).hexdigest()[:10]
            suffix = (
                "."
                + candidate.language
                + ("." + candidate.kind if candidate.kind != "full" else "")
            )
            target = Path(job["target"]).with_suffix("")
            target = target.with_name(target.name + f".{label}" + suffix + "." + fmt)
            if artifact_kind == "artwork":
                target = Path(job["target"]).with_suffix("." + fmt)
            with e.store._connect() as conn:
                prior = rows(
                    conn,
                    "SELECT * FROM media_artifacts WHERE path=? AND status='active'",
                    (str(target),),
                )
            if target.exists() or target.is_symlink():
                actual = fs.receipt(root, target, digest=True)
                if not prior or actual != json.loads(prior[0]["receipt_json"]):
                    raise ValueError("existing local sidecar is not owned; preserve it")
                if actual["digest"] != hashlib.sha256(payload).hexdigest():
                    raise ValueError("owned local sidecar content changed")
                return
            aid = uuid.uuid4().hex
            temp = target.parent / (".media-subtitle-" + aid)
            expected = {"digest": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
            with e.store._connect() as conn:
                conn.execute(
                    "INSERT INTO media_artifacts VALUES(?,?,?,?,1,'publishing',?,?)",
                    (aid, str(target), p.name, artifact_kind, encode(expected), e.clock()),
                )
                roots.record_artifact(conn, aid, p._historical_descriptor)
                conn.execute(
                    "INSERT INTO media_publications VALUES(?,?,?,?,?,'pending')",
                    (aid, job["source_id"], str(temp), str(target), encode(expected)),
                )
                e.record_publication_fence(conn, aid, job["source_id"])
            with fs.parent_fd(root, temp) as (fd, name):
                out = os.open(
                    name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
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
            e.write_gate("subtitle")
            e._link(root, temp, root, target, kind="subtitle")
            with e.store._connect() as conn:
                conn.execute(
                    "UPDATE media_artifacts SET status='active',receipt_json=? WHERE id=?",
                    (encode(receipt), aid),
                )
                conn.execute(
                    "INSERT INTO media_artifact_sources VALUES(?,?)", (aid, job["source_id"])
                )
                e.event(
                    conn,
                    job["source_id"],
                    "subtitle_published",
                    {"artifact": aid, "candidate": candidate.payload(), "provider": provider_name},
                )
            e._unlink(root, temp, receipt, kind="subtitle")
            with e.store._connect() as conn:
                conn.execute(
                    "UPDATE media_publications SET status='done' WHERE artifact_id=?", (aid,)
                )
