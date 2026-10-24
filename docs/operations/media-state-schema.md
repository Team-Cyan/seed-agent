# Independent Media State Schema

This schema belongs only to the media store, not seed StateStore. Schema version: 4.
Plans, artifact and directory roots retain historical route/marker/identity/revision. Publication fences retain source/plan/config/restore baselines.

## SQLite Tables

`media_artifact_roots`

- `artifact_id`
- `descriptor_json`

`media_artifact_sources`

- `artifact_id`
- `source_id`

`media_artifacts`

- `id`
- `path`
- `profile`
- `kind`
- `owned`
- `status`
- `receipt_json`
- `created`

`media_commands`

- `id`
- `coalesce_key`
- `action`
- `payload_json`
- `config_source`
- `config_revision`
- `epoch`
- `modes_json`
- `status`
- `created`
- `claimed`
- `claim_token`
- `result_json`

`media_control`

- `id`
- `epoch`
- `schema_version`

`media_directory_roots`

- `path`
- `descriptor_json`

`media_events`

- `id`
- `source_id`
- `event`
- `created`
- `payload_json`

`media_import_jobs`

- `source_id`
- `revision`
- `status`
- `mapping_json`
- `target`
- `error`
- `updated`

`media_inventory_stage`

- `run_id`
- `path`
- `fingerprint`

`media_migrations`

- `export_digest`
- `imported_at`
- `counts_json`

`media_owned_directories`

- `path`
- `profile`
- `identity`

`media_output_exclusions`

- `path`

Historical output parents remain excluded before traversal after route/config changes.

`media_plan_routes`

- `source_id`
- `revision`
- `descriptor_json`

`media_provider_state`

- `provider`
- `next_request`
- `status`

`media_publication_fences`

- `artifact_id`
- `payload_json`

`media_publications`

- `artifact_id`
- `source_id`
- `temporary`
- `target`
- `receipt_json`
- `status`

`media_reconcile_actions`

- `id`
- `source_id`
- `revision`
- `manifest_json`
- `status`
- `created`
- `result_json`

`media_review_decisions`

- `source_id`
- `fingerprint`
- `mapping_json`
- `ready`
- `revision`
- `updated`

`media_runtime_status`

- `role`
- `payload_json`

`media_scan_runs`

- `id`
- `profile`
- `started`
- `completed`
- `status`
- `root_identity`
- `count`
- `error`

`media_schema`

- `version`

`media_source_files`

- `id`
- `profile`
- `path`
- `generation`
- `fingerprint`
- `first_seen`
- `last_seen`
- `stable_count`
- `missing_since`
- `missing_count`
- `status`
- `readiness`
- `probe_json`
- `original_release`

`media_subtitle_jobs`

- `id`
- `source_id`
- `generation`
- `requirement`
- `status`
- `attempts`
- `next_attempt`
- `first_attempt`
- `payload_json`
- `error`
- `claim_token`
- `plan_revision`
- `target`

`media_work_cursor`

- `profile`
- `source_id`
