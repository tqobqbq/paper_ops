from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from paper_ops.paper_search_client import (
    PaperSearchClient,
    PaperSearchError,
    PaperSearchResult,
    _extract_pdf_path_from_message,
    to_discovery_candidate,
    to_paper_metadata,
)


def _completed(stdout: str, stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["node"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _client_with_cli(tmp_path: Path) -> PaperSearchClient:
    cli_path = tmp_path / "cli.js"
    cli_path.write_text("// fake\n")
    return PaperSearchClient(cli_path=cli_path)


def test_paper_search_result_parses_paper_factory_dict():
    payload = {
        "paper_id": "10.0/example",
        "title": "Example",
        "authors": "Alice; Bob; ",
        "abstract": "abs",
        "doi": "10.0/example",
        "pdf_url": "https://example.com/x.pdf",
        "url": "https://example.com/x",
        "source": "crossref",
        "journal": "Journal X",
        "year": 2024,
    }
    result = PaperSearchResult.from_paper_search_dict(payload)
    assert result.authors == ["Alice", "Bob"]
    assert result.year == 2024
    assert result.title == "Example"


def test_paper_search_result_handles_list_authors_and_string_year():
    payload = {
        "paper_id": "x",
        "title": "T",
        "authors": ["A", "B"],
        "year": "2023",
    }
    result = PaperSearchResult.from_paper_search_dict(payload)
    assert result.authors == ["A", "B"]
    assert result.year == 2023


def test_search_parses_data_list(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    fake_stdout = json.dumps(
        {
            "ok": True,
            "tool": "search_papers",
            "message": "Found 1 papers.",
            "data": [
                {
                    "paper_id": "p1",
                    "title": "Paper 1",
                    "authors": "Alice; Bob",
                    "source": "crossref",
                    "year": 2024,
                }
            ],
        }
    )

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _completed(fake_stdout)

    monkeypatch.setattr("paper_ops.paper_search_client.subprocess.run", fake_run)
    results = client.search(
        "predictive coding",
        platform="crossref",
        sources=None,
        max_results=3,
        year="2023-2025",
    )

    assert [r.title for r in results] == ["Paper 1"]
    assert "search" in captured["cmd"]
    assert "predictive coding" in captured["cmd"]
    assert "--platform" in captured["cmd"]
    assert "crossref" in captured["cmd"]
    assert "--max-results" in captured["cmd"]
    assert "3" in captured["cmd"]
    assert "--year" in captured["cmd"]
    assert "2023-2025" in captured["cmd"]


def test_run_raises_on_empty_stdout(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    monkeypatch.setattr(
        "paper_ops.paper_search_client.subprocess.run",
        lambda *args, **kwargs: _completed("", stderr="boom", returncode=1),
    )
    with pytest.raises(PaperSearchError, match="empty stdout"):
        client.search("x")


def test_run_raises_on_non_json_stdout(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    monkeypatch.setattr(
        "paper_ops.paper_search_client.subprocess.run",
        lambda *args, **kwargs: _completed("not json"),
    )
    with pytest.raises(PaperSearchError, match="non-JSON"):
        client.search("x")


def test_run_raises_on_ok_false(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    payload = json.dumps(
        {"ok": False, "tool": "search_papers", "message": "missing API key"}
    )
    monkeypatch.setattr(
        "paper_ops.paper_search_client.subprocess.run",
        lambda *args, **kwargs: _completed(payload),
    )
    with pytest.raises(PaperSearchError, match="missing API key"):
        client.search("x")


def test_ensure_built_raises_when_dist_missing(tmp_path: Path):
    client = PaperSearchClient(cli_path=tmp_path / "missing.js")
    with pytest.raises(PaperSearchError, match="paper-ops setup"):
        client.search("x")


def test_download_parses_path_from_message(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    payload = json.dumps(
        {
            "ok": True,
            "tool": "download_paper",
            "message": "PDF downloaded successfully to: /tmp/x.pdf",
            "data": None,
        }
    )
    monkeypatch.setattr(
        "paper_ops.paper_search_client.subprocess.run",
        lambda *args, **kwargs: _completed(payload),
    )
    path = client.download(
        "10.0/x", platform="arxiv", save_path=tmp_path / "downloads"
    )
    assert path == Path("/tmp/x.pdf")


def test_download_with_fallback_returns_path_from_data(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    payload = json.dumps(
        {
            "ok": True,
            "tool": "download_with_fallback",
            "message": "Download with fallback ok.",
            "data": {
                "status": "ok",
                "path": "/tmp/y.pdf",
                "attempts": [{"stage": "primary", "status": "ok", "message": "/tmp/y.pdf"}],
            },
        }
    )
    monkeypatch.setattr(
        "paper_ops.paper_search_client.subprocess.run",
        lambda *args, **kwargs: _completed(payload),
    )
    path = client.download_with_fallback(
        source="crossref",
        paper_id="10.0/y",
        doi="10.0/y",
        save_path=tmp_path / "downloads",
    )
    assert path == Path("/tmp/y.pdf")


def test_download_with_fallback_raises_when_status_not_ok(monkeypatch, tmp_path: Path):
    client = _client_with_cli(tmp_path)
    payload = json.dumps(
        {
            "ok": True,
            "tool": "download_with_fallback",
            "message": "Download with fallback error.",
            "data": {
                "status": "error",
                "attempts": [
                    {"stage": "primary", "status": "error", "message": "404"},
                    {"stage": "scihub", "status": "error", "message": "no mirror"},
                ],
            },
        }
    )
    monkeypatch.setattr(
        "paper_ops.paper_search_client.subprocess.run",
        lambda *args, **kwargs: _completed(payload),
    )
    with pytest.raises(PaperSearchError, match="no PDF"):
        client.download_with_fallback(
            source="crossref",
            paper_id="10.0/y",
            save_path=tmp_path / "downloads",
        )


def test_extract_pdf_path_from_message_strips_marker():
    assert _extract_pdf_path_from_message("PDF downloaded successfully to: /tmp/a.pdf") == "/tmp/a.pdf"
    assert _extract_pdf_path_from_message("PDF downloaded successfully to: /tmp/a.pdf\nextra") == "/tmp/a.pdf"
    assert _extract_pdf_path_from_message("no marker here") is None


def test_to_paper_metadata_handles_minimal_result():
    result = PaperSearchResult(
        paper_id="p", title="T", source="crossref", year=2024, authors=["A"]
    )
    metadata = to_paper_metadata(result)
    assert metadata.title == "T"
    assert metadata.year == 2024
    assert metadata.authors == ["A"]


def test_to_discovery_candidate_uses_url_then_doi():
    result_with_url = PaperSearchResult(
        paper_id="p", title="T", source="crossref", url="https://u/p"
    )
    candidate = to_discovery_candidate(result_with_url, discovered_from="test")
    assert candidate.source_url == "https://u/p"

    result_no_url = PaperSearchResult(paper_id="p", title="T", source="crossref", doi="10.0/p")
    candidate2 = to_discovery_candidate(result_no_url, discovered_from="test")
    assert candidate2.source_url == "10.0/p"
