# Architecture And Supported Features

This document is the durable architecture snapshot for the current project shape.
It focuses on shipped or wired behavior, not future aspirations.

## High-Level Architecture

```mermaid
flowchart TB
  operator["Operator / Web UI / CLI"] --> config["config.yaml"]
  operator --> local_secrets["local/secrets/*"]
  operator --> inbox["local/inbox/*"]

  config --> runtime["Seed Agent Runtime"]
  local_secrets --> runtime
  inbox --> intent_sources["Intent Sources"]

  subgraph discovery["PT Upload Strategy Loop"]
    rss["RSS adapters"] --> candidates["TorrentCandidate"]
    mteam_api["M-Team API discovery"] --> candidates
    candidates --> scoring["Scoring policy"]
    scoring --> enqueue_plan["Enqueue plan"]
  end

  subgraph intents["Resource Intent Loop"]
    douban["Douban wanted public page/export"] --> intent_sources
    imdb["IMDb watchlist/list page or CSV export"] --> intent_sources
    file_inbox["JSONL file inbox"] --> intent_sources
    chat_sources["Telegram / WeChat parsers"] --> intent_sources
    intent_sources --> aliases["External ID aliases and source evidence"]
    aliases --> normalized["Canonical ResourceIntent"]
    normalized --> search["RSS / M-Team intent search"]
    search --> ranking["Intent ranking and ambiguity checks"]
    ranking --> intent_enqueue["Intent enqueue"]
  end

  runtime --> discovery
  runtime --> intents
  enqueue_plan --> qb["qBittorrent"]
  intent_enqueue --> qb
  qb --> review["Review / prune / runtime enrichment"]
  review --> state[".seed-agent/state.db"]
  enqueue_plan --> state
  normalized --> state
  ranking --> state
  qb --> audit[".seed-agent/audit.jsonl"]
  runtime --> heartbeat["state/schedule-heartbeat.json"]
  state --> web_status["Web UI status and Want List"]
  heartbeat --> web_status
```

## Runtime Boundaries

- `config.yaml` stores strategy and integration configuration.
- `local/secrets/*` stores credentials such as qBittorrent credentials, M-Team
  API keys, cookies, and chat bridge secrets. Secret values are not written to
  normal config or Web UI payloads.
- `.seed-agent/state.db` is durable local evidence for candidates, intents,
  release candidates, qB runtime facts, and lifecycle reconciliation.
- `.seed-agent/audit.jsonl` records downloader mutations and policy decisions.
- `state/schedule-heartbeat.json` is the scheduler liveness signal.

## Supported Features

| Area | Current support |
| --- | --- |
| Deployment | Docker image, Docker Compose, Unraid DockerMan template, Kubernetes CronJob example, scheduler heartbeat, runtime status, healthcheck. |
| Downloader | qBittorrent only. Category policies define mutable seed pools and add-only media pools. |
| PT discovery | NexusPHP-style RSS, M-Team RSS fallback, M-Team API discovery with native filters and deferred download-token resolution. |
| Seed strategy | Free/2x-free filtering, leecher/seeder scoring, size scoring, runtime enqueue gates, budget-pool pause behavior, review, prune, stale-state reconciliation. |
| Strategy reporting | `strategy-report`, joined enqueue-time evidence, qB runtime enrichment, no-upload observation, missing-from-qB reconciliation. |
| Resource intents | CLI add, JSONL inbox, Douban wanted ingestion, IMDb watchlist/list ingestion, deterministic parsing, RSS search, M-Team API search, ranking, confirmation/rejection, enqueue. |
| Want List | Web UI page backed by canonical intent state, Douban/IMDb source labels, source/type filters, merged source evidence, media type, added time, and search/queue status. |
| M-Team intent search | Native Douban/IMDb ID search first, generic required/preferred/excluded keyword preferences after fetch, Remux-first configs, and configurable TV/anime `series_search_mode` for season-pack or episode search. |
| Web UI | Local settings UI, tracker config, read-only status, budget-pool summary, safe section saves with schema validation and diff preview, search/acquisition settings, and Douban/IMDb Want List source configuration. |
| Source adapters | File inbox, Douban wanted, and IMDb watchlists are wired; Telegram and WeChat bridge parsers are present but no hosted bot/receiver loop is shipped. |

## Key Modules

- `src/seed_agent/cli.py`: CLI command surface and runtime assembly.
- `src/seed_agent/config.py`: Pydantic config schema and safe defaults.
- `src/seed_agent/actions/pt.py`: PT discovery, scoring, and M-Team API option assembly.
- `src/seed_agent/actions/intent.py`: intent ingestion, search, ranking, confirmation, and enqueue.
- `src/seed_agent/sites/mteam.py`: M-Team API/RSS integration and token resolution.
- `src/seed_agent/search/mteam.py`: M-Team intent search provider.
- `src/seed_agent/sources/douban.py`: Douban wanted ingestion.
- `src/seed_agent/sources/imdb.py`: IMDb watchlist/list ingestion.
- `src/seed_agent/web/app.py`: local Web UI API.
- `src/seed_agent/web/static/*`: local Web UI.
- `src/seed_agent/state.py`: SQLite state model.

## Design Rules

- RSS remains supported even when M-Team API is preferred.
- Secrets stay behind gitignored local files and are referenced by path.
- qB mutations are dry-run by default unless the operator explicitly executes.
- Cleanup authority comes from configured category policy, not tags alone.
- Source adapters stay upstream of the generic `ResourceIntent` boundary.
- Want List deduplication uses reliable external ID aliases only; title-only
  fuzzy matching must not auto-merge works.
- Release-quality preferences are composable config knobs, not hardcoded profiles.
