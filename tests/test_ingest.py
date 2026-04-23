import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from paper_ops.ingest import IngestResult, ingest_local_pdf
from paper_ops.paths import paper_id_from_metadata
from paper_ops.fetchers import fetch_url_metadata


def test_ingest_local_pdf_copies_pdf_and_writes_metadata(tmp_path: Path):
    source_pdf = tmp_path / "source.pdf"
    pdf_bytes = b"%PDF-1.4\nfake pdf bytes\n"
    source_pdf.write_bytes(pdf_bytes)

    result = ingest_local_pdf(
        source_pdf=source_pdf,
        library_root=tmp_path,
        direction="predictive_coding",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        authors=["Karlsson", "Lee"],
        year=2026,
        venue="ICLR",
    )

    assert isinstance(result, IngestResult)
    assert result.paths.pdf_path.exists()
    assert result.paths.metadata_path.exists()
    assert result.paths.pdf_path.read_bytes() == pdf_bytes

    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()
    payload = json.loads(result.paths.metadata_path.read_text(encoding="utf-8"))
    assert payload["paper_id"] == result.paper_id
    assert payload["source"]["type"] == "pdf"
    assert payload["source"]["local_path"] == str(source_pdf)
    assert payload["hashes"]["pdf_sha256"] == expected_hash
    assert payload["status"]["ingested"]["state"] == "completed"

    expected_id = paper_id_from_metadata(
        payload_to_metadata(payload)
    )
    assert result.paper_id == expected_id


def test_fetch_url_metadata_uses_html_title():
    response = Mock()
    response.raise_for_status.return_value = None
    response.text = "<html><head><title>  Example Paper Title  </title></head><body></body></html>"

    with patch("paper_ops.fetchers.requests.get", return_value=response) as get_mock:
        metadata = fetch_url_metadata("https://example.com/paper")

    get_mock.assert_called_once_with("https://example.com/paper", timeout=30)
    assert metadata == {"title": "Example Paper Title"}


def test_ingest_local_pdf_rejects_duplicate_ingest_with_different_content(tmp_path: Path):
    first_source_pdf = tmp_path / "source-1.pdf"
    second_source_pdf = tmp_path / "source-2.pdf"
    first_bytes = b"%PDF-1.4\nfirst bytes\n"
    second_bytes = b"%PDF-1.4\nsecond bytes\n"
    first_source_pdf.write_bytes(first_bytes)
    second_source_pdf.write_bytes(second_bytes)

    first_result = ingest_local_pdf(
        source_pdf=first_source_pdf,
        library_root=tmp_path,
        direction="predictive_coding",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        authors=["Karlsson", "Lee"],
        year=2026,
        venue="ICLR",
    )

    with pytest.raises(FileExistsError):
        ingest_local_pdf(
            source_pdf=second_source_pdf,
            library_root=tmp_path,
            direction="predictive_coding",
            title="Difference Predictive Coding for Training Spiking Neural Networks",
            authors=["Karlsson", "Lee"],
            year=2026,
            venue="ICLR",
        )

    archived_bytes = first_result.paths.pdf_path.read_bytes()
    archived_payload = json.loads(first_result.paths.metadata_path.read_text(encoding="utf-8"))
    assert archived_bytes == first_bytes
    assert archived_payload["hashes"]["pdf_sha256"] == hashlib.sha256(first_bytes).hexdigest()


@pytest.mark.parametrize(
    ("html", "url"),
    [
        ("<html><head></head><body></body></html>", "https://example.com/no-title"),
        ("<html><head><title>   </title></head><body></body></html>", "https://example.com/blank-title"),
    ],
)
def test_fetch_url_metadata_falls_back_to_url_when_title_missing_or_blank(html: str, url: str):
    response = Mock()
    response.raise_for_status.return_value = None
    response.text = html

    with patch("paper_ops.fetchers.requests.get", return_value=response):
        metadata = fetch_url_metadata(url)

    assert metadata == {"title": url}


def test_fetch_url_metadata_propagates_http_errors():
    response = Mock()
    response.raise_for_status.side_effect = RuntimeError("boom")
    response.text = ""

    with patch("paper_ops.fetchers.requests.get", return_value=response):
        with pytest.raises(RuntimeError, match="boom"):
            fetch_url_metadata("https://example.com/error")


def payload_to_metadata(payload: dict) -> object:
    from paper_ops.models import PaperMetadata

    return PaperMetadata(**payload["metadata"])
