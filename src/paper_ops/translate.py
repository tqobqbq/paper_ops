from __future__ import annotations

from pathlib import Path
from typing import Any

from paper_ops.artifact_agents import (
    TRANSLATION_SPEC,
    extract_output_text as _extract_output_text,
    run_single_artifact_from_pdf,
)
from paper_ops.settings import RuntimeSettings


def translate_pdf_to_markdown(
    pdf_path: Path,
    output_path: Path,
    settings: RuntimeSettings,
    metadata: dict[str, Any] | None = None,
) -> None:
    if metadata is None:
        metadata = {
            "title": pdf_path.stem,
            "authors": [],
            "year": "",
            "venue": "",
            "direction": "",
            "keywords": [],
        }
    run_single_artifact_from_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        metadata=metadata,
        settings=settings,
        spec=TRANSLATION_SPEC,
    )
