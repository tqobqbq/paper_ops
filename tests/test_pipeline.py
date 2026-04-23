import json
from pathlib import Path

from paper_ops.pipeline import process_local_pdf
from paper_ops.settings import RuntimeSettings


def test_process_local_pdf_runs_end_to_end_and_updates_statuses(
    tmp_path: Path, monkeypatch
):
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 fake")
    library_root = tmp_path / "papers"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

    def fake_translate(pdf_path: Path, output_path: Path, settings: RuntimeSettings) -> None:
        assert pdf_path.exists()
        assert settings.model == "gpt-5.4"
        output_path.write_text("# 中文翻译\n\n方法和实验。", encoding="utf-8")

    monkeypatch.setattr("paper_ops.pipeline.translate_pdf_to_markdown", fake_translate)

    result = process_local_pdf(
        source_pdf=source_pdf,
        library_root=library_root,
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        authors=["Karlsson", "Lee"],
        year=2026,
        venue="ICLR",
        abstract="A predictive coding method for training SNNs with local errors.",
        keywords=["predictive coding", "spiking neural network"],
        settings=settings,
    )

    assert result.direction == "predictive_coding"
    assert result.paths.pdf_path.exists()
    assert result.paths.translation_path.exists()
    assert result.paths.summary_path.exists()
    assert result.paths.experiments_path.exists()
    assert result.paths.notes_path.exists()
    assert result.paths.relevance_path.exists()
    assert result.paths.code_links_path.exists()
    assert (library_root / "indexes" / "papers_index.json").exists()

    payload = json.loads(result.paths.metadata_path.read_text(encoding="utf-8"))
    assert payload["direction"] == "predictive_coding"
    assert payload["metadata"]["keywords"] == [
        "predictive coding",
        "spiking neural network",
    ]
    assert payload["status"]["ingested"]["state"] == "completed"
    assert payload["status"]["classified"]["state"] == "completed"
    assert payload["status"]["translated"]["state"] == "completed"
    assert payload["status"]["summarized"]["state"] == "completed"
    assert payload["status"]["indexed"]["state"] == "completed"


def test_process_local_pdf_honors_manual_direction_override(
    tmp_path: Path, monkeypatch
):
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 fake")
    library_root = tmp_path / "papers"
    settings = RuntimeSettings(
        codex_root=Path("/root/.codex"),
        base_url="https://api.example.com/v1",
        model="gpt-5.4",
        api_key="secret-key",
    )

    def fake_translate(pdf_path: Path, output_path: Path, settings: RuntimeSettings) -> None:
        output_path.write_text("# 中文翻译\n\n内容。", encoding="utf-8")

    monkeypatch.setattr("paper_ops.pipeline.translate_pdf_to_markdown", fake_translate)

    result = process_local_pdf(
        source_pdf=source_pdf,
        library_root=library_root,
        title="A generic title",
        authors=["Author"],
        year=2026,
        venue=None,
        direction="theory_reviews",
        abstract="No obvious classifier keywords.",
        keywords=[],
        settings=settings,
    )

    assert result.direction == "theory_reviews"
    payload = json.loads(result.paths.metadata_path.read_text(encoding="utf-8"))
    assert payload["direction"] == "theory_reviews"
