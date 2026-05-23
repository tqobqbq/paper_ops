# Policies

## PDF Acquisition

PDF acquisition runs through the vendored paper-search-cli funnel exposed via `paper-ops fetch` and `paper-ops resolve-pdf`:

1. native source download (arXiv, PMC, Europe PMC, IACR, etc.)
2. metadata PDF URL discovered during search
3. open-access repository fallback (PMC, Europe PMC, CORE, OpenAIRE)
4. Unpaywall DOI resolution
5. final DOI-targeted fallback stage

If the funnel returns no PDF, create a manual download request. The user is responsible for placing the PDF in `manual_downloads/inbox/` matching the request's `expected_filenames`.

## Discovery Policy

Paper discovery should be LLM-led. Use Codex/Claude to judge relevance, novelty, direction fit, and whether the paper should enter the queue. Python scripts may collect candidates, normalize metadata, deduplicate, query legal APIs, or validate formats; they should not be the only decision-maker.

## Processing Policy

PDF processing should also be agent-led where judgment is required. Python code handles file layout, extraction, queue state, hashes, indexes, ledgers, and reproducible writes. LLMs handle translation, single-paper summaries, experiments, notes, code links, and relevance artifacts.

Do not tie direction or overview summaries to every PDF processing run. Single-paper artifacts are automatic during processing; direction summaries and total overview are explicit separate actions.

## Manual README Behavior

`manual_downloads/README.md` is for humans. It should reflect the active YAML state:

- active requests appear while waiting for a PDF
- matched and processed requests are removed from the active list
- processing failures remain visible with failure status

When the README is stale, regenerate it from YAML rather than editing it directly.
