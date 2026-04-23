from pathlib import Path

from paper_ops.library import ensure_paper_archive
from paper_ops.models import PaperMetadata, PaperRecord, ProcessingStatus, SourceInfo
from paper_ops.paths import paper_paths


def test_ensure_paper_archive_creates_standard_files(tmp_path: Path):
    record = PaperRecord(
        paper_id="2026-karlsson-difference-predictive-coding-for-training-spiking",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        direction="predictive_coding",
        status=ProcessingStatus(),
        source=SourceInfo(type="url", url="https://openreview.net/forum?id=iu9dbz2lB9"),
        metadata=PaperMetadata(
            title="Difference Predictive Coding for Training Spiking Neural Networks",
            authors=["Karlsson", "Lee"],
            year=2026,
            venue="ICLR",
            source_urls=["https://openreview.net/forum?id=iu9dbz2lB9"],
        ),
    )

    paths = paper_paths(tmp_path, record.paper_id, record.direction)
    ensure_paper_archive(paths)

    assert paths.paper_dir.exists()
    assert paths.pdf_path.name == "paper.pdf"
    assert paths.translation_path.name == "translation_zh.md"


def test_ensure_paper_archive_creates_parent_direction_readme_dir(tmp_path: Path):
    record = PaperRecord(
        paper_id="2026-karlsson-difference-predictive-coding-for-training-spiking",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        direction="predictive_coding",
        status=ProcessingStatus(),
        source=SourceInfo(type="url", url="https://openreview.net/forum?id=iu9dbz2lB9"),
        metadata=PaperMetadata(
            title="Difference Predictive Coding for Training Spiking Neural Networks",
            authors=["Karlsson", "Lee"],
            year=2026,
            venue="ICLR",
            source_urls=["https://openreview.net/forum?id=iu9dbz2lB9"],
        ),
    )

    paths = paper_paths(tmp_path, record.paper_id, record.direction)
    ensure_paper_archive(paths)
    assert paths.paper_dir.parent.name == "predictive_coding"
