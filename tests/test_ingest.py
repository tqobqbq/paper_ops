import hashlib
import json
from pathlib import Path

import pytest

from paper_ops.ingest import IngestResult, ingest_local_pdf
from paper_ops.paths import paper_id_from_metadata


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


def payload_to_metadata(payload: dict) -> object:
    from paper_ops.models import PaperMetadata

    return PaperMetadata(**payload["metadata"])
