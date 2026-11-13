"""Read-only cross-page candidates for explicit media actions."""

import json
import re

from seed_agent.media_import.variants import work_key


def reviewed_request_status(engine, request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", request_id):
        raise ValueError("invalid request ID")
    with engine.store._connect() as conn:
        records = conn.execute(
            "SELECT id,status,result_json FROM media_commands "
            "WHERE json_extract(payload_json,'$.client_request_id')=? LIMIT 2",
            (request_id,),
        ).fetchall()
    if len(records) > 1:
        raise ValueError("request has multiple commands; inspect command receipts")
    return [
        {"id": row[0], "status": row[1], "result": json.loads(row[2]) if row[2] else None}
        for row in records
    ]


def variant_candidates(engine, source_id):
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{32}", source_id):
        raise ValueError("invalid source ID")
    with engine.store._connect() as conn:
        conn.execute("BEGIN")
        selected = conn.execute(
            "SELECT j.mapping_json FROM media_import_jobs j JOIN media_source_files s "
            "ON s.id=j.source_id WHERE s.id=? AND s.status='imported' "
            "AND j.status='imported' AND s.missing_count=0",
            (source_id,),
        ).fetchone()
        if not selected or not selected[0]:
            return []
        mapping = json.loads(selected[0])
        key = work_key(mapping)
        candidates = conn.execute(
            "SELECT s.id,s.path,j.mapping_json FROM media_source_files s "
            "JOIN media_import_jobs j ON j.source_id=s.id "
            "WHERE s.id!=? AND s.missing_count=0 AND s.stable_count>=2 "
            "AND json_extract(j.mapping_json,'$.tmdb_id')=? "
            "AND json_extract(j.mapping_json,'$.media_type')=? "
            "AND NOT EXISTS (SELECT 1 FROM media_extra_attachments e WHERE e.source_id=s.id) "
            "AND NOT EXISTS (SELECT 1 FROM media_artifacts a JOIN media_artifact_sources r "
            "ON r.artifact_id=a.id WHERE r.source_id=s.id "
            "AND a.status IN ('active','publishing','deleting')) "
            "ORDER BY s.path,s.id LIMIT 200",
            (source_id, mapping["tmdb_id"], mapping["media_type"]),
        ).fetchall()
        return [
            {"source_id": row[0], "path": row[1]}
            for row in candidates
            if work_key(json.loads(row[2])) == key
        ][:50]
