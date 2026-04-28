# M-Team Module

## Purpose

Handle M-Team-specific discovery, detail enrichment, and download-token generation concerns.

## Primary Files

- `src/seed_agent/sites/mteam.py`
- `src/seed_agent/sites/rss.py`
- `tests/test_mteam_site.py`
- `docs/specs/2026-04-24-mteam-api-driven-discovery.md`

## Current Status

Implemented today:

- RSS candidate parsing for M-Team feed shape
- `x-api-key` detail enrichment
- API-driven discovery with FREE filtering and activity-based sorting
- deferred `genDlToken` download URL generation for accepted API-discovered
  candidates during execute-mode enqueue
- `site-probe` visibility for authenticated M-Team access and discovery mode

Current preferred auth:

- `api_key_ref`

Current fallback still present in code:

- cookie-based enrichment compatibility

## Important Constraints

- Do not delete the RSS path. It remains useful for fallback and for other sites.
- Do not reintroduce browser-login assumptions into the main flow.
- Treat M-Team API key as the long-term preferred authenticated path.
- Keep API discovery cheap: search/detail calls may run during discovery and
  scoring, but `genDlToken` should only run for accepted candidates when
  enqueue is executing.

## Desired Future State

- keep API discovery as the preferred M-Team path,
- retain RSS as a tested fallback and reusable adapter.

## Verification

- `uv run pytest -q tests/test_mteam_site.py tests/test_rss_site.py`
- `uv run seed-agent site-probe --config <mteam-config>`

## If You Get Stuck

Read:

- `docs/ai/reference-repos.md`
- `docs/specs/2026-04-24-mteam-api-driven-discovery.md`
