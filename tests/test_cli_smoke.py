from typer.testing import CliRunner

from paper_ops.cli import app


def test_cli_shows_top_level_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.stdout
    assert "process" in result.stdout
    assert "discover" in result.stdout
