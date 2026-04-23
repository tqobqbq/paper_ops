import json
from pathlib import Path


def write_summary_files(paper_dir: Path, metadata: dict[str, str], translation_text: str) -> None:
    title = metadata["title"]
    direction = metadata["direction"]
    translation_snippet = translation_text[:200]

    (paper_dir / "summary_zh.md").write_text(
        f"# {title} 方法总结\n\n方向：{direction}\n\n基于全文翻译生成的第一版方法总结。\n",
        encoding="utf-8",
    )
    (paper_dir / "experiments_zh.md").write_text(
        f"# {title} 实验总结\n\n待从全文翻译中提取数据集、指标和结果。\n",
        encoding="utf-8",
    )
    (paper_dir / "notes_zh.md").write_text(
        f"# {title} 阅读笔记\n\n从翻译文本生成逐节笔记。\n\n{translation_snippet}\n",
        encoding="utf-8",
    )
    (paper_dir / "relevance_to_my_research.md").write_text(
        (
            f"# {title} 与我的研究相关性\n\n方向：{direction}\n\n"
            "待评估与局部学习、预测编码、EI balance、吸引子动力学、自适应计算时间的关系。\n"
        ),
        encoding="utf-8",
    )
    (paper_dir / "code_links.json").write_text(
        json.dumps({"official": [], "community": [], "baseline_ready": False}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
