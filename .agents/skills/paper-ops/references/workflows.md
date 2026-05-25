# Paper Ops Workflows

## Candidate To PDF

1. Use deterministic graph-backed screening before asking a model to rank candidates when candidates come from already downloaded papers.
2. For each candidate, try legal OA resolution before manual intake.
3. If a legal PDF is found, process it with explicit metadata and `--library-root`.
4. If no legal PDF is found, create a manual request. Do not fail the candidate just because it needs user input.

Example:

```bash
paper-ops resolve-pdf \
  --title "Paper Title" \
  --authors "Author One, Author Two" \
  --year 2026 \
  --source-url "https://arxiv.org/abs/2601.00001" \
  --create-manual-request \
  --library-root ./papers
```

Use `PYTHONPATH=src python3 -m paper_ops ...` when the console script is not installed.

## Citation Graph Discovery

Separate graph maintenance from paper search decisions.

Recommended loop:

```bash
paper-ops fetch "<query>" --top 5 --update-graph --library-root ./papers
paper-ops graph candidates predictive_coding --library-root ./papers
paper-ops graph review predictive_coding --library-root ./papers
paper-ops graph enqueue-downloads predictive_coding --priority high --limit 5 --library-root ./papers
```

After new papers are downloaded and processed, update graph facts only:

```bash
paper-ops graph update predictive_coding --library-root ./papers
```

`graph update` records local papers, external IDs, reference/cited-by relations,
relation contexts, and provider metadata. It dedupes paper identity at discovery
time and does not select candidates or call the LLM.

When the user is ready to search for the next papers, refresh/export candidates:

```bash
paper-ops graph candidates predictive_coding --library-root ./papers
```

This deterministic step builds the not-yet-downloaded candidate view from the
database and writes `indexes/graph_candidates/<direction>.json`.

Only call the LLM when the user explicitly asks for review/ranking:

```bash
paper-ops graph review predictive_coding --library-root ./papers
```

The review step sends compact candidate cards, records decision/priority/rationale
in the graph database, and preserves previous queued/downloaded/skipped states.

When LLM or human review marks candidates for download, enqueue them through the
legal PDF funnel:

```bash
paper-ops graph enqueue-downloads predictive_coding --decision fetch --priority high --limit 5 --library-root ./papers
```

Successful legal downloads are queued for manual scan processing. If no legal PDF
is found, create a manual request and mark the graph candidate `manual_required`.
Manual scan callbacks update graph candidates to `downloaded` or `download_failed`.

Use snapshots and maps when the user asks for history or a literature overview:

```bash
paper-ops graph snapshot predictive_coding --library-root ./papers
paper-ops graph map predictive_coding --library-root ./papers
```

Use the shortcut only when the user asks for citation expansion now:

```bash
paper-ops expand-citations predictive_coding --library-root ./papers
paper-ops expand-citations predictive_coding --rank --library-root ./papers
```

The `--rank` form calls the LLM; the no-rank form does not.

## Manual PDF Arrives

1. User places an authorized PDF in `<papers_root>/manual_downloads/inbox/`.
2. Run `manual scan-once`, or start `manual watch` for long-interval polling.
3. The scanner claims a matching YAML request into `processing/`.
4. Successful processing moves the request to `processed/`, records `linked_paper_id`, hash, and `paper_dir`, then regenerates `README.md`.
5. Failed processing moves the request back to `requests/` with `status: processing_failed`.

## Local PDF Processing

Process local PDFs with explicit metadata. Use `--direction <slug>` when known; classify or ask when uncertain.

```bash
paper-ops process --queued --library-root ./papers
```

For a single PDF, use the module entrypoint:

```bash
PYTHONPATH=src python3 -m paper_ops.process_local_pdf \
  /path/to/paper.pdf \
  "Paper Title" \
  "Author One, Author Two" \
  2026 \
  --venue "ICLR" \
  --abstract "Short abstract or relevance note" \
  --keywords "predictive coding, spiking neural network" \
  --direction predictive_coding \
  --library-root ./papers
```

Single-paper processing creates single-paper artifacts automatically. Direction summaries and the overview are separate triggers.

## Incremental Summaries

Run pending first when the user asks for new single-paper summaries:

```bash
paper-ops summarize pending --library-root ./papers
```

Direction summary policy:

1. Start with existing `library/<direction>/<direction>_summary_zh.md`.
2. Read pending or changed paper artifacts for that direction.
3. Do not default to all old papers.
4. Read selected old paper artifacts only when needed to compare, place, or correct the incremental update.
5. Read `translation_zh.md` only when other artifacts are insufficient.
6. Write a complete rewritten direction summary, not an appended delta.
7. Update `indexes/summary_ledger.json` after success.

Overview policy:

1. Start with existing `library/overview_zh.md`.
2. Read changed direction summaries first.
3. Read other direction summaries only when cross-direction structure or comparisons require it.
4. Write a complete rewritten overview.
5. Update `indexes/summary_ledger.json` after success.

## Batch And Queue Work

Use queue-oriented commands for multi-paper work:

```bash
paper-ops discover --keywords "predictive coding, SNN" --library-root ./papers
paper-ops ingest url "https://example.org/paper" --library-root ./papers
paper-ops ingest pdf /path/to/paper.pdf --library-root ./papers
paper-ops ingest batch candidates.jsonl --library-root ./papers
paper-ops process --queued --library-root ./papers
```

Use controlled parallelism for model-heavy artifact generation:

```bash
PAPER_OPS_MAX_MODEL_CONCURRENCY=2 paper-ops process --queued --library-root ./papers
```

Set concurrency to `1` for fully serial model calls.
