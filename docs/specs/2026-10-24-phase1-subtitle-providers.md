# Phase 1 Chinese Subtitle Providers

Status: authorized scope expansion, 2026-10-24. Supersedes the earlier decision
to defer additional providers to Phase 2. This is a planned contract, not evidence
that additional providers have been implemented or accepted in production.

## Provider Selection And Evidence

- Keep OpenSubtitles.com. Its existing allowance, credential and payload evidence
  remains independent from evidence for other websites.
- Prioritize ASSRT (the site labels itself the unofficial/alternative Shooter site)
  for Chinese subtitle discovery. It has a documented token-authenticated API;
  the inspected Bazarr adapter reads `/user/quota` before name search/detail/download.
  Runtime pacing must honor actual token/IP quota rather than assume unlimited use.
- Add SubDL as another configurable API provider. Official search supports IMDb/TMDB,
  movie/TV, season/episode and language constraints, and requires an account API key.
  Verify current v1/v2 support before selecting an endpoint. Official documentation
  lists separate request and download quotas; account/IP limits must remain distinct.
- Evaluate traditional Shooter as an optional hash-based supplement, separate from
  ASSRT. The inspected Bazarr code contains a legacy Shooter adapter, but the project's
  installed upstream Subliminal 2.8 package does not expose that provider module.
  Do not assume an import or copied adapter establishes compatibility or availability.
- Zimuku/SubHD and other page-driven sources remain candidates for later expansion
  unless their supported integration and maintenance cost are separately accepted.
  A CAPTCHA/login page is not a subtitle payload; no bypass automation is in scope.

Current bounded public-endpoint checks from the development host:

- ASSRT documentation: HTTP 200. Unauthenticated `/v1/user/quota`: structured HTTP
  400 JSON. This proves reachability, not authenticated search or download acceptance.
- Traditional Shooter dummy-hash query: HTTP 200 with a one-byte no-result response;
  no real candidate/payload or Chinese-corpus acceptance has been demonstrated.
- SubDL official API documentation is accessible. No account-specific search,
  allowance or payload acceptance has been performed without its API key.

ASSRT Token and SubDL API key are separate from OpenSubtitles credentials. Store
them in ignored owner-only secret files; do not require account passwords for their
documented token/key interfaces. Missing credentials disable that provider visibly,
without blocking video import or another healthy provider. Real provider acceptance
requires configured credentials; request only these missing items when needed.

## Shared Scheduling And Publication Contract

1. Inventory actual simplified/traditional Chinese coverage independently from provider
   job status. First cover files lacking a suitable subtitle; alternatives follow.
2. Use configurable provider priorities/capabilities, not a hardcoded promise that one
   website always has better subtitles. Aggregate normalized evidence and/or fall back
   when a provider is unavailable, exhausted or has no safe match. A failure must not
   prevent another provider from making bounded progress.
3. Keep per-provider authentication, pacing, daily allowance, reset time, retry state
   and download-link reservations persistent. Token/IP/account scopes must be explicit.
   One provider's exhaustion cannot place all providers in a shared cooldown. Do not
   rotate credentials/IPs to evade service limits.
4. Bound provider fan-out, search/detail requests and archive retrieval. Never hold a
   SQLite transaction during provider calls. Multi-source search is not permission
   for unbounded payload downloads; retain at most one attempted new remote payload
   per source file per cycle, across providers, before moving to the next missing file.
5. Normalize provider-qualified candidate IDs, Chinese script, full/forced/SDH,
   identity, episode coverage, release/edition, FPS, rating/popularity and provenance.
   Unknown evidence stays unknown. Title-only ASSRT results and season packs cannot
   silently become exact identity/episode matches. Hash/version evidence outranks
   popularity; unsupported archive members remain explicit unsupported/review cases.
6. Deduplicate candidate identities and verified content digests across providers.
   Distinguish attempted/seen candidates from actual unique published choices; a
   duplicate cannot occupy `max_subtitles` or cause another paid request in that cycle.
7. Reuse existing bounded payload validation, exact ownership receipts, source/route/
   config/claim/restore fencing and cleanup. No provider-specific filesystem writer.
   Metadata `movie`/`tv` identity remains correct under animation destination routing.
8. The UI exposes provider, credential/availability/quota status, next eligible time,
   matching evidence and subtitle choices. Attribute ASSRT with its required site link.
   Aggregate coverage must not hide partial provider failures.

## Acceptance And Phase Boundary

### Chinese Script Fallback

The user's requirement is Chinese subtitles, without a script-exclusive restriction.
Support generic `zh` as an explicit language requirement member and `.zh` filename
tag. For new production Chinese-fallback configuration, prefer verified `zh-Hans`,
then `zh-Hant`, then provider-verified generic Chinese `zh`. Show script as unknown
for the last case; never relabel it as simplified/traditional or infer script from
country, bilingual labels or a small text sample. This is an explicit config/policy
choice, not a silent change to existing profiles requiring only Hans/Hant.

An exact Hans-only or Hant-only requirement must not be satisfied by `zh`. A generic
Chinese candidate may satisfy a requirement explicitly containing `zh` only when
its provider language evidence confirms Chinese and normal identity/version/episode/
payload checks pass. `unknown`/`und` language, a title mentioning China, or a filename
with Chinese characters is insufficient. Expose all three distinctions in the UI;
preserve the same preference/coverage semantics for embedded/local/remote subtitles.
Test generic acceptance, script-exclusive rejection, unknown-language rejection,
preference and cross-provider dedup. No payload is downloaded merely to guess script.

Implement the multi-provider orchestration and ASSRT/SubDL adapters in Phase 1,
with independent tests for one exhausted provider plus another successful provider,
restart/restore, rate/daily limits, cross-provider duplicates, single payload attempt,
Chinese script ambiguity, packs, late responses and manual-asset protection.

Configured additional providers require real authenticated search and at least one
matching Chinese payload acceptance from the eventual runtime. Report missing keys,
no matches and network failures separately. A provider with only fixture tests is
implemented locally, not production-accepted. Traditional Shooter becomes supported
only after real hash-match/payload validation; otherwise keep it disabled with an
explicit limitation rather than blocking the reliable API providers.

Phase 2 retains further providers, expanded archive/numbering capabilities and
subtitle synchronization improvements. No auto-translation, subscription purchase,
subtitle upload or account creation is authorized by this scope expansion.

References:

- [ASSRT API documentation](https://assrt.net/api/doc)
- [SubDL API documentation](https://subdl.com/api-doc)
- [Bazarr ASSRT adapter](https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal_patch/providers/assrt.py)
- [Bazarr legacy Shooter adapter](https://github.com/morpheus65535/bazarr/blob/master/custom_libs/subliminal/providers/shooter.py)

Use upstream workflow/schema ideas with license review; do not copy GPL provider
implementation into this MIT repository.
