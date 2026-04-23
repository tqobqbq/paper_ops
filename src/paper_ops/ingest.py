from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil

from paper_ops.library import ensure_paper_archive
from paper_ops.models import PaperMetadata, PaperPaths, PaperRecord, ProcessingStatus, SourceInfo
from paper_ops.paths import paper_id_from_metadata, paper_paths


@dataclass(frozen=True)
class IngestResult:
    paper_id: str
    paths: PaperPaths


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_local_pdf(
    source_pdf: Path,
    library_root: Path,
    direction: str,
    title: str,
    authors: list[str],
    year: int,
    venue: str | None,
) -> IngestResult:
    metadata = PaperMetadata(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        source_urls=[],
    )
    paper_id = paper_id_from_metadata(metadata)
    paths = paper_paths(library_root, paper_id, direction)

    ensure_paper_archive(paths)
    shutil.copy2(source_pdf, paths.pdf_path)

    record = PaperRecord(
        paper_id=paper_id,
        title=title,
        direction=direction,
        status=ProcessingStatus(),
        source=SourceInfo(type="pdf", local_path=str(source_pdf)),
        metadata=metadata,
    )
    payload = record.model_dump()
    payload["hashes"] = {"pdf_sha256": sha256_file(paths.pdf_path)}
    paths.metadata_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return IngestResult(paper_id=paper_id, paths=paths)
