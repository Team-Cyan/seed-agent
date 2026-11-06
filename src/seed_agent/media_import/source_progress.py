"""Aggregate persisted source progress without touching media files."""


def source_progress(engine):
    """Count latest generations for configured profiles; no physical readback is implied."""
    names = [p.name for p in engine.profiles()]
    result = {
        "scope": "configured_sources_latest_generation",
        "physical_readback": False,
        "records": 0,
        "historical_generations": 0,
        "total": 0,
        "present": 0,
        "imported": 0,
        "pending": 0,
        "review": 0,
        "conflict": 0,
        "blocked": 0,
        "missing": 0,
        "unknown": 0,
        "by_status": {},
        "by_source_status": {},
        "by_import_status": {},
    }
    if not names:
        return result
    placeholders = ",".join("?" for _ in names)
    latest = (
        "WITH latest AS (SELECT profile,path,MAX(generation) AS generation "
        "FROM media_source_files "
        f"WHERE profile IN ({placeholders}) GROUP BY profile,path), "
        "current AS (SELECT s.status AS source_status,s.readiness,s.missing_count, "
        "j.status AS import_status, "
        "CASE WHEN s.missing_count>0 THEN 'missing_pending' "
        "WHEN s.status='removed' THEN 'removed' "
        "WHEN j.status IN ('blocked_source','blocked_destination') THEN j.status "
        "WHEN s.status IN ('changed','conflict','target_missing') THEN s.status "
        "WHEN j.status IN ('changed','conflict','target_missing') THEN j.status "
        "WHEN s.readiness='completion_unverified' THEN s.readiness "
        "WHEN s.status='review_required' THEN s.status "
        "ELSE COALESCE(j.status,s.status) END AS effective_status "
        "FROM latest l JOIN media_source_files s ON s.profile=l.profile AND s.path=l.path "
        "AND s.generation=l.generation LEFT JOIN media_import_jobs j ON j.source_id=s.id), "
        "classified AS (SELECT *,CASE "
        "WHEN missing_count>0 OR source_status='removed' THEN 'missing' "
        "WHEN import_status IN ('blocked_source','blocked_destination') THEN 'blocked' "
        "WHEN source_status IN ('changed','conflict','target_missing') "
        "OR import_status IN ('changed','conflict','target_missing') THEN 'conflict' "
        "WHEN readiness='completion_unverified' OR source_status='review_required' "
        "OR import_status='review_required' THEN 'review' "
        "WHEN source_status='imported' AND import_status='imported' THEN 'imported' "
        "WHEN COALESCE(import_status,source_status) IN "
        "('stabilizing','ready','identified','planned','pending','retrying','executing',"
        "'discovered','missing_pending') THEN 'pending' "
        "ELSE 'unknown' END AS category FROM current) "
    )
    with engine.store._connect() as conn:
        conn.execute("BEGIN")
        result["records"] = conn.execute(
            f"SELECT COUNT(*) FROM media_source_files WHERE profile IN ({placeholders})", names
        ).fetchone()[0]
        for category, count in conn.execute(
            latest + "SELECT category,COUNT(*) FROM classified GROUP BY category", names
        ):
            result[category] = count
        result["total"] = sum(
            result[key]
            for key in (
                "imported",
                "pending",
                "review",
                "conflict",
                "blocked",
                "missing",
                "unknown",
            )
        )
        result["present"] = result["total"] - result["missing"]
        result["historical_generations"] = result["records"] - result["total"]
        for key, column in (
            ("by_status", "effective_status"),
            ("by_source_status", "source_status"),
            ("by_import_status", "import_status"),
        ):
            result[key] = dict(
                conn.execute(
                    latest + f"SELECT COALESCE({column},'none'),COUNT(*) FROM classified "
                    f"GROUP BY {column}",
                    names,
                )
            )
    return result
