# Release Process

`seed-agent` publishes Docker images as the primary distribution artifact.

## Version Source

Keep these files on the same version before tagging a release:

- `VERSION`
- `Dockerfile`
- `pyproject.toml`
- `src/seed_agent/__init__.py`

The current release line is `0.9.1`.

## Version Bump Policy

Every commit or push intended for deployment must consider whether it changes
the published Docker image behavior.

- Code fixes and operational fixes bump the patch slot by `0.0.1`
  - example: `0.1.0` -> `0.1.1`
- New features bump the minor slot by `0.1.0`
  - example: `0.1.0` -> `0.2.0`
- Documentation-only changes may leave the version unchanged unless they are
  part of a release or deployment handoff.

Agents must check this before commit, push, or release. If a change is expected
to be pulled by Unraid or another Docker host, bump the version before pushing
so the registry, image labels, changelog, and operator UI make the update
visible.

## GHCR Image

GitHub Actions publishes to:

- `ghcr.io/team-cyan/seed-agent:latest`
- `ghcr.io/team-cyan/seed-agent:main`
- `ghcr.io/team-cyan/seed-agent:sha-<short-sha>`

Version tags such as `v0.1.3` also publish:

- `ghcr.io/team-cyan/seed-agent:v0.1.3`
- `ghcr.io/team-cyan/seed-agent:0.1.3`
- `ghcr.io/team-cyan/seed-agent:0.1`

The image name must stay lowercase for registry compatibility.

## Archival Release Branches

Keep normal development on `main`.

For each minor release line, create an archival branch named
`release/<major>.<minor>` such as `release/0.8`. This branch is a historical
pointer for that minor line, not a working branch.

- Point the branch at the latest known patch commit for that minor line.
- Do not develop routine fixes or features on archival release branches.
- When a newer minor line starts, treat the previous minor branch as immutable
  unless there is an explicit decision to correct the archive pointer.
- Tags remain the release artifact triggers; archival branches are only for
  repository history navigation.

## Release Checklist

1. Classify the change as docs-only, codefix/operational fix, or feature.
2. Apply the version bump policy when the change affects the published Docker
   image or deployment behavior.
3. When a version bump is required, run `python scripts/bump_version.py <version>`
   to update release metadata, then review the diff before committing.
4. Move user-facing entries from `CHANGELOG.md` `Unreleased` into a versioned
   section.
5. Run:

```bash
uv run pytest -q
uv run ruff check .
```

6. Tag and push:

```bash
git tag v0.1.3
git push origin v0.1.3
```

7. Confirm the GitHub Actions run publishes the GHCR image and that the package
   page shows the expected tags.

## Release Boundaries

Do not bake operator config, secrets, tracker credentials, `.seed-agent/`,
`local/`, or `state/` into the image. Runtime behavior must continue to come
from environment variables and mounted files.
