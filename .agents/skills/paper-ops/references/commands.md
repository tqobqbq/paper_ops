# Command Reference

## Runner Fallback

Try installed commands first:

```bash
paper-ops --help
```

If unavailable, use the repository source entrypoint from the `paper_ops` repo root:

```bash
PYTHONPATH=src python3 -m paper_ops --help
```

Use the same fallback pattern for subcommands:

```bash
PYTHONPATH=src python3 -m paper_ops resolve-pdf --help
PYTHONPATH=src python3 -m paper_ops manual --help
PYTHONPATH=src python3 -m paper_ops summarize --help
```

## Common Commands

```bash
paper-ops setup
paper-ops fetch "<query>" --top 5 --sources crossref,arxiv --year 2023-2025 --library-root ./papers
paper-ops fetch "<query>" --top 5 --library-root ./papers --dry-run
paper-ops resolve-pdf --help
paper-ops discover --help
paper-ops ingest --help
paper-ops process --help
paper-ops build-index --library-root ./papers
paper-ops manual create-request --help
paper-ops manual render-readme --library-root ./papers
paper-ops manual scan-once --library-root ./papers
paper-ops manual watch --interval-seconds 1800 --library-root ./papers
paper-ops summarize pending --library-root ./papers
paper-ops summarize direction predictive_coding --library-root ./papers
paper-ops summarize overview --library-root ./papers
paper-ops graph update predictive_coding --library-root ./papers
paper-ops graph sync --library-root ./papers
paper-ops graph candidates predictive_coding --library-root ./papers
paper-ops graph review predictive_coding --library-root ./papers
paper-ops graph enqueue-downloads predictive_coding --priority high --limit 5 --library-root ./papers
paper-ops graph snapshot predictive_coding --library-root ./papers
paper-ops graph map predictive_coding --library-root ./papers
paper-ops expand-citations predictive_coding --library-root ./papers
paper-ops expand-citations predictive_coding --rank --library-root ./papers
```

`paper-ops setup` runs `npm install && npm run build` in `vendor/paper-search-cli/`. It must succeed once before any command that calls paper-search (`fetch`, `discover --query`, `resolve-pdf`).

`paper-ops fetch <query>` is the one-shot entrypoint: search via paper-search, take top-N, download each through the funnel into `manual_downloads/inbox/`, run the existing `manual scan-once` state machine to ingest + generate all per-paper artifacts. Add `--summarize` to also refresh direction + overview summaries for touched directions.

## External API And Model Boundaries

Commands likely to call model APIs or trigger model-heavy processing:

- `process --queued`
- `fetch` (downstream pipeline runs translation + 5 artifacts per paper)
- `paper_ops.process_local_pdf`
- `manual scan-once` when a matching PDF is processed
- `manual watch` when a matching PDF is processed
- `summarize direction`
- `summarize overview`
- `graph review`
- `expand-citations --rank`
- discovery flows that explicitly use Codex/Claude judgment

Commands that are usually local or metadata/network oriented:

- `setup` (only npm install + build)
- `build-index`
- `manual create-request`
- `manual render-readme`
- `summarize pending`
- `resolve-pdf` calls paper-search (network) but no LLM
- `discover --source <feed-url>` (RSS only)
- `discover --query <text>` (paper-search only, no LLM)
- `graph update` calls citation metadata providers but no LLM; it records graph facts only.
- `graph sync` runs graph updates across library directions; no LLM.
- `graph candidates` refreshes the deterministic not-yet-downloaded candidate view from SQLite; no LLM.
- `graph enqueue-downloads` uses paper-search network download resolution; no LLM.
- `graph snapshot` and `graph map` export existing graph/candidate data; no LLM.
- `expand-citations` without `--rank` updates graph facts and exports candidates; no LLM.

Ask the user before running model/API-heavy commands when the request does not clearly authorize cost, network use, provider choice, or changes to the default library root.

## Provider Overrides

Only use provider overrides when the user or environment requires them:

```bash
paper-ops manual scan-once --model-provider claude --model "<model>" --library-root ./papers
```

Useful environment variables:

- `PAPER_OPS_LIBRARY_ROOT`: default paper library root.
- `PAPER_OPS_MAX_MODEL_CONCURRENCY`: max concurrent model calls.
- `PAPER_OPS_MAX_WORKERS`: general worker fallback.

Do not set these globally unless the user asks.
