# Workflow Router

Read only the workflow reference that matches the user's request:

- `references/intake.md`: DOI/title/URL resolution, legal PDF acquisition, manual PDF intake, local PDF processing, queue/batch work.
- `references/graph.md`: citation graph update, graph candidates, graph review, graph enqueue-downloads, snapshots, literature maps, citation expansion.
- `references/summaries.md`: pending single-paper summaries, direction summaries, and overview summaries.

Default sequence for iterative paper discovery:

```bash
paper-ops fetch "<query>" --top 5 --update-graph --library-root ./papers
paper-ops graph candidates <direction> --library-root ./papers
paper-ops graph review <direction> --library-root ./papers
paper-ops graph enqueue-downloads <direction> --priority high --limit 5 --library-root ./papers
```
