# Discovery Module

## Purpose

Turn external site-specific list sources into `TorrentCandidate` objects.

## Primary Files

- `src/seed_agent/sites/rss.py`
- `src/seed_agent/sites/mteam.py`
- `src/seed_agent/actions/pt.py`
- `src/seed_agent/search/rss.py`
- `src/seed_agent/search/mteam.py`

## Current Responsibilities

- fetch RSS feeds,
- fetch M-Team API-discovered candidates when configured,
- inherit global discovery thresholds into M-Team API lower-bound filters when
  site-level API thresholds are set to `null`,
- parse site-specific candidate fields,
- support M-Team detail enrichment,
- search M-Team API candidates for resource intents when an API key is
  configured,
- hand discovered candidates to scoring and search flows.

## Current Expectations

- preserve `TorrentCandidate` as the stable boundary,
- do not leak raw secrets into CLI output or audit,
- keep site-specific logic out of scoring and qB code,
- keep discovery adapters additive when possible.
- preserve explicit numeric zero values from tracker APIs instead of treating
  them as missing enrichment data,
- propagate rate-limit and network failures from optional RSS enrichment so the
  scheduler can activate its existing backoff controls,
- route anime intent searches through M-Team's TV search mode.

## Verification

- `uv run pytest -q tests/test_rss_site.py tests/test_pt_actions.py tests/test_search_rss.py`
- `uv run seed-agent discover --config <config>`
- `uv run seed-agent site-probe --config <config>`

## Near-Term Work

- keep RSS solid,
- prefer `discovery_mode: api` for M-Team when `api_key_ref` is available,
- use explicit `0` in M-Team API thresholds when the operator wants broad native
  API retrieval followed by local scoring,
- keep `TorrentCandidate` as the stable boundary between discovery and scoring.
- keep source integrations such as Douban, chat bridges, and future rating sites
  upstream of the generic `ResourceIntent` boundary.
