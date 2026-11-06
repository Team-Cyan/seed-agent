"""Reviewed, hash-bound local SRT delivery through the normal media worker."""

import hashlib
import json
import math
import os
import re
import stat
import uuid
from pathlib import Path

from seed_agent.media_import import filesystem as fs
from seed_agent.media_import.engine import encode, rows
from seed_agent.media_import.subtitles.jobs import SubtitleJobs
from seed_agent.media_import.subtitles.languages import matches
from seed_agent.media_import.subtitles.provider import Candidate
from seed_agent.media_import.subtitles.validation import MAX_BYTES, validate

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_BASE = {
    "source_id",
    "generation",
    "fingerprint",
    "payload_sha256",
    "language",
    "kind",
    "provenance",
}
_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def validate_request(request, *, execute):
    allowed = _BASE | {"preview_id", "compatibility_acknowledged"}
    if not isinstance(request, dict) or not _BASE <= request.keys() or request.keys() - allowed:
        raise ValueError("exact local subtitle request required")
    if not isinstance(request["source_id"], str) or not re.fullmatch(
        r"[a-f0-9]{32}", request["source_id"]
    ):
        raise ValueError("source ID required")
    if type(request["generation"]) is not int or request["generation"] < 1:
        raise ValueError("source generation required")
    if not isinstance(request["fingerprint"], str) or len(request["fingerprint"]) > 256:
        raise ValueError("source fingerprint required")
    fp = json.loads(request["fingerprint"])
    if not isinstance(fp, list) or len(fp) != 4 or any(type(n) is not int or n < 0 for n in fp):
        raise ValueError("canonical source fingerprint required")
    if not isinstance(request["payload_sha256"], str) or not _SHA.fullmatch(
        request["payload_sha256"]
    ):
        raise ValueError("staged SRT digest required")
    if request["language"] not in {"zh", "zh-Hans", "zh-Hant", "en"}:
        raise ValueError("explicit supported language required")
    if request["kind"] not in {"full", "forced", "sdh"}:
        raise ValueError("explicit subtitle kind required")
    provenance = request["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != {
        "provider",
        "reference",
        "original_sha256",
        "transformation",
    }:
        raise ValueError("bounded local provenance required")
    if provenance["provider"] not in {"manual", "zimuku", "assrt", "subdl", "opensubtitlescom"}:
        raise ValueError("unsupported provenance provider")
    if not isinstance(provenance["reference"], str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,100}", provenance["reference"]
    ):
        raise ValueError("stable provenance reference required; URLs are not accepted")
    if not isinstance(provenance["original_sha256"], str) or not _SHA.fullmatch(
        provenance["original_sha256"]
    ):
        raise ValueError("original SRT digest required")
    transform = provenance["transformation"]
    if transform == {"kind": "none"}:
        if provenance["original_sha256"] != request["payload_sha256"]:
            raise ValueError("unchanged payload must retain original digest")
    elif isinstance(transform, dict) and set(transform) == {
        "kind",
        "numerator",
        "denominator",
        "source_fps",
        "evidence_sha256",
    }:
        if transform["kind"] != "precomputed_time_scale":
            raise ValueError("only explicit precomputed timing proof is supported")
        if any(
            type(transform[k]) is not int or not 0 < transform[k] <= 100000
            for k in ["numerator", "denominator"]
        ):
            raise ValueError("bounded positive timing ratio required")
        fps = transform["source_fps"]
        if type(fps) not in {int, float} or not math.isfinite(fps) or not 0 < fps <= 240:
            raise ValueError("known source FPS required")
        if not isinstance(transform["evidence_sha256"], str) or not _SHA.fullmatch(
            transform["evidence_sha256"]
        ):
            raise ValueError("timing evidence digest required")
    else:
        raise ValueError("explicit transformation provenance required")
    if execute:
        if type(request.get("preview_id")) is not int or request["preview_id"] < 1:
            raise ValueError("prior local subtitle preview required")
        if request.get("compatibility_acknowledged") is not True:
            raise ValueError("explicit source/version/timing compatibility acknowledgment required")
    elif request.keys() & {"preview_id", "compatibility_acknowledged"}:
        raise ValueError("preview request cannot carry execution approval")
    return {key: request[key] for key in sorted(_BASE)}


def _read_staged(engine, digest):
    root = engine.store.path.parent / "subtitle-inbox"
    with fs.parent_fd(root, root / (digest + ".srt")) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
                raise ValueError("staged subtitle must be a bounded regular file")
            data = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("staged subtitle changed during read")
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("staged subtitle digest changed")
    if data.startswith((b"PK", b"Rar!")):
        raise ValueError("only staged plain SRT is supported; archives require separate review")
    return data


def _srt(data, duration):
    result, fmt = validate(data, duration=duration)
    if fmt != "srt" or not any(
        "-->" in line and len(_TIME.findall(line)) == 2 for line in result.decode().splitlines()
    ):
        raise ValueError("plain millisecond SRT required")
    return result


def _verify_transform(engine, request, output, duration, fps):
    provenance = request["provenance"]
    transform = provenance["transformation"]
    if transform["kind"] == "none":
        return
    if (
        type(fps) not in {int, float}
        or not math.isfinite(fps)
        or abs(fps - transform["source_fps"]) > 0.1
    ):
        raise ValueError("source FPS differs from reviewed timing proof")
    numerator, denominator = transform["numerator"], transform["denominator"]
    original = _srt(
        _read_staged(engine, provenance["original_sha256"]), duration * denominator / numerator
    )

    def scale(match):
        h, m, s, ms = map(int, match.groups())
        ticks = (
            (h * 3600000 + m * 60000 + s * 1000 + ms) * numerator + denominator // 2
        ) // denominator
        return (
            f"{ticks // 3600000:02}:{ticks // 60000 % 60:02}:"
            f"{ticks // 1000 % 60:02},{ticks % 1000:03}"
        )

    # Verify an explicitly supplied transform; never infer or publish a new retiming.
    transformed = (
        "\n".join(
            _TIME.sub(scale, line) if "-->" in line else line
            for line in original.decode().splitlines()
        ).strip()
        + "\n"
    )
    if transformed != output.decode().strip() + "\n":
        raise ValueError("precomputed subtitle does not match original/timing proof")


class LocalSubtitleImport:
    def __init__(self, engine):
        self.engine = engine

    def _prepare(self, request):
        e = self.engine
        with e.store._connect() as conn:
            found = rows(
                conn,
                "SELECT s.*,i.mapping_json,i.target,i.revision AS plan_revision,"
                "i.status AS import_status FROM media_source_files s JOIN media_import_jobs i "
                "ON i.source_id=s.id WHERE s.id=?",
                (request["source_id"],),
            )
        if not found:
            raise ValueError("unknown imported subtitle source")
        source = found[0]
        if (
            source["status"] != "imported"
            or source["import_status"] != "imported"
            or source["missing_count"]
            or source["generation"] != request["generation"]
            or source["fingerprint"] != request["fingerprint"]
        ):
            raise ValueError("local subtitle source baseline changed")
        p = e.for_plan(e.profile(source["profile"]), source["id"])
        e.health(p)
        if fs.fingerprint(Path(p.source_root) / source["path"]) != source["fingerprint"]:
            raise ValueError("local subtitle source replaced")
        with e.store._connect() as conn:
            video = conn.execute(
                "SELECT receipt_json FROM media_artifacts WHERE path=? AND status='active'",
                (source["target"],),
            ).fetchone()
        if not video or fs.receipt(Path(p.target_root), Path(source["target"])) != json.loads(
            video[0]
        ):
            raise ValueError("active owned video receipt required for subtitle preview")
        requirement = next(
            (group for group in p.languages if matches(request["language"], group)), None
        )
        if requirement is None or request["kind"] != p.subtitle_kind:
            raise ValueError("local subtitle language/kind is outside the active profile")
        probe = json.loads(source["probe_json"])
        duration = probe.get("duration")
        if type(duration) not in {int, float} or not math.isfinite(duration) or duration <= 0:
            raise ValueError("known source duration required")
        raw = _read_staged(e, request["payload_sha256"])
        payload = _srt(raw, duration)
        _verify_transform(e, request, payload, duration, probe.get("fps"))
        binding = {
            "request": request,
            "epoch": e.store_epoch,
            "config_revision": e.config_view.effective_revision,
            "source_path": source["path"],
            "target": source["target"],
            "plan_revision": source["plan_revision"],
            "mapping_sha256": hashlib.sha256(source["mapping_json"].encode()).hexdigest(),
            "video_receipt_sha256": hashlib.sha256(video[0].encode()).hexdigest(),
            "published_sha256": hashlib.sha256(payload).hexdigest(),
            "published_bytes": len(payload),
            "requirement": requirement,
        }
        return binding, source, p, payload

    def run(self, request, *, execute=False):
        core = validate_request(request, execute=execute)
        e = self.engine
        binding, source, profile, payload = self._prepare(core)
        if not execute:
            with e.lease(), e.store._connect() as conn:
                e.event(conn, source["id"], "subtitle_local_preview", binding)
                preview_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return {
                "status": "preview",
                "preview_id": preview_id,
                "binding": binding,
                "requires_compatibility_acknowledgment": True,
                "published": False,
                "automatic_retiming": False,
            }
        if e.config.subtitle_policy != "execute":
            raise ValueError("subtitle execution policy required")
        with e.store._connect() as conn:
            prior = conn.execute(
                "SELECT payload_json FROM media_events WHERE id=? "
                "AND source_id=? AND event='subtitle_local_preview'",
                (request["preview_id"], source["id"]),
            ).fetchone()
        if not prior or json.loads(prior[0]) != binding:
            raise ValueError("local subtitle preview changed; preview again")
        jobs = SubtitleJobs(e)
        digest = binding["published_sha256"]
        # The normal worker is the only executor. Short leases protect admission;
        # the common publisher acquires its own lease and rechecks all fences.
        with e.lease(), e.store._connect() as conn:
            artifacts = rows(
                conn,
                "SELECT a.* FROM media_artifacts a JOIN media_artifact_sources r "
                "ON r.artifact_id=a.id WHERE r.source_id=? AND a.status='active' "
                "AND a.kind='subtitle'",
                (source["id"],),
            )
            digests = set()
            for artifact in artifacts:
                receipt = json.loads(artifact["receipt_json"])
                if (
                    fs.receipt(Path(profile.target_root), Path(artifact["path"]), digest=True)
                    != receipt
                ):
                    raise ValueError("managed subtitle artifact changed; reconcile first")
                if receipt.get("digest"):
                    digests.add(receipt["digest"])
            if digest in digests:
                return {
                    "status": "already_present",
                    "published": False,
                    "external_count": len(digests),
                    "published_sha256": digest,
                    "preview_id": request["preview_id"],
                }
            if len(digests) >= profile.max_subtitles:
                return {
                    "status": "limit_reached",
                    "published": False,
                    "external_count": len(digests),
                }
            jid = uuid.uuid5(uuid.NAMESPACE_URL, source["id"] + encode(binding["requirement"])).hex
            conn.execute(
                "INSERT OR IGNORE INTO media_subtitle_jobs "
                "(id,source_id,generation,requirement,status,attempts,next_attempt,"
                "first_attempt,payload_json) "
                "VALUES(?,?,?,?,'missing',0,?,?,?)",
                (
                    jid,
                    source["id"],
                    source["generation"],
                    encode(binding["requirement"]),
                    e.clock(),
                    e.clock(),
                    encode({"discovery_version": 1}),
                ),
            )
            job = rows(conn, "SELECT * FROM media_subtitle_jobs WHERE id=?", (jid,))[0]
            if job["generation"] != source["generation"] or job["status"] == "cancelled":
                raise ValueError("stale or cancelled subtitle job")
            if job["status"] == "running" and job["next_attempt"] > e.clock():
                raise ValueError("subtitle job already claimed")
            token = uuid.uuid4().hex
            conn.execute(
                "UPDATE media_subtitle_jobs SET status='running',claim_token=?,"
                "next_attempt=?,plan_revision=?,target=? WHERE id=?",
                (token, e.clock() + 600, source["plan_revision"], source["target"], jid),
            )
            job.update(
                claim_token=token,
                plan_revision=source["plan_revision"],
                target=source["target"],
                profile=source["profile"],
                fingerprint=source["fingerprint"],
            )
            data = json.loads(job["payload_json"])
        candidate = Candidate(
            id="reviewed-" + core["payload_sha256"],
            language=core["language"],
            kind=core["kind"],
            provider="local",
            identity_basis="operator_source_review",
            match_basis="operator_confirmed",
        )
        try:
            # Re-read both staged objects and live binding immediately before publication.
            refreshed, _, _, refreshed_payload = self._prepare(core)
            if refreshed != binding or refreshed_payload != payload:
                raise ValueError("local subtitle changed after admission")
            jobs.publish(job, candidate, payload, "srt", provider_name="local")
        except Exception:
            jobs.finish(job, "retrying", data, 60, "local import interrupted; reconcile receipts")
            raise
        data.setdefault("local_published", []).append("reviewed:" + digest)
        data["digests"] = list(dict.fromkeys([*data.get("digests", []), digest]))
        data.update(
            external_count=len(digests) + 1,
            external_state="published",
            coverage_satisfied=True,
            coverage_state="present",
        )
        jobs.finish(job, "satisfied", data, max(60, job["next_attempt"] - e.clock()))
        with e.lease(), e.store._connect() as conn:
            e.event(
                conn,
                source["id"],
                "subtitle_local_imported",
                {
                    "preview_id": request["preview_id"],
                    "binding": binding,
                    "compatibility_acknowledged": True,
                    "provider": "local",
                },
            )
        return {
            "status": "published",
            "published": True,
            "external_count": len(digests) + 1,
            "published_sha256": digest,
            "preview_id": request["preview_id"],
            "automatic_retiming": False,
        }
