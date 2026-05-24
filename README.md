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
paper-ops graph update predictive_coding       # persist citation expansion into SQLite graph database
paper-ops graph candidates predictive_coding   # export current graph-backed candidates
paper-ops graph review predictive_coding       # rank existing graph candidates with the configured LLM
paper-ops summarize direction predictive_coding
```

`expand-citations` only writes an index artifact by default:
`<library-root>/indexes/candidate_expansions/<direction>.json`.
It dedupes against the existing library before any PDF download. Use the generated
candidate cards to decide what to fetch next.

The durable project-level paper graph lives at:
`<library-root>/indexes/paper_graph.sqlite`. It records local papers, external IDs,
reference/cited-by relations, relation contexts, deterministic candidates, and LLM
reviews so repeated expansion runs can be audited instead of treated as disposable
search output.
