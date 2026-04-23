from pathlib import Path

import pytest

from paper_ops.models import PaperMetadata
from paper_ops.paths import paper_id_from_metadata, paper_paths


def test_paper_id_from_metadata_builds_stable_slug():
    metadata = PaperMetadata(
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        authors=["Karlsson", "Lee"],
        year=2026,
        venue="ICLR",
        source_urls=["https://openreview.net/forum?id=iu9dbz2lB9"],
    )
    assert (
        paper_id_from_metadata(metadata)
        == "2026-karlsson-difference-predictive-coding-for-training-spiking"
    )


def test_paper_id_from_metadata_handles_empty_authors_with_stable_non_empty_id():
    metadata = PaperMetadata(
        title="Spiking Networks",
        authors=[],
        year=2026,
        venue="ICLR",
        source_urls=["https://example.com/paper"],
    )
    paper_id = paper_id_from_metadata(metadata)
    assert paper_id == paper_id_from_metadata(metadata)
    assert paper_id.startswith("2026-")
    assert paper_id != "2026--"


def test_paper_id_from_metadata_handles_non_ascii_only_metadata():
    metadata = PaperMetadata(
        title="中文标题",
        authors=["王 小明"],
        year=2026,
        venue="ICLR",
        source_urls=["https://example.com/paper"],
    )
    paper_id = paper_id_from_metadata(metadata)
    assert paper_id == paper_id_from_metadata(metadata)
    assert paper_id.startswith("2026-")
    assert paper_id != "2026--"


def test_paper_paths_rejects_unsafe_direction(tmp_path: Path):
    with pytest.raises(ValueError):
        paper_paths(tmp_path, "2026-safe-paper", "../outside")


def test_paper_paths_rejects_unsafe_paper_id(tmp_path: Path):
    with pytest.raises(ValueError):
        paper_paths(tmp_path, "../outside", "predictive_coding")
