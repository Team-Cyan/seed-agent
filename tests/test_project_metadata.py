from __future__ import annotations

import re
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
    assert "--entrypoint python" in step_text
    assert "from pathlib import Path" in step_text
    assert "StateStore(" in step_text
    assert "/app/.seed-agent/state.db" in step_text
    assert '"${state_dir}:/app/.seed-agent"' in step_text
    assert "seed-agent:ci healthcheck --config /app/config/example.yaml" in step_text
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert workflow["jobs"]["test"]["timeout-minutes"] == 30


def test_github_actions_are_pinned_to_immutable_commits() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    uses_pattern = re.compile(r"^\s*uses:\s*([^\s#]+)(?:\s+#.*)?$")
    pinned_pattern = re.compile(r"[^@\s]+@[0-9a-f]{40}")
    uses: list[str] = []
    for workflow_path in sorted(workflow_root.glob("*.yml")):
        for line in workflow_path.read_text(encoding="utf-8").splitlines():
            match = uses_pattern.match(line)
            if match:
                uses.append(match.group(1))

    assert uses
    assert all(pinned_pattern.fullmatch(value) for value in uses)


def test_docker_publish_gates_main_tags_on_successful_ci_and_serializes_updates() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "docker-publish.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    publish = workflow["jobs"]["publish"]
    step_text = "\n".join(
        str(step) for job in workflow["jobs"].values() for step in job.get("steps", [])
    )

    assert "branches" not in triggers["push"]
    assert triggers["push"]["tags"] == ["v*"]
    assert triggers["workflow_run"]["workflows"] == ["CI"]
    assert triggers["workflow_run"]["types"] == ["completed"]
    assert triggers["workflow_run"]["branches"] == ["main"]
    assert "github.event.workflow_run.conclusion == 'success'" in publish["if"]
    assert "github.event.workflow_run.event == 'push'" in publish["if"]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert "workflow_run" in workflow["concurrency"]["group"]
    assert "github.event.workflow_run.head_sha" in step_text
    assert "git/ref/heads/main" in step_text
    assert "actions/workflows/ci.yml/runs" in step_text
    assert "type=raw,value=latest" in step_text
    assert "type=raw,value=main" in step_text
