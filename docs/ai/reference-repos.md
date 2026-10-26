# Reference Repositories

These projects are references, not implementation templates. Use them to borrow ideas, boundary decisions, and troubleshooting clues without cloning their whole product shape.

## PT Discovery And Automation

### `pt-tools`

- Source: https://github.com/sunerpy/pt-tools
- Refer to for:
  - PT automation patterns,
  - candidate evaluation ideas,
  - operational command shape.
- Do not copy:
  - product assumptions that do not fit this repo's config-first CLI model.

### `flexget-nexusphp`

- Source: https://github.com/pt-plugins/PT-Plugin-Plus/tree/main/plugins/flexget
- Refer to for:
  - NexusPHP/RSS integration ideas,
  - tracker-specific feed handling,
  - rule-oriented PT workflows.
- Do not copy:
  - large plugin abstractions that would overcomplicate `seed-agent`.

### `PT-Plugin-Plus`

- Source: https://github.com/pt-plugins/PT-Plugin-Plus
- Refer to for:
  - site support breadth,
  - rule integration patterns,
  - PT workflow ergonomics.
- Do not copy:
  - plugin surface area that exceeds the scope of this repo.

## Intent And Subscription Flows

### `Auto_Bangumi`

- Source: https://github.com/EstrellaXD/Auto_Bangumi
- Refer to for:
  - subscription-driven acquisition,
  - feed-to-download flow design.
- Do not copy:
  - domain-specific assumptions that do not generalize beyond anime.

### `ani-rss`

- Source: https://github.com/walse0/ani-rss
- Refer to for:
  - light subscription workflows,
  - simple rule-driven discovery patterns.

### `bgmi`

- Source: https://github.com/BGmi/BGmi
- Refer to for:
  - content tracking loops,
  - episode-oriented workflow ideas.

## NAS And PT Product Boundary References

### `MoviePilot`

- Source: https://github.com/jxxghp/MoviePilot
- Refer to for:
  - end-to-end NAS workflow coverage,
  - feature boundary inspiration,
  - what a larger integrated product looks like.
- Do not copy:
  - dashboard/product scope into this repo's current phase.

### `nas-tools`

- Source: https://github.com/NAStool/nas-tools
- Refer to for:
  - media automation boundary choices,
  - operational workflow expectations from NAS users.

### `vertex`

- Source: https://github.com/vertex-app/vertex
- Refer to for:
  - PT/NAS product surface ideas,
  - category breadth and operator expectations.

## M-Team-Specific References

### `mteam-active-top-rss`

- Source: https://hub.docker.com/r/xiaohaigreen/mteam-active-top-rss
- Refer to for:
  - M-Team laboratory access token usage,
  - API-key-based filtering/sorting clues,
  - practical operator expectations around FREE-oriented discovery.

### `M-Team FREE Torrents Extractor`

- Source: https://greasyfork.org/en/scripts/562990-m-team-%E5%85%8D%E8%B4%B9%E7%A7%8D%E5%AD%90%E6%8F%90%E5%8F%96
- Refer to for:
  - `x-api-key` usage patterns,
  - `genDlToken` endpoint shape,
  - filtering ideas for FREE torrents.

## Later Kernel References

### `autobrr`

- Source: https://github.com/autobrr/autobrr
- Refer to for:
  - event/filter/action separation,
  - client-agnostic action wiring,
  - explainable rule matching for automated acquisition.
- Do not copy:
  - full announce-driven product scope before `seed-agent` provider contracts
    remain stable under current scheduler/Web flows.

### `Prowlarr`

- Source: https://github.com/Prowlarr/Prowlarr
- Refer to for:
  - indexer management boundaries,
  - Torznab-like provider proxy patterns,
  - capability and health modeling for search providers.
- Do not copy:
  - full indexer-manager ownership into the core PT strategy loop.

### `cross-seed`

- Source: https://github.com/cross-seed/cross-seed
- Refer to for:
  - conservative file-to-torrent matching,
  - read-only reseed evaluation before execution,
  - Torznab-backed discovery for equivalent torrents.
- Do not copy:
  - automatic cross-seed execution without exact candidate evidence and
    operator-confirmed mutation boundaries.

## Media Import, Series Layout, And Subtitles

Reviewed 2026-10-22 against upstream source, not just feature descriptions.
See `docs/plans/2026-10-22-media-import-integration.md` for adoption scope.

### `Radarr`: Identity And Path Parsing (2026-10-26)

- Source: https://github.com/Radarr/Radarr
- Inspected revision: `e77fd33e82d1d80f1cc58c7a5ebd959a90210299`.
- Code: `src/NzbDrone.Core/Parser/ParsingService.cs`.
- Borrow the filename/directory hint fallback and provider-ID-first matching design.
  Its matching considers original, translated and alternative names with year
  evidence. Keep titles and release metadata separate; a download title alone is
  not a new authoritative media ID.
- This is a GPL reference: use its workflow ideas, not copied implementation.
  Our local implementation retains typed evidence, bounded requests, explicit
  ambiguity and provider-confirmed TV numbering. No Radarr service is required.

### `Sonarr` (new)

- Source: https://github.com/Sonarr/Sonarr
- Inspected revision: `b3d4bb8c18f7feb6744a6cd3231279a45351bb5e`.
- Code: `src/NzbDrone.Core/MediaFiles/EpisodeImport/ImportApprovedEpisodes.cs`,
  `src/NzbDrone.Core/MediaFiles/EpisodeFileMovingService.cs`, and
  `src/NzbDrone.Core/Organizer/FileNameBuilder.cs` (`BuildFilePath`,
  `BuildSeasonPath`, `GetSeasonFolder`).
- Borrow the approved-import boundary and separate series/season/episode naming.
  Consult `src/NzbDrone.Core.Test/OrganizerTests/FileNameBuilderTests/` for
  multi-episode, absolute-number, invalid-character, and same-title cases.
- Adapt to this user's `Season NN` layout. Do not adopt `HardLinkOrCopy` fallback:
  seed-agent must report EXDEV instead of silently consuming another full copy.

### `Bazarr` (new)

- Source: https://github.com/morpheus65535/bazarr
- Inspected revision: `bfe4593b04caa16eb4a09c2a233777b0bd7723b6`.
- Code: `bazarr/subtitles/wanted/series.py`, `bazarr/subtitles/download.py`,
  `bazarr/subtitles/indexer/series.py`, and `bazarr/subtitles/processing.py`.
- Borrow missing-language indexing, language profiles, score cutoffs, unusable
  candidate blacklisting, adaptive search, and provider throttling.
- Keep subtitle jobs independent of successful video imports. Do not assume
  Bazarr is a generic standalone API for this product: its ordinary workflow is
  coupled to Sonarr/Radarr. Do not add those services as required dependencies.

### `Subliminal` (new)

- Source: https://github.com/Diaoul/subliminal
- Inspected revision: `7fb41f89d8c265591ae328d9a704c1b54b9bf655`.
- Code: `src/subliminal/core.py` (provider pool, language/FPS filtering and score
  ordering), `src/subliminal/score.py`, and
  `src/subliminal/providers/opensubtitlescom.py`.
- Candidate reusable Python dependency behind a small SubtitleProvider contract;
  evaluate Python 3.14 compatibility, dependency/license closure, provider auth,
  Chinese language support, timeouts, and quotas before selecting a version.
- Use its matching/provider concepts; do not vendor Bazarr's full subtitle fork.

### Existing `MoviePilot`: Focused Source Review

- Inspected revision: `5fc4f2efd88fadf4de6d25b44395975e2779fa1f`.
- Code: `app/chain/transfer/workflow.py`, `app/chain/transfer/plan.py`,
  `app/chain/transfer/execution.py`, `app/chain/search/subtitle.py`, and
  `app/chain/download/subtitle.py`.
- Borrow separation of transfer planning/execution and media-identity/episode
  aware subtitle lookup; inspect `_match_subtitle_episode` for mismatch handling.
- Do not bring its broad workflow engine or plugin platform into this phase.

Identity follow-up inspected on 2026-10-26 at
`1528176beacc0f9f8d8d9cbf1adf048b0da67b5c` (`v2`): `app/chain/media.py`.
Borrow separate Chinese/original/English title hints, provider-ID-aware recognition,
and season-year context. Keep requested recognition source and identity provenance
intact across fallbacks. See `docs/research/2026-10-26-media-identity-repair.md` for
our production-derived failure classes and independently implemented fixes.

### Subtitle Provider Inventory (Inspected Source, 2026-10-23)

These are supported adapters in the inspected revisions, not evidence of any
particular user's enabled providers or working external credentials.

| Reference | Observed subtitle integration |
| --- | --- |
| Bazarr | `custom_libs/subliminal_patch/providers/`: OpenSubtitles.com, Assrt, SubDL, Addic7ed, Gestdown, Zimuku, Shooter, YIFY and others. Provider availability/authentication requires separate live checks. |
| Subliminal | `src/subliminal/providers/`: OpenSubtitles.com, legacy OpenSubtitles.org adapter, Podnapisi, Addic7ed, Gestdown, TVsubtitles and others. Legacy adapter presence is not a recommendation or proof of service availability. |
| MoviePilot | Current inspected `app/modules/subtitle/__init__.py` extracts subtitle links from configured site detail pages; search chains use configured site subtitle capabilities. Plugins may add sources; do not infer all plugins are built in or enabled. |
| Sonarr | `Extras/Subtitles/` handles existing sidecar import/organization; it is a naming/import reference, not the automatic online subtitle provider implementation selected here. |
| seed-agent local implementation | OpenSubtitles.com only, via Subliminal adapter. No Assrt/SubDL/Zimuku provider is currently integrated. |

The selected integration is the modern `.com` REST API, not legacy `.org` XML-RPC.
Metadata provider TMDB and subtitle providers have independent credentials/lifecycles.

### Code Reuse Boundary

The reviewed Sonarr, Bazarr, and MoviePilot license files are GPLv3; Subliminal
is MIT. This repository declares MIT. Use GPL projects as behavioral/design
references and write fitting local implementations. Any proposed source reuse
must explicitly resolve license obligations first. Retain notices for reused
MIT material and inspect transitive dependency licenses before adoption.
Reference discovery itself adds no runtime dependencies.

## Troubleshooting Guidance

If the repo gets stuck on a site integration, search these references for:

- how they authenticate,
- what list/search/detail endpoints they rely on,
- whether they use RSS, direct API calls, or both,
- which fields they consider necessary before enqueue.

Do not blindly port code. Port the smallest stable idea that matches this repo's architecture.
