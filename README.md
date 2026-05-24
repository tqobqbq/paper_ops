# paper-ops

Standalone paper ingestion, translation, and indexing package. Discovery and PDF acquisition run through a vendored, modified [paper-search-cli](vendor/paper-search-cli/) (TypeScript/Node).

## Architecture

- `src/paper_ops/` — Python pipeline (ingest, translation, LLM artifacts, summaries, indexes)
- `vendor/paper-search-cli/` — vendored TypeScript CLI that handles all paper search and PDF download across 25 academic sources. Modified from upstream; do not pull from upstream
- `src/paper_ops/paper_search_client.py` — Python wrapper that shells out to the vendored CLI via `node`

## Local development

Requires Python 3.12+, Node.js 18+, and npm.

```bash
cd /root/python_project/paper_ops
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
paper-ops setup    # one-time: runs `npm install && npm run build` in vendor/paper-search-cli/
pytest tests -v
```

## Quick usage

```bash
paper-ops fetch "predictive coding" --top 5 --sources crossref,arxiv --library-root ./papers
paper-ops fetch "<query>" --dry-run            # preview what would be downloaded
paper-ops fetch "<query>" --update-graph       # update graph after successful downloads/processes
paper-ops discover --query "<query>"           # paper-search-backed discovery → queue
paper-ops discover --source <feed-url>         # RSS/Atom feed → queue (feedparser)
paper-ops resolve-pdf --doi 10.0/example       # try paper-search funnel, optional --create-manual-request
paper-ops expand-citations predictive_coding   # citation/reference expansion from local papers
paper-ops expand-citations predictive_coding --rank  # add LLM ranking after deterministic dedupe
paper-ops graph update predictive_coding       # persist paper/relation facts into SQLite graph database
paper-ops graph candidates predictive_coding   # deterministically refresh/export graph-backed candidates
paper-ops graph review predictive_coding       # rank existing graph candidates with the configured LLM
paper-ops summarize direction predictive_coding
```

`expand-citations` updates the graph and writes the current candidate view to:
`<library-root>/indexes/graph_candidates/<direction>.json`.
Paper identity is deduped as soon as references/citations are discovered; candidate
screening is recomputed from the graph before any PDF download.

The durable project-level paper graph lives at:
`<library-root>/indexes/paper_graph.sqlite`. `graph update` records local papers,
external IDs, reference/cited-by relations, and relation contexts incrementally.
Candidate selection is deferred until the next explicit search step
(`graph candidates`, `graph review`, or `expand-citations`), so processing a newly
downloaded batch does not immediately spend LLM calls or lock in a candidate list.
LLM reviews are stored separately for auditability.
