# Explicit extras and source variants: implementation contract

Status: featurette attachment, cross-source variant switching and independent completion
facts are locally implemented, integrated and independently reviewed. Controlled migration,
deployment and production acceptance remain outstanding. Existing repair is scoped to one source and must not
be used to switch variants.

## Identity and authority

An extra is an explicitly reviewed attachment to a confirmed parent work, never a
new film, inferred special or TMDB match. Persist its parent work identity, role,
source ID, generation, fingerprint, completion evidence and intended filename.
Only the parent's validated `Featurettes` directory is an eligible target for the
requested featurettes. A source whose role is extra must bypass ordinary matching,
`finish_link`, artwork and subtitle-job creation. Attachments and progress must
remain visible independently of primary films. File observations, ownership and
recovery still use source and destination root identities, configuration revision
and restore epoch. An extra publisher needs its own durable intent and exact owned
hardlink receipt, and must refuse occupied or changed paths. A review cannot convert
an unstable or unconfirmed source into completion evidence implicitly.

Variants belong to a confirmed work, episode range and edition. Quality or codec is
not an edition. A persisted selection identifies the chosen source generation and
fingerprint and has a monotonic revision. Unselected sources remain present and
retained, with an explicit progress category, and ordinary scan/enrichment cannot
reimport them or publish their subtitles. Original source files are never removed.
Work-level posters and extras do not become version-specific merely because a
selection changes.

## Fences and durable operations

A preview must bind both source IDs, generations and fingerprints; work, episode
and edition; current selection revision; both plans and review revisions; exact
old/new targets and owned artifact manifests; source and destination root identities;
configuration revision; and restore epoch. Execution rechecks the entire baseline
under the media filesystem lease. The worker is the only filesystem and provider
executor; read-only clients submit durable commands. Selection changes must also
fence in-flight video, subtitle and artwork publishers and recovery, including
provider responses obtained before selection changed. A stale response must not gain
publication authority. Existing publication fences do not include this selection
revision and therefore are insufficient.

For distinct target paths, persist an intent before any filesystem mutation, create
and verify the new hardlink and receipt, then atomically compare-and-swap selection
and the associated artifact state. Only after that commit may the worker retire the
exact previously owned video and version-specific subtitles, each with a durable
retirement intent and verified receipt. Unknown, modified, unowned or shared assets
remain untouched and yield a visible conflict. Do not reuse `retire_old`: it queries
artifacts attached to the same source as the new plan.

A selected variant uses a source-ID-qualified filename in the same canonical work
folder, so the new and old video paths are always distinct. The previous canonical
filename is accepted as an old receipt. Before retirement, retain a verified managed
hidden hardlink backup without a media extension on the same target root; preserve
the backup until selection and exact old-artifact retirement are durably resolved.
Quality is a display label and must not be encoded as an edition.

A recovery state machine must define and test intent creation, old-backup creation,
canonical removal, new-link publication, selection CAS, old-version retirement and
backup removal, including crashes between each filesystem mutation and its database
acknowledgement. Revalidate source and root identity as well as receipts before every
mutation. Fail closed if ownership or commit state is ambiguous. Reconcile interrupted
commands from their durable intents and receipts; do not blindly replay a command.

## Schema and migration

A schema revision must add explicit attachment, selection and switch/publication
intent state and include it in exact schema validation, backup/restore, inventory and
migration tests. Current `MediaStore` requires schema version 4 and validates an
exact signature before opening existing state. Never automatically upgrade a live
production database. A future explicit offline migration must acquire the existing
exclusive access and filesystem fences, verify the exact old schema and complete
backup, reject active work, perform transactional migration with a new restore epoch,
validate the resulting signature and provide a tested rollback/readback procedure.
Old databases cannot acquire an inferred selected source or extra attachment without
reviewed evidence. The schema 4 to 5 backend migration requires an explicit offline call; the operator
workflow and production migration are separate.

## Acceptance

Fixtures must exercise explicit six-source featurette attachments, no full-film
matching or subtitle jobs for extras, retained unselected variants, stale preview and
selection CAS, source/root/config/epoch changes, unknown and modified assets, late
publisher responses and every durable crash boundary for source-qualified distinct paths. Verify all original sources, shared posters and work extras survive. Local
fixtures are not evidence of deployed migration, real filesystem acceptance or
client playback. The requested Inland Empire featurettes and Joker 2 selection remain
unfulfilled until the complete implementation, reviewed migration, and separately
authorized production execution and client verification are complete.
