# Seed Agent Settings Web UI

## Purpose

Add a small, maintainable web UI for configuring `seed-agent` without changing
the project into a dashboard-first product.

The UI is a configuration surface for local operators. It edits versioned
configuration values and local secret files, then offers safe verification and
dry-run previews before users run the existing CLI workflows.

## Product Boundaries

The first version is a settings app, not an operations console.

In scope:

- create and edit tracker configuration,
- keep tracker secrets in local files and store only secret references in YAML,
- show field-level help,
- support Chinese and English UI text with Chinese as the default,
- support light and dark themes,
- provide tracker-local validation, site probe, and dry-run preview actions,
- expose raw YAML only through an advanced view.

Out of scope for the first version:

- execute-mode enqueue from the UI,
- destructive cleanup actions,
- live dashboard metrics,
- broad multi-site plugin management,
- replacing the CLI as the source of operational behavior.

## Information Architecture

The main navigation should stay compact:

- Tracker
- Downloader
- Discovery
- Cleanup
- Intent
- Advanced YAML

The initial implemented screen is `Tracker`.

## Tracker Screen

For a new user, the Tracker page starts empty. The top right area contains:

- a globe-style language button that opens `CN` / `EN` choices,
- a sun/moon theme button that toggles light and dark mode,
- an `Add Tracker` button.

The page top should not contain tracker validation, site probe, or dry-run
actions. Those actions belong to individual tracker containers.

## Tracker Containers

Each tracker is represented by one large expandable container.

The container owns:

- type,
- tracker name,
- type-specific fields,
- authentication fields,
- status,
- tracker-local actions.

Multiple trackers produce multiple containers. Containers can expand and
collapse. A collapsed tracker should still show useful summary badges such as
tracker type, discovery mode, readiness, and last check summary.

## Add Tracker Flow

Clicking `Add Tracker` creates a new empty tracker container.

Inside that container:

1. The first required field is `type`.
2. The second required field is `tracker name`.
3. Until `type` is selected, type-specific fields are hidden.
4. After `type` is selected, the same container renders the fields required for
   that tracker type.

The type picker is not a separate card or separate module. It is just the first
field inside the tracker configuration container.

For `mteam`, the type-specific fields include:

- RSS URL,
- discovery mode,
- API key reference,
- API key value write field,
- auth header stored in tracker config and used by the M-Team API client,
- optional cookie reference,
- M-Team API discovery parameters.

For `nexusphp`, the type-specific fields should focus on RSS and cookie-style
authentication.

## Secret Handling

Authentication belongs inside the tracker container.

The UI must keep the existing config-vs-secret boundary:

- YAML stores references such as `local/secrets/mt.api-key`,
- secret values are written to local secret files,
- saved secret values are not shown back as plaintext,
- generated summaries and validation output must avoid leaking token values.

## Field Help

Every non-obvious field label should include a small `?` help icon.

Help text should explain:

- what the field does,
- whether it is written to YAML or to a local secret file,
- what the safe default means,
- when the user should avoid changing it.

## Tracker-Local Actions

Tracker-related actions live inside each tracker container:

- `Validate This Tracker`
- `Site Probe`
- `Dry-run Preview`

These actions are safe in the first version:

- validation checks that tracker fields can be written into the full config
  model,
- site probe checks that the selected tracker access works,
- dry-run preview is scoped to the selected tracker and must not enqueue or
  mutate qBittorrent.

Results from these actions update the status area inside that tracker container.

## Advanced YAML

Raw YAML editing and YAML preview belong in `Advanced YAML`, not beside normal
forms. The normal path is form-first.

The advanced view should support:

- generated YAML preview,
- validation before save,
- a clear indication that secret values are not written into YAML.

## Implementation Notes

The UI should reuse existing config models and CLI behavior where possible.

Preferred implementation shape:

- a lightweight local web server module under `src/seed_agent/web/`,
- typed request/response models that map to existing Pydantic config models,
- file operations that preserve `config/config.yaml` and `local/secrets/*`
  boundaries,
- no custom JavaScript build pipeline unless the implementation clearly needs
  it.

The first implementation should be easy to run locally and easy to package in
the existing Docker-first deployment model.
