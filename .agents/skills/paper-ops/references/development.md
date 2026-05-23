# Development Reference

## Source Map

- CLI entrypoints: `src/paper_ops/cli.py`, `src/paper_ops/process_local_pdf.py`
- manual download workflow: `src/paper_ops/manual_downloads.py`
- legal PDF resolver and vendored CLI wrapper: `src/paper_ops/paper_search_client.py`
- orchestration: `src/paper_ops/pipeline.py`
- summary ledger: `src/paper_ops/summary_ledger.py`
- model/API calls: `src/paper_ops/artifact_agents.py`
- prompts: `src/paper_ops/prompts/`
- filesystem layout and IDs: `src/paper_ops/paths.py`
- indexes: `src/paper_ops/indexer.py`
- config/providers: `src/paper_ops/settings.py`
- discovery and queue basics: `src/paper_ops/discovery.py`, `src/paper_ops/queue.py`, `src/paper_ops/ingest.py`

Keep behavior in the Python package and tests. The skill is workflow policy, safety guidance, and command selection.

## Code-Change Defaults

- Prefer existing CLI and package patterns over new abstractions.
- Use structured parsers for YAML/JSON/metadata.
- Keep project-local library root behavior: `--library-root`, `PAPER_OPS_LIBRARY_ROOT`, then `./papers`.
- Do not reintroduce runtime model-token caps for generated artifacts.
- Keep manual YAML as canonical state and README as derived state.

## Verification

For manual download or CLI changes:

```bash
PYTHONPATH=src pytest tests/test_manual_downloads.py tests/test_cli_smoke.py -v
```

For summary, artifact, index, or pipeline changes, add the relevant focused tests, then run:

```bash
PYTHONPATH=src pytest tests -v
```

If the installed `paper-ops` command is unavailable, this is not itself a failure; use `PYTHONPATH=src python3 -m paper_ops ...` from the repo root.
