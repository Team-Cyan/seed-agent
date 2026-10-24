# Mixed Source Routing Implementation Slices

Contract: `docs/specs/2026-10-24-media-source-routing.md`. This is newly authorized
Phase 1 scope. Do not publish the old fixed-profile-only implementation. Existing
R0.1/R1 reviewed state and R2 queue/quota protections remain prerequisites.

## S1: Configuration And Traversal

Add one/many stable named source roots and separate movie/TV/animated-movie/animated-TV
destinations. Offer one animation base as shorthand for distinct Movies and TV roots.
Sources own readiness/markers/exclusions; destinations own marker/root health and
naming. Content type and animation are independent values. Retain legacy profiles
through an explicit adapter; never silently reinterpret their IDs or stored mappings.

Validate all source pairs for overlap. Targets may be strict descendants of sources,
but may not equal/contain any source. Canonical exclusions cover every configured
output root before descent, including outputs belonging to another source. Reject
symlink ancestors and preserve incomplete-source exclusions. Scan source health
separately from destination availability so an offline library cannot imply absence.

## S2: Plans, Historical Destinations And Repair

Introduce a route resolver and small effective-profile adapter at existing publication
boundaries rather than copy the engine per destination. Persist route/content type,
classification, target root/marker/identity and effective revision with plans and
publication receipts. Historical artifact root information is authoritative for
cleanup/recovery; never select deletion roots from the current source destination.

Legacy import preserves generations, decisions, artifact IDs and references while
verifying and recording the legacy destination root. Unknown legacy assets retain no
deletion authority. Changing a route/root requires explicit preview and stale-safe
repair, verified new outputs before old owned receipts retire, and independent shared
support checks. Late provider responses, commands and recovery intents must reject
changed source/plan/route/config/restore epochs.

## S3: Identity, Classification And Review

Filename/release-folder hints select bounded TMDB movie/TV searches; neither a folder
name nor absent episode syntax establishes a type. Confirm one exact work and resolved
numbering before auto-import. Animation derives from confirmed metadata genre evidence
or explicit persisted operator override, never language/country. Animated films use
movie APIs/naming; animated series use TV APIs/naming.

Expose identity/type, animation evidence, route, planned destination and uncertainty in
the Chinese review UI. Manual classification is separate from completion confirmation.
Preserve original titles, seasons/episodes, edition uncertainty and no-guess review.

## S4: Freeze And Acceptance

Test one mixed source with movie/series/animated film/animated series, misleading parent
names, multiple disjoint sources/shared destinations, nested output exclusion before
and after restart/config changes, unknown/ambiguous mapping, manual override persistence,
route repair, EXDEV/offline roots, shared posters, and late subtitle/poster fencing.
Retain seed/worker/queue/quota/restore regression. Freeze a reviewable routing checkpoint
before R3 container/mount/health acceptance and the already-authorized scoped release.

Source paths/bytes and unknown/manual assets remain preserved. No production migration
or completion claim follows merely from local routing tests. Production acceptance
must count source/import/review/conflict, destination, poster and subtitle coverage for
the whole configured movie/TV corpus under actual provider allowance.
