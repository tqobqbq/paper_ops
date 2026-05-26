# Intake Workflows

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
