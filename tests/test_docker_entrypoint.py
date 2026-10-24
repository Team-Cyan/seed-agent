from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_entrypoint_adds_prune_flag_from_environment(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "argv.txt"
    seed_agent = bin_dir / "seed-agent"
    seed_agent.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$SEED_AGENT_ARGV_LOG"\n',
        encoding="utf-8",
    )
    seed_agent.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SEED_AGENT_ARGV_LOG": str(log_path),
        "SEED_AGENT_MODE": "schedule-run",
        "SEED_AGENT_CONFIG": "/app/config/config.yaml",
        "SEED_AGENT_PRUNE": "true",
        "SEED_AGENT_MAX_CYCLES": "1",
    }

    result = subprocess.run(
        ["sh", "docker/entrypoint.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--prune" in log_path.read_text(encoding="utf-8").splitlines()


def test_entrypoint_adds_intent_execute_flag_from_environment(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "argv.txt"
    seed_agent = bin_dir / "seed-agent"
    seed_agent.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$SEED_AGENT_ARGV_LOG"\n',
        encoding="utf-8",
    )
    seed_agent.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SEED_AGENT_ARGV_LOG": str(log_path),
        "SEED_AGENT_MODE": "schedule-run",
        "SEED_AGENT_CONFIG": "/app/config/config.yaml",
        "SEED_AGENT_INTENT_EXECUTE": "true",
        "SEED_AGENT_MAX_CYCLES": "1",
    }

    result = subprocess.run(
        ["sh", "docker/entrypoint.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--intent-execute" in log_path.read_text(encoding="utf-8").splitlines()


def test_entrypoint_emits_startup_runtime_status(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "argv.txt"
    seed_agent = bin_dir / "seed-agent"
    seed_agent.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" >> "$SEED_AGENT_ARGV_LOG"\n',
        encoding="utf-8",
    )
    seed_agent.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SEED_AGENT_ARGV_LOG": str(log_path),
        "SEED_AGENT_MODE": "schedule-run",
        "SEED_AGENT_CONFIG": "/workspace/runtime/config/config.yaml",
        "SEED_AGENT_HEARTBEAT_FILE": "/workspace/runtime/state/schedule-heartbeat.json",
        "SEED_AGENT_MAX_CYCLES": "1",
    }

    result = subprocess.run(
        ["sh", "docker/entrypoint.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    argv = log_path.read_text(encoding="utf-8")
    assert "runtime-status" in argv
    assert "/workspace/runtime/config/config.yaml" in argv
    assert "/workspace/runtime/state/schedule-heartbeat.json" in argv


def _entrypoint_calls(tmp_path, arguments=(), **overrides):
    import json

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = bin_dir / "seed-agent"
    # Use this interpreter directly; the entrypoint's PATH intentionally has no
    # dependency on an installed seed-agent command.
    import sys

    stub.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        "with open(os.environ['SEED_AGENT_ARGV_LOG'], 'a') as f:\n"
        " f.write(json.dumps(sys.argv[1:])+'\\n')\n"
    )
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SEED_AGENT_")}
    env.update(
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        SEED_AGENT_ARGV_LOG=str(log),
        HOME=str(tmp_path),
        PUID="",
        PGID="",
        **overrides,
    )
    result = subprocess.run(
        ["sh", "docker/entrypoint.sh", *arguments],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )
    return result, [
        json.loads(line) for line in log.read_text().splitlines()
    ] if log.exists() else []


def test_media_entrypoint_never_starts_seed_or_web_even_if_web_enabled(tmp_path):
    result, calls = _entrypoint_calls(
        tmp_path,
        SEED_AGENT_MODE="media-worker",
        SEED_AGENT_WEB_ENABLED="true",
        SEED_AGENT_CONFIG="/app/shared config/config.yaml",
        SEED_AGENT_MAX_CYCLES="1",
        SEED_AGENT_HEARTBEAT_FILE="/seed/heartbeat",
        SEED_AGENT_EXECUTE="true",
    )
    assert result.returncode == 0
    assert calls == [
        ["runtime-status", "--config", "/app/shared config/config.yaml", "--role", "media"],
        ["media-worker", "--config", "/app/shared config/config.yaml", "--max-cycles", "1"],
    ]


def test_entrypoint_preserves_spaces_empty_arguments_globs_and_literal_shell(tmp_path):
    args = [
        "media-worker",
        "--config",
        "/config with spaces/config.yaml",
        "",
        "*.mkv",
        "$(echo nope)",
    ]
    result, calls = _entrypoint_calls(tmp_path, args, SEED_AGENT_STARTUP_STATUS="false")
    assert result.returncode == 0
    assert calls == [["media-worker", "--config", "/app/config/config.yaml", *args[1:]]]


def test_media_healthcheck_ignores_seed_heartbeat_defaults(tmp_path):
    result, calls = _entrypoint_calls(
        tmp_path,
        ["healthcheck"],
        SEED_AGENT_ROLE="media",
        SEED_AGENT_HEARTBEAT_FILE="/seed/heartbeat",
        SEED_AGENT_MAX_STALENESS_MINUTES="90",
        SEED_AGENT_WEB_ENABLED="true",
    )
    assert result.returncode == 0
    assert calls == [["healthcheck", "--config", "/app/config/config.yaml", "--role", "media"]]


def test_media_role_cannot_launch_seed_scheduler(tmp_path):
    result, calls = _entrypoint_calls(tmp_path, SEED_AGENT_ROLE="media")
    assert result.returncode == 2
    assert "media role requires" in result.stderr
    assert calls == []


def test_seed_explicit_command_passthrough_still_preserves_arguments(tmp_path):
    result, calls = _entrypoint_calls(tmp_path, ["seed-agent", "runtime-status", "--config", "a b"])
    assert result.returncode == 0
    assert calls == [["runtime-status", "--config", "a b"]]


def test_explicit_command_prefix_cannot_bypass_media_role_boundary(tmp_path):
    result, calls = _entrypoint_calls(
        tmp_path, ["seed-agent", "schedule-run"], SEED_AGENT_ROLE="media"
    )
    assert result.returncode == 2
    assert calls == []


def test_media_deployment_cannot_healthcheck_seed_role(tmp_path):
    result, calls = _entrypoint_calls(
        tmp_path, ["healthcheck", "--role", "seed"], SEED_AGENT_ROLE="media"
    )
    assert result.returncode == 2
    assert calls == []
