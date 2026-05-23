from __future__ import annotations

import json
import mimetypes
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests

from paper_ops.models import PaperPaths
from paper_ops.settings import RuntimeSettings


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
FILES_TIMEOUT_SECONDS = 120
RESPONSE_TIMEOUT_SECONDS_DEFAULT = 3600
POLL_TIMEOUT_SECONDS_DEFAULT = 3600
POLL_INTERVAL_SECONDS = 2
REQUEST_MAX_ATTEMPTS = 3
REQUEST_SPACING_SECONDS = float(
    os.environ.get("PAPER_OPS_REQUEST_SPACING_SECONDS", "0")
)
TERMINAL_RESPONSE_STATUSES = {"completed", "failed", "cancelled", "incomplete"}
PENDING_RESPONSE_STATUSES = {"queued", "in_progress"}
CODE_LINKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "official": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["name", "url", "evidence"],
            },
        },
        "community": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["name", "url", "evidence"],
            },
        },
        "mentioned_but_unlinked": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["name", "context"],
            },
        },
        "baseline_ready": {"type": "boolean"},
        "baseline_ready_reason": {"type": "string"},
    },
    "required": [
        "official",
        "community",
        "mentioned_but_unlinked",
        "baseline_ready",
        "baseline_ready_reason",
    ],
}


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    prompt_filename: str
    output_path_attr: str
    output_kind: Literal["markdown", "json"]
    schema_name: str | None = None
    schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ArtifactRunSummary:
    completed: dict[str, Path]
    failed: dict[str, str]


@dataclass(frozen=True)
class SourcePayload:
    file_id: str | None = None
    text: str | None = None


class FileUploadUnsupportedError(RuntimeError):
    pass


def _timeout_seconds(env_name: str, default: int) -> int:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


TRANSLATION_SPEC = ArtifactSpec(
    name="translation",
    prompt_filename="translate_fulltext.md",
    output_path_attr="translation_path",
    output_kind="markdown",
)

ARTIFACT_SPECS = (
    ArtifactSpec(
        name="summary",
        prompt_filename="summarize_paper.md",
        output_path_attr="summary_path",
        output_kind="markdown",
    ),
    ArtifactSpec(
        name="experiments",
        prompt_filename="summarize_experiments.md",
        output_path_attr="experiments_path",
        output_kind="markdown",
    ),
    ArtifactSpec(
        name="notes",
        prompt_filename="summarize_notes.md",
        output_path_attr="notes_path",
        output_kind="markdown",
    ),
    ArtifactSpec(
        name="code_links",
        prompt_filename="extract_code_links.md",
        output_path_attr="code_links_path",
        output_kind="json",
        schema_name="paper_code_links",
        schema=CODE_LINKS_SCHEMA,
    ),
    ArtifactSpec(
        name="relevance",
        prompt_filename="summarize_relevance.md",
        output_path_attr="relevance_path",
        output_kind="markdown",
    ),
)


def _max_workers_from_env(env_name: str, default: int) -> int:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def _api_url(settings: RuntimeSettings, endpoint: str) -> str:
    return f"{settings.base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _api_url_from_base(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("value", "text"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
    return None


def _extract_content_texts(content_items: Any) -> list[str]:
    chunks: list[str] = []
    if not isinstance(content_items, list):
        return chunks
    for content in content_items:
        if not isinstance(content, dict):
            continue
        content_type = content.get("type")
        if content_type in {"output_text", "text"}:
            text = _coerce_text(content.get("text"))
            if text:
                chunks.append(text)
    return chunks


def extract_output_text(payload: dict[str, Any]) -> str:
    direct_text = _coerce_text(payload.get("output_text"))
    if direct_text:
        return direct_text

    chunks: list[str] = []

    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        chunks.extend(_extract_content_texts(item.get("content")))

    for choice in payload.get("choices", []) or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            direct_message = _coerce_text(message.get("content"))
            if direct_message:
                chunks.append(direct_message)
            chunks.extend(_extract_content_texts(message.get("content")))

    if isinstance(payload.get("message"), dict):
        message = payload["message"]
        direct_message = _coerce_text(message.get("content"))
        if direct_message:
            chunks.append(direct_message)
        chunks.extend(_extract_content_texts(message.get("content")))

    deduped_chunks = list(dict.fromkeys(chunk for chunk in chunks if chunk.strip()))
    return "\n".join(deduped_chunks)


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
    json_payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    max_attempts: int = REQUEST_MAX_ATTEMPTS,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_payload,
                data=data,
                files=files,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise last_error


def _ensure_completed_response(payload: dict[str, Any], context: str) -> None:
    status = payload.get("status")
    if status is not None and status != "completed":
        context_bits: list[str] = [f"status={status!r}"]
        if "incomplete_details" in payload:
            context_bits.append(
                f"incomplete_details={payload.get('incomplete_details')!r}"
            )
        if "error" in payload:
            context_bits.append(f"error={payload.get('error')!r}")
        raise ValueError(f"{context} was not completed: " + ", ".join(context_bits))


@lru_cache(maxsize=8)
def _supports_file_upload(base_url: str) -> bool:
    try:
        response = requests.post(
            _api_url_from_base(base_url, "files"),
            data={"purpose": "user_data"},
            timeout=FILES_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return True
    return response.status_code not in {404, 405}


def upload_file(file_path: Path, settings: RuntimeSettings) -> str:
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
        try:
            with file_path.open("rb") as handle:
                response = requests.post(
                    _api_url(settings, "files"),
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                    data={"purpose": "user_data"},
                    files={"file": (file_path.name, handle, content_type)},
                    timeout=FILES_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                file_id = payload.get("id")
                if not isinstance(file_id, str) or not file_id:
                    raise ValueError("Upload response did not include a valid file id.")
                return file_id
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in {404, 405}:
                raise FileUploadUnsupportedError(
                    f"File upload is not supported by base_url={settings.base_url!r}."
                ) from exc
            last_error = exc
            if attempt == REQUEST_MAX_ATTEMPTS:
                break
            time.sleep(min(2**attempt, 8))
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == REQUEST_MAX_ATTEMPTS:
                break
            time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise last_error


def upload_pdf_file(pdf_path: Path, settings: RuntimeSettings) -> str:
    return upload_file(pdf_path, settings)


def delete_uploaded_file(file_id: str, settings: RuntimeSettings) -> None:
    try:
        requests.delete(
            _api_url(settings, f"files/{file_id}"),
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=FILES_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return


def _poll_response(response_id: str, settings: RuntimeSettings) -> dict[str, Any]:
    poll_timeout_seconds = _timeout_seconds(
        "PAPER_OPS_POLL_TIMEOUT_SECONDS", POLL_TIMEOUT_SECONDS_DEFAULT
    )
    deadline = time.monotonic() + poll_timeout_seconds
    while True:
        payload = _request_json(
            "GET",
            _api_url(settings, f"responses/{response_id}"),
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=_timeout_seconds(
                "PAPER_OPS_RESPONSE_TIMEOUT_SECONDS",
                RESPONSE_TIMEOUT_SECONDS_DEFAULT,
            ),
        )
        status = payload.get("status")
        if status in TERMINAL_RESPONSE_STATUSES or status is None:
            return payload
        if status not in PENDING_RESPONSE_STATUSES:
            raise ValueError(f"Unexpected response status while polling: {status!r}")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out while waiting for response {response_id} to finish."
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def _metadata_context(metadata: dict[str, Any]) -> str:
    authors = metadata.get("authors") or []
    authors_text = ", ".join(str(author) for author in authors) if authors else "Unknown"
    keywords = metadata.get("keywords") or []
    keywords_text = ", ".join(str(keyword) for keyword in keywords) if keywords else "None"
    venue = metadata.get("venue") or "Unknown"
    direction = metadata.get("direction") or "Unknown"
    return (
        "Paper metadata:\n"
        f"- title: {metadata.get('title', 'Unknown')}\n"
        f"- authors: {authors_text}\n"
        f"- year: {metadata.get('year', 'Unknown')}\n"
        f"- venue: {venue}\n"
        f"- assigned direction: {direction}\n"
        f"- keywords: {keywords_text}\n\n"
        "Use the attached source as the primary source of truth. "
        "If metadata conflicts with the source, trust the source content and note the discrepancy."
    )


def _text_file_bundle(path: Path) -> str:
    return (
        f"Source file: {path.name}\n"
        "[[BEGIN FILE]]\n"
        f"{path.read_text(encoding='utf-8').rstrip()}\n"
        "[[END FILE]]"
    )


def _extract_pdf_pages(pdf_path: Path) -> list[str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        if any(page.strip() for page in pages):
            return pages
    except Exception:
        pages = []

    try:
        import fitz

        with fitz.open(str(pdf_path)) as document:
            pages = [page.get_text("text") or "" for page in document]
            if any(page.strip() for page in pages):
                return pages
    except Exception as exc:
        if not pages:
            raise RuntimeError(f"Failed to extract text from PDF: {pdf_path}") from exc

    if not pages:
        raise RuntimeError(f"Failed to extract text from PDF: {pdf_path}")
    return pages


def _pdf_text_bundle(pdf_path: Path) -> str:
    pages = _extract_pdf_pages(pdf_path)
    lines = [
        f"Source PDF: {pdf_path.name}",
        f"Pages: {len(pages)}",
        "",
    ]
    for index, page_text in enumerate(pages, start=1):
        content = page_text.rstrip()
        if not content:
            content = "[no extractable text on this page]"
        lines.extend(
            [
                f"[[BEGIN PAGE {index}]]",
                content,
                f"[[END PAGE {index}]]",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _prepare_source_payload(source_path: Path, *, is_pdf: bool, settings: RuntimeSettings) -> SourcePayload:
    if is_pdf:
        if _supports_file_upload(settings.base_url):
            try:
                return SourcePayload(file_id=upload_pdf_file(source_path, settings))
            except FileUploadUnsupportedError:
                pass
        return SourcePayload(text=_pdf_text_bundle(source_path))
    return SourcePayload(text=_text_file_bundle(source_path))


def _chat_completion_payload(
    *,
    source: SourcePayload,
    model: str,
    system_prompt: str,
    context_text: str,
    spec: ArtifactSpec,
    settings: RuntimeSettings,
) -> dict[str, Any]:
    if source.file_id:
        user_content: str | list[dict[str, Any]] = [
            {"type": "file", "file": {"file_id": source.file_id}},
            {"type": "text", "text": context_text.rstrip()},
        ]
    elif source.text:
        user_content = (
            f"{context_text.rstrip()}\n\n"
            "## Source bundle\n"
            "[[BEGIN SOURCE]]\n"
            f"{source.text.rstrip()}\n"
            "[[END SOURCE]]"
        )
    else:
        raise ValueError("source payload must include text or file_id.")

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }
    if spec.output_kind == "json" and settings.model_provider != "claude":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _parse_json_output(output_text: str) -> Any:
    text = output_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            return json.loads(candidate)
        raise


def _run_artifact_agent(
    *,
    source: SourcePayload,
    spec: ArtifactSpec,
    output_path: Path,
    metadata: dict[str, Any] | None = None,
    context_text: str | None = None,
    settings: RuntimeSettings,
) -> Path:
    if context_text is None:
        if metadata is None:
            raise ValueError("context_text or metadata must be provided.")
        context_text = _metadata_context(metadata)
    system_prompt = (PROMPTS_DIR / spec.prompt_filename).read_text(encoding="utf-8")
    created = _request_json(
        "POST",
        _api_url(settings, "chat/completions"),
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        json_payload=_chat_completion_payload(
            source=source,
            model=settings.model,
            system_prompt=system_prompt,
            context_text=context_text,
            spec=spec,
            settings=settings,
        ),
        timeout=_timeout_seconds(
            "PAPER_OPS_RESPONSE_TIMEOUT_SECONDS",
            RESPONSE_TIMEOUT_SECONDS_DEFAULT,
        ),
    )
    output_text = extract_output_text(created).strip()
    if not output_text:
        raise ValueError(f"{spec.name} response returned empty output.")

    if spec.output_kind == "json":
        try:
            parsed = _parse_json_output(output_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{spec.name} response did not contain valid JSON."
            ) from exc
        output_path.write_text(
            json.dumps(parsed, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        output_path.write_text(output_text.rstrip() + "\n", encoding="utf-8")

    if REQUEST_SPACING_SECONDS > 0:
        time.sleep(REQUEST_SPACING_SECONDS)

    return output_path


def run_artifact_agent_from_file(
    *,
    source_path: Path,
    spec: ArtifactSpec,
    output_path: Path,
    context_text: str,
    settings: RuntimeSettings,
) -> Path:
    source = _prepare_source_payload(source_path, is_pdf=False, settings=settings)
    try:
        return _run_artifact_agent(
            source=source,
            spec=spec,
            output_path=output_path,
            context_text=context_text,
            settings=settings,
        )
    finally:
        if source.file_id:
            delete_uploaded_file(source.file_id, settings)


def generate_parallel_artifacts_from_pdf(
    *,
    pdf_path: Path,
    paths: PaperPaths,
    metadata: dict[str, Any],
    settings: RuntimeSettings,
) -> ArtifactRunSummary:
    source = _prepare_source_payload(pdf_path, is_pdf=True, settings=settings)
    completed: dict[str, Path] = {}
    failed: dict[str, str] = {}

    try:
        max_workers = min(
            len(ARTIFACT_SPECS),
            _max_workers_from_env(
                "PAPER_OPS_MAX_MODEL_CONCURRENCY",
                _max_workers_from_env("PAPER_OPS_MAX_WORKERS", 3),
            ),
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _run_artifact_agent,
                    source=source,
                    spec=spec,
                    output_path=getattr(paths, spec.output_path_attr),
                    metadata=metadata,
                    settings=settings,
                ): spec
                for spec in ARTIFACT_SPECS
            }
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    completed[spec.name] = future.result()
                except Exception as exc:
                    failed[spec.name] = str(exc)
    finally:
        if source.file_id:
            delete_uploaded_file(source.file_id, settings)

    return ArtifactRunSummary(completed=completed, failed=failed)


def generate_translation_from_pdf(
    *,
    pdf_path: Path,
    output_path: Path,
    metadata: dict[str, Any],
    settings: RuntimeSettings,
) -> None:
    run_single_artifact_from_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        metadata=metadata,
        settings=settings,
        spec=TRANSLATION_SPEC,
    )


def run_single_artifact_from_pdf(
    *,
    pdf_path: Path,
    output_path: Path,
    metadata: dict[str, Any],
    settings: RuntimeSettings,
    spec: ArtifactSpec,
) -> None:
    source = _prepare_source_payload(pdf_path, is_pdf=True, settings=settings)
    try:
        _run_artifact_agent(
            source=source,
            spec=spec,
            output_path=output_path,
            context_text=_metadata_context(metadata),
            settings=settings,
        )
    finally:
        if source.file_id:
            delete_uploaded_file(source.file_id, settings)
