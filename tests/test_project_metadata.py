from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_license_file_exists_and_pyproject_declares_mit() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "MIT License" in license_text
    assert 'license = "MIT"' in pyproject_text


def test_readme_exposes_support_matrix_and_source_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Current Support Matrix" in readme
    assert "## Roadmap Snapshot" in readme
    assert "## Source Adapter Status" in readme
    assert "| Web Settings UI | WIP |" in readme
    assert "| Transmission downloader | Supported |" in readme
    assert "| Torznab search | Supported |" in readme
    assert "| file inbox | Wired |" in readme
    assert "| Telegram | Wired |" in readme
    assert "| WeChat bridge | Parser skeleton |" in readme
    assert "| Douban wanted | Wired |" in readme
    assert "| Letterboxd watchlist | Wired |" in readme


def test_ci_workflow_has_python_and_docker_smoke_gates() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job_steps = workflow["jobs"]["test"]["steps"]
    step_text = "\n".join(str(step) for step in job_steps)

    assert "uv run ruff check ." in step_text
    assert "uv run pytest -q" in step_text
    assert "uv run --with pip-audit pip-audit --strict --local" in step_text
    assert "docker compose --env-file deploy/seed-agent.env.example" in step_text
    assert "docker build -t seed-agent:ci ." in step_text
    assert "seed-agent:ci healthcheck --config /app/config/example.yaml" in step_text
