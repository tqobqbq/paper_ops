from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from paper_ops.classify import classify_direction
from paper_ops.indexer import rebuild_indexes
from paper_ops.ingest import IngestResult, ingest_local_pdf
from paper_ops.models import PaperPaths, PaperRecord
from paper_ops.settings import RuntimeSettings, load_runtime_settings
from paper_ops.summarize import write_summary_files
from paper_ops.translate import translate_pdf_to_markdown


@dataclass(frozen=True)
class ProcessResult:
    paper_id: str
    direction: str
    paths: PaperPaths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_record(paths: PaperPaths) -> tuple[PaperRecord, dict]:
    payload = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    hashes = payload.get("hashes", {})
    return PaperRecord.model_validate(payload), hashes


def _write_record(paths: PaperPaths, record: PaperRecord, hashes: dict) -> None:
    payload = record.model_dump(mode="json")
    if hashes:
        payload["hashes"] = hashes
    paths.metadata_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _mark_stage(record: PaperRecord, stage_name: str) -> None:
    stage = getattr(record.status, stage_name)
    stage.state = "completed"
    stage.updated_at = _utc_now()
    stage.last_error = None


def process_local_pdf(
    source_pdf: Path,
    library_root: Path,
    title: str,
    authors: list[str],
    year: int,
    venue: str | None,
    abstract: str = "",
    keywords: list[str] | None = None,
    direction: str | None = None,
    settings: RuntimeSettings | None = None,
) -> ProcessResult:
    normalized_keywords = keywords or []
    resolved_direction = direction or classify_direction(
        title=title,
        abstract=abstract,
        keywords=normalized_keywords,
    )
    runtime_settings = settings or load_runtime_settings()

    ingest_result: IngestResult = ingest_local_pdf(
        source_pdf=source_pdf,
        library_root=library_root,
        direction=resolved_direction,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
    )

    record, hashes = _load_record(ingest_result.paths)
    record.metadata.keywords = list(normalized_keywords)
    if record.status.ingested.updated_at is None:
        record.status.ingested.updated_at = _utc_now()
    _mark_stage(record, "classified")
    _write_record(ingest_result.paths, record, hashes)

    translate_pdf_to_markdown(
        pdf_path=ingest_result.paths.pdf_path,
        output_path=ingest_result.paths.translation_path,
        settings=runtime_settings,
    )
    record, hashes = _load_record(ingest_result.paths)
    _mark_stage(record, "translated")
    _write_record(ingest_result.paths, record, hashes)

    translation_text = ingest_result.paths.translation_path.read_text(encoding="utf-8")
    write_summary_files(
        paper_dir=ingest_result.paths.paper_dir,
        metadata={"title": title, "direction": resolved_direction},
        translation_text=translation_text,
    )
    record, hashes = _load_record(ingest_result.paths)
    _mark_stage(record, "summarized")
    _mark_stage(record, "indexed")
    _write_record(ingest_result.paths, record, hashes)

    rebuild_indexes(library_root)

    return ProcessResult(
        paper_id=ingest_result.paper_id,
        direction=resolved_direction,
        paths=ingest_result.paths,
    )
