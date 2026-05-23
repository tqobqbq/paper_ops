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
paper-ops discover --query "<query>"           # paper-search-backed discovery → queue
paper-ops discover --source <feed-url>         # RSS/Atom feed → queue (feedparser)
paper-ops resolve-pdf --doi 10.0/example       # try paper-search funnel, optional --create-manual-request
paper-ops summarize direction predictive_coding
```
