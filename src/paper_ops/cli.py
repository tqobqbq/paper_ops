import json
from pathlib import Path

import typer

from paper_ops.citation_expansion import (
    SemanticScholarExpansionProvider,
)
from paper_ops.discovery import filter_arxiv_candidates, parse_feed_entries
from paper_ops.indexer import rebuild_indexes
from paper_ops.manual_downloads import (
    ManualDownloadRequest,
    ManualProcessResult,
    create_manual_download_request,
    process_manual_downloads_once,
    render_manual_download_readme,
    watch_manual_downloads,
)
from paper_ops.paper_search_client import (
    PaperSearchClient,
    PaperSearchError,
    setup_paper_search,
)
from paper_ops.paper_graph import (
    export_graph_candidates,
    review_graph_candidates,
    update_graph_for_direction,
)
from paper_ops.pipeline import process_local_pdf as run_local_pdf_pipeline
from paper_ops.queue import CandidateQueue
from paper_ops.settings import load_runtime_settings, resolve_library_root
from paper_ops.summarize import (
    OVERVIEW_SUMMARY_FILENAME,
    generate_direction_summary_for_direction,
    generate_overview_summary_from_current_directions,
)
from paper_ops.summary_ledger import (
    load_summary_ledger,
    pending_directions_for_overview,
    pending_paper_dirs_for_direction,
)

app = typer.Typer(help="Paper ingestion, translation, and discovery pipeline.")

ingest_app = typer.Typer(help="Ingest URLs, PDFs, or batches into the candidate queue.")
manual_app = typer.Typer(help="Manage manually downloaded PDF requests.")
summarize_app = typer.Typer(help="Generate direction or overview summaries.")
graph_app = typer.Typer(help="Maintain the project-level paper graph database.")

app.add_typer(ingest_app, name="ingest")
app.add_typer(manual_app, name="manual")
app.add_typer(summarize_app, name="summarize")
app.add_typer(graph_app, name="graph")


def _candidate_queue(library_root: Path) -> CandidateQueue:
    return CandidateQueue(library_root / "candidates" / "queue.json")


@ingest_app.command("url")
def ingest_url(
    paper_url: str,
    process_now: bool = False,
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    queue = _candidate_queue(resolved_library_root)
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
def ingest_pdf(
    local_pdf_path: Path,
    process_now: bool = False,
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    queue = _candidate_queue(resolved_library_root)
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
def ingest_batch(
    batch_file: Path,
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    queue = _candidate_queue(resolved_library_root)
    payload = json.loads(batch_file.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        entries = payload.get("candidates", [])
    else:
        entries = payload
    if not isinstance(entries, list):
        raise typer.BadParameter("batch file must contain a list or {'candidates': [...]}.")

    enqueued = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        candidate = queue.enqueue(
            title=str(item["title"]),
            source_url=str(item["source_url"]),
            source_type=str(item.get("source_type") or "url"),
            discovered_from=str(item.get("discovered_from") or "batch"),
            priority=str(item.get("priority") or "high"),
            matched_keywords=[
                str(keyword)
                for keyword in (item.get("matched_keywords") or [])
                if str(keyword).strip()
            ],
            reason=str(item.get("reason") or "batch ingest"),
        )
        enqueued.append(candidate.model_dump(mode="json"))

    typer.echo(
        json.dumps(
            {
                "batch_file": str(batch_file),
                "enqueued": enqueued,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def _manual_processor(
    *,
    library_root: Path,
    model_provider: str | None,
    model: str | None,
    base_url: str | None,
):
    settings = None

    def process_request(
        pdf_path: Path,
        request: ManualDownloadRequest,
    ) -> ManualProcessResult:
        nonlocal settings
        if request.year is None:
            raise ValueError(
                f"Manual download request {request.request_id} is missing year."
            )
        if settings is None:
            settings = load_runtime_settings(
                model_override=model,
                base_url_override=base_url,
                model_provider_override=model_provider,
            )
        result = run_local_pdf_pipeline(
            source_pdf=pdf_path,
            library_root=library_root,
            title=request.title,
            authors=request.authors,
            year=request.year,
            venue=request.venue,
            abstract=request.abstract,
            keywords=request.keywords,
            direction=request.direction,
            settings=settings,
            refresh_direction_and_overview_summaries=False,
        )
        return ManualProcessResult(
            paper_id=result.paper_id,
            paper_dir=result.paths.paper_dir,
        )

    return process_request


@manual_app.command("render-readme")
def manual_render_readme(
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    readme_path = render_manual_download_readme(resolved_library_root)
    typer.echo(json.dumps({"readme": str(readme_path)}, indent=2))


@manual_app.command("create-request")
def manual_create_request(
    title: str = typer.Option(..., "--title"),
    request_id: str | None = typer.Option(None, "--request-id"),
    authors: str = typer.Option("", "--authors"),
    year: int | None = typer.Option(None, "--year"),
    venue: str | None = typer.Option(None, "--venue"),
    doi: str | None = typer.Option(None, "--doi"),
    direction: str | None = typer.Option(None, "--direction"),
    abstract: str = typer.Option("", "--abstract"),
    keywords: str = typer.Option("", "--keywords"),
    source_url: str | None = typer.Option(None, "--source-url"),
    expected_filename: list[str] | None = typer.Option(
        None,
        "--expected-filename",
    ),
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    normalized_request_id = request_id or title.lower().replace(" ", "-")[:64].strip("-")
    request = ManualDownloadRequest(
        request_id=normalized_request_id,
        title=title,
        authors=[item.strip() for item in authors.split(",") if item.strip()],
        year=year,
        venue=venue,
        doi=doi,
        direction=direction,
        abstract=abstract,
        keywords=[item.strip() for item in keywords.split(",") if item.strip()],
        source_url=source_url,
        expected_filenames=expected_filename or [f"{normalized_request_id}.pdf"],
    )
    request_path = create_manual_download_request(resolved_library_root, request)
    typer.echo(json.dumps({"request": str(request_path)}, indent=2))


@manual_app.command("scan-once")
def manual_scan_once(
    library_root: Path | None = typer.Option(None, "--library-root"),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    result = process_manual_downloads_once(
        resolved_library_root,
        processor=_manual_processor(
            library_root=resolved_library_root,
            model_provider=model_provider,
            model=model,
            base_url=base_url,
        ),
    )
    typer.echo(
        json.dumps(
            {
                "processed": result.processed_count,
                "failed": result.failed_count,
                "readme": str(result.readme_path),
            },
            indent=2,
        )
    )


@manual_app.command("watch")
def manual_watch(
    library_root: Path | None = typer.Option(None, "--library-root"),
    interval_seconds: int = 1800,
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    watch_manual_downloads(
        resolved_library_root,
        processor=_manual_processor(
            library_root=resolved_library_root,
            model_provider=model_provider,
            model=model,
            base_url=base_url,
        ),
        interval_seconds=interval_seconds,
    )


def _load_cli_runtime_settings(
    *,
    model_provider: str | None,
    model: str | None,
    base_url: str | None,
):
    return load_runtime_settings(
        model_override=model,
        base_url_override=base_url,
        model_provider_override=model_provider,
    )


@summarize_app.command("direction")
def summarize_direction(
    direction: str,
    library_root: Path | None = typer.Option(None, "--library-root"),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    settings = _load_cli_runtime_settings(
        model_provider=model_provider,
        model=model,
        base_url=base_url,
    )
    summary_path = generate_direction_summary_for_direction(
        library_root=resolved_library_root,
        direction=direction,
        settings=settings,
    )
    typer.echo(
        json.dumps(
            {
                "direction": direction,
                "summary_path": str(summary_path),
            },
            indent=2,
        )
    )


@summarize_app.command("overview")
def summarize_overview(
    library_root: Path | None = typer.Option(None, "--library-root"),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    settings = _load_cli_runtime_settings(
        model_provider=model_provider,
        model=model,
        base_url=base_url,
    )
    generate_overview_summary_from_current_directions(
        library_root=resolved_library_root,
        settings=settings,
    )
    overview_path = (
        resolved_library_root / "library" / OVERVIEW_SUMMARY_FILENAME
    )
    typer.echo(
        json.dumps(
            {
                "overview_path": str(overview_path),
            },
            indent=2,
        )
    )


@summarize_app.command("pending")
def summarize_pending(
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    ledger = load_summary_ledger(resolved_library_root)
    directions = {
        direction
        for entry in ledger.get("papers", {}).values()
        if isinstance(entry, dict) and isinstance(entry.get("direction"), str)
        for direction in [entry["direction"]]
    }
    directions.update(
        direction
        for direction in ledger.get("directions", {}).keys()
        if isinstance(direction, str)
    )
    directions.update(pending_directions_for_overview(resolved_library_root))

    pending_papers = {
        direction: [
            str(path)
            for path in pending_paper_dirs_for_direction(
                resolved_library_root,
                direction,
            )
        ]
        for direction in sorted(directions)
    }
    pending_papers = {
        direction: papers for direction, papers in pending_papers.items() if papers
    }
    typer.echo(
        json.dumps(
            {
                "pending_papers_by_direction": pending_papers,
                "pending_overview_directions": pending_directions_for_overview(
                    resolved_library_root
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("resolve-pdf")
def resolve_pdf(
    title: str = typer.Option(..., "--title"),
    authors: str = typer.Option("", "--authors"),
    year: int | None = typer.Option(None, "--year"),
    venue: str | None = typer.Option(None, "--venue"),
    doi: str | None = typer.Option(None, "--doi"),
    direction: str | None = typer.Option(None, "--direction"),
    abstract: str = typer.Option("", "--abstract"),
    keywords: str = typer.Option("", "--keywords"),
    source_url: str | None = typer.Option(None, "--source-url"),
    pdf_url: str | None = typer.Option(None, "--pdf-url"),
    source: str = typer.Option(
        "crossref",
        "--source",
        help="paper-search source name for download_with_fallback (e.g. crossref, arxiv).",
    ),
    paper_id: str | None = typer.Option(
        None,
        "--paper-id",
        help="Source-native paper id. Defaults to DOI if available.",
    ),
    save_path: Path | None = typer.Option(
        None,
        "--save-path",
        help="Directory to write the downloaded PDF. Defaults to <library-root>/manual_downloads/inbox.",
    ),
    create_manual_request: bool = typer.Option(False, "--create-manual-request"),
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    resolved_save_path = save_path or (
        resolved_library_root / "manual_downloads" / "inbox"
    )
    resolved_paper_id = paper_id or doi
    if not resolved_paper_id:
        raise typer.BadParameter(
            "Provide --doi or --paper-id so paper-search has something to look up."
        )

    client = PaperSearchClient()
    try:
        pdf_path = client.download_with_fallback(
            source=source,
            paper_id=resolved_paper_id,
            doi=doi,
            title=title,
            save_path=resolved_save_path,
        )
    except PaperSearchError as exc:
        manual_request_path = None
        if create_manual_request:
            request = ManualDownloadRequest(
                request_id=resolved_paper_id.replace("/", "-").replace(":", "-")[:64]
                or "paper",
                title=title,
                authors=[item.strip() for item in authors.split(",") if item.strip()],
                year=year,
                venue=venue,
                doi=doi,
                direction=direction,
                abstract=abstract,
                keywords=[
                    item.strip() for item in keywords.split(",") if item.strip()
                ],
                source_url=source_url or pdf_url,
                legal_pdf_attempts=[
                    {"source": source, "result": "paper-search failed", "error": str(exc)}
                ],
                expected_filenames=[],
            )
            manual_path = create_manual_download_request(resolved_library_root, request)
            manual_request_path = str(manual_path)
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "manual_request_path": manual_request_path,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        raise typer.Exit(code=1)

    typer.echo(
        json.dumps(
            {
                "ok": True,
                "pdf_path": str(pdf_path),
                "source": source,
                "paper_id": resolved_paper_id,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("process")
def process_paper(
    paper_id: str | None = None,
    queued: bool = False,
    batch: Path | None = None,
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    queue = _candidate_queue(resolved_library_root)
    entries = queue.load()
    if queued:
        entries = [entry for entry in entries if entry.accepted is None]
    if paper_id:
        entries = [
            entry
            for entry in entries
            if entry.linked_paper_id == paper_id or entry.candidate_id == paper_id
        ]
    typer.echo(
        json.dumps(
            {
                "library_root": str(resolved_library_root),
                "batch": str(batch) if batch else None,
                "candidates": [entry.model_dump(mode="json") for entry in entries],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("build-index")
def build_index(
    direction: str | None = None,
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    rebuild_indexes(resolved_library_root)
    typer.echo(
        json.dumps(
            {
                "direction": direction,
                "library_root": str(resolved_library_root),
                "rebuilt": True,
            }
        )
    )


@app.command("expand-citations")
def expand_citations(
    direction: str,
    library_root: Path | None = typer.Option(None, "--library-root"),
    limit: int = typer.Option(
        50,
        "--limit",
        help="Maximum candidates to keep in the written expansion artifact.",
    ),
    citations_per_seed: int = typer.Option(
        25,
        "--citations-per-seed",
        help="Semantic Scholar citing-paper records to inspect per local seed.",
    ),
    references_per_seed: int = typer.Option(
        25,
        "--references-per-seed",
        help="Semantic Scholar reference records to inspect per local seed.",
    ),
    rank: bool = typer.Option(
        False,
        "--rank",
        help="Call the configured LLM to rank the deterministic candidate cards.",
    ),
    llm_limit: int = typer.Option(
        30,
        "--llm-limit",
        help="Maximum deterministic candidates to send to the LLM ranking step.",
    ),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude. Only used with --rank.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    provider = SemanticScholarExpansionProvider(
        citations_limit=citations_per_seed,
        references_limit=references_per_seed,
    )
    graph_result = update_graph_for_direction(
        library_root=resolved_library_root,
        direction=direction,
        provider=provider,
    )
    review_count = 0
    if rank:
        settings = _load_cli_runtime_settings(
            model_provider=model_provider,
            model=model,
            base_url=base_url,
        )
        review = review_graph_candidates(
            library_root=resolved_library_root,
            direction=direction,
            settings=settings,
            limit=llm_limit,
        )
        review_count = review.reviewed_count
    output_path = export_graph_candidates(
        library_root=resolved_library_root,
        direction=direction,
        limit=limit,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    typer.echo(
        json.dumps(
            {
                "direction": direction,
                "library_root": str(resolved_library_root),
                "db_path": str(graph_result.db_path),
                "update_path": str(graph_result.expansion_path),
                "output_path": str(output_path),
                "seed_count": graph_result.seed_count,
                "raw_candidate_count": graph_result.raw_candidate_count,
                "discovered_paper_count": graph_result.candidate_count,
                "relation_count": graph_result.relation_count,
                "candidate_count": payload.get("candidate_count"),
                "llm_review_count": review_count,
                "llm_ranked": review_count > 0,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@graph_app.command("update")
def graph_update(
    direction: str,
    library_root: Path | None = typer.Option(None, "--library-root"),
    limit: int = typer.Option(
        50,
        "--limit",
        help="Deprecated; graph update no longer performs candidate selection.",
    ),
    citations_per_seed: int = typer.Option(
        25,
        "--citations-per-seed",
        help="Semantic Scholar citing-paper records to inspect per local seed.",
    ),
    references_per_seed: int = typer.Option(
        25,
        "--references-per-seed",
        help="Semantic Scholar reference records to inspect per local seed.",
    ),
    rank: bool = typer.Option(
        False,
        "--rank",
        help="Deprecated; candidate ranking is deferred to graph review.",
    ),
    llm_limit: int = typer.Option(
        30,
        "--llm-limit",
        help="Deprecated; run graph review with --limit instead.",
    ),
    model_provider: str | None = typer.Option(
        None,
        help="Deprecated for graph update; model settings are used by graph review.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    provider = SemanticScholarExpansionProvider(
        citations_limit=citations_per_seed,
        references_limit=references_per_seed,
    )
    result = update_graph_for_direction(
        library_root=resolved_library_root,
        direction=direction,
        provider=provider,
    )
    notes = []
    if rank:
        notes.append(
            "graph update only records paper/relation facts; run graph review to call the LLM"
        )
    typer.echo(
        json.dumps(
            {
                "direction": direction,
                "library_root": str(resolved_library_root),
                "db_path": str(result.db_path),
                "update_path": str(result.expansion_path),
                "seed_count": result.seed_count,
                "raw_candidate_count": result.raw_candidate_count,
                "discovered_paper_count": result.candidate_count,
                "relation_count": result.relation_count,
                "llm_review_count": result.llm_review_count,
                "notes": notes,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@graph_app.command("candidates")
def graph_candidates(
    direction: str,
    library_root: Path | None = typer.Option(None, "--library-root"),
    limit: int = typer.Option(50, "--limit"),
    state: str | None = typer.Option(
        None,
        "--state",
        help="Optional candidate state filter, e.g. new or llm_reviewed.",
    ),
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    output_path = export_graph_candidates(
        library_root=resolved_library_root,
        direction=direction,
        limit=limit,
        state=state,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    typer.echo(
        json.dumps(
            {
                "direction": direction,
                "library_root": str(resolved_library_root),
                "output_path": str(output_path),
                "candidate_count": payload.get("candidate_count"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@graph_app.command("review")
def graph_review(
    direction: str,
    library_root: Path | None = typer.Option(None, "--library-root"),
    limit: int = typer.Option(
        30,
        "--limit",
        help="Maximum existing graph candidates to send to the LLM.",
    ),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    resolved_library_root = resolve_library_root(library_root)
    settings = _load_cli_runtime_settings(
        model_provider=model_provider,
        model=model,
        base_url=base_url,
    )
    result = review_graph_candidates(
        library_root=resolved_library_root,
        direction=direction,
        settings=settings,
        limit=limit,
    )
    typer.echo(
        json.dumps(
            {
                "direction": direction,
                "library_root": str(resolved_library_root),
                "db_path": str(result.db_path),
                "reviewed_count": result.reviewed_count,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("discover")
def discover(
    source: str = typer.Option(
        "",
        "--source",
        help="Feed URL (RSS/Atom). Routes through feedparser. Mutually exclusive with --query.",
    ),
    query: str = typer.Option(
        "",
        "--query",
        help="Free-text query for paper-search. Mutually exclusive with --source.",
    ),
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="paper-search platform (e.g. crossref, arxiv, semantic). Only with --query.",
    ),
    sources: str | None = typer.Option(
        None,
        "--sources",
        help="paper-search multi-source comma list. Only with --query.",
    ),
    max_results: int = typer.Option(10, "--max-results"),
    year: str | None = typer.Option(None, "--year"),
    keywords: str = typer.Option("", "--keywords"),
    library_root: Path | None = typer.Option(None, "--library-root"),
) -> None:
    if not source and not query:
        raise typer.BadParameter("Provide either --source <feed-url> or --query <text>.")
    if source and query:
        raise typer.BadParameter("--source and --query are mutually exclusive.")

    resolved_library_root = resolve_library_root(library_root)
    normalized_keywords = [
        keyword.strip() for keyword in keywords.split(",") if keyword.strip()
    ]
    queue = _candidate_queue(resolved_library_root)
    enqueued: list[dict] = []

    if source:
        entries = parse_feed_entries(source)
        filtered_entries = (
            filter_arxiv_candidates(entries, normalized_keywords)
            if normalized_keywords
            else entries
        )
        for entry in filtered_entries:
            title = entry.get("title") or entry.get("link") or "Untitled paper"
            source_url = entry.get("link") or title
            candidate = queue.enqueue(
                title=title,
                source_url=source_url,
                source_type="arxiv" if "arxiv.org" in source_url else "url",
                discovered_from=source,
                priority="medium",
                matched_keywords=normalized_keywords,
                reason=(
                    "keyword match"
                    if normalized_keywords
                    else "feed entry from discovery source"
                ),
            )
            enqueued.append(candidate.model_dump(mode="json"))
        payload = {
            "mode": "feed",
            "source": source,
            "keywords": normalized_keywords,
            "enqueued": enqueued,
        }
    else:
        from paper_ops.paper_search_client import (
            PaperSearchClient,
            to_discovery_candidate,
        )

        client = PaperSearchClient()
        results = client.search(
            query,
            platform=platform,
            sources=sources,
            max_results=max_results,
            year=year,
        )
        discovered_from = f"paper-search:{platform or sources or 'crossref'}"
        for result in results:
            candidate = to_discovery_candidate(
                result,
                discovered_from=discovered_from,
                matched_keywords=normalized_keywords,
                reason="paper-search query result",
            )
            existing = queue.enqueue(
                title=candidate.title,
                source_url=candidate.source_url,
                source_type=candidate.source_type,
                discovered_from=candidate.discovered_from,
                priority=candidate.priority,
                matched_keywords=candidate.matched_keywords,
                reason=candidate.reason,
            )
            enqueued.append(existing.model_dump(mode="json"))
        payload = {
            "mode": "paper-search",
            "query": query,
            "platform": platform,
            "sources": sources,
            "year": year,
            "max_results": max_results,
            "enqueued": enqueued,
        }

    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> None:
    app()


@app.command("fetch")
def fetch(
    query: str,
    top: int = typer.Option(5, "--top", help="Top-N papers to ingest into the library."),
    platform: str | None = typer.Option(None, "--platform"),
    sources: str | None = typer.Option(None, "--sources"),
    year: str | None = typer.Option(None, "--year"),
    direction: str | None = typer.Option(
        None,
        "--direction",
        help="Override direction classification for all fetched papers.",
    ),
    library_root: Path | None = typer.Option(None, "--library-root"),
    summarize: bool = typer.Option(
        False,
        "--summarize",
        help="After ingest, refresh direction and overview summaries for touched directions.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    update_graph: bool = typer.Option(
        False,
        "--update-graph",
        help="After successful processing, update the paper graph for touched directions.",
    ),
    rank_graph: bool = typer.Option(
        False,
        "--rank-graph",
        help="Deprecated; run graph review when you are ready to search new papers.",
    ),
    model_provider: str | None = typer.Option(
        None,
        help="Select a model provider such as claude.",
    ),
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    from paper_ops.classify import classify_direction
    from paper_ops.paper_search_client import PaperSearchClient

    resolved_library_root = resolve_library_root(library_root)
    inbox_dir = resolved_library_root / "manual_downloads" / "inbox"

    client = PaperSearchClient()
    results = client.search(
        query,
        platform=platform,
        sources=sources,
        max_results=top,
        year=year,
    )
    selected = results[:top]

    plan = []
    for result in selected:
        resolved_direction = direction or classify_direction(
            title=result.title,
            abstract=result.abstract,
            keywords=[],
        )
        request_id = _request_id_for(result)
        expected_filename = f"{request_id}.pdf"
        plan.append(
            {
                "paper_id": result.paper_id,
                "title": result.title,
                "year": result.year,
                "doi": result.doi,
                "source": result.source,
                "request_id": request_id,
                "expected_filename": expected_filename,
                "resolved_direction": resolved_direction,
                "result_obj": result,
            }
        )

    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "mode": "dry-run",
                    "query": query,
                    "candidates": [
                        {k: v for k, v in entry.items() if k != "result_obj"}
                        for entry in plan
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    download_outcomes = []
    successful_directions: set[str] = set()
    for entry in plan:
        result = entry["result_obj"]
        request = ManualDownloadRequest(
            request_id=entry["request_id"],
            title=result.title or "Untitled",
            authors=result.authors,
            year=result.year,
            venue=result.journal or None,
            doi=result.doi or None,
            direction=entry["resolved_direction"],
            abstract=result.abstract,
            keywords=[],
            source_url=result.url or None,
            expected_filenames=[entry["expected_filename"]],
        )
        create_manual_download_request(resolved_library_root, request)

        try:
            client.download_with_fallback(
                source=result.source or "crossref",
                paper_id=result.doi or result.paper_id,
                doi=result.doi or None,
                title=result.title,
                save_path=inbox_dir,
            )
            target_path = inbox_dir / entry["expected_filename"]
            downloaded_files = list(inbox_dir.glob("*.pdf"))
            if not target_path.exists() and downloaded_files:
                latest = max(downloaded_files, key=lambda p: p.stat().st_mtime)
                latest.rename(target_path)
            download_outcomes.append(
                {"request_id": entry["request_id"], "download": "ok"}
            )
        except PaperSearchError as exc:
            download_outcomes.append(
                {
                    "request_id": entry["request_id"],
                    "download": "failed",
                    "error": str(exc),
                }
            )

    sweep = process_manual_downloads_once(
        resolved_library_root,
        processor=_manual_processor(
            library_root=resolved_library_root,
            model_provider=model_provider,
            model=model,
            base_url=base_url,
        ),
    )

    for entry in plan:
        successful_directions.add(entry["resolved_direction"])

    summary_results: list[dict] = []
    if summarize and sweep.processed_count > 0:
        settings = _load_cli_runtime_settings(
            model_provider=model_provider,
            model=model,
            base_url=base_url,
        )
        for d in sorted(successful_directions):
            summary_path = generate_direction_summary_for_direction(
                library_root=resolved_library_root,
                direction=d,
                settings=settings,
            )
            summary_results.append({"direction": d, "summary_path": str(summary_path)})
        generate_overview_summary_from_current_directions(
            library_root=resolved_library_root,
            settings=settings,
        )

    graph_results: list[dict] = []
    if update_graph and sweep.processed_count > 0:
        for d in sorted(successful_directions):
            graph_result = update_graph_for_direction(
                library_root=resolved_library_root,
                direction=d,
            )
            graph_results.append(
                {
                    "direction": d,
                    "db_path": str(graph_result.db_path),
                    "update_path": str(graph_result.expansion_path),
                    "discovered_paper_count": graph_result.candidate_count,
                    "relation_count": graph_result.relation_count,
                    "llm_review_count": graph_result.llm_review_count,
                }
            )
        if rank_graph:
            graph_results.append(
                {
                    "note": (
                        "fetch only updates graph facts; run graph review when "
                        "you are ready to search new papers"
                    )
                }
            )

    typer.echo(
        json.dumps(
            {
                "mode": "fetch",
                "query": query,
                "selected": len(plan),
                "download_outcomes": download_outcomes,
                "processed": sweep.processed_count,
                "failed": sweep.failed_count,
                "summary_results": summary_results,
                "graph_results": graph_results,
                "readme": str(sweep.readme_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def _request_id_for(result) -> str:
    from paper_ops.paths import slugify

    year_part = str(result.year) if result.year else "unknown-year"
    title_slug = slugify(result.title or "paper") or "paper"
    return f"{year_part}-{title_slug[:64].rstrip('-') or 'paper'}"


@app.command("setup")
def setup() -> None:
    try:
        report = setup_paper_search()
    except PaperSearchError as exc:
        typer.echo(json.dumps({"ok": False, "error": str(exc)}, indent=2), err=True)
        raise typer.Exit(code=1)
    typer.echo(
        json.dumps(
            {
                "ok": True,
                "node_version": report.node_version,
                "npm_version": report.npm_version,
                "dist_built": report.dist_built,
                "cli_path": str(report.cli_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
