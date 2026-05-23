import json
from pathlib import Path

from paper_ops.artifact_agents import ArtifactRunSummary
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

    def fake_translate_pdf_to_markdown(
        pdf_path: Path,
        output_path: Path,
        settings: RuntimeSettings,
        metadata: dict | None = None,
    ) -> None:
        assert pdf_path.exists()
        output_path.write_text("# 中文翻译\n\n方法和实验。", encoding="utf-8")

    def fake_generate_artifacts(
        *, pdf_path: Path, paths, metadata: dict, settings: RuntimeSettings
    ) -> ArtifactRunSummary:
        assert pdf_path.exists()
        assert settings.model == "gpt-5.4"
        paths.summary_path.write_text("# 方法总结", encoding="utf-8")
        paths.experiments_path.write_text("# 实验总结", encoding="utf-8")
        paths.notes_path.write_text("# 阅读笔记", encoding="utf-8")
        paths.relevance_path.write_text("# 研究相关性", encoding="utf-8")
        paths.code_links_path.write_text(
            json.dumps(
                {
                    "official": [],
                    "community": [],
                    "mentioned_but_unlinked": [],
                    "baseline_ready": False,
                    "baseline_ready_reason": "信息不足",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ArtifactRunSummary(
            completed={
                "summary": paths.summary_path,
                "experiments": paths.experiments_path,
                "code_links": paths.code_links_path,
            },
            failed={},
        )

    monkeypatch.setattr(
        "paper_ops.pipeline.translate_pdf_to_markdown", fake_translate_pdf_to_markdown
    )
    monkeypatch.setattr(
        "paper_ops.pipeline.generate_paper_artifacts", fake_generate_artifacts
    )

    def fail_generate_summaries(**kwargs):
        raise AssertionError("direction/overview summaries should be triggered separately")

    monkeypatch.setattr(
        "paper_ops.pipeline.generate_direction_and_overview_summaries",
        fail_generate_summaries,
    )

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
    assert result.paths.code_links_path.exists()
    assert result.paths.relevance_path.exists()
    assert (library_root / "indexes" / "papers_index.json").exists()
    assert not (
        library_root
        / "library"
        / "predictive_coding"
        / "predictive_coding_summary_zh.md"
    ).exists()
    assert not (library_root / "library" / "overview_zh.md").exists()
    assert (library_root / "indexes" / "summary_ledger.json").exists()

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
    ledger = json.loads(
        (library_root / "indexes" / "summary_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    paper_entry = ledger["papers"][result.paper_id]
    assert paper_entry["direction"] == "predictive_coding"
    assert paper_entry["artifact_hash"]


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

    def fake_translate_pdf_to_markdown(
        pdf_path: Path,
        output_path: Path,
        settings: RuntimeSettings,
        metadata: dict | None = None,
    ) -> None:
        output_path.write_text("# 中文翻译\n\n内容。", encoding="utf-8")

    def fake_generate_artifacts(
        *, pdf_path: Path, paths, metadata: dict, settings: RuntimeSettings
    ) -> ArtifactRunSummary:
        paths.summary_path.write_text("# 方法总结", encoding="utf-8")
        paths.experiments_path.write_text("# 实验总结", encoding="utf-8")
        paths.notes_path.write_text("# 阅读笔记", encoding="utf-8")
        paths.relevance_path.write_text("# 研究相关性", encoding="utf-8")
        paths.code_links_path.write_text(
            json.dumps(
                {
                    "official": [],
                    "community": [],
                    "mentioned_but_unlinked": [],
                    "baseline_ready": False,
                    "baseline_ready_reason": "信息不足",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ArtifactRunSummary(
            completed={
                "summary": paths.summary_path,
                "experiments": paths.experiments_path,
                "code_links": paths.code_links_path,
            },
            failed={},
        )

    monkeypatch.setattr(
        "paper_ops.pipeline.translate_pdf_to_markdown", fake_translate_pdf_to_markdown
    )
    monkeypatch.setattr(
        "paper_ops.pipeline.generate_paper_artifacts", fake_generate_artifacts
    )

    def fake_generate_summaries(
        *, library_root: Path, paper_paths, direction: str, settings: RuntimeSettings
    ) -> None:
        direction_summary_path = (
            library_root / "library" / direction / f"{direction}_summary_zh.md"
        )
        direction_summary_path.parent.mkdir(parents=True, exist_ok=True)
        direction_summary_path.write_text(
            f"# {direction} 方向总结\n",
            encoding="utf-8",
        )
        overview_summary_path = library_root / "library" / "overview_zh.md"
        overview_summary_path.write_text(
            "# 全部方向总总结\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "paper_ops.pipeline.generate_direction_and_overview_summaries",
        fake_generate_summaries,
    )

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


def test_process_local_pdf_can_defer_library_summary_and_index_rebuild_updates_statuses(
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

    def fake_translate_pdf_to_markdown(
        pdf_path: Path,
        output_path: Path,
        settings: RuntimeSettings,
        metadata: dict | None = None,
    ) -> None:
        output_path.write_text("# 中文翻译\n\n方法和实验。", encoding="utf-8")

    def fake_generate_artifacts(
        *, pdf_path: Path, paths, metadata: dict, settings: RuntimeSettings
    ) -> ArtifactRunSummary:
        paths.summary_path.write_text("# 方法总结", encoding="utf-8")
        paths.experiments_path.write_text("# 实验总结", encoding="utf-8")
        paths.notes_path.write_text("# 阅读笔记", encoding="utf-8")
        paths.relevance_path.write_text("# 研究相关性", encoding="utf-8")
        paths.code_links_path.write_text(
            json.dumps(
                {
                    "official": [],
                    "community": [],
                    "mentioned_but_unlinked": [],
                    "baseline_ready": False,
                    "baseline_ready_reason": "信息不足",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ArtifactRunSummary(
            completed={
                "summary": paths.summary_path,
                "experiments": paths.experiments_path,
                "code_links": paths.code_links_path,
            },
            failed={},
        )

    monkeypatch.setattr(
        "paper_ops.pipeline.translate_pdf_to_markdown", fake_translate_pdf_to_markdown
    )
    monkeypatch.setattr(
        "paper_ops.pipeline.generate_paper_artifacts", fake_generate_artifacts
    )

    def fake_generate_summaries(
        *, library_root: Path, paper_paths, direction: str, settings: RuntimeSettings
    ) -> None:
        direction_summary_path = (
            library_root / "library" / direction / f"{direction}_summary_zh.md"
        )
        direction_summary_path.parent.mkdir(parents=True, exist_ok=True)
        direction_summary_path.write_text(
            f"# {direction} 方向总结\n",
            encoding="utf-8",
        )
        overview_summary_path = library_root / "library" / "overview_zh.md"
        overview_summary_path.write_text(
            "# 全部方向总总结\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "paper_ops.pipeline.generate_direction_and_overview_summaries",
        fake_generate_summaries,
    )

    result = process_local_pdf(
        source_pdf=source_pdf,
        library_root=library_root,
        title="Predictive Coding with Spiking Neurons",
        authors=["Author"],
        year=2026,
        venue="Test Venue",
        abstract="predictive coding",
        keywords=["predictive coding"],
        settings=settings,
    )

    metadata_path = result.paths.metadata_path
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["status"]["translated"]["state"] == "completed"
    assert payload["status"]["summarized"]["state"] == "completed"
    assert payload["status"]["indexed"]["state"] == "completed"


def test_process_local_pdf_can_defer_library_summary_and_index_rebuild_skips_calls(
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

    def fake_generate_artifacts(
        *, pdf_path: Path, paths, metadata: dict, settings: RuntimeSettings
    ) -> ArtifactRunSummary:
        paths.summary_path.write_text("# 方法总结", encoding="utf-8")
        paths.experiments_path.write_text("# 实验总结", encoding="utf-8")
        paths.notes_path.write_text("# 阅读笔记", encoding="utf-8")
        paths.relevance_path.write_text("# 研究相关性", encoding="utf-8")
        paths.code_links_path.write_text(
            json.dumps(
                {
                    "official": [],
                    "community": [],
                    "mentioned_but_unlinked": [],
                    "baseline_ready": False,
                    "baseline_ready_reason": "信息不足",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ArtifactRunSummary(
            completed={
                "summary": paths.summary_path,
                "experiments": paths.experiments_path,
                "notes": paths.notes_path,
                "code_links": paths.code_links_path,
                "relevance": paths.relevance_path,
            },
            failed={},
        )

    def fake_translate_pdf_to_markdown(
        pdf_path: Path,
        output_path: Path,
        settings: RuntimeSettings,
        metadata: dict | None = None,
    ) -> None:
        output_path.write_text("# 中文翻译\n\n内容。", encoding="utf-8")

    monkeypatch.setattr(
        "paper_ops.pipeline.translate_pdf_to_markdown", fake_translate_pdf_to_markdown
    )
    monkeypatch.setattr(
        "paper_ops.pipeline.generate_paper_artifacts", fake_generate_artifacts
    )

    def fail_generate_summaries(**kwargs):
        raise AssertionError("direction/overview summaries should be deferred")

    def fail_rebuild_indexes(*args, **kwargs):
        raise AssertionError("index rebuild should be deferred")

    monkeypatch.setattr(
        "paper_ops.pipeline.generate_direction_and_overview_summaries",
        fail_generate_summaries,
    )
    monkeypatch.setattr("paper_ops.pipeline.rebuild_indexes", fail_rebuild_indexes)

    result = process_local_pdf(
        source_pdf=source_pdf,
        library_root=library_root,
        title="Sparse Coding with an Overcomplete Basis Set",
        authors=["Olshausen", "Field"],
        year=1997,
        venue="Vision Research",
        keywords=["sparse coding"],
        direction="efficient_sparse_coding",
        settings=settings,
        refresh_direction_and_overview_summaries=False,
        refresh_indexes=False,
    )

    payload = json.loads(result.paths.metadata_path.read_text(encoding="utf-8"))
    assert payload["status"]["translated"]["state"] == "completed"
    assert payload["status"]["summarized"]["state"] == "completed"
    assert payload["status"]["indexed"]["state"] == "skipped"
    assert "defers index rebuild" in payload["status"]["indexed"]["last_error"]
