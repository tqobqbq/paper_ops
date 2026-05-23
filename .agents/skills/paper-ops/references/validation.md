# Skill Validation

## Structural Validation

Run after skill-only changes:

```bash
python3 /root/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/paper-ops
```

Run a stale-token scan:

```bash
rg -n 'T[O]DO|\[T[O]DO|source[.]pdf|Use [-]ops|PAPERS_ROOT|snn_codex' .agents/skills/paper-ops --glob '!**/validation.md'
```

The skill may intentionally mention development rules such as not reintroducing runtime model-token caps. Do not treat those deliberate policy mentions as stale residue.

## Pressure Scenarios

Use `evals/trigger_queries.json` and `evals/evals.json` as the machine-readable scenario set. They cover trigger decisions and expected behavior for the pressure prompts below.

- "Download this paywalled paper." Expected: call `paper-ops resolve-pdf` or `paper-ops fetch`; create a manual request only if the funnel returns no PDF.
- "Use this DOI in my current project." Expected: use current project `./papers`, not the `paper_ops` repo path.
- "I put the PDF in the inbox; update the library." Expected: run or propose `manual scan-once`, not hand-edit README.
- "Summarize new papers." Expected: run `summarize pending`; direction and overview summaries stay separately triggered.
- "Update the predictive_coding direction summary." Expected: read existing direction summary plus pending/new paper artifacts first; read old papers only as needed.
- "The manual download README is stale." Expected: regenerate from YAML with `manual render-readme`.

If a scenario fails, revise the shortest relevant instruction in `SKILL.md` or the matching reference file. Avoid adding broad, generic rules.
