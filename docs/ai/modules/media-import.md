# Media Import Module

## Ownership And Entry Points

`src/seed_agent/media_import/` owns directory-authoritative library synchronization.
It shares Web, CLI and the image with acquisition. MediaStore owns a separate SQLite
database; seed initialization never installs media tables or takes media locks. Media
connections never open and close extra database or SHM descriptors, which would
release process-wide POSIX locks held by another SQLite connection. Initialization
uses the exclusive access fence and exclusive first creation; existing files use
no-follow metadata operations. Sidecar disappearance alone is tolerated. Failed
worker observations retain optional SQLite extended error codes without messages.

The dedicated CLI worker may explicitly opt into `--sqlite-io-diagnostics` to
capture rare SQLite I/O failures. This audited single-threaded startup owns the
process-wide LOG slot; SQLite has no public getter to discover an existing owner.
Other/embedded entrypoints must not enable it. The optional native shim is built
and scratch-tested as UID 1000 for both image architectures, with no added runtime
compiler dependency. ABI/provider/source/atomic/platform/startup failures disable
diagnostics without preventing business startup. Registered native/provider references
remain pinned until process exit; no online reconfiguration/unload/shutdown occurs.
The callback saves only bounded numeric fields and exact configured target classes,
never raw SQLite messages, paths or SQL. Existing connection boundaries record fixed
phases, process session, native thread and sequence windows without extra database
connections or file descriptors. One bounded consumer retains other-thread events;
drops, evictions, read failures, conflicting errno or unknown targets prevent causal
association. Diagnostic failures preserve original commit/rollback/close behavior
and exceptions. Capturing an errno is evidence, not a repair or readiness decision.

Media operations do not construct a downloader to scan, identify, import or reconcile files.
`media-scan` and `/api/media*` submit persistent commands; `media-worker` alone
executes scans/providers on its independent clock. `media-status` reads paginated state. The Web Media Library page uses Chinese UI labels;
filenames default to metadata original titles. Existing torrent cleanup authority
and tracker/RSS workflows remain separate.

## Inventory And Readiness

`routing.py`/`sources.py` implement the mixed-source contract in
`docs/specs/2026-10-24-media-source-routing.md`. New configuration uses independent
`sources` and `destinations`; legacy profiles remain an explicit compatibility adapter.
One source can route confirmed movie/TV and animation/non-animation work independently.
Animation base destinations render separate Movies and TV subtrees. All configured and
historically recorded output roots are excluded before source traversal. Each mixed
source may also declare `legacy_output_roots`, a bounded list of exact absolute
legacy output paths in the same container coordinates as `root`. These are excluded
before descent even when absent, without excluding nested directories with matching
basenames. They remain config authority across fresh/restored MediaStore state and
are persisted into historical output exclusions on scan. The effective config
revision fences changes just like source/destination changes; a configured exclusion
equal to or above its source is rejected. Overlapping
sources and destinations equal to/above a source are rejected. A historical output
ancestor of a new source blocks observation rather than publishing an empty scan.

Legacy profiles retain disjoint absolute source/target roots and explicit markers.
Health checks reject symlink ancestors, changed root identity and missing/mismatched
markers. A complete traversal is published transactionally; failed/incomplete scans
never advance missing counters. Files retain full-history generations, fingerprints
(device, inode, size, nanosecond mtime), release names and scan observations.
A unique unchanged fingerprint may reassociate a renamed file; ambiguity is protected.

Two complete observations and minimum age are required. `completed_folder` additionally
requires operator acknowledgement of a downloader-independent publication contract;
`manual` remains `completion_unverified` until explicit operator ready confirmation.
Stability and ffprobe alone never establish completion. ffprobe is bounded and measures
video duration/FPS/embedded language evidence. Source replacement invalidates choices;
active predecessor artifacts force review. Unchanged imports do not rematch/relink.
Missing targets require explicit repair instead of an automatic recreation loop.

## Identity And Publication

Mixed-source TMDB matching searches both movie/TV identities using bounded separate
filename, parent, Chinese and English hints. Title numbers remain part of the name;
year extraction precedes technical release fields. Latin accent/punctuation
normalization does not erase non-Latin marks. Official alternative titles and
translations can confirm an alias; conflicting bilingual candidates require unique
provider corroboration of multiple hints, never fuzzy similarity. Explicit `SxxEyy`
excludes movie candidates but still requires exact provider season/episode evidence.
Season-year fallback requires the provider's season air date and retains the series
premiere year for its library root. Absent episode syntax does not establish a film.
Numbered extras and explicit ancillary paths remain review-only, not primary films
or inferred specials. Matching has a 120-second/32-request per-file budget and a
bounded five-minute response cache; see the identity repair research note.
One exact identity and resolved TV episode metadata are required; animation uses explicit genre evidence
(including non-Japanese animation), never language/country. Missing genre/type/numbering
or cross-type ambiguity remains review-required. Manual animation classification is
persisted separately from completion confirmation. Legacy exact title/year matching
is retained. Ambiguity, missing credentials,
absolute anime numbering and uncertain specials require review. Manual mappings,
season/episode ranges, editions and readiness decisions persist with fingerprints
and revisions. Series previews bind the exact file set, mapping/revision/target, pending decision
revision and naming profile configuration; any stale baseline rejects the entire apply.
Original/localized aliases, IMDb/TMDB/collection IDs and reference duration are stored
independently from Plex naming. Runtime differences generate uncertainty evidence;
only explicit release tokens or operator evidence name an edition.

Plex TV uses one title/year/TMDB root, `Season NN`, and `SxxEyy[-Ezz]`. Movies have
independent title/year/edition folders. No copy/symlink video fallback, replacement,
permission change, source rename or source deletion is permitted. Descriptor-relative
exclusive hardlinks are verified by receipts. Existing equivalent outputs may satisfy
an import without acquiring deletion authority.

The process-shared media flock serializes filesystem writers. `media_publications`
records exact temporary/final paths and receipts before publication, including the
first temporary video hardlink. Recovery completes publications and removes recorded
active-stage temporaries. Partial subtitle payloads with unverifiable content become
explicit recovery conflicts, retaining their exact manifest; other inventory/import
work continues. No broad glob is used to claim ownership. Repair validates the new
active receipt, source fingerprint, root health and revision on every recovery before
retiring old owned artifacts. Retirement persists intent before unlink. Modified old
assets remain conflicts. Old incompatible sidecars are retired and re-searched.

## Subtitles And Local Artwork

`docs/specs/2026-10-24-phase1-subtitle-providers.md` defines Phase 1 provider scope.
`subtitle_providers` is an ordered list of at most three unique fixed provider names
(`opensubtitlescom`, `assrt`, `subdl`), each with `enabled` and `secret_ref`. The
legacy `opensubtitles_secret_ref` applies only when this list is absent/empty.
Adapters share bounded orchestration while retaining independent auth/pacing/quota
state. Missing credentials or an exhausted provider do not disable healthy providers.
SubDL account evidence supplies search/download allowances and reset times; ASSRT's
minute quota determines its actual pacing. Never infer a daily ASSRT download budget.
Candidate IDs are namespaced; payload digests deduplicate across providers and language
jobs. Only pre-payload failures may fall back within a cycle; every actual remote
payload attempt, including duplicates or invalid bytes, consumes that file's turn.
Invalid payload candidates cool down before another candidate is tried next cycle.

`subtitles/` owns provider protocol, inventory, validation, matching and durable jobs.
Subliminal 2.8.0 imports on Python 3.14 and supplies the OpenSubtitles.com search
adapter. Its subtitle response subclass preserves optional `ratings`/`from_trusted`;
missing values remain unknown, and download counts never override identity/version
conflicts. `zh-Hans`/`zh-Hant` explicitly map to provider `zh-cn`/`zh-tw` and back.
The real OpenSubtitles hash uses exactly two 64 KiB reads with fingerprint checks.

One Chinese requirement defaults to simplified Chinese with traditional fallback;
English is opt-in. Explicit `zh` permits provider-confirmed Chinese with unspecified
script; production uses `[[zh-Hans, zh-Hant, zh]]` in that preference order. Existing
script-only profiles stay strict. Unknown language cannot satisfy Chinese. Generic
Chinese is displayed as Chinese with unspecified script and uses `.zh` filenames.
Full/forced/SDH remain distinct; generic Chinese is not evidence of either script. Existing embedded/sidecar coverage does not stop bounded
periodic alternative discovery. Matching requires exact work and episode identity;
explicit edition/FPS conflicts reject. Automatic publication requires hash or exact
original-release evidence; other candidates remain review-required.

Jobs retain coverage, candidate evidence, provider IDs/digests, attempts, next time,
source generation, target, plan revision and claim token. Refresh cannot steal a live
claim. Publication and result completion both fence tokens/revisions; a late response
cannot overwrite repaired/cancelled work. Profile filters apply to scanning and jobs. Operator selection can confirm a work-safe
but unverified release candidate; rejected identity/version conflicts cannot be selected.
HTTP pacing includes each adapter criterion, login, link and payload request.
429 Retry-After is rate_limited; daily_quota persists remaining/reset evidence and
pre-link token reservations separately. Payload failure never refunds link allowance;
unknown outcomes pause for a conservative 24 hours. One probe resumes after reset.
Restore cannot refund post-snapshot downloads. Daily/rate waits do not become permanent
failures through the generic retry horizon. One new candidate per file/cycle gives
missing coverage priority before alternatives. Preview never downloads payloads or writes sidecars.

Payloads are streamed/bounded, decoded/validated, checked for impossible timestamps
and HTML, and safely inspected for ZIP count/size/path/encryption/symlink hazards.
Files publish exclusively beside library videos, with digest receipts; source bytes
are not rewritten or muxed. Original source sidecars and matching per-file JPEG/PNG
artwork may be copied under subtitle execute policy and are independently owned.
`artwork.py` implements bounded official TMDB posters and the worker invokes it
with the configured work batch limit. Persisted paginated poster statuses are exposed
through the media snapshot without provider requests in Web handlers. JPEG/PNG and negotiated WebP input is verified
by ffprobe; WebP becomes bounded JPEG via ffmpeg. The same receipt/intents/fences govern
publication/recovery. Shared series poster references include all supporting sources;
only the last eligible source permits removal. Manual/changed artwork is protected.
Subtitle end time never proves synchronization. Multiple-choice filenames use a stable
provider-ID label before language/kind suffixes; real client visibility remains a gate.

## Reconciliation And Recovery

Source roots are authoritative. Default cleanup requires two healthy complete missing
observations and 24 hours, then an exact persisted owned-artifact manifest. Preview
is the default. An independently enabled reconcile policy executes routine eligible
cleanup; large disappearance batches remain review-only. Source return/rename, root
replacement/outage, active supporting sources and modified receipts preserve outputs.
Many-to-many references protect shared outputs until every supporting source passes
its own absence/health/grace gates. Jobs are fenced before unlink; each target receipt
is revalidated. Only exact owned files and verified empty owned directories are removed.
Targets, user files, unknown pre-existing assets and historical unowned files are never
adopted for deletion. Tombstones/events survive removal. Media backup/restore validates the exact independent MediaStore schema. Restore takes
only media filesystem/access locks, rotates the persistent restore epoch and invalidates
all restored network claim tokens. Every filesystem publication rechecks the epoch,
preventing in-flight responses from writing into the restored timeline. Seed backup
preserves an exact legacy combined schema without initializing or migrating media. DB failure cannot establish
new cleanup authority.

## Verification And Boundaries

- `uv run pytest -q tests/test_media_import.py tests/test_media_subtitles.py tests/test_media_runtime.py`
- `uv run pytest -q tests/test_qbittorrent.py tests/test_maintenance.py tests/test_state_schema_inventory.py`
- `scripts/check_media_import_container.py` uses only generated temporary media, real
  container ffprobe, hardlink inode receipts, subtitles and exact removal assertions.
- Full pytest, Ruff, diff whitespace and public-repository checks remain release gates.

See `docs/operations/media-import.md` for configuration, mount probes and downloader setup.
Fixtures and image checks do not establish real-provider corpus, deployed qB path behavior,
production mount compatibility, server metadata recognition or client playback/subtitle sync.
Historical migration, remote artwork, server refresh, ASR, upgrades and deployment are separate.

## Configuration And State Boundary (R0.1/R1)

One YAML document is authoritative; role loaders validate common deployment identity
and their own sections. Invalid media configuration does not prevent valid seed
execution. Full/effective revisions use public configuration structure and credential
references, never credential file contents. Each publication revalidates its initial
configuration revision, policy and restore epoch. A preview command cannot gain
execution permission after a reload. Source identity is explicit for worker deployment.

Media state requires explicit `media-state-init`. `media-state-export` and
`media-state-import` preview by default; executing an import uses a consistent bounded
legacy snapshot, validates identities/paths/owned receipts, rolls back interrupted
transactions and records the export digest for idempotence. Original state/audit
history is retained. `media-state-backup` and `media-state-restore` are independent of
seed maintenance. See `docs/operations/media-state-schema.md` for the exact inventory.

The seed scheduler now emits `worker_required` and never invokes media execution.
The independent worker now owns scans/providers; Web/CLI queue bounded, coalesced
commands pinned to policy, source/plan baseline, config revision and restore epoch.
Restart interrupts manual commands; restore supersedes them. Neither path replays
uncertain completed side effects. Inventory count/time and enrichment batches are
bounded; observations stage in 250-row transactions before authoritative completion.
This intermediate R2 checkpoint still requires R3 container health/mount verification. Applied media observations include source/full/effective revision,
application/image/schema and epoch; role health/UI integration follows with the worker.

OpenSubtitles anonymous search and payload download work with API key only; username
and password are optional. A bounded real key-only acceptance saved one validated
SRT under ignored local evidence. Trusted API redirects are capped and each hop is
paced; credentials cannot follow a redirect to another domain. Provider quota errors
remain quota, not a request for mandatory account credentials.


## Historical Route Authority (Schema 4)

`media_plan_routes`, `media_artifact_roots` and `media_directory_roots` record target
root, marker, inode identity, route/subtree and configuration revision. Cleanup and
repair validate these historical descriptors instead of inferring roots from today's
source route. Imported legacy histories receive verified descriptors without changing
source IDs/generations. Existing imported outputs keep their old route until explicit
repair verifies new outputs before retiring exact owned old receipts.

Publication fences bind source generation/fingerprint, work plan, review revision,
configuration and restore epoch. A late interrupted video/subtitle/poster intent cannot
recover into a changed route or override a newer review. Source health is independent
from destination availability; one offline target blocks that publication without
making the source absent or blocking other routes. UI pages expose type, animation
evidence, historical route and manual classification/target previews.

Mixed routing is locally implemented and awaiting independent checkpoint review;
R3 roles/mount-health and Phase1 multi-provider acceptance remain outstanding.


Destination validation failures are scoped domain health states. `prune_dirs` retains
unsafe historical roots/directories and records bounded latest visible conflicts,
while processing healthy roots. Same-path inode replacement never becomes a newly
trusted plan merely through retry. Validation itself remains pure for transaction
callers; health observations are persisted at application boundaries. Subtitle jobs
preflight source and historical target before provider work, retry typed temporary
mount blocks automatically, and preserve generation/version/receipt rejection.
Legacy export/import explicitly rejects mixed-source config; mixed stores use the
full independent backup/restore boundary.

## Video Priority And Subtitle Choice Budget

Queued ready decisions in execute mode process their exact source immediately through
the existing import checks, without advancing the inventory work cursor or waiting
for subtitle search. Scan commands defer enrichment. The worker drains queued
commands before automatic enrichment; idle cycles budget one poster and one subtitle
job. An already-running provider request remains bounded by its existing timeout.

The existing source/profile `max_subtitles` field is the sole choice limit, defaults
to five, and accepts 1--10. The Chinese media panel edits that field through the
existing config revision CAS. Unique managed external payloads share the cap across
languages, providers and copied local sidecars; embedded Chinese still permits
compatible alternatives. Lowering the cap preserves existing and manual files.
Per-source provider search histories retain completed results until their refresh
interval. Incomplete providers resume at their own next eligible time without
repeating healthy providers. Embedded coverage is separate from external acquisition.


### Bounded Idle Enrichment And Provider Evidence

Idle enrichment runs independently from the inventory deadline and admits one poster
and one subtitle job per quantum after queued commands drain. Subtitle coverage has
its own finite lookahead: `min(max_inventory_files, 50, 4 * limit)`. Never-attempted
jobs advance first; persisted `coverage_observed` rotates the window across worker
reconstruction. Within the window, never-attempted jobs and missing coverage receive
priority. The claimed job rechecks current coverage before publication. This is
bounded window priority, not a global per-cycle coverage sort. Existing jobs are not
reinserted on every idle poll; obsolete language requirements cannot fill the window.

Download allowance does not gate pool search. Provider-specific search quotas and
per-request pacing still apply. Download-budget failures and daily download-only
responses do not become provider-wide search cooldowns; link reservations, uncertain
outcomes, shared choice caps and payload validation remain unchanged.

Provider health separately persists the current observation, last request failure or
response, and last HTTP response. A later persistent gate observation cannot erase
the real failure origin or response status. Fixed allowlisted stage, numeric HTTP/API
code, exception class, Retry-After and numeric reset-header evidence exclude raw
messages, bodies, headers, URLs and credentials. Numeric reset headers retain their
original value without assuming a unit. Absent evidence remains unknown.

Exact-release comparison removes only one recognized media/subtitle extension,
normalizes Unicode formatting and separators, and retains year, episode, edition,
source, encode and release-group tokens, including extensionless groups. This does
not authorize work-ID/FPS-only or fuzzy automatic subtitle publication.


### External Discovery State And Single-Source Commands

Subtitle payloads separately persist coverage state, managed external count/state,
logical search attempt/completion time, search outcome, adapter-returned candidate
reason counts and each provider's last completed search/next eligible check. The
legacy aggregate job status remains backward compatible; `satisfied` alone never
establishes an external download, search completion, quality or synchronization.
Gate-only observations do not advance completed-search time. Missing old timestamps
remain unknown. Reason counts cover adapter-returned candidates, not discarded raw
provider responses. Existing hash/release identity/version/episode gates remain.

Provider histories/cache are source/job-specific and fenced by the existing source,
plan, configuration and epoch path. Automatic retries visit only due providers;
completed empty/review results are cached. At most three providers contribute at
most100 each into a deterministic fair100-result output. Remaining compatible
alternatives consume the same fenced candidate cache in bounded 60-second download
turns, one actual payload attempt per source per cycle, until the shared configured
external cap. They do not shorten the provider's search refresh. OpenSubtitles file
IDs remain download locators; ASSRT fetches fresh official details under its quota.
SubDL reconstructs only API-proven canonical unsigned locators (a boolean plus its
existing opaque ID, no URL). Signed or unknown cached locators request a fresh bounded
search before a later download turn; uncertain paid links are never replayed. A
SubDL gate failure before any payload attempt does not make an account read a
post-download observation and cannot refund an exhausted reservation. Explicit single-source search
may revisit cached results but never clears real provider gates or download budgets.

`subtitle-search` commands require exact source ID/generation/fingerprint and pin
source/plan/review/config/epoch/modes through the durable command queue. They scan
nothing, enrich no other source and never mark readiness or choose a candidate.
Preview searches cannot gain payload authority. The Chinese source panel and
`media-subtitle-search` CLI submit this command through the same boundary.

A one-time, schema-free payload-version upgrade admits at most the coverage lookahead
of old imported jobs per quantum. It records an event, retains old evidence/unknown
times, makes only those legacy jobs due and never alters provider quota/retry rows.
Running/cancelled/stale-generation/obsolete-language jobs are protected. New jobs
start with the current discovery version, so the backfill is finite and restart-safe.

`probe.py` is the shared offline ffprobe implementation used by inventory, the
`media-probe` CLI and `scripts/probe_media.py`. It holds a no-follow regular-file
read descriptor, checks fstat/path identity before/after, enforces20seconds and
streaming stdout1MB/stderr64KB limits, permits only file/pipe protocols and detects
containers by content rather than suffix. Missing/invalid/nonfinite/zero duration,
no real video (including attached-picture-only audio), source replacement and
process failures are explicit unknown errors. Stored measured duration and TMDB
reference duration remain distinct; a >600second difference is a UI warning,
never an automatic edition name or subtitle synchronization proof.
