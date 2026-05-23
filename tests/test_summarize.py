import json
from pathlib import Path

from paper_ops.models import PaperPaths
from paper_ops.summarize import write_summary_files
from paper_ops.settings import RuntimeSettings
from paper_ops.summary_ledger import (
    pending_paper_dirs_for_direction,
    record_direction_summary_run,
    record_paper_artifacts,
)


def _make_paper_dir(
    root: Path,
    *,
    direction: str,
    paper_id: str,
    title: str,
    summary_text: str,
    experiments_text: str,
    notes_text: str,
) -> PaperPaths:
    paper_dir = root / "library" / direction / paper_id
    paper_dir.mkdir(parents=True)
    metadata = {
        "paper_id": paper_id,
        "title": title,
        "direction": direction,
        "metadata": {
            "authors": ["Author"],
            "year": 2026,
            "venue": "ICLR",
            "keywords": ["predictive coding"],
            "code_urls": [],
        },
    }
    (paper_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "summary_zh.md").write_text(summary_text, encoding="utf-8")
    (paper_dir / "experiments_zh.md").write_text(
        experiments_text,
        encoding="utf-8",
    )
    (paper_dir / "notes_zh.md").write_text(notes_text, encoding="utf-8")
    (paper_dir / "translation_zh.md").write_text(
        f"# {title}\n\n全文翻译。",
        encoding="utf-8",
    )
    return PaperPaths(
        paper_dir=paper_dir,
        pdf_path=paper_dir / "paper.pdf",
        metadata_path=paper_dir / "metadata.json",
        translation_path=paper_dir / "translation_zh.md",
        summary_path=paper_dir / "summary_zh.md",
        experiments_path=paper_dir / "experiments_zh.md",
        notes_path=paper_dir / "notes_zh.md",
        code_links_path=paper_dir / "code_links.json",
        relevance_path=paper_dir / "relevance_to_my_research.md",
    )


def test_write_summary_files_creates_all_dossier_artifacts(tmp_path: Path):
    translation = tmp_path / "translation_zh.md"
    translation.write_text("# 中文翻译\n\n方法和实验。", encoding="utf-8")

    write_summary_files(
        paper_dir=tmp_path,
        metadata={"title": "Example Paper", "direction": "predictive_coding"},
        translation_text=translation.read_text(encoding="utf-8"),
    )

    assert (tmp_path / "summary_zh.md").exists()
    assert (tmp_path / "experiments_zh.md").exists()
    assert (tmp_path / "notes_zh.md").exists()
    assert (tmp_path / "relevance_to_my_research.md").exists()
    assert (tmp_path / "code_links.json").exists()


def test_summary_file_mentions_direction(tmp_path: Path):
    translation = tmp_path / "translation_zh.md"
    translation.write_text("# 中文翻译\n\n方法和实验。", encoding="utf-8")

    write_summary_files(
        paper_dir=tmp_path,
        metadata={"title": "Example Paper", "direction": "predictive_coding"},
        translation_text=translation.read_text(encoding="utf-8"),
    )

    assert "predictive_coding" in (tmp_path / "summary_zh.md").read_text(encoding="utf-8")


def test_summary_ledger_tracks_pending_direction_papers(tmp_path: Path):
    library_root = tmp_path / "papers"
    paper_paths = _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-karlsson-difference-predictive-coding-snn",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        summary_text="# 单篇总结\n\n贡献。",
        experiments_text="# 实验总结\n\n结果。",
        notes_text="# 笔记\n\n备注。",
    )
    paper_paths.code_links_path.write_text("{}", encoding="utf-8")
    paper_paths.relevance_path.write_text("# 相关性", encoding="utf-8")

    record_paper_artifacts(library_root, paper_paths)

    assert pending_paper_dirs_for_direction(library_root, "predictive_coding") == [
        paper_paths.paper_dir
    ]

    direction_summary_path = (
        library_root / "library" / "predictive_coding" / "predictive_coding_summary_zh.md"
    )
    direction_summary_path.write_text("# 方向总结", encoding="utf-8")
    record_direction_summary_run(
        library_root,
        "predictive_coding",
        [paper_paths.paper_dir],
        direction_summary_path,
    )

    assert pending_paper_dirs_for_direction(library_root, "predictive_coding") == []

    paper_paths.summary_path.write_text("# 单篇总结\n\n更新。", encoding="utf-8")
    record_paper_artifacts(library_root, paper_paths)

    assert pending_paper_dirs_for_direction(library_root, "predictive_coding") == [
        paper_paths.paper_dir
    ]


def test_generate_direction_summary_for_direction_uses_existing_summary_and_pending_papers(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"
    old_paper = _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2025-old-predictive-coding",
        title="Old Predictive Coding",
        summary_text="# 旧单篇\n\n旧贡献。",
        experiments_text="# 旧实验\n\n旧结果。",
        notes_text="# 旧笔记\n\n旧备注。",
    )
    new_paper = _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-new-predictive-coding",
        title="New Predictive Coding",
        summary_text="# 新单篇\n\n新贡献。",
        experiments_text="# 新实验\n\n新结果。",
        notes_text="# 新笔记\n\n新备注。",
    )
    for paper_paths in (old_paper, new_paper):
        paper_paths.code_links_path.write_text("{}", encoding="utf-8")
        paper_paths.relevance_path.write_text("# 相关性", encoding="utf-8")
        record_paper_artifacts(library_root, paper_paths)

    direction_summary_path = (
        library_root / "library" / "predictive_coding" / "predictive_coding_summary_zh.md"
    )
    direction_summary_path.write_text("# 旧方向总结\n\n已经覆盖旧论文。", encoding="utf-8")
    record_direction_summary_run(
        library_root,
        "predictive_coding",
        [old_paper.paper_dir],
        direction_summary_path,
    )

    bundles: list[str] = []

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
        bundles.append(source_path.read_text(encoding="utf-8"))
        output_path.write_text("# 新方向总结\n\n输出。", encoding="utf-8")
        return output_path

    monkeypatch.setattr(
        "paper_ops.summarize.run_artifact_agent_from_file",
        fake_run_artifact_agent_from_file,
    )

    from paper_ops.summarize import generate_direction_summary_for_direction

    output_path = generate_direction_summary_for_direction(
        library_root=library_root,
        direction="predictive_coding",
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
    )

    assert output_path == direction_summary_path
    assert output_path.read_text(encoding="utf-8").startswith("# 新方向总结")
    assert bundles
    assert "# 旧方向总结" in bundles[0]
    assert "# 新单篇" in bundles[0]
    assert "# 旧单篇" not in bundles[0]
    assert pending_paper_dirs_for_direction(library_root, "predictive_coding") == []


def test_generate_direction_and_overview_summaries_updates_existing_summaries(
    tmp_path: Path, monkeypatch
):
    library_root = tmp_path / "papers"
    paper_paths = _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-karlsson-difference-predictive-coding-snn",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        summary_text="# 旧单篇总结\n\n贡献。",
        experiments_text="# 旧实验总结\n\n结果。",
        notes_text="# 旧笔记\n\n备注。",
    )

    direction_summary_path = (
        library_root / "library" / "predictive_coding" / "predictive_coding_summary_zh.md"
    )
    direction_summary_path.parent.mkdir(parents=True, exist_ok=True)
    direction_summary_path.write_text(
        "# 旧方向总结\n\n旧内容。",
        encoding="utf-8",
    )
    overview_summary_path = library_root / "library" / "overview_zh.md"
    overview_summary_path.write_text(
        "# 旧总总结\n\n旧内容。",
        encoding="utf-8",
    )

    bundles: list[tuple[str, str]] = []

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
        bundles.append((spec.name, source_path.read_text(encoding="utf-8")))
        output_path.write_text(f"# {spec.name}\n\n输出。", encoding="utf-8")
        return output_path

    monkeypatch.setattr(
        "paper_ops.summarize.run_artifact_agent_from_file",
        fake_run_artifact_agent_from_file,
    )

    from paper_ops.summarize import generate_direction_and_overview_summaries

    generate_direction_and_overview_summaries(
        library_root=library_root,
        paper_paths=paper_paths,
        direction="predictive_coding",
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
    )

    direction_summary = direction_summary_path.read_text(encoding="utf-8")
    overview_summary = overview_summary_path.read_text(encoding="utf-8")

    assert direction_summary.startswith("# direction_summary")
    assert overview_summary.startswith("# overview_summary")

    direction_bundle = next(text for name, text in bundles if name == "direction_summary")
    overview_bundle = next(text for name, text in bundles if name == "overview_summary")

    assert "# 旧方向总结" in direction_bundle
    assert "library/predictive_coding/predictive_coding_summary_zh.md" in direction_bundle
    assert "# 旧总总结" not in direction_bundle
    assert "# 旧单篇总结" in direction_bundle
    assert "Difference Predictive Coding for Training Spiking Neural Networks" in direction_bundle
    assert "# 旧总总结" in overview_bundle
    assert "# 旧方向总结" in overview_bundle
    assert "# direction_summary" in overview_bundle


def test_generate_direction_and_overview_summaries_bootstraps_from_all_papers(
    tmp_path: Path, monkeypatch
):
    library_root = tmp_path / "papers"
    paper_one = _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-karlsson-difference-predictive-coding-snn",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        summary_text="# 单篇 A\n\n贡献。",
        experiments_text="# 单篇 A 实验\n\n结果。",
        notes_text="# 单篇 A 笔记\n\n备注。",
    )
    _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-lee-event-driven-predictive-coding",
        title="Event-Driven Predictive Coding",
        summary_text="# 单篇 B\n\n贡献。",
        experiments_text="# 单篇 B 实验\n\n结果。",
        notes_text="# 单篇 B 笔记\n\n备注。",
    )

    bundles: list[tuple[str, str]] = []

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
        bundles.append((spec.name, source_path.read_text(encoding="utf-8")))
        output_path.write_text(f"# {spec.name}\n\n输出。", encoding="utf-8")
        return output_path

    monkeypatch.setattr(
        "paper_ops.summarize.run_artifact_agent_from_file",
        fake_run_artifact_agent_from_file,
    )

    from paper_ops.summarize import generate_direction_and_overview_summaries

    generate_direction_and_overview_summaries(
        library_root=library_root,
        paper_paths=paper_one,
        direction="predictive_coding",
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
    )

    direction_bundle = next(text for name, text in bundles if name == "direction_summary")
    assert "# 单篇 A" in direction_bundle
    assert "# 单篇 B" in direction_bundle
    assert "# 旧方向总结" not in direction_bundle
    assert "initial_build" in direction_bundle


def test_rebuild_all_direction_and_overview_summaries_uses_full_direction_snapshots(
    tmp_path: Path, monkeypatch
):
    library_root = tmp_path / "papers"
    _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-karlsson-difference-predictive-coding-snn",
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        summary_text="# 单篇 A\n\n贡献。",
        experiments_text="# 单篇 A 实验\n\n结果。",
        notes_text="# 单篇 A 笔记\n\n备注。",
    )
    _make_paper_dir(
        library_root,
        direction="predictive_coding",
        paper_id="2026-lee-event-driven-predictive-coding",
        title="Event-Driven Predictive Coding",
        summary_text="# 单篇 B\n\n贡献。",
        experiments_text="# 单篇 B 实验\n\n结果。",
        notes_text="# 单篇 B 笔记\n\n备注。",
    )
    _make_paper_dir(
        library_root,
        direction="attractor_dynamics",
        paper_id="2026-zhou-attractor-controllers",
        title="Attractor Controllers for SNNs",
        summary_text="# 单篇 C\n\n贡献。",
        experiments_text="# 单篇 C 实验\n\n结果。",
        notes_text="# 单篇 C 笔记\n\n备注。",
    )

    bundles: list[tuple[str, str]] = []

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
        bundle_text = source_path.read_text(encoding="utf-8")
        bundles.append((spec.name, bundle_text))
        if spec.name == "direction_summary":
            if "direction: predictive_coding" in bundle_text:
                output_path.write_text("# predictive direction\n\n输出。", encoding="utf-8")
            else:
                output_path.write_text("# attractor direction\n\n输出。", encoding="utf-8")
        else:
            output_path.write_text("# overview_summary\n\n输出。", encoding="utf-8")
        return output_path

    monkeypatch.setattr(
        "paper_ops.summarize.run_artifact_agent_from_file",
        fake_run_artifact_agent_from_file,
    )

    from paper_ops.summarize import rebuild_all_direction_and_overview_summaries

    rebuild_all_direction_and_overview_summaries(
        library_root=library_root,
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
    )

    predictive_bundle = next(
        text
        for name, text in bundles
        if name == "direction_summary" and "direction: predictive_coding" in text
    )
    attractor_bundle = next(
        text
        for name, text in bundles
        if name == "direction_summary" and "direction: attractor_dynamics" in text
    )
    overview_bundle = next(text for name, text in bundles if name == "overview_summary")

    assert "# 单篇 A" in predictive_bundle
    assert "# 单篇 B" in predictive_bundle
    assert "initial_build" in predictive_bundle
    assert "# 单篇 C" in attractor_bundle
    assert "mode: full_rebuild" in overview_bundle
    assert "# predict" in overview_bundle or "# predictive direction" in overview_bundle
    assert "# attractor direction" in overview_bundle
    assert (library_root / "library" / "predictive_coding" / "predictive_coding_summary_zh.md").exists()
    assert (library_root / "library" / "attractor_dynamics" / "attractor_dynamics_summary_zh.md").exists()
    assert (library_root / "library" / "overview_zh.md").exists()
