# Config And State Field Inventory

This document is the operator-facing inventory for the current config and local
SQLite state names. The config names are user-editable YAML/API keys. The
SQLite names are durable evidence fields and should not be renamed just to match
page labels.

## Naming Rules

- Use explicit domain prefixes at the top level: `pt_*` for PT upload strategy,
  `want_*` for Want List acquisition, and `release_*` for release candidate
  matching.
- Keep nested field names stable when they already describe the local object,
  for example `category_policies`, `budget_pools`, `quality_tag_scores`, and
  `candidate_retention_days`.
- Keep SQLite lifecycle columns named `state`; they refer to persisted lifecycle
  evidence, not the config section formerly called `state`.
- Keep M-Team OpenAPI filter names such as `sources`, `mediums`, `standards`,
  `video_codecs`, and `audio_codecs` aligned with M-Team's API vocabulary.

## Config Sections

`mode`

- `mode`

`tracker_sites[]`

- `name`
- `type`
- `enabled`
- `rss_url`
- `cookie_ref`
- `api_key_ref`
- `auth_header`
- `discovery_mode`
- `api_discovery.mode`
- `api_discovery.modes`
- `api_discovery.page_number`
- `api_discovery.only_free`
- `api_discovery.discount`
- `api_discovery.sort_field`
- `api_discovery.sort_order`
- `api_discovery.page_size`
- `api_discovery.max_pages`
- `api_discovery.last_id`
- `api_discovery.keyword`
- `api_discovery.categories`
- `api_discovery.imdb`
- `api_discovery.douban`
- `api_discovery.dmm_code`
- `api_discovery.author`
- `api_discovery.sources`
- `api_discovery.mediums`
- `api_discovery.standards`
- `api_discovery.video_codecs`
- `api_discovery.audio_codecs`
- `api_discovery.teams`
- `api_discovery.processings`
- `api_discovery.countries`
- `api_discovery.labels`
- `api_discovery.labels_new`
- `api_discovery.visible`
- `api_discovery.only_fav`
- `api_discovery.offer`
- `api_discovery.hot`
- `api_discovery.upload_date_start`
- `api_discovery.upload_date_end`
- `api_discovery.dmm_field`
- `api_discovery.dmm_keyword`
- `api_discovery.min_seeders`
- `api_discovery.max_seeders`
- `api_discovery.min_leechers`
- `api_discovery.min_times_completed`

`pt_filters`

- `discounts`
- `min_left_time_minutes`
- `min_leechers`
- `target_seed_leecher_ratio`
- `allow_non_free`
- `allow_hr`
- `min_seeders`
- `max_leechers`
- `leecher_score_full_at_multiplier`
- `min_size_gb`
- `max_size_gb`
- `preferred_size_min_gb`
- `preferred_size_max_gb`
- `size_partial_max_gb`
- `max_active_downloads`
- `max_total_amount_left_gb`

`pt_scoring`

- `min_score_to_enqueue`
- `weights.discount`
- `weights.leechers`
- `weights.seeders`
- `weights.left_time`
- `weights.size`
- `weights.site_history`

`download_client`

- `type`
- `target`
- `default_category`
- `secret_ref`
- `media_category_map.movie`
- `media_category_map.tv`
- `media_category_map.anime`
- `category_policies[].name`
- `category_policies[].mode`
- `category_policies[].budget_pool`
- `category_policies[].delete_enabled`
- `category_policies[].over_budget_behavior`
- `category_policies[].tags`
- `budget_pools[].name`
- `budget_pools[].max_size_tib`

`seed_cleanup`

- `cold_after_days`
- `min_upload_delta_gb`
- `protect_hr`
- `protect_manual`
- `protect_media_library`
- `pause_before_delete_hours`
- `delete_after_no_upload_hours`
- `delete_completed_low_upload_after_hours`
- `completed_low_upload_min_ratio`
- `completed_low_upload_min_gb`

`want_decision`

- `confirmation_threshold`
- `auto_enqueue_threshold`
- `ambiguity_gap`
- `default_resolution`
- `series_search_mode`
- `preferred_languages`
- `inbox_ref`

`release_preferences`

- `site_priority`
- `max_results_per_site`
- `prefer_free`
- `reject_hr_by_default`
- `quality_tag_scores`

`want_sources`

- `telegram.enabled`
- `telegram.secret_ref`
- `wechat_bridge.enabled`
- `wechat_bridge.secret_ref`
- `douban_wanted.enabled`
- `douban_wanted.export_ref`
- `douban_wanted.user_name`
- `douban_wanted.max_pages`
- `want_lists[].provider`
- `want_lists[].id`
- `want_lists[].label`
- `want_lists[].enabled`
- `want_lists[].user_name`
- `want_lists[].watchlist_url`
- `want_lists[].export_ref`
- `want_lists[].max_pages`
- `subscription.enabled`
- `subscription.rules_ref`

`local_state`

- `candidate_retention_days`

## SQLite Tables

`candidates`

- `stable_id`
- `site`
- `title`
- `state`
- `score`
- `torrent_hash`
- `free_window_expires_at`
- `size_bytes`
- `seeders`
- `leechers`
- `discount`
- `left_time_minutes`
- `score_reasons`
- `first_seen_at`
- `updated_at`

`intents`

- `intent_id`
- `source`
- `raw_text`
- `title`
- `kind`
- `state`
- `normalized_json`
- `selected_release_id`
- `created_at`
- `updated_at`

`release_candidates`

- `intent_id`
- `release_id`
- `site`
- `title`
- `score`
- `confidence`
- `accepted`
- `confirmation_required`
- `release_json`
- `created_at`

`intent_aliases`

- `alias`
- `intent_id`
- `created_at`
- `updated_at`

`intent_source_evidence`

- `evidence_id`
- `intent_id`
- `source`
- `source_event_id`
- `source_config_id`
- `source_label`
- `requested_at`
- `raw_text`
- `metadata_json`
- `created_at`
- `updated_at`

`torrent_runtime`

- `torrent_hash`
- `paused_at`
- `uploaded_bytes`
- `downloaded_bytes`
- `upspeed_bps`
- `dlspeed_bps`
- `missing_from_qb_at`
- `missing_from_qb_reason`
- `no_upload_since_at`
- `seen_at`
- `updated_at`
