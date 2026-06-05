# qBittorrent Web API Contract

## Scope

`seed-agent` targets the latest qBittorrent WebUI API, currently documented as
the qBittorrent `5.0+` WebUI API.

Older qBittorrent WebUI API variants are not a compatibility target. If a live
host runs an older qBittorrent version, prefer upgrading qBittorrent over adding
legacy behavior to `seed-agent`.

Official reference:

- qBittorrent WebUI API 5.0+: <https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29>

## Current Endpoint Surface

`seed-agent` uses a deliberately small qB API surface:

- `POST /api/v2/auth/login`
  - Authenticates with WebUI username/password.
  - qB uses cookie-based auth; subsequent requests must carry the session
    cookie.
  - `seed-agent` accepts the documented `Ok.` success shape and the observed
    qBittorrent 5.2.1 `204 No Content` plus `Set-Cookie` success shape.
- `POST /api/v2/torrents/add`
  - Adds a URL into the configured qB category and tags.
  - `seed-agent` passes `stopped=true` when policy wants an add-paused enqueue.
- `GET /api/v2/torrents/info`
  - Reads qB runtime state.
  - qB remains the source of truth for live torrent progress, transfer counters,
    category, state, and remaining download volume.
- `POST /api/v2/torrents/stop`
  - Stops a torrent only when an explicit cleanup decision says to pause an
    incomplete managed download.
- `POST /api/v2/torrents/delete`
  - Deletes a torrent only when an explicit cleanup decision says to delete it.
  - `deleteFiles=true` is high risk and must remain behind dry-run/execute
    semantics plus bounded hash-set evidence.

## Field Mapping

`src/seed_agent/downloaders/qbittorrent.py` maps qB torrent rows into
`ManagedTorrent`:

- `hash` -> `ManagedTorrent.hash`
- `name` -> `ManagedTorrent.name`
- `category` -> `ManagedTorrent.category`
- `tags` -> `ManagedTorrent.tags`
- `state` -> `ManagedTorrent.state`
- `size` -> `ManagedTorrent.size_bytes`
- `uploaded` with `uploaded_session` fallback -> `ManagedTorrent.uploaded_bytes`
- `downloaded` -> `ManagedTorrent.downloaded_bytes`
- `added_on` -> `ManagedTorrent.added_at`
- `completion_on` -> `ManagedTorrent.completed_at`
- `last_activity` -> `ManagedTorrent.last_activity_at`
- `save_path` -> `ManagedTorrent.save_path`
- `uploaded_session` -> `metadata.uploaded_session_bytes`
- `upspeed` -> `metadata.upspeed_bps`
- `dlspeed` -> `metadata.dlspeed_bps`
- `amount_left` -> `metadata.amount_left_bytes`

## Compatibility Rules

- Prefer latest qBittorrent behavior over legacy compatibility branches.
- Keep endpoint usage explicit in `QbittorrentClient`; do not hide qB mutations
  behind broad helper methods that obscure the Web API operation.
- Treat qB category membership as the cleanup authority boundary.
- Tags are metadata and filtering hints, not delete authority by themselves.
- Mutating commands must stay dry-run first unless the user explicitly requests
  execute mode.
- Completed managed seeds should remain available for upload. Automated cleanup
  may pause or delete incomplete managed downloads when policy and capacity
  rules allow it, but it should not stop completed seeds merely because a free
  window expired or recent upload is low.
