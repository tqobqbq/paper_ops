from __future__ import annotations

import json
from pathlib import Path

import typer

from paper_ops.pipeline import process_local_pdf
from paper_ops.settings import load_runtime_settings, resolve_library_root

app = typer.Typer(help="Run the full local-PDF paper pipeline.")


@app.command()
def main(
    source_pdf: Path,
    title: str,
    authors: str,
    year: int,
    venue: str | None = None,
    abstract: str = "",
    keywords: str = "",
    direction: str | None = None,
    library_root: Path | None = typer.Option(None, "--library-root"),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    runtime_settings = load_runtime_settings(
        model_override=model,
        base_url_override=base_url,
        model_provider_override=model_provider,
    )
    result = process_local_pdf(
        source_pdf=source_pdf,
        library_root=resolved_library_root,
        title=title,
        authors=[item.strip() for item in authors.split(",") if item.strip()],
        year=year,
        venue=venue,
        abstract=abstract,
        keywords=[item.strip() for item in keywords.split(",") if item.strip()],
        direction=direction,
        settings=runtime_settings,
    )
    typer.echo(
        json.dumps(
            {
                "paper_id": result.paper_id,
                "direction": result.direction,
                "paper_dir": str(result.paths.paper_dir),
                "translation_path": str(result.paths.translation_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    app()
