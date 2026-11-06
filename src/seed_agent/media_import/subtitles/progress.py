"""Read-only, library-wide subtitle progress from persisted receipts and jobs."""

from seed_agent.media_import.engine import encode

# These remain visible separately in by_status; they need operator attention.
_REVIEW = (
    "review_required",
    "mapping_review",
    "terminal_failure",
    "credentials_required",
    "limit_reached",
)


def subtitle_progress(engine, *, profile=None):
    """Summarize eligible sources without scanning files or changing jobs.

    Managed external counts describe active database receipts, not filesystem readback.
    Due/waiting are scheduler timing counts and may overlap review counts.
    """
    profiles = [p for p in engine.profiles() if profile is None or p.name == profile]
    names = [p.name for p in profiles]
    requirements = [(p.name, encode(group)) for p in profiles for group in p.languages]
    now = engine.clock()
    result = {
        "scope": "eligible_imported_sources",
        "physical_readback": False,
        "state": "no_sources",
        "eligible_sources": 0,
        "expected_requirements": 0,
        "jobs_initialized": 0,
        "by_status": {},
        "due": 0,
        "waiting": 0,
        "review": 0,
        "oldest_due": None,
        "next_attempt": None,
        "coverage_satisfied_jobs": 0,
        "sources_with_any_coverage": 0,
        "fully_covered_sources": 0,
        "discovery_completed_jobs": 0,
        "managed_external_artifacts": 0,
        "sources_with_managed_external": 0,
        "sources_without_managed_external": 0,
    }
    if not names:
        return result
    marks = ",".join("?" for _ in names)
    source_cte = (
        "WITH eligible AS (SELECT s.id,s.profile,s.generation FROM media_source_files s "
        "JOIN media_import_jobs i ON i.source_id=s.id WHERE s.status='imported' "
        "AND s.missing_count=0 AND i.status='imported' "
        f"AND s.profile IN ({marks})) "
    )
    with engine.store._connect() as conn:
        conn.execute("BEGIN")
        counts = dict(
            conn.execute(
                source_cte + "SELECT profile,COUNT(*) FROM eligible GROUP BY profile", names
            )
        )
        result["eligible_sources"] = sum(counts.values())
        result["expected_requirements"] = sum(
            counts.get(p.name, 0) * len(set(map(encode, p.languages))) for p in profiles
        )
        artifacts = conn.execute(
            source_cte + "SELECT COUNT(DISTINCT a.id),COUNT(DISTINCT e.id) FROM eligible e "
            "JOIN media_artifact_sources r ON r.source_id=e.id "
            "JOIN media_artifacts a ON a.id=r.artifact_id "
            "WHERE a.status='active' AND a.kind='subtitle'",
            names,
        ).fetchone()
        result["managed_external_artifacts"], result["sources_with_managed_external"] = artifacts
        result["sources_without_managed_external"] = result["eligible_sources"] - artifacts[1]
        if requirements:
            clauses = " OR ".join("(e.profile=? AND j.requirement=?)" for _ in requirements)
            args = [*names, *(value for pair in requirements for value in pair)]
            jobs_cte = (
                source_cte.rstrip() + ", active_jobs AS (SELECT j.* FROM media_subtitle_jobs j "
                "JOIN eligible e ON e.id=j.source_id AND e.generation=j.generation "
                f"WHERE ({clauses})) "
            )
            result["by_status"] = dict(
                conn.execute(
                    jobs_cte + "SELECT status,COUNT(*) FROM active_jobs GROUP BY status", args
                )
            )
            result["jobs_initialized"] = sum(result["by_status"].values())
            review_marks = ",".join("?" for _ in _REVIEW)
            aggregate = conn.execute(
                jobs_cte + "SELECT "
                "COUNT(CASE WHEN status NOT IN ('cancelled','terminal_failure') "
                "AND next_attempt<=? THEN 1 END),"
                "COUNT(CASE WHEN status NOT IN ('cancelled','terminal_failure') "
                "AND next_attempt>? THEN 1 END),"
                f"COUNT(CASE WHEN status IN ({review_marks}) THEN 1 END),"
                "MIN(CASE WHEN status NOT IN ('cancelled','terminal_failure') "
                "AND next_attempt<=? THEN next_attempt END),"
                "MIN(CASE WHEN status NOT IN ('cancelled','terminal_failure') "
                "AND next_attempt>? THEN next_attempt END),"
                "COUNT(CASE WHEN json_extract(payload_json,'$.coverage_satisfied')=1 THEN 1 END),"
                "COUNT(DISTINCT CASE WHEN json_extract(payload_json,'$.coverage_satisfied')=1 "
                "THEN source_id END),"
                "COUNT(CASE WHEN json_extract(payload_json,'$.search_state')='complete' "
                "THEN 1 END) "
                "FROM active_jobs",
                (*args, now, now, *_REVIEW, now, now),
            ).fetchone()
            for key, value in zip(
                (
                    "due",
                    "waiting",
                    "review",
                    "oldest_due",
                    "next_attempt",
                    "coverage_satisfied_jobs",
                    "sources_with_any_coverage",
                    "discovery_completed_jobs",
                ),
                aggregate,
                strict=False,
            ):
                result[key] = value
            values = ",".join("(?,?)" for _ in requirements)
            result["fully_covered_sources"] = conn.execute(
                jobs_cte.rstrip() + f", required(profile,requirement) AS (VALUES {values}) "
                "SELECT COUNT(*) FROM eligible e "
                "WHERE EXISTS (SELECT 1 FROM required r WHERE r.profile=e.profile) "
                "AND NOT EXISTS (SELECT 1 FROM required r WHERE r.profile=e.profile "
                "AND NOT EXISTS (SELECT 1 FROM active_jobs j WHERE j.source_id=e.id "
                "AND j.requirement=r.requirement "
                "AND json_extract(j.payload_json,'$.coverage_satisfied')=1))",
                (*args, *(value for pair in requirements for value in pair)),
            ).fetchone()[0]
    if result["eligible_sources"]:
        if (
            result["due"]
            or result["by_status"].get("running", 0)
            or result["jobs_initialized"] < result["expected_requirements"]
        ):
            result["state"] = "processing"
        elif result["review"]:
            result["state"] = "review"
        else:
            result["state"] = "waiting"
    return result
