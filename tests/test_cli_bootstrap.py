from typer.testing import CliRunner

from seed_agent.cli import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    expected = "Docker-first PT automation for NAS and homelab operations."
    assert "seed-agent" in result.output or expected in result.output
