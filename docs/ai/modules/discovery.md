# Discovery Module

## Purpose

Turn external site-specific list sources into `TorrentCandidate` objects.

## Primary Files

- `src/seed_agent/sites/rss.py`
- `src/seed_agent/sites/mteam.py`
- `src/seed_agent/actions/pt.py`
- `src/seed_agent/search/rss.py`

## Current Responsibilities

- fetch RSS feeds,
- fetch M-Team API-discovered candidates when configured,
- parse site-specific candidate fields,
- support M-Team detail enrichment,
- hand discovered candidates to scoring and search flows.

## Current Expectations

- preserve `TorrentCandidate` as the stable boundary,
- do not leak raw secrets into CLI output or audit,
- keep site-specific logic out of scoring and qB code,
- keep discovery adapters additive when possible.

## Verification

- `uv run pytest -q tests/test_rss_site.py tests/test_pt_actions.py tests/test_search_rss.py`
- `uv run seed-agent discover --config <config>`
- `uv run seed-agent site-probe --config <config>`

## Near-Term Work

- keep RSS solid,
- prefer `discovery_mode: api` for M-Team when `api_key_ref` is available,
- keep `TorrentCandidate` as the stable boundary between discovery and scoring.
