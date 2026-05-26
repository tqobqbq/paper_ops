# Graph Workflows

## Discovery Loop

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

Only call the LLM when the user explicitly asks for review/ranking:

```bash
paper-ops graph review predictive_coding --library-root ./papers
```

## Download Reviewed Candidates

When LLM or human review marks candidates for download, enqueue them through the
legal PDF funnel:

```bash
paper-ops graph enqueue-downloads predictive_coding --decision fetch --priority high --limit 5 --library-root ./papers
```

Successful legal downloads are queued for manual scan processing. If no legal PDF
is found, create a manual request and mark the graph candidate `manual_required`.
Manual scan callbacks update graph candidates to `downloaded` or `download_failed`.

## Snapshots And Maps

Use snapshots and maps when the user asks for history or a literature overview:

```bash
paper-ops graph snapshot predictive_coding --library-root ./papers
paper-ops graph map predictive_coding --library-root ./papers
```

## Citation Expansion Shortcut

Use the shortcut only when the user asks for citation expansion now:

```bash
paper-ops expand-citations predictive_coding --library-root ./papers
paper-ops expand-citations predictive_coding --rank --library-root ./papers
```

The `--rank` form calls the LLM; the no-rank form does not.
