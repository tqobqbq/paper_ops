import typer

app = typer.Typer(help="Paper ingestion, translation, and discovery pipeline.")

ingest_app = typer.Typer(help="Ingest URLs, PDFs, or batches into the candidate queue.")
process_app = typer.Typer(help="Run classification, translation, summarization, and indexing.")
discover_app = typer.Typer(help="Discover candidate papers from supported sources.")

app.add_typer(ingest_app, name="ingest")
app.add_typer(process_app, name="process")
app.add_typer(discover_app, name="discover")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
