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
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SEED_AGENT_ARGV_LOG\"\n",
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


def test_entrypoint_emits_startup_runtime_status(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "argv.txt"
    seed_agent = bin_dir / "seed-agent"
    seed_agent.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$SEED_AGENT_ARGV_LOG\"\n",
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
