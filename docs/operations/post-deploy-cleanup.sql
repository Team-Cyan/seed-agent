-- One-time cleanup for deployments that previously used the old confirmed
-- intent state. Run against the workspace SQLite database after deploying a
-- build that no longer exposes the confirm flow:
--
--   sqlite3 .seed-agent/state.db < docs/operations/post-deploy-cleanup.sql
--
-- The application also performs this migration at StateStore startup. This SQL
-- is kept as an explicit operator tool for Docker/Unraid post-deploy cleanup.

BEGIN;

UPDATE intents
SET
  state = 'confirmation_required',
  normalized_json = json_set(normalized_json, '$.state', 'confirmation_required'),
  updated_at = datetime('now')
WHERE state = 'confirmed'
  AND json_valid(normalized_json);

UPDATE intents
SET
  state = 'confirmation_required',
  updated_at = datetime('now')
WHERE state = 'confirmed';

COMMIT;
