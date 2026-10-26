# Media Identity Repair

Date: 2026-10-26; validation continued 2026-10-27. Scope: mixed-source metadata recognition, independently of source
completion, output publication and subtitle matching. Research does not authorize
readiness or source mutation. Private corpus paths and receipts stay in ignored
runtime evidence.

## Observed Causes

The first whole-library pass identified 138 of 272 completion-correlated pending
files, leaving 134 unresolved. Six numbered `Extras` files in the identified set
were later excluded from primary-feature publication; the original approved set
therefore contains 132 eligible identities, not 138 safe feature imports.

- Bracketed Chinese and English release titles were concatenated into one query.
  Filename hints prevented useful parent or language-specific fallbacks.
- The first year-like number truncated titles such as `Detective Chinatown 1900`
  and `Cold War 1994` before their actual release year.
- Latin accents were significant despite otherwise identical provider titles.
- Matching did not consult provider-confirmed alternatives or translated names.
- Known movie years were not passed to search, allowing common titles to hide the
  intended candidate beyond the bounded first results. TV season years cannot use
  the same series-premiere-year search filter.
- Episode filenames could remain ambiguous against namesake films despite explicit
  `SxxEyy`; season release years were compared only with series premiere years.
- Numbered extras could become primary-film mappings; duration/collision protection
  later in the pipeline is not an acceptable identity admission rule.

## Upstream Sources And Adoption

- [Radarr ParsingService](https://github.com/Radarr/Radarr/blob/e77fd33e82d1d80f1cc58c7a5ebd959a90210299/src/NzbDrone.Core/Parser/ParsingService.cs)
  separates path parsing from identity matching, tries directory context, and uses
  provider IDs and original/alternative/translated titles with year evidence.
- [MoviePilot MediaChain](https://github.com/jxxghp/MoviePilot/blob/1528176beacc0f9f8d8d9cbf1adf048b0da67b5c/app/chain/media.py)
  keeps language-specific names and season-year context for recognition fallbacks.
- Official TMDB APIs provide [movie aliases](https://developer.themoviedb.org/reference/movie-alternative-titles),
  [TV aliases](https://developer.themoviedb.org/reference/tv-series-alternative-titles),
  [translations](https://developer.themoviedb.org/reference/movie-translations) and
  [season details](https://developer.themoviedb.org/reference/tv-season-details).

GPL projects supply workflow evidence only. This change is an independent local
implementation, with no vendored upstream code or new runtime dependency.

## Implemented Recognition Boundaries

1. Extract at most four distinct bounded filename/parent/language hints. Preserve
   title numbers; use the last release-year token before technical release fields.
   Bracketed names and explicit `aka` titles are separate provider search hints.
2. Normalize punctuation and Latin accents, retaining Japanese voicing and other
   non-Latin marks. No edit-distance, arbitrary substring or transliteration match.
3. Try exact original/localized identity first, then provider-confirmed aliases and
   translations. Conflicting bilingual candidates require unique corroboration of
   multiple independent hints; one generic English title cannot override identity.
4. Explicit `SxxEyy` excludes movie candidates, but a TV import still requires the
   provider's exact season and each episode number. A different season year needs
   official season-air-date evidence; the library root keeps the series premiere year.
   Missing episode syntax still does not establish movie identity.
   Namesake series may be disambiguated by the provider's requested episode only
   when a unique series confirms it. A 404 for a wrong namesake's season/episode is
   nonmatching evidence; 429 and service errors remain retryable provider failures.
5. Explicit numbered extras, ancillary directories and trailing sample/trailer
   markers remain visible review cases. Do not invent Season 00 or change sources.
6. Keep a 120-second/32-request per-file budget, eight alias-expansion candidates,
   and a five-minute bounded in-memory response cache (128 entries, each at most
   128 KiB). Repeated episodes reuse series evidence; errors are not cached.

## Acceptance

Regression tests cover bilingual conflicts, missing official alias confirmation,
year and episode conflicts, accented titles, numbered titles, ancillary false
positives, bounded hint fan-out and repeated-series caching. Live re-identification
is read-only and preserves source identity/fingerprint/generation with the resulting
candidate evidence. Record exact code hashes and measured corpus deltas before
release. Successful recognition is not readiness, hardlink publication or playback
acceptance. Existing acquisition IDs can later be supplied through a typed,
fingerprint-bound control-plane handoff; this worker must not read the seed database
or depend on qBittorrent to identify media.

The final local targeted run passed 92 tests. Staged live re-identification first
resolved 113 of the original 134, then resolved 16 more when the remaining 21 were
rechecked after season-404 and namesake-episode fixes. All final five remained
review-required on another read-only query, with no provider errors. The earlier
eight errors were invalid-season 404s, now correctly treated as nonmatches. These
are staged corpus results, not a claim that 129 files were published. A final
complete recheck binds the frozen code hash in ignored runtime evidence before
integrated release acceptance. All rechecks make zero production/source writes.
