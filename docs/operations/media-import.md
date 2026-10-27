# Media Library Operations

The independent media worker scans configured folders without a downloader.
`seed-agent media-scan --config config/config.yaml` submits a preview command and
returns its durable ID; `--execute` permits only the policies already enabled in
that configuration. Web actions also submit commands and show queued/completed or
failed status. Neither interface runs providers inline. `media-command-status`
reads command results; `media-status` reads a bounded media evidence page.

Run `seed-agent media-worker --config config/config.yaml` as a separate process.
It owns its own clock and exclusive worker lease; the seed scheduler never enqueues,
executes or waits for media. A missing worker leaves commands visibly queued.
Set a stable `deployment.source_id` in the shared authoritative config directory.
Mount the directory read-only into the worker so atomic Web/CAS replacement is seen.

## Mixed Source Configuration (New Installations)

Use stable source IDs with one or many disjoint roots. A source directory never
sets content type; movie/TV identity and animation are confirmed from metadata or
explicit review. The production default uses Movie, TV and Animation as three
physical destinations; animated feature films share Movie.
Every physical root below needs its configured marker before use. Outputs can be
inside a broad source, because current/historical library subtrees are excluded before
recursive descent. Targets equal to/above a source and overlapping sources are invalid.

```yaml
deployment:
  source_id: example-media-deployment
media_import:
  enabled: true
  state_path: .media-import/state.db
  import_policy: preview
  subtitle_policy: preview
  reconcile_policy: preview
  profiles: []
  sources:
    - id: main-media
      root: /media/Media
      marker_value: example-source
      readiness: manual
      languages: [[zh-Hans, zh-Hant, zh]]
  destinations:
    library_root: /media/Library
    movies:
      root: /media/Library/Movie
      marker_value: example-movies
    tv:
      root: /media/Library/TV
      marker_value: example-tv
    animated_movies:
      root: /media/Library/Movie
      marker_value: example-movies
    animated_tv:
      root: /media/Library/Animation
      marker_value: example-animation
```

The explicit `animated_movies` alias must have the same marker/title/locale policy
as `movies`; omitting it also defaults animated films to Movie. Cross-content-type or
ancestor/descendant aliases are rejected. `library_root` excludes the entire output
parent, including unknown/manual subfolders, and persists after configuration changes.
Optionally use a separate animated-film destination, or an `animation` base with
Movies/TV subdirectories. Do not combine that base with separate animated destinations. Animated
films use movie APIs/naming; animated series use TV APIs/naming. Japanese language or
country does not establish animation. Ambiguous type/genre/numbering requires Chinese
UI review; animation classification and download completion are separate inputs.

Existing profiles remain supported using the legacy example below. To migrate,
stop/drain the old writer, export/import to a new independent state file with the old
profile configuration, then configure mixed source IDs equal to their preserved old
profile names and the same physical source roots. Verify receipts/counts before
starting the new worker. Keep the original database/audit. Schema 3 local checkpoints
require this explicit export/import to a new schema 4 file; initialization never
silently upgrades them. Existing imported output routes remain historical until an
explicit reviewed repair creates verified new links before retiring old owned assets.

## Legacy Profile Configuration

Private host/container paths and marker contents belong in ignored runtime config.
The following paths and identities are generic examples, not deployed mounts:

```yaml
deployment:
  source_id: example-media-deployment
media_import:
  state_path: .media-import/state.db
  enabled: true
  interval_seconds: 1800
  import_policy: preview
  subtitle_policy: preview
  reconcile_policy: preview
  tmdb_secret_ref: local/secrets/media-tmdb.json
  opensubtitles_secret_ref: local/secrets/media-subtitles.json
  profiles:
    - name: tv
      source_root: /data/completed/tv
      target_root: /data/library/tv
      marker: .media-volume
      marker_value: example-completed-volume
      target_marker_value: example-library-volume
      media_type: tv
      readiness: manual
      min_age_seconds: 60
      languages: [[zh-Hans, zh-Hant]]
      max_subtitles: 3
      grace_seconds: 86400
      missing_scans: 2
```

Use a separate profile/target root for movies or anime. Sources and all targets must
be disjoint; symlink roots/ancestors are rejected. Place the configured marker file
in each actual mounted root. Marker text and root inode must remain consistent;
replacement requires investigation rather than automatically trusting a new mount.
No scan command creates markers or assumes a folder named `completed` is ready.

TMDB secret JSON contains `token` (API read bearer token). OpenSubtitles secret JSON
requires `api_key`; `username` and `password` are optional account credentials. Create a registered API consumer and use
your own credentials. Keep these files under ignored `local/secrets/`, with owner-only
permissions. OpenSubtitles requires a valid application User-Agent and API key. API-key-only anonymous
search/download has a small daily allowance; an account can increase it. A quota
response is not evidence that an account password is required;
account/quota/corpus acceptance is separate. Chinese script tags map explicitly to
the provider country codes; generic Chinese never proves either script. The integrated Subliminal adapter sends
its application/version User-Agent. Missing credentials are visible and never block
video import. Provider failures preserve existing subtitle coverage.

## Downloader Publication Contract

For any downloader, configure unfinished content outside the scanned source. Publish
completed content to the final source root only after writing/moving/checking finishes.
Configure category routing and verify both single-file and multi-file torrents, magnets
with delayed metadata, restart and moving/checking behavior. Use a bounded quiet period
and inspect actual source content before acknowledging the completed-folder contract.
Then set `readiness: completed_folder` and `completed_contract_acknowledged: true`.
These settings are an operator assertion, not an inferred downloader capability.

For in-place downloads, leave `readiness: manual`. Stable size, old mtime and readable
duration are insufficient for paused/preallocated downloads. The UI's explicit ready
confirmation is required. This importer never relocates existing download tasks or
changes downloader-global preferences. Unsupported clients require manual temporary/final
configuration; do not acknowledge the publication contract until verified.

Optional qB per-task routing for newly managed media tasks:

```yaml
download_client:
  # Retain the existing type, categories, pools and credentials.
  enqueue_paths:
    tv:
      completed: /downloads/completed/tv
      incomplete: /downloads/incomplete/tv
```

These are qB namespace paths; explicitly map them to importer container/host views.
Do not pass importer paths blindly. Configured categories must exist; Transmission
rejects this optional capability rather than dropping it. qB Web API >= 2.8.4 is
checked before add. Only configured categories get per-task `savepath`, `downloadPath`,
`useDownloadPath=true`, `autoTMM=false`; other tasks retain their existing inheritance.
After successful enqueue, inspect actual hash, save/download paths and AutoTMM. Delayed
metadata or conflicting acceptance is reported as `review_required` on the successful
enqueue receipt; do not repeatedly add the task to repair its paths. HTTP success alone
is not acceptance. No real qB settings changes are part of local fixture validation.

## Mounts And Hardlinks

Mount one common filesystem parent into the container where practical. Similar path
prefixes do not establish hardlink compatibility. On an authorized scratch fixture in
the actual source/target mounts, create a small file, hardlink it, compare device/inode,
then remove only the scratch names. EXDEV is a blocking error; there is no copy/symlink
video fallback. Do not chmod/chown through a hardlink because source inode metadata
would also change. The image packages ffprobe/ffmpeg and libmediainfo.

## Review, Repair And Source Removal

Start all three policies in preview. Scan twice, inspect volume health, original release,
completion evidence, original/Chinese metadata aliases, IDs, season/episode, duration,
edition and planned path. Save corrected identity/readiness in a source detail panel.
A series correction previews the exact file set and preserves individual season/episode
mapping; a changed file set invalidates apply. Saved decisions are consumed next scan.
Switch only accepted policies to execute. New playable links are verified before old
owned artifacts retire; failed repairs preserve prior output. Modified sidecars require
review and are never overwritten. Work-safe subtitle candidates requiring version
preview have an explicit confirmation button; identity/version mismatches cannot be
confirmed into automatic publication. Missing targets require explicit repair.

Plex naming defaults to original metadata title/year, `Season 01` and `S01E01`; movies
have independent title/year folders. Explicit editions use Plex edition syntax, whose
native support depends on Plex entitlement/server version. Runtime differences alone
never name a cut. Unknown editions/absolute numbering/collisions remain review-required.
No full Jellyfin/Emby compatibility is claimed for edition/sidecar semantics.

Source roots are authoritative: removing any source may eventually remove its owned
library video, subtitles and per-file artwork after healthy missing observations/grace.
The importer never deletes the source itself. Other episodes/manual files/shared outputs
remain protected. Cleanup unlinks exact receipt paths, then removes only empty owned
directories. It never recursively deletes a show/movie folder. Modified/replaced targets,
unknown legacy files, mount failures, partial scans and large disappearance batches do
not grant deletion authority. UI previews are persisted with per-artifact outcomes.
Interrupted cleanup and video publication resume from receipts; partial unverifiable
payloads remain explicit recovery conflicts with exact temporary paths, without blocking
other safe profile work. Keep state/audit and backup receipts; never rebuild ownership
from directory names after database loss.

## Separate Acceptance Gates

Before live rollout, independently accept actual mount hardlinks, real TMDB matching,
OpenSubtitles login/quota and Chinese corpus, qB path publication, server recognition,
and fresh client playback with multiple subtitle choices. Hash/release compatibility
is evidence, not full audio timing verification. No deployment, historical migration,
server refresh or source cleanup is implied by local tests.

## Independent State, Commands And Cutover

Explicitly initialize media state with `media-state-init`; missing/corrupt media state
never grants cleanup authority or blocks seed. Store it on machine-local appdata,
not SMB/NFS. Seed and media backups/restores use separate databases and locks.

For migration, stop and drain the old media writer first, export its media tables
with `media-state-export --source OLD_DB --output SNAPSHOT --execute`, preview and
execute `media-state-import --source SNAPSHOT --execute`, verify counts/receipts and
then start exactly one new worker. The export takes the old media lease, but that
lease only covers export, so it does not replace stopping the legacy service. Retain
old DB/audit and backup. Do not run legacy/new writers concurrently or infer ownership
from a directory listing. Restore rotates an epoch and supersedes queued/running
commands; stale responses cannot publish. Interrupted manual commands require receipt
inspection and explicit resubmission rather than automatic replay.

Commands pin deployment identity, effective config revision, policies, restore epoch
and relevant source/plan baseline. Identical pending commands coalesce only within
the same requested mode; the queue caps at 100 pending commands and bodies at 32KB.
Current restrictions revoke stale work. Each scan bounds inventory count/time,
stages observations in 250-row transactions and advances absence only on a complete
generation. Enrichment runs in configured batches with a persistent round-robin cursor.
The Web read model pages sources and includes only related artifacts/jobs.

Daily download allowance is separate from request pacing. A link request reserves
budget before network work. Remaining/reset evidence is persisted even if payload
retrieval later fails; remaining zero pauses the provider across workers/restarts.
Service reset timestamps/durations take precedence; missing evidence means a
conservative 24-hour wait with one probe. Restore cannot refund spent allowance.
Daily quota waiting never expires through the general retry horizon. Each file gets
one new compatible subtitle per cycle before subsequent alternatives. Anonymous and
account allowances may differ; 100/day is not assumed without provider evidence.

The R2 worker/queue slice is locally implemented; container supervision/health/mount
verification (R3), remote posters, final independent review and production acceptance
remain outstanding. The user has authorized a scoped feature release, controlled
DockerMan deployment and full real movie/TV organization after those gates. Tests
alone do not establish production library coverage or client playback acceptance.


## Destination Faults And Mixed-State Maintenance

`media-state-export` and `media-state-import` are legacy-profile migration commands;
they reject a mixed-source configuration explicitly. Use `media-state-backup --output`
and `media-state-restore --source` for a mixed-source schema4 database. Restore previews
by default; `--execute` replaces only verified independent media state, rotates its
epoch and supersedes old commands. It does not grant ownership of new filesystem data.

Target marker/inode/symlink/outage failures preserve directory and artifact receipts.
A replaced inode at the same path cannot be silently relearned on retry; historical
root authority remains binding. Paginated media status exposes bounded latest root/
directory conflicts. Restoring the original marker/root identity clears root blocking.
Healthy source/route work continues while an unavailable destination stays blocked.
Subtitle source/historical-target health is checked before provider requests/payloads;
transient mount failures use due blocked states rather than permanent provider failure.
Ordinary source-generation, plan, payload/version and receipt mismatches still reject.

### Multiple Subtitle Providers

Use `media_import.subtitle_providers` as an ordered list, for example:

```yaml
subtitle_providers:
  - name: opensubtitlescom
    secret_ref: local/secrets/media-subtitles.json
  - name: assrt
    secret_ref: local/secrets/media-assrt.json
  - name: subdl
    secret_ref: local/secrets/media-subdl.json
```

Keep credential JSON ignored: OpenSubtitles/SubDL use `api_key`; ASSRT uses `token`.
No arbitrary API host configuration is accepted. Missing/invalid credentials remain
provider-local status. Legacy `opensubtitles_secret_ref` remains a fallback when no
provider list is configured. Explicit production Chinese requirements are
`languages: [[zh-Hans, zh-Hant, zh]]`; generic `zh` does not satisfy script-only
requirements. Local known-title download evidence is separate from deployed source
matching, subtitle coverage and client playback acceptance.


### Inspect actual media duration offline

Run `uv run python scripts/probe_media.py /absolute/path/video.mkv` or
`uv run seed-agent media-probe /absolute/path/video.avi --json`. ffprobe is required
and included in the published image. MP4/MKV/AVI and extensionless local files share
the same content-based inspection; the script reports measured HH:MM:SS/seconds,
container, FPS and basic streams. It reads no configuration/database/provider and
writes no media/state. Unknown duration, timeout, invalid/no video or a replaced
source returns an explicit error and nonzero exit. A runtime difference from TMDB
can flag a version for review but cannot establish a named edition or sync.

The source panel displays coverage independently from external search/downloads.
Embedded tracks may be unusable and do not complete external discovery. For one
imported file, use its “为此文件搜索额外字幕” button, or the fenced
`media-subtitle-search` command, rather than a whole-profile refresh. Existing
provider cooldowns and paid-link reservations remain authoritative. Cached healthy
sources are not re-requested on automatic retries for another provider. Legacy
job-state backfill is finite/bounded; old missing timestamps stay unknown.
