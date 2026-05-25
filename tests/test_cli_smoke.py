import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from typer.testing import CliRunner
import yaml

import paper_ops.cli as cli
from paper_ops.cli import app
from paper_ops.queue import CandidateQueue
from paper_ops.process_local_pdf import app as local_pdf_app
import paper_ops.process_local_pdf as process_local_pdf_cli


def test_cli_shows_top_level_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.stdout
    assert "process" in result.stdout
    assert "discover" in result.stdout
    assert "manual" in result.stdout
    assert "summarize" in result.stdout
    assert "graph" in result.stdout


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


def test_ingest_batch_enqueues_json_candidates(tmp_path: Path):
    library_root = tmp_path / "papers"
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(
        json.dumps(
            [
                {
                    "title": "Paper A",
                    "source_url": "https://example.com/a",
                    "source_type": "url",
                    "matched_keywords": ["predictive coding"],
                    "reason": "agent selected",
                },
                {
                    "title": "Paper B",
                    "source_url": "https://example.com/b",
                    "source_type": "url",
                    "priority": "medium",
                    "reason": "agent selected",
                },
            ]
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "ingest",
            "batch",
            str(batch_file),
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    entries = CandidateQueue(library_root / "candidates" / "queue.json").load()
    assert [entry.title for entry in entries] == ["Paper A", "Paper B"]
    assert entries[0].matched_keywords == ["predictive coding"]
    assert entries[1].priority == "medium"


def test_discover_from_feed_enqueues_keyword_matches(tmp_path: Path, monkeypatch):
    library_root = tmp_path / "papers"
    monkeypatch.setattr(
        "paper_ops.cli.parse_feed_entries",
        lambda source: [
            {
                "title": "Predictive Coding Paper",
                "summary": "SNN learning",
                "link": "https://arxiv.org/abs/2601.00001",
            },
            {
                "title": "Transformer Paper",
                "summary": "Scaling laws",
                "link": "https://arxiv.org/abs/2601.00002",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "discover",
            "--source",
            "https://example.com/feed.xml",
            "--keywords",
            "predictive coding",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    entries = CandidateQueue(library_root / "candidates" / "queue.json").load()
    assert [entry.title for entry in entries] == ["Predictive Coding Paper"]
    assert entries[0].source_url == "https://arxiv.org/abs/2601.00001"


def test_process_queued_lists_unaccepted_candidates(tmp_path: Path):
    library_root = tmp_path / "papers"
    queue = CandidateQueue(library_root / "candidates" / "queue.json")
    queue.enqueue(
        title="Queued Paper",
        source_url="https://example.com/queued",
        source_type="url",
        discovered_from="manual",
        priority="high",
        matched_keywords=[],
        reason="manual",
    )
    accepted = queue.enqueue(
        title="Accepted Paper",
        source_url="https://example.com/accepted",
        source_type="url",
        discovered_from="manual",
        priority="high",
        matched_keywords=[],
        reason="manual",
    )
    queue.accept(accepted.candidate_id, "2026-example-accepted-paper")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "process",
            "--queued",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    assert "Queued Paper" in result.stdout
    assert "Accepted Paper" not in result.stdout


def test_cli_lists_manual_subcommands():
    runner = CliRunner()
    result = runner.invoke(app, ["manual", "--help"])
    assert result.exit_code == 0
    assert "render-readme" in result.stdout
    assert "scan-once" in result.stdout
    assert "watch" in result.stdout


def test_cli_lists_summarize_subcommands():
    runner = CliRunner()
    result = runner.invoke(app, ["summarize", "--help"])
    assert result.exit_code == 0
    assert "direction" in result.stdout
    assert "overview" in result.stdout
    assert "pending" in result.stdout


def test_cli_lists_graph_subcommands():
    runner = CliRunner()
    result = runner.invoke(app, ["graph", "--help"])
    assert result.exit_code == 0
    assert "update" in result.stdout
    assert "sync" in result.stdout
    assert "candidates" in result.stdout
    assert "snapshot" in result.stdout
    assert "map" in result.stdout
    assert "review" in result.stdout
    assert "enqueue-downloads" in result.stdout


def test_manual_render_readme_uses_library_root(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "manual",
            "render-readme",
            "--library-root",
            str(tmp_path / "papers"),
        ],
    )
    assert result.exit_code == 0
    assert "README.md" in result.stdout
    assert (tmp_path / "papers" / "manual_downloads" / "README.md").exists()


def test_manual_scan_once_without_requests_does_not_process(tmp_path: Path):
    original_load_runtime_settings = cli.load_runtime_settings
    cli.load_runtime_settings = Mock(
        side_effect=AssertionError("settings should not load without a matched PDF")
    )
    runner = CliRunner()
    try:
        result = runner.invoke(
            app,
            [
                "manual",
                "scan-once",
                "--library-root",
                str(tmp_path / "papers"),
            ],
        )
    finally:
        cli.load_runtime_settings = original_load_runtime_settings
    assert result.exit_code == 0
    assert '"processed": 0' in result.stdout
    assert '"failed": 0' in result.stdout


def test_build_index_uses_library_root_option(tmp_path: Path, monkeypatch):
    seen: list[Path] = []

    def fake_rebuild_indexes(library_root: Path) -> None:
        seen.append(library_root)

    monkeypatch.setattr("paper_ops.cli.rebuild_indexes", fake_rebuild_indexes)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "build-index",
            "--library-root",
            str(tmp_path / "papers"),
        ],
    )

    assert result.exit_code == 0
    assert seen == [tmp_path / "papers"]
    assert '"rebuilt": true' in result.stdout


def test_expand_citations_cli_writes_artifact_without_loading_model_settings(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"
    seen = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            seen["provider_kwargs"] = kwargs

    class FakeGraphResult:
        db_path = library_root / "indexes" / "paper_graph.sqlite"
        expansion_path = (
            library_root / "indexes" / "graph_updates" / "predictive_coding.json"
        )
        seed_count = 1
        raw_candidate_count = 3
        candidate_count = 2
        llm_review_count = 0
        relation_count = 3

    def fake_update_graph_for_direction(**kwargs):
        seen.update(kwargs)
        return FakeGraphResult()

    def fake_export_graph_candidates(**kwargs):
        output_path = (
            library_root / "indexes" / "graph_candidates" / "predictive_coding.json"
        )
        output_path.parent.mkdir(parents=True)
        output_path.write_text(
            json.dumps({"direction": kwargs["direction"], "candidate_count": 2}),
            encoding="utf-8",
        )
        seen["export_kwargs"] = kwargs
        return output_path

    monkeypatch.setattr("paper_ops.cli.SemanticScholarExpansionProvider", FakeProvider)
    monkeypatch.setattr(
        "paper_ops.cli.update_graph_for_direction",
        fake_update_graph_for_direction,
    )
    monkeypatch.setattr(
        "paper_ops.cli.export_graph_candidates",
        fake_export_graph_candidates,
    )
    monkeypatch.setattr(
        "paper_ops.cli.load_runtime_settings",
        Mock(side_effect=AssertionError("model settings should only load with --rank")),
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "expand-citations",
            "predictive_coding",
            "--library-root",
            str(library_root),
            "--limit",
            "7",
            "--citations-per-seed",
            "3",
            "--references-per-seed",
            "4",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["output_path"].endswith("predictive_coding.json")
    assert payload["db_path"].endswith("paper_graph.sqlite")
    assert payload["candidate_count"] == 2
    assert payload["raw_candidate_count"] == 3
    assert payload["discovered_paper_count"] == 2
    assert payload["relation_count"] == 3
    assert seen["library_root"] == library_root
    assert seen["direction"] == "predictive_coding"
    assert "limit" not in seen
    assert "settings" not in seen
    assert seen["export_kwargs"]["limit"] == 7
    assert seen["provider_kwargs"] == {
        "citations_limit": 3,
        "references_limit": 4,
    }


def test_graph_update_cli_writes_database_without_loading_model_settings(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"
    seen = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            seen["provider_kwargs"] = kwargs

    class FakeGraphResult:
        db_path = library_root / "indexes" / "paper_graph.sqlite"
        expansion_path = (
            library_root / "indexes" / "graph_updates" / "predictive_coding.json"
        )
        seed_count = 1
        raw_candidate_count = 2
        candidate_count = 2
        llm_review_count = 0
        relation_count = 2

    def fake_update_graph_for_direction(**kwargs):
        seen.update(kwargs)
        return FakeGraphResult()

    monkeypatch.setattr("paper_ops.cli.SemanticScholarExpansionProvider", FakeProvider)
    monkeypatch.setattr(
        "paper_ops.cli.update_graph_for_direction",
        fake_update_graph_for_direction,
    )
    monkeypatch.setattr(
        "paper_ops.cli.load_runtime_settings",
        Mock(side_effect=AssertionError("model settings should only load with --rank")),
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "graph",
            "update",
            "predictive_coding",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["db_path"].endswith("paper_graph.sqlite")
    assert payload["discovered_paper_count"] == 2
    assert payload["relation_count"] == 2
    assert "settings" not in seen


def test_graph_candidates_cli_exports_current_candidates(tmp_path: Path, monkeypatch):
    library_root = tmp_path / "papers"
    output_path = (
        library_root / "indexes" / "graph_candidates" / "predictive_coding.json"
    )

    def fake_export_graph_candidates(**kwargs):
        output_path.parent.mkdir(parents=True)
        output_path.write_text(
            json.dumps(
                {
                    "direction": kwargs["direction"],
                    "candidate_count": 1,
                    "candidates": [],
                }
            ),
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(
        "paper_ops.cli.export_graph_candidates",
        fake_export_graph_candidates,
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "graph",
            "candidates",
            "predictive_coding",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["candidate_count"] == 1
    assert payload["output_path"].endswith("predictive_coding.json")


def test_manual_render_readme_defaults_to_env_library_root(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("PAPER_OPS_LIBRARY_ROOT", str(tmp_path / "env-papers"))
    runner = CliRunner()

    result = runner.invoke(app, ["manual", "render-readme"])

    assert result.exit_code == 0
    assert (tmp_path / "env-papers" / "manual_downloads" / "README.md").exists()


def test_manual_create_request_writes_yaml_and_readme(tmp_path: Path):
    library_root = tmp_path / "papers"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "manual",
            "create-request",
            "--library-root",
            str(library_root),
            "--request-id",
            "req-001",
            "--title",
            "Difference Predictive Coding for Training Spiking Neural Networks",
            "--authors",
            "Karlsson, Lee",
            "--year",
            "2026",
            "--direction",
            "predictive_coding",
            "--source-url",
            "https://openreview.net/forum?id=example",
            "--expected-filename",
            "req-001.pdf",
        ],
    )

    assert result.exit_code == 0
    request_path = library_root / "manual_downloads" / "requests" / "req-001.yaml"
    assert request_path.exists()
    payload = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    assert payload["title"] == "Difference Predictive Coding for Training Spiking Neural Networks"
    assert payload["authors"] == ["Karlsson", "Lee"]
    assert payload["expected_filenames"] == ["req-001.pdf"]
    readme = (library_root / "manual_downloads" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "Difference Predictive Coding" in readme


def test_resolve_pdf_cli_invokes_paper_search_and_falls_back_to_manual(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def download_with_fallback(self, **kwargs):
            from paper_ops.paper_search_client import PaperSearchError

            raise PaperSearchError("no PDF available across all stages")

    monkeypatch.setattr("paper_ops.cli.PaperSearchClient", _FakeClient)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "resolve-pdf",
            "--library-root",
            str(library_root),
            "--title",
            "Closed Paper",
            "--authors",
            "Author One, Author Two",
            "--year",
            "2026",
            "--direction",
            "predictive_coding",
            "--doi",
            "10.0/closed",
            "--source-url",
            "https://publisher.example/closed-paper",
            "--create-manual-request",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["manual_request_path"] is not None
    assert "10.0/closed" not in payload["manual_request_path"]  # slug-safe
    request_files = list(
        (library_root / "manual_downloads" / "requests").glob("*.yaml")
    )
    assert request_files, "expected a manual request to be created"


def test_summarize_direction_uses_library_root_and_model_settings(
    tmp_path: Path,
    monkeypatch,
):
    seen: dict[str, object] = {}
    library_root = tmp_path / "papers"

    monkeypatch.setattr(
        "paper_ops.cli.load_runtime_settings",
        lambda **kwargs: seen.setdefault("settings_kwargs", kwargs) or object(),
    )

    def fake_generate_direction_summary_for_direction(**kwargs):
        seen.update(kwargs)
        return library_root / "library" / "predictive_coding" / "predictive_coding_summary_zh.md"

    monkeypatch.setattr(
        "paper_ops.cli.generate_direction_summary_for_direction",
        fake_generate_direction_summary_for_direction,
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "summarize",
            "direction",
            "predictive_coding",
            "--library-root",
            str(library_root),
            "--model-provider",
            "claude",
        ],
    )

    assert result.exit_code == 0
    assert seen["library_root"] == library_root
    assert seen["direction"] == "predictive_coding"
    assert seen["settings_kwargs"] == {
        "model_override": None,
        "base_url_override": None,
        "model_provider_override": "claude",
    }
    assert "predictive_coding_summary_zh.md" in result.stdout


def test_summarize_pending_reports_pending_ledger_entries(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"
    pending_paper = library_root / "library" / "predictive_coding" / "paper-1"

    monkeypatch.setattr(
        "paper_ops.cli.pending_paper_dirs_for_direction",
        lambda root, direction: [pending_paper] if direction == "predictive_coding" else [],
    )
    monkeypatch.setattr(
        "paper_ops.cli.pending_directions_for_overview",
        lambda root: ["predictive_coding"],
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "summarize",
            "pending",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    assert "predictive_coding" in result.stdout
    assert "paper-1" in result.stdout


def test_local_pdf_cli_exposes_claude_provider_option():
    runner = CliRunner()
    result = runner.invoke(local_pdf_app, ["--help"])
    assert result.exit_code == 0
    assert "--model-provider" in result.stdout
    assert "claude" in result.stdout


def test_local_pdf_cli_defaults_library_root_to_env(
    tmp_path: Path,
    monkeypatch,
):
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 fake")
    env_root = tmp_path / "env-papers"
    seen: list[Path] = []

    monkeypatch.setenv("PAPER_OPS_LIBRARY_ROOT", str(env_root))
    monkeypatch.setattr(
        process_local_pdf_cli,
        "load_runtime_settings",
        lambda **kwargs: object(),
    )

    def fake_process_local_pdf(**kwargs):
        seen.append(kwargs["library_root"])

        class Result:
            paper_id = "paper-1"
            direction = "predictive_coding"

            class paths:
                paper_dir = env_root / "library" / "predictive_coding" / "paper-1"
                translation_path = paper_dir / "translation_zh.md"

        return Result()

    monkeypatch.setattr(
        process_local_pdf_cli,
        "process_local_pdf",
        fake_process_local_pdf,
    )
    runner = CliRunner()

    result = runner.invoke(
        local_pdf_app,
        [
            str(source_pdf),
            "Example Paper",
            "Author",
            "2026",
        ],
    )

    assert result.exit_code == 0
    assert seen == [env_root]


def test_setup_command_invokes_setup_paper_search(monkeypatch):
    from paper_ops.paper_search_client import SetupReport

    fake_report = SetupReport(
        node_version="v20.0.0",
        npm_version="10.0.0",
        dist_built=True,
        cli_path=Path("/tmp/vendor/dist/cli.js"),
        install_log_tail="added 100 packages",
        build_log_tail="built ok",
    )

    monkeypatch.setattr("paper_ops.cli.setup_paper_search", lambda: fake_report)
    runner = CliRunner()
    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["node_version"] == "v20.0.0"
    assert payload["dist_built"] is True


def test_discover_with_query_uses_paper_search_client(tmp_path: Path, monkeypatch):
    from paper_ops.paper_search_client import PaperSearchResult

    library_root = tmp_path / "papers"
    fake_results = [
        PaperSearchResult(
            paper_id="10.0/x",
            title="Predictive coding x",
            authors=["Alice"],
            doi="10.0/x",
            url="https://example.com/x",
            source="crossref",
            year=2024,
        )
    ]

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, **kwargs):
            assert query == "predictive coding"
            return fake_results

    monkeypatch.setattr(
        "paper_ops.paper_search_client.PaperSearchClient", _FakeClient
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "discover",
            "--query",
            "predictive coding",
            "--platform",
            "crossref",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "paper-search"
    entries = CandidateQueue(library_root / "candidates" / "queue.json").load()
    assert [entry.title for entry in entries] == ["Predictive coding x"]

def test_discover_requires_source_or_query():
    runner = CliRunner()
    result = runner.invoke(app, ["discover"])
    assert result.exit_code != 0
    assert "--source" in result.stdout or "--query" in result.stdout or "--source" in result.stderr or "--query" in result.stderr


def test_fetch_dry_run_reports_candidates_without_downloads(
    tmp_path: Path,
    monkeypatch,
):
    from paper_ops.paper_search_client import PaperSearchResult

    library_root = tmp_path / "papers"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, **kwargs):
            return [
                PaperSearchResult(
                    paper_id="10.0/y",
                    title="Predictive coding y",
                    authors=["Bob"],
                    doi="10.0/y",
                    url="https://example.com/y",
                    source="crossref",
                    year=2024,
                )
            ]

        def download_with_fallback(self, **kwargs):  # pragma: no cover - dry run
            raise AssertionError("dry run must not download")

    monkeypatch.setattr(
        "paper_ops.paper_search_client.PaperSearchClient", _FakeClient
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "fetch",
            "predictive coding",
            "--top",
            "1",
            "--dry-run",
            "--library-root",
            str(library_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["title"] == "Predictive coding y"
