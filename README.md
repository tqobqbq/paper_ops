# paper-ops

Standalone paper ingestion, translation, and indexing package.

## Local development

```bash
cd /root/projects/paper_ops
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest tests -v
```
