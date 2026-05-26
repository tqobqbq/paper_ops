# Summary Workflows

## Pending Single-Paper Summaries

Run pending first when the user asks for new single-paper summaries:

```bash
paper-ops summarize pending --library-root ./papers
```

## Direction Summary

1. Start with existing `library/<direction>/<direction>_summary_zh.md`.
2. Read pending or changed paper artifacts for that direction.
3. Do not default to all old papers.
4. Read selected old paper artifacts only when needed to compare, place, or correct the incremental update.
5. Read `translation_zh.md` only when other artifacts are insufficient.
6. Write a complete rewritten direction summary, not an appended delta.
7. Update `indexes/summary_ledger.json` after success.

```bash
paper-ops summarize direction predictive_coding --library-root ./papers
```

## Overview

1. Start with existing `library/overview_zh.md`.
2. Read changed direction summaries first.
3. Read other direction summaries only when cross-direction structure or comparisons require it.
4. Write a complete rewritten overview.
5. Update `indexes/summary_ledger.json` after success.

```bash
paper-ops summarize overview --library-root ./papers
```
