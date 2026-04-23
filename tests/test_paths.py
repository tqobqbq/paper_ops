from paper_ops.models import PaperMetadata
from paper_ops.paths import paper_id_from_metadata


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
