from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field


MANUAL_DOWNLOADS_DIR = "manual_downloads"


class ManualDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    status: str = "waiting_for_manual_pdf"
    created_at: str | None = None
    updated_at: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    direction: str | None = None
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    candidate_id: str | None = None
    source_url: str | None = None
    landing_pages: list[str] = Field(default_factory=list)
    legal_pdf_attempts: list[dict[str, Any]] = Field(default_factory=list)
    expected_filenames: list[str] = Field(default_factory=list)
    manual_note: str | None = None
    resolved_pdf_path: str | None = None
    linked_paper_id: str | None = None
    paper_dir: str | None = None
    processed_at: str | None = None
    pdf_sha256: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class ManualProcessResult:
    paper_id: str
    paper_dir: Path


@dataclass(frozen=True)
class ManualSweepResult:
    processed_count: int
    failed_count: int
    readme_path: Path


ManualProcessor = Callable[[Path, ManualDownloadRequest], ManualProcessResult]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _manual_root(library_root: Path) -> Path:
    return library_root / MANUAL_DOWNLOADS_DIR


def _ensure_manual_dirs(library_root: Path) -> Path:
    manual_root = _manual_root(library_root)
    for dirname in ("inbox", "requests", "processing", "processed", "rejected"):
        (manual_root / dirname).mkdir(parents=True, exist_ok=True)
    return manual_root


def _load_request(path: Path) -> ManualDownloadRequest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ManualDownloadRequest.model_validate(payload)


def _dump_request(path: Path, request: ManualDownloadRequest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = request.model_dump(mode="json", exclude_none=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    tmp_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _claim_request_path(request_path: Path, processing_dir: Path) -> Path | None:
    claim_path = processing_dir / request_path.name
    if claim_path.exists():
        return None
    try:
        request_path.rename(claim_path)
    except FileNotFoundError:
        return None
    return claim_path


def create_manual_download_request(
    library_root: Path,
    request: ManualDownloadRequest,
    *,
    now: str | None = None,
) -> Path:
    manual_root = _ensure_manual_dirs(library_root)
    timestamp = now or _utc_now()
    expected_filenames = request.expected_filenames or [f"{request.request_id}.pdf"]
    created_at = request.created_at or timestamp
    updated = request.model_copy(
        update={
            "status": "waiting_for_manual_pdf",
            "created_at": created_at,
            "updated_at": timestamp,
            "expected_filenames": expected_filenames,
        }
    )
    request_path = manual_root / "requests" / f"{request.request_id}.yaml"
    _dump_request(request_path, updated)
    render_manual_download_readme(library_root, now=timestamp)
    return request_path


def _load_requests(directory: Path) -> list[ManualDownloadRequest]:
    if not directory.exists():
        return []
    requests: list[ManualDownloadRequest] = []
    for path in sorted(directory.glob("*.yaml")):
        requests.append(_load_request(path))
    return requests


def _markdown_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _first_expected_filename(request: ManualDownloadRequest) -> str:
    if request.expected_filenames:
        return request.expected_filenames[0]
    return f"{request.request_id}.pdf"


def _render_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_escape(cell) for cell in row) + " |")
    return lines


def render_manual_download_readme(
    library_root: Path,
    *,
    now: str | None = None,
) -> Path:
    manual_root = _ensure_manual_dirs(library_root)
    active_requests = _load_requests(manual_root / "requests")
    processed_requests = _load_requests(manual_root / "processed")
    rejected_requests = _load_requests(manual_root / "rejected")

    waiting = [
        request
        for request in active_requests
        if request.status == "waiting_for_manual_pdf"
    ]
    failed = [
        request
        for request in active_requests
        if request.status == "processing_failed"
    ]

    lines = [
        "# Manual Downloads",
        "",
        f"Last updated: {now or _utc_now()}",
        "",
        "## Waiting",
        "",
    ]
    if waiting:
        lines.extend(
            _render_table(
                ["Request", "Title", "Year", "Direction", "Expected filename", "Source"],
                [
                    [
                        request.request_id,
                        request.title,
                        request.year or "",
                        request.direction or "",
                        _first_expected_filename(request),
                        request.source_url or "",
                    ]
                    for request in waiting
                ],
            )
        )
    else:
        lines.append("No waiting manual downloads.")

    lines.extend(["", "## Processing Failed", ""])
    if failed:
        lines.extend(
            _render_table(
                ["Request", "Title", "Error", "PDF"],
                [
                    [
                        request.request_id,
                        request.title,
                        request.last_error or "",
                        request.resolved_pdf_path or "",
                    ]
                    for request in failed
                ],
            )
        )
    else:
        lines.append("No failed manual downloads.")

    lines.extend(["", "## Processed", ""])
    if processed_requests:
        lines.extend(
            _render_table(
                ["Request", "Title", "Paper ID", "Processed At"],
                [
                    [
                        request.request_id,
                        request.title,
                        request.linked_paper_id or "",
                        request.processed_at or "",
                    ]
                    for request in processed_requests
                ],
            )
        )
    else:
        lines.append("No processed manual downloads.")

    lines.extend(["", "## Rejected", ""])
    if rejected_requests:
        lines.extend(
            _render_table(
                ["Request", "Title", "Reason"],
                [
                    [
                        request.request_id,
                        request.title,
                        request.last_error or request.manual_note or "",
                    ]
                    for request in rejected_requests
                ],
            )
        )
    else:
        lines.append("No rejected manual downloads.")

    readme_path = manual_root / "README.md"
    tmp_path = readme_path.with_suffix(".md.tmp")
    tmp_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp_path.replace(readme_path)
    return readme_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_candidates(request: ManualDownloadRequest) -> list[str]:
    filenames = list(request.expected_filenames)
    fallback = f"{request.request_id}.pdf"
    if fallback not in filenames:
        filenames.append(fallback)
    return filenames


def _match_inbox_pdf(inbox_dir: Path, request: ManualDownloadRequest) -> Path | None:
    for filename in _pdf_candidates(request):
        candidate = inbox_dir / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def process_manual_downloads_once(
    library_root: Path,
    *,
    processor: ManualProcessor,
    now: str | None = None,
) -> ManualSweepResult:
    manual_root = _ensure_manual_dirs(library_root)
    timestamp = now or _utc_now()
    processed_count = 0
    failed_count = 0

    for request_path in sorted((manual_root / "requests").glob("*.yaml")):
        claim_path = _claim_request_path(request_path, manual_root / "processing")
        if claim_path is None:
            continue
        request = _load_request(claim_path)
        if request.status not in {"waiting_for_manual_pdf", "processing_failed"}:
            claim_path.rename(request_path)
            continue
        matched_pdf = _match_inbox_pdf(manual_root / "inbox", request)
        if matched_pdf is None:
            claim_path.rename(request_path)
            continue

        updated = request.model_copy(
            update={
                "status": "processing",
                "updated_at": timestamp,
                "resolved_pdf_path": str(matched_pdf),
                "pdf_sha256": _sha256_file(matched_pdf),
            }
        )
        _dump_request(claim_path, updated)
        try:
            result = processor(matched_pdf, updated)
        except Exception as exc:
            failed = updated.model_copy(
                update={
                    "status": "processing_failed",
                    "updated_at": timestamp,
                    "last_error": str(exc),
                }
            )
            _dump_request(request_path, failed)
            claim_path.unlink(missing_ok=True)
            failed_count += 1
            continue

        processed = updated.model_copy(
            update={
                "status": "processed",
                "updated_at": timestamp,
                "processed_at": timestamp,
                "linked_paper_id": result.paper_id,
                "paper_dir": str(result.paper_dir),
                "last_error": None,
            }
        )
        processed_path = manual_root / "processed" / request_path.name
        _dump_request(processed_path, processed)
        claim_path.unlink(missing_ok=True)
        processed_count += 1

    readme_path = render_manual_download_readme(library_root, now=timestamp)
    return ManualSweepResult(
        processed_count=processed_count,
        failed_count=failed_count,
        readme_path=readme_path,
    )


def watch_manual_downloads(
    library_root: Path,
    *,
    processor: ManualProcessor,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    iterations = 0
    while True:
        process_manual_downloads_once(library_root, processor=processor)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return
        time.sleep(interval_seconds)
