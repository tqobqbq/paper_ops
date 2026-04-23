from pathlib import Path

from paper_ops.summarize import write_summary_files


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
