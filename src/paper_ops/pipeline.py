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
from paper_ops.summary_ledger import record_paper_artifacts
from paper_ops.summarize import (
    generate_direction_and_overview_summaries,
    generate_paper_artifacts,
)
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


def _mark_stage_failed(record: PaperRecord, stage_name: str, error: Exception) -> None:
    stage = getattr(record.status, stage_name)
    stage.state = "failed"
    stage.updated_at = _utc_now()
    stage.last_error = str(error)


def _mark_stage_skipped(record: PaperRecord, stage_name: str, reason: str) -> None:
    stage = getattr(record.status, stage_name)
    stage.state = "skipped"
    stage.updated_at = _utc_now()
    stage.last_error = reason


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
    refresh_direction_and_overview_summaries: bool = False,
    refresh_indexes: bool = True,
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

    paper_metadata = {
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "direction": resolved_direction,
        "keywords": normalized_keywords,
    }

    record, hashes = _load_record(ingest_result.paths)
    try:
        translate_pdf_to_markdown(
            pdf_path=ingest_result.paths.pdf_path,
            output_path=ingest_result.paths.translation_path,
            settings=runtime_settings,
            metadata=paper_metadata,
        )
    except Exception as exc:
        _mark_stage_failed(record, "translated", exc)
        _write_record(ingest_result.paths, record, hashes)
    else:
        _mark_stage(record, "translated")
        _write_record(ingest_result.paths, record, hashes)

    try:
        artifact_summary = generate_paper_artifacts(
            pdf_path=ingest_result.paths.pdf_path,
            paths=ingest_result.paths,
            metadata=paper_metadata,
            settings=runtime_settings,
        )
    except Exception as exc:
        record, hashes = _load_record(ingest_result.paths)
        _mark_stage_failed(record, "summarized", exc)
        _write_record(ingest_result.paths, record, hashes)
        raise

    non_translation_failures = artifact_summary.failed
    if non_translation_failures:
        formatted_error = "; ".join(
            f"{name}: {error}" for name, error in sorted(non_translation_failures.items())
        )
        record, hashes = _load_record(ingest_result.paths)
        _mark_stage_failed(record, "summarized", RuntimeError(formatted_error))
        _write_record(ingest_result.paths, record, hashes)
        raise RuntimeError(f"Artifact generation failed: {formatted_error}")

    record_paper_artifacts(library_root, ingest_result.paths)

    if refresh_direction_and_overview_summaries:
        try:
            generate_direction_and_overview_summaries(
                library_root=library_root,
                paper_paths=ingest_result.paths,
                direction=resolved_direction,
                settings=runtime_settings,
            )
        except Exception as exc:
            _mark_stage_failed(record, "summarized", exc)
            _write_record(ingest_result.paths, record, hashes)
            raise
        else:
            _mark_stage(record, "summarized")
            _write_record(ingest_result.paths, record, hashes)
    else:
        record, hashes = _load_record(ingest_result.paths)
        _mark_stage(record, "summarized")
        _write_record(ingest_result.paths, record, hashes)

    if refresh_indexes:
        try:
            rebuild_indexes(library_root)
        except Exception as exc:
            record, hashes = _load_record(ingest_result.paths)
            _mark_stage_failed(record, "indexed", exc)
            _write_record(ingest_result.paths, record, hashes)
            raise

        record, hashes = _load_record(ingest_result.paths)
        _mark_stage(record, "indexed")
        _write_record(ingest_result.paths, record, hashes)
    else:
        record, hashes = _load_record(ingest_result.paths)
        _mark_stage_skipped(
            record,
            "indexed",
            "Batch pipeline defers index rebuild until the library-level rebuild step.",
        )
        _write_record(ingest_result.paths, record, hashes)

    return ProcessResult(
        paper_id=ingest_result.paper_id,
        direction=resolved_direction,
        paths=ingest_result.paths,
    )
