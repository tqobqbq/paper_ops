import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from paper_ops.cli import app


def test_cli_shows_top_level_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.stdout
    assert "process" in result.stdout
    assert "discover" in result.stdout


def test_module_entrypoint_shows_top_level_help():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    result = subprocess.run(
        [sys.executable, "-m", "paper_ops", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "ingest" in output
    assert "process" in output
    assert "discover" in output


def test_cli_lists_discovery_and_ingest_subcommands():
    runner = CliRunner()
    result = runner.invoke(app, ["discover", "--help"])
    assert result.exit_code == 0
    assert "--source" in result.stdout


def test_cli_lists_process_and_ingest_variants():
    runner = CliRunner()
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    assert "url" in result.stdout
    assert "pdf" in result.stdout
