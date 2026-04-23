import json
from pathlib import Path

from paper_ops.indexer import rebuild_indexes


def _write_metadata(
    root: Path,
    direction: str,
    paper_id: str,
    title: str,
) -> None:
    paper_dir = root / "library" / direction / paper_id
    paper_dir.mkdir(parents=True)
    payload = {
        "paper_id": paper_id,
        "title": title,
        "direction": direction,
        "metadata": {"authors": ["Author"], "year": 2026, "venue": "ICLR"},
    }
    (paper_dir / "metadata.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_rebuild_indexes_creates_global_index_and_direction_readme(tmp_path: Path):
    _write_metadata(
        tmp_path,
        "predictive_coding",
        "2026-karlsson-difference-predictive-coding-snn",
        "Difference Predictive Coding for Training Spiking Neural Networks",
    )
    _write_metadata(
        tmp_path,
        "predictive_coding",
        "2026-lee-event-driven-predictive-coding",
        "Event-Driven Predictive Coding",
    )

    rebuild_indexes(tmp_path)

    papers_index_path = tmp_path / "indexes" / "papers_index.json"
    directions_index_path = tmp_path / "indexes" / "directions_index.json"
    direction_readme = tmp_path / "library" / "predictive_coding" / "README.md"

    assert papers_index_path.exists()
    assert directions_index_path.exists()
    assert direction_readme.exists()

    papers_index = json.loads(papers_index_path.read_text(encoding="utf-8"))
    directions_index = json.loads(directions_index_path.read_text(encoding="utf-8"))
    readme_text = direction_readme.read_text(encoding="utf-8")

    assert "2026-karlsson-difference-predictive-coding-snn" in papers_index
    assert "2026-lee-event-driven-predictive-coding" in papers_index
    assert directions_index["predictive_coding"] == [
        "2026-karlsson-difference-predictive-coding-snn",
        "2026-lee-event-driven-predictive-coding",
    ]
    assert "- `2026-karlsson-difference-predictive-coding-snn`" in readme_text
    assert "- `2026-lee-event-driven-predictive-coding`" in readme_text


def test_rebuild_indexes_creates_top_level_library_readme(tmp_path: Path):
    _write_metadata(
        tmp_path,
        "predictive_coding",
        "2026-karlsson-difference-predictive-coding-snn",
        "Difference Predictive Coding for Training Spiking Neural Networks",
    )
    _write_metadata(
        tmp_path,
        "attractor_dynamics",
        "2026-zhou-attractor-controllers",
        "Attractor Controllers for SNNs",
    )
    _write_metadata(
        tmp_path,
        "attractor_dynamics",
        "2026-zhang-stable-attractors",
        "Stable Attractors in Spiking Systems",
    )

    rebuild_indexes(tmp_path)

    top_readme = tmp_path / "README.md"
    assert top_readme.exists()
    readme_text = top_readme.read_text(encoding="utf-8")
    assert "- attractor_dynamics (2 papers)" in readme_text
    assert "- predictive_coding (1 papers)" in readme_text
