# Paper Ops Workflows

## Candidate To PDF

1. Use Codex/Claude judgment for discovery and ranking; Python helpers are tools, not the main decision-maker.
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
