import typer

app = typer.Typer(help="AI-first PT and downloader operations toolkit.")


@app.callback(invoke_without_command=True)
def main() -> None:
    """Seed Agent CLI."""
