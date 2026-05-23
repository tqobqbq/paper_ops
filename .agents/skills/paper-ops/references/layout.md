# Library Layout

## Root

The library root is project-local by default:

```text
<project>/papers/
```

Resolution order:

1. explicit `--library-root`
2. `PAPER_OPS_LIBRARY_ROOT`
3. current working directory `./papers`

Do not assume papers belong under the `paper_ops` source repository unless that is the user's active project.

## Manual Downloads

Canonical state is YAML. Markdown is a regenerated human view.

```text
<papers_root>/manual_downloads/
  inbox/       # user places authorized PDFs here
  requests/    # active YAML requests
  processing/  # temporary claim files while a watcher processes a request
  processed/   # successful requests
  rejected/    # rejected requests
  README.md    # regenerated human-readable view
```

Create one YAML request per paper with:

- `request_id`
- `status: waiting_for_manual_pdf`
- title, authors, year, venue, DOI if available
- direction
- source or landing pages
- legal PDF attempts
- `expected_filenames`

Do not hand-edit `README.md` as canonical state. Edit YAML or run CLI commands, then regenerate:

```bash
paper-ops manual render-readme --library-root ./papers
```

## Processed Paper Directory

Single-paper processing should produce or verify:

```text
library/<direction>/<paper_id>/
  metadata.json
  paper.pdf
  translation_zh.md
  summary_zh.md
  experiments_zh.md
  notes_zh.md
  code_links.json
  relevance_to_my_research.md
```

Summary state is tracked in:

```text
indexes/summary_ledger.json
```

Indexes are rebuilt with:

```bash
paper-ops build-index --library-root ./papers
```

## Direction Slugs

Use stable lowercase slugs such as `predictive_coding`. Avoid near-duplicate direction names. When direction is unknown:

1. Classify from title, abstract, keywords, and paper content.
2. Check existing library directions.
3. Ask the user only if multiple directions remain plausible.

Do not rename generated directories by hand. Reprocess or add a migration in code when a direction change is needed.
