"""Versioned media tables installed by the shared StateStore migration."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_schema (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO media_schema VALUES (1);
CREATE TABLE IF NOT EXISTS media_scan_runs (
 id INTEGER PRIMARY KEY, profile TEXT NOT NULL, started REAL NOT NULL,
 completed REAL, status TEXT NOT NULL, root_identity TEXT, count INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS media_source_files (
 id TEXT PRIMARY KEY, profile TEXT NOT NULL, path TEXT NOT NULL, generation INTEGER NOT NULL,
 fingerprint TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
 stable_count INTEGER NOT NULL, missing_since REAL, missing_count INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL, readiness TEXT, probe_json TEXT, original_release TEXT NOT NULL,
 UNIQUE(profile,path,generation)
);
CREATE TABLE IF NOT EXISTS media_import_jobs (
 source_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, status TEXT NOT NULL,
 mapping_json TEXT, target TEXT, error TEXT, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS media_artifacts (
 id TEXT PRIMARY KEY, path TEXT NOT NULL, profile TEXT NOT NULL,
 kind TEXT NOT NULL, owned INTEGER NOT NULL, status TEXT NOT NULL,
 receipt_json TEXT NOT NULL, created REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS media_active_path ON media_artifacts(path)
 WHERE status IN ('active','publishing','deleting');
CREATE TABLE IF NOT EXISTS media_publications (
 artifact_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, temporary TEXT NOT NULL,
 target TEXT NOT NULL, receipt_json TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_artifact_sources (
 artifact_id TEXT NOT NULL, source_id TEXT NOT NULL,
 PRIMARY KEY(artifact_id,source_id)
);
CREATE TABLE IF NOT EXISTS media_owned_directories (
 path TEXT PRIMARY KEY, profile TEXT NOT NULL, identity TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_review_decisions (
 source_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, mapping_json TEXT NOT NULL,
 ready INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS media_subtitle_jobs (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, generation INTEGER NOT NULL,
 requirement TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt REAL NOT NULL, first_attempt REAL NOT NULL, payload_json TEXT NOT NULL,
 error TEXT, claim_token TEXT, plan_revision INTEGER, target TEXT
);
CREATE TABLE IF NOT EXISTS media_reconcile_actions (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, revision INTEGER NOT NULL,
 manifest_json TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, result_json TEXT
);
CREATE TABLE IF NOT EXISTS media_events (
 id INTEGER PRIMARY KEY, source_id TEXT, event TEXT NOT NULL, created REAL NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS media_sources_profile ON media_source_files(profile);
CREATE INDEX IF NOT EXISTS media_subtitle_due ON media_subtitle_jobs(status,next_attempt);
"""

SCHEMA += """
CREATE TABLE IF NOT EXISTS media_provider_state (
 provider TEXT PRIMARY KEY, next_request REAL NOT NULL, status TEXT NOT NULL
);
"""
