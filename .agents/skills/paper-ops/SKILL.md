---
name: paper-ops
description: "Use for paper_ops workflows: legal paper PDF resolution, manual PDF intake, local paper processing, graph-backed citation discovery/review/download, summaries, indexes, and paper_ops pipeline development."
---

# Paper Ops

## Core Rule

Use the `paper_ops` Python package as the executable source of truth. This skill chooses the right workflow, safety boundary, and command sequence; it does not replace deterministic code with prose.

Paper library root resolution:

1. explicit `--library-root`
2. `PAPER_OPS_LIBRARY_ROOT`
3. current working directory `./papers`

Default to the user's current project `./papers`, not the `paper_ops` source repository, unless the user is developing this package or explicitly chooses another root.

## First Action

| User asks for | Do first |
| --- | --- |
| DOI, URL, title, or candidate paper | Resolve legal OA sources; read `references/intake.md` |
| No legal PDF found | Create/update a manual request; read `references/policies.md` |
| User placed PDFs in manual inbox | Run one manual scan or start watcher; read `references/layout.md` |
| Local PDF with metadata | Process the PDF into the library; read `references/commands.md` |
| New single-paper summaries/artifacts | Process PDF or run pending summary flow; read `references/intake.md` or `references/summaries.md` |
| Citation graph expansion or finding next papers from downloaded papers | Use graph update/candidates/review separation; read `references/graph.md` |
| Direction summary or total overview | Use incremental summary commands; read `references/summaries.md` |
| Stale README, indexes, ledger, or paths | Read `references/layout.md` and `references/commands.md` |
| Code changes to `paper_ops` | Read `references/development.md` before editing |
| Skill quality, packaging, or validation | Read `references/validation.md` |

## Safety And Defaults

- Use the vendored paper-search-cli funnel (`paper-ops fetch`, `paper-ops resolve-pdf`) for all PDF acquisition. It tries native sources, then PMC/Europe PMC/CORE/OpenAIRE, then Unpaywall, then a final DOI-targeted fallback.
- If the funnel returns no PDF, create a manual download request instead of marking the paper failed.
- Treat graph updates and candidate review as separate stages: updating the graph records paper/relation facts; candidate screening and LLM review happen only when explicitly requested.
- Confirm before running commands that may call external model APIs or modify the default paper library when the user's intent, library root, or cost tolerance is ambiguous.
- Never print full API keys from `/root/.codex/auth.json` or `~/.config/paper-search-cli/config.json`.

## Command Runner

Prefer the installed console script:

```bash
paper-ops --help
```

If it is unavailable, run from the `paper_ops` repository root:

```bash
PYTHONPATH=src python3 -m paper_ops --help
```

Use `references/commands.md` for concrete commands and model-call boundaries.

## Reference Map

- `references/workflows.md`: short router for choosing the right detailed workflow reference.
- `references/intake.md`: legal PDF acquisition, manual intake, local PDF processing, and queue/batch work.
- `references/graph.md`: graph update/candidates/review/enqueue, snapshots, maps, and citation expansion.
- `references/summaries.md`: pending, direction, and overview summary workflows.
- `references/commands.md`: command defaults, installed-vs-source fallback, and external API/model-call notes.
- `references/layout.md`: project-local library layout, manual download state, generated artifacts, and direction slugs.
- `references/policies.md`: legal PDF policy, manual intake rules, and human-readable README behavior.
- `references/development.md`: source map, test strategy, and code-change verification.
- `references/validation.md`: skill validation and pressure scenarios.

Keep `SKILL.md` lean. Move detailed operational rules into these one-hop references instead of adding long sections here.
