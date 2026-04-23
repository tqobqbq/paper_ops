from pathlib import Path
from typing import Any

import requests

from paper_ops.settings import RuntimeSettings


PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "translate_fulltext.md"


def _extract_output_text(payload: dict[str, Any]) -> str:
    text = payload.get("output_text")
    if isinstance(text, str):
        return text

    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(
                content.get("text"), str
            ):
                chunks.append(content["text"])
    return "\n".join(chunks)


def translate_pdf_to_markdown(
    pdf_path: Path, output_path: Path, settings: RuntimeSettings
) -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    with pdf_path.open("rb") as handle:
        upload = requests.post(
            f"{settings.base_url}/files",
            headers=headers,
            files={"file": (pdf_path.name, handle, "application/pdf")},
            data={"purpose": "user_data"},
            timeout=120,
        )
    upload.raise_for_status()
    file_id = upload.json()["id"]

    response = requests.post(
        f"{settings.base_url}/responses",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "model": settings.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_file", "file_id": file_id},
                    ],
                }
            ],
        },
        timeout=300,
    )
    response.raise_for_status()

    payload = response.json()
    status = payload.get("status")
    if status is not None and status != "completed":
        context_bits: list[str] = [f"status={status!r}"]
        if "incomplete_details" in payload:
            context_bits.append(f"incomplete_details={payload.get('incomplete_details')!r}")
        if "error" in payload:
            context_bits.append(f"error={payload.get('error')!r}")
        raise ValueError(
            "Translation response was not completed: " + ", ".join(context_bits)
        )

    output_text = _extract_output_text(payload)
    if not output_text.strip():
        raise ValueError("No translation text found in API response payload.")
    output_path.write_text(output_text, encoding="utf-8")
