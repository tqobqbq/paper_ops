from pathlib import Path

import pytest
import yaml

from paper_ops.manual_downloads import (
    ManualDownloadRequest,
    ManualProcessResult,
    create_manual_download_request,
    process_manual_downloads_once,
    render_manual_download_readme,
)


def _write_request(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_render_manual_download_readme_groups_requests_by_status(tmp_path: Path):
    library_root = tmp_path / "papers"
    manual_root = library_root / "manual_downloads"
    _write_request(
        manual_root / "requests" / "req-001.yaml",
        {
            "request_id": "req-001",
            "status": "waiting_for_manual_pdf",
            "created_at": "2026-05-18T00:00:00Z",
            "updated_at": "2026-05-18T00:00:00Z",
            "title": "Difference Predictive Coding for Training Spiking Neural Networks",
            "authors": ["Karlsson", "Lee"],
            "year": 2026,
            "direction": "predictive_coding",
            "source_url": "https://openreview.net/forum?id=example",
            "expected_filenames": ["req-001.pdf"],
        },
    )
    _write_request(
        manual_root / "processed" / "req-002.yaml",
        {
            "request_id": "req-002",
            "status": "processed",
            "title": "Finished Paper",
            "authors": ["Lee"],
            "year": 2026,
            "direction": "local_learning",
            "expected_filenames": ["req-002.pdf"],
            "linked_paper_id": "2026-lee-finished-paper",
            "processed_at": "2026-05-18T01:00:00Z",
        },
    )

    readme_path = render_manual_download_readme(
        library_root, now="2026-05-18T02:00:00Z"
    )

    readme = readme_path.read_text(encoding="utf-8")
    assert "# Manual Downloads" in readme
    assert "Last updated: 2026-05-18T02:00:00Z" in readme
    assert "## Waiting" in readme
    assert "req-001.pdf" in readme
    assert "Difference Predictive Coding" in readme
    assert "## Processed" in readme
    assert "2026-lee-finished-paper" in readme


def test_create_manual_download_request_writes_yaml_and_refreshes_readme(
    tmp_path: Path,
):
    library_root = tmp_path / "papers"
    request = ManualDownloadRequest(
        request_id="req-001",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        authors=["Karlsson", "Lee"],
        year=2026,
        direction="predictive_coding",
        source_url="https://openreview.net/forum?id=example",
        expected_filenames=["req-001.pdf"],
    )

    request_path = create_manual_download_request(
        library_root,
        request,
        now="2026-05-18T02:00:00Z",
    )

    assert request_path == library_root / "manual_downloads" / "requests" / "req-001.yaml"
    payload = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "waiting_for_manual_pdf"
    assert payload["created_at"] == "2026-05-18T02:00:00Z"
    assert payload["updated_at"] == "2026-05-18T02:00:00Z"
    assert payload["expected_filenames"] == ["req-001.pdf"]
    readme = (library_root / "manual_downloads" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "Difference Predictive Coding" in readme


def test_process_manual_downloads_once_matches_pdf_and_moves_request(
    tmp_path: Path,
):
    library_root = tmp_path / "papers"
    manual_root = library_root / "manual_downloads"
    _write_request(
        manual_root / "requests" / "req-001.yaml",
        {
            "request_id": "req-001",
            "status": "waiting_for_manual_pdf",
            "created_at": "2026-05-18T00:00:00Z",
            "updated_at": "2026-05-18T00:00:00Z",
            "title": "Difference Predictive Coding for Training Spiking Neural Networks",
            "authors": ["Karlsson", "Lee"],
            "year": 2026,
            "venue": "ICLR",
            "direction": "predictive_coding",
            "abstract": "A predictive coding method for SNNs.",
            "keywords": ["predictive coding", "spiking neural network"],
            "expected_filenames": ["req-001.pdf"],
        },
    )
    inbox_pdf = manual_root / "inbox" / "req-001.pdf"
    inbox_pdf.parent.mkdir(parents=True, exist_ok=True)
    inbox_pdf.write_bytes(b"%PDF-1.4 fake")
    seen: list[tuple[Path, str]] = []

    def fake_processor(pdf_path, request):
        assert not (manual_root / "requests" / "req-001.yaml").exists()
        assert (manual_root / "processing" / "req-001.yaml").exists()
        seen.append((pdf_path, request.request_id))
        return ManualProcessResult(
            paper_id="2026-karlsson-difference-predictive-coding",
            paper_dir=library_root
            / "library"
            / "predictive_coding"
            / "2026-karlsson-difference-predictive-coding",
        )

    result = process_manual_downloads_once(
        library_root,
        processor=fake_processor,
        now="2026-05-18T02:00:00Z",
    )

    assert result.processed_count == 1
    assert result.failed_count == 0
    assert seen == [(inbox_pdf, "req-001")]
    assert not (manual_root / "requests" / "req-001.yaml").exists()
    assert not (manual_root / "processing" / "req-001.yaml").exists()
    processed_path = manual_root / "processed" / "req-001.yaml"
    assert processed_path.exists()

    payload = yaml.safe_load(processed_path.read_text(encoding="utf-8"))
    assert payload["status"] == "processed"
    assert payload["linked_paper_id"] == "2026-karlsson-difference-predictive-coding"
    assert payload["resolved_pdf_path"] == str(inbox_pdf)
    assert payload["processed_at"] == "2026-05-18T02:00:00Z"
    assert payload["pdf_sha256"]

    readme = (manual_root / "README.md").read_text(encoding="utf-8")
    assert "No waiting manual downloads." in readme
    assert "2026-karlsson-difference-predictive-coding" in readme


def test_process_manual_downloads_once_records_failure_without_moving_request(
    tmp_path: Path,
):
    library_root = tmp_path / "papers"
    manual_root = library_root / "manual_downloads"
    _write_request(
        manual_root / "requests" / "req-001.yaml",
        {
            "request_id": "req-001",
            "status": "waiting_for_manual_pdf",
            "title": "Problem Paper",
            "authors": ["Author"],
            "year": 2026,
            "direction": "predictive_coding",
            "expected_filenames": ["req-001.pdf"],
        },
    )
    inbox_pdf = manual_root / "inbox" / "req-001.pdf"
    inbox_pdf.parent.mkdir(parents=True, exist_ok=True)
    inbox_pdf.write_bytes(b"%PDF-1.4 fake")

    def failing_processor(pdf_path, request):
        raise RuntimeError("processing failed")

    result = process_manual_downloads_once(
        library_root,
        processor=failing_processor,
        now="2026-05-18T02:00:00Z",
    )

    assert result.processed_count == 0
    assert result.failed_count == 1
    active_path = manual_root / "requests" / "req-001.yaml"
    assert active_path.exists()
    assert not (manual_root / "processing" / "req-001.yaml").exists()
    assert not (manual_root / "processed" / "req-001.yaml").exists()

    payload = yaml.safe_load(active_path.read_text(encoding="utf-8"))
    assert payload["status"] == "processing_failed"
    assert payload["last_error"] == "processing failed"
    assert payload["resolved_pdf_path"] == str(inbox_pdf)

    readme = (manual_root / "README.md").read_text(encoding="utf-8")
    assert "## Processing Failed" in readme
    assert "Problem Paper" in readme
    assert "processing failed" in readme
