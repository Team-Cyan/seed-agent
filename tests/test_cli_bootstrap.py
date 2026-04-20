from typer.testing import CliRunner

from seed_agent.cli import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    expected = "AI-first PT and downloader operations toolkit."
    assert "seed-agent" in result.output or expected in result.output
