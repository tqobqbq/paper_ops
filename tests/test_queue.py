from pathlib import Path

from paper_ops.queue import CandidateQueue, DiscoveryCandidate


def test_candidate_queue_initializes_file_and_roundtrips_load_save(tmp_path: Path):
    queue_path = tmp_path / "candidates" / "queue.json"
    queue = CandidateQueue(queue_path)

    assert queue_path.exists()
    assert queue_path.read_text(encoding="utf-8") == "[]"
    assert queue.load() == []

    entry = DiscoveryCandidate(
        candidate_id="cand-1",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        source_url="https://openreview.net/forum?id=iu9dbz2lB9",
        source_type="openreview",
        discovered_from="manual",
        priority="high",
        reason="keyword match",
    )
    queue.save([entry])

    loaded = queue.load()
    assert len(loaded) == 1
    assert isinstance(loaded[0], DiscoveryCandidate)
    assert loaded[0].matched_keywords == []
    assert loaded[0].accepted is None
    assert loaded[0].linked_paper_id is None


def test_candidate_queue_enqueue_dedupes_and_accepts(tmp_path: Path):
    queue = CandidateQueue(tmp_path / "queue.json")

    first = queue.enqueue(
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        source_url="https://openreview.net/forum?id=iu9dbz2lB9",
        source_type="openreview",
        discovered_from="manual",
        priority="high",
        matched_keywords=["predictive coding"],
        reason="keyword match",
    )
    second = queue.enqueue(
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        source_url="https://openreview.net/forum?id=iu9dbz2lB9",
        source_type="openreview",
        discovered_from="manual",
        priority="high",
        matched_keywords=["predictive coding"],
        reason="keyword match",
    )

    assert second.candidate_id == first.candidate_id
    assert len(queue.load()) == 1

    accepted = queue.accept(first.candidate_id, "2026-karlsson-difference-predictive-coding")
    assert accepted.accepted is True
    assert accepted.linked_paper_id == "2026-karlsson-difference-predictive-coding"

    loaded = queue.load()
    assert len(loaded) == 1
    assert loaded[0].candidate_id == first.candidate_id
    assert loaded[0].accepted is True
    assert loaded[0].linked_paper_id == "2026-karlsson-difference-predictive-coding"


def test_candidate_queue_reject_marks_entry_without_removal(tmp_path: Path):
    queue = CandidateQueue(tmp_path / "queue.json")
    created = queue.enqueue(
        title="Some Paper",
        source_url="https://example.com/paper",
        source_type="url",
        discovered_from="manual",
        priority="low",
        matched_keywords=[],
        reason="manual",
    )

    rejected = queue.reject(created.candidate_id)
    assert rejected.accepted is False

    loaded = queue.load()
    assert len(loaded) == 1
    assert loaded[0].candidate_id == created.candidate_id
    assert loaded[0].accepted is False


def test_candidate_queue_reject_after_accept_clears_linked_paper_id(tmp_path: Path):
    queue = CandidateQueue(tmp_path / "queue.json")
    created = queue.enqueue(
        title="Accepted Then Rejected Paper",
        source_url="https://example.com/accepted-then-rejected",
        source_type="url",
        discovered_from="manual",
        priority="medium",
        matched_keywords=[],
        reason="manual",
    )

    queue.accept(created.candidate_id, "2026-example-accepted-paper")
    queue.reject(created.candidate_id)

    loaded = queue.load()
    assert len(loaded) == 1
    assert loaded[0].candidate_id == created.candidate_id
    assert loaded[0].accepted is False
    assert loaded[0].linked_paper_id is None
