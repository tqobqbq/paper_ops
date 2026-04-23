import json
from pathlib import Path

import typer

from paper_ops.indexer import rebuild_indexes
from paper_ops.queue import CandidateQueue

app = typer.Typer(help="Paper ingestion, translation, and discovery pipeline.")
PAPERS_ROOT = Path("/root/projects/snn_codex/papers")
QUEUE_PATH = PAPERS_ROOT / "candidates" / "queue.json"

ingest_app = typer.Typer(help="Ingest URLs, PDFs, or batches into the candidate queue.")

app.add_typer(ingest_app, name="ingest")


@ingest_app.command("url")
def ingest_url(paper_url: str, process_now: bool = False) -> None:
    queue = CandidateQueue(QUEUE_PATH)
    candidate = queue.enqueue(
        title=paper_url,
        source_url=paper_url,
        source_type="url",
        discovered_from="manual",
        priority="high",
        matched_keywords=[],
        reason="manual URL ingest",
    )
    typer.echo(candidate.model_dump_json(indent=2))


@ingest_app.command("pdf")
def ingest_pdf(local_pdf_path: Path, process_now: bool = False) -> None:
    queue = CandidateQueue(QUEUE_PATH)
    candidate = queue.enqueue(
        title=local_pdf_path.stem,
        source_url=str(local_pdf_path),
        source_type="pdf",
        discovered_from="manual",
        priority="high",
        matched_keywords=[],
        reason="manual PDF ingest",
    )
    typer.echo(candidate.model_dump_json(indent=2))


@ingest_app.command("batch")
def ingest_batch(batch_file: Path) -> None:
    typer.echo(json.dumps({"batch_file": str(batch_file)}))


@app.command("process")
def process_paper(
    paper_id: str | None = None,
    queued: bool = False,
    batch: Path | None = None,
) -> None:
    typer.echo(
        json.dumps(
            {
                "paper_id": paper_id,
                "queued": queued,
                "batch": str(batch) if batch else None,
            }
        )
    )


@app.command("build-index")
def build_index(direction: str | None = None) -> None:
    rebuild_indexes(PAPERS_ROOT)
    typer.echo(json.dumps({"direction": direction, "rebuilt": True}))


@app.command("discover")
def discover(source: str = "top_venues", keywords: str = "") -> None:
    typer.echo(
        json.dumps(
            {"source": source, "keywords": keywords.split(",") if keywords else []}
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
