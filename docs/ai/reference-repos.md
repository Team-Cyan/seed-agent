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

## Troubleshooting Guidance

If the repo gets stuck on a site integration, search these references for:

- how they authenticate,
- what list/search/detail endpoints they rely on,
- whether they use RSS, direct API calls, or both,
- which fields they consider necessary before enqueue.

Do not blindly port code. Port the smallest stable idea that matches this repo's architecture.
