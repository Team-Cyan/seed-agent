# Release Process

`seed-agent` publishes Docker images as the primary distribution artifact.

## Version Source

Keep these files on the same version before tagging a release:

- `VERSION`
- `pyproject.toml`
- `src/seed_agent/__init__.py`

The current release line is `0.1.0`.

## GHCR Image

GitHub Actions publishes to:

- `ghcr.io/team-cyan/seed-agent:latest`
- `ghcr.io/team-cyan/seed-agent:main`
- `ghcr.io/team-cyan/seed-agent:sha-<short-sha>`

Version tags such as `v0.1.0` also publish:

- `ghcr.io/team-cyan/seed-agent:v0.1.0`
- `ghcr.io/team-cyan/seed-agent:0.1.0`
- `ghcr.io/team-cyan/seed-agent:0.1`

The image name must stay lowercase for registry compatibility.

## Release Checklist

1. Update `VERSION`, `pyproject.toml`, and `src/seed_agent/__init__.py`.
2. Move user-facing entries from `CHANGELOG.md` `Unreleased` into a versioned
   section.
3. Run:

```bash
uv run pytest -q
uv run ruff check .
docker compose --env-file deploy/seed-agent.env.example -f deploy/docker-compose.example.yml config
docker build -t seed-agent:local .
```

4. Tag and push:

```bash
git tag v0.1.0
git push origin v0.1.0
```

5. Confirm the GitHub Actions run publishes the GHCR image and that the package
   page shows the expected tags.

## Release Boundaries

Do not bake operator config, secrets, tracker credentials, `.seed-agent/`,
`local/`, or `state/` into the image. Runtime behavior must continue to come
from environment variables and mounted files.
