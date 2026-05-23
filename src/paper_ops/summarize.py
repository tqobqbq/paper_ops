from __future__ import annotations

import json
import tempfile
from pathlib import Path

from paper_ops.artifact_agents import (
    ArtifactRunSummary,
    ArtifactSpec,
    generate_parallel_artifacts_from_pdf,
    run_artifact_agent_from_file,
)
from paper_ops.models import PaperPaths
from paper_ops.settings import RuntimeSettings
from paper_ops.summary_ledger import (
    pending_paper_dirs_for_direction,
    record_direction_summary_run,
    record_overview_summary_run,
)


OVERVIEW_SUMMARY_FILENAME = "overview_zh.md"


def _direction_summary_path(library_root: Path, direction: str) -> Path:
    return library_root / "library" / direction / f"{direction}_summary_zh.md"


def _overview_summary_path(library_root: Path) -> Path:
    return library_root / "library" / OVERVIEW_SUMMARY_FILENAME


def _bundle_path_label(library_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(library_root))
    except ValueError:
        return str(path)


SUMMARY_SPEC = ArtifactSpec(
    name="direction_summary",
    prompt_filename="summarize_direction.md",
    output_path_attr="",
    output_kind="markdown",
)
OVERVIEW_SPEC = ArtifactSpec(
    name="overview_summary",
    prompt_filename="summarize_overview.md",
    output_path_attr="",
    output_kind="markdown",
)


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
        json.dumps(
            {"official": [], "community": [], "baseline_ready": False},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def generate_paper_artifacts(
    *,
    pdf_path: Path,
    paths: PaperPaths,
    metadata: dict[str, object],
    settings: RuntimeSettings,
) -> ArtifactRunSummary:
    return generate_parallel_artifacts_from_pdf(
        pdf_path=pdf_path,
        paths=paths,
        metadata=metadata,
        settings=settings,
    )


def _read_text(path: Path) -> str:
    if not path.exists():
        return "[missing]"
    return path.read_text(encoding="utf-8")


def _normalize_text(text: str) -> str:
    return text.rstrip() + "\n"


def _paper_payload(paper_dir: Path) -> dict[str, object]:
    metadata_path = paper_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata.json in {paper_dir}")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _paper_identity_lines(payload: dict[str, object]) -> list[str]:
    metadata = payload.get("metadata", {})
    metadata_dict = metadata if isinstance(metadata, dict) else {}

    authors = metadata_dict.get("authors", [])
    keywords = metadata_dict.get("keywords", [])
    code_urls = metadata_dict.get("code_urls", [])

    def _join(value: object) -> str:
        if isinstance(value, list):
            items = [str(item) for item in value if str(item).strip()]
            return ", ".join(items) if items else "None"
        return "None"

    return [
        f"- paper_id: {payload.get('paper_id', 'unknown')}",
        f"- title: {payload.get('title', 'unknown')}",
        f"- direction: {payload.get('direction', 'unknown')}",
        f"- year: {metadata_dict.get('year', 'unknown')}",
        f"- venue: {metadata_dict.get('venue', 'unknown')}",
        f"- authors: {_join(authors)}",
        f"- keywords: {_join(keywords)}",
        f"- code_urls: {_join(code_urls)}",
    ]


def _file_section(path: Path) -> str:
    return (
        f"### {path.name}\n"
        f"PATH: {path}\n"
        "[[BEGIN FILE]]\n"
        f"{_read_text(path).rstrip()}\n"
        "[[END FILE]]\n"
    )


def _paper_dossier_text(paper_dir: Path, include_translation: bool = False) -> str:
    payload = _paper_payload(paper_dir)
    title = str(payload.get("title", paper_dir.name))

    lines = [f"### {title}"]
    lines.extend(_paper_identity_lines(payload))
    lines.append("")
    for filename in ("summary_zh.md", "experiments_zh.md", "notes_zh.md"):
        lines.append(_file_section(paper_dir / filename))
    if include_translation:
        lines.append(_file_section(paper_dir / "translation_zh.md"))
    return "\n".join(lines).rstrip() + "\n"


def _direction_paper_dirs(library_root: Path, direction: str) -> list[Path]:
    direction_root = library_root / "library" / direction
    if not direction_root.exists():
        return []
    paper_dirs = [
        child
        for child in direction_root.iterdir()
        if child.is_dir() and (child / "metadata.json").exists()
    ]
    paper_dirs.sort(key=lambda paper_dir: str(_paper_payload(paper_dir).get("paper_id", paper_dir.name)))
    return paper_dirs


def _paper_reference_table(paper_dirs: list[Path]) -> str:
    if not paper_dirs:
        return "[no papers]"

    lines = ["| # | paper_id | title | year | venue |", "| --- | --- | --- | --- | --- |"]
    for index, paper_dir in enumerate(paper_dirs, start=1):
        payload = _paper_payload(paper_dir)
        metadata = payload.get("metadata", {})
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        lines.append(
            "| {index} | {paper_id} | {title} | {year} | {venue} |".format(
                index=index,
                paper_id=payload.get("paper_id", "unknown"),
                title=payload.get("title", "unknown"),
                year=metadata_dict.get("year", "unknown"),
                venue=metadata_dict.get("venue", "unknown"),
            )
        )
    return "\n".join(lines)


def _direction_bundle_text(
    *,
    library_root: Path,
    direction: str,
    current_paper_dir: Path | None = None,
    existing_direction_summary: str | None,
    paper_dirs_for_bundle: list[Path] | None = None,
) -> str:
    paper_dirs = _direction_paper_dirs(library_root, direction)
    direction_summary_path = _direction_summary_path(library_root, direction)
    use_incremental_mode = existing_direction_summary is not None
    if paper_dirs_for_bundle is None:
        if current_paper_dir is not None:
            paper_dirs_for_bundle = [current_paper_dir] if use_incremental_mode else paper_dirs
        else:
            paper_dirs_for_bundle = paper_dirs

    lines = [
        "# Direction Summary Bundle",
        "",
        "## Task",
        f"- mode: {'incremental_update' if use_incremental_mode else 'initial_build'}",
        f"- direction: {direction}",
        "",
        "## Reference Index",
        _paper_reference_table(paper_dirs),
        "",
        "## Existing direction summary",
    ]
    if existing_direction_summary is not None:
        lines.extend(
            [
                f"### {_bundle_path_label(library_root, direction_summary_path)}",
                "[[BEGIN FILE]]",
                existing_direction_summary.rstrip(),
                "[[END FILE]]",
                "",
            ]
        )
    else:
        lines.append("[none]")
        lines.append("")

    lines.append("## Paper dossiers")
    for paper_dir in paper_dirs_for_bundle:
        include_translation = (
            current_paper_dir is not None
            and paper_dir == current_paper_dir
            and (use_incremental_mode or len(paper_dirs_for_bundle) == 1)
        )
        lines.append(_paper_dossier_text(paper_dir, include_translation=include_translation))

    return "\n".join(lines).rstrip() + "\n"


def _overview_direction_index(library_root: Path) -> list[tuple[str, int, Path | None]]:
    library_dir = library_root / "library"
    if not library_dir.exists():
        return []

    direction_entries: list[tuple[str, int, Path | None]] = []
    for direction_dir in sorted(path for path in library_dir.iterdir() if path.is_dir()):
        direction = direction_dir.name
        paper_dirs = [
            child
            for child in direction_dir.iterdir()
            if child.is_dir() and (child / "metadata.json").exists()
        ]
        summary_path = _direction_summary_path(library_root, direction)
        direction_entries.append(
            (
                direction,
                len(paper_dirs),
                summary_path if summary_path.exists() else None,
            )
        )
    return direction_entries


def _overview_bundle_text(
    *,
    library_root: Path,
    updated_direction: str,
    previous_overview_summary: str | None,
    previous_direction_summary: str | None,
    new_direction_summary: str,
    updated_paper_dir: Path,
) -> str:
    direction_entries = _overview_direction_index(library_root)
    current_snapshot_paths = {
        direction: summary_path
        for direction, _, summary_path in direction_entries
        if summary_path is not None
    }
    overview_summary_path = _overview_summary_path(library_root)
    previous_direction_summary_path = _direction_summary_path(
        library_root, updated_direction
    )

    lines = [
        "# Overview Summary Bundle",
        "",
        "## Task",
        f"- mode: {'incremental_update' if previous_overview_summary is not None else 'initial_build'}",
        f"- updated direction: {updated_direction}",
        "",
        "## Direction Index",
        "| direction | papers | summary_path |",
        "| --- | ---: | --- |",
    ]
    for direction, paper_count, summary_path in direction_entries:
        summary_text = summary_path.name if summary_path is not None else "[missing]"
        lines.append(f"| {direction} | {paper_count} | {summary_text} |")

    lines.extend(["", "## Previous total summary"])
    if previous_overview_summary is not None:
        lines.extend(
            [
                f"### {_bundle_path_label(library_root, overview_summary_path)}",
                "[[BEGIN FILE]]",
                previous_overview_summary.rstrip(),
                "[[END FILE]]",
                "",
            ]
        )
    else:
        lines.append("[none]")
        lines.append("")

    lines.extend(["## Updated direction: previous summary"])
    if previous_direction_summary is not None:
        lines.extend(
            [
                f"### {_bundle_path_label(library_root, previous_direction_summary_path)}",
                "[[BEGIN FILE]]",
                previous_direction_summary.rstrip(),
                "[[END FILE]]",
                "",
            ]
        )
    else:
        lines.append("[none]")
        lines.append("")

    lines.extend(["## Updated direction: new summary"])
    lines.extend(
        [
            f"### {_bundle_path_label(library_root, previous_direction_summary_path)}",
            "[[BEGIN FILE]]",
            new_direction_summary.rstrip(),
            "[[END FILE]]",
            "",
        ]
    )

    lines.extend(["## Updated paper dossier"])
    include_translation = True
    lines.append(
        _paper_dossier_text(updated_paper_dir, include_translation=include_translation)
    )

    lines.extend(["## Current direction summaries"])
    for direction, summary_path in sorted(current_snapshot_paths.items()):
        if direction == updated_direction:
            continue
        lines.extend(
            [
                f"### {_bundle_path_label(library_root, summary_path)}",
                "[[BEGIN FILE]]",
                _read_text(summary_path).rstrip(),
                "[[END FILE]]",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"

def _write_summary_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_normalize_text(text), encoding="utf-8")


def _generate_direction_summary(
    *,
    library_root: Path,
    direction: str,
    current_paper_dir: Path | None = None,
    previous_direction_summary: str | None,
    settings: RuntimeSettings,
    paper_dirs_for_bundle: list[Path] | None = None,
) -> str:
    with tempfile.TemporaryDirectory(prefix="paper_ops_direction_summary_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        direction_bundle_path = tmp_dir / f"{direction}_direction_bundle.md"
        direction_bundle_path.write_text(
            _normalize_text(
                _direction_bundle_text(
                    library_root=library_root,
                    direction=direction,
                    current_paper_dir=current_paper_dir,
                    existing_direction_summary=previous_direction_summary,
                    paper_dirs_for_bundle=paper_dirs_for_bundle,
                )
            ),
            encoding="utf-8",
        )

        direction_output_path = tmp_dir / f"{direction}_summary_zh.md"
        run_artifact_agent_from_file(
            source_path=direction_bundle_path,
            spec=SUMMARY_SPEC,
            output_path=direction_output_path,
            context_text=(
                "Direction summary update task.\n"
                f"- direction: {direction}\n"
                f"- mode: {'incremental_update' if previous_direction_summary is not None else 'initial_build'}\n"
                "- The attached bundle is the source of truth.\n"
                "- Rebuild the full direction summary instead of appending a delta.\n"
            ),
            settings=settings,
        )
        return _read_text(direction_output_path)


def _generate_incremental_overview_summary(
    *,
    library_root: Path,
    updated_direction: str,
    previous_overview_summary: str | None,
    previous_direction_summary: str | None,
    new_direction_summary: str,
    updated_paper_dir: Path,
    settings: RuntimeSettings,
) -> str:
    with tempfile.TemporaryDirectory(prefix="paper_ops_overview_summary_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        overview_bundle_path = tmp_dir / "overview_bundle.md"
        overview_bundle_path.write_text(
            _normalize_text(
                _overview_bundle_text(
                    library_root=library_root,
                    updated_direction=updated_direction,
                    previous_overview_summary=previous_overview_summary,
                    previous_direction_summary=previous_direction_summary,
                    new_direction_summary=new_direction_summary,
                    updated_paper_dir=updated_paper_dir,
                )
            ),
            encoding="utf-8",
        )

        overview_output_path = tmp_dir / OVERVIEW_SUMMARY_FILENAME
        run_artifact_agent_from_file(
            source_path=overview_bundle_path,
            spec=OVERVIEW_SPEC,
            output_path=overview_output_path,
            context_text=(
                "Total summary update task.\n"
                f"- updated direction: {updated_direction}\n"
                f"- mode: {'incremental_update' if previous_overview_summary is not None else 'initial_build'}\n"
                "- Read the previous overview, the previous direction summary, the new direction summary, "
                "and the current direction snapshot.\n"
                "- If needed, inspect the attached paper dossier for the updated paper.\n"
                "- Rebuild the full overview instead of appending a delta.\n"
            ),
            settings=settings,
        )
        return _read_text(overview_output_path)


def _overview_full_rebuild_bundle_text(*, library_root: Path) -> str:
    direction_entries = _overview_direction_index(library_root)
    current_snapshot_paths = {
        direction: summary_path
        for direction, _, summary_path in direction_entries
        if summary_path is not None
    }

    lines = [
        "# Overview Summary Bundle",
        "",
        "## Task",
        "- mode: full_rebuild",
        "- Rebuild the total summary from the current direction summaries only.",
        "",
        "## Direction Index",
        "| direction | papers | summary_path |",
        "| --- | ---: | --- |",
    ]
    for direction, paper_count, summary_path in direction_entries:
        summary_text = summary_path.name if summary_path is not None else "[missing]"
        lines.append(f"| {direction} | {paper_count} | {summary_text} |")

    lines.extend(["", "## Current direction summaries"])
    for direction, summary_path in sorted(current_snapshot_paths.items()):
        lines.extend(
            [
                f"### {_bundle_path_label(library_root, summary_path)}",
                "[[BEGIN FILE]]",
                _read_text(summary_path).rstrip(),
                "[[END FILE]]",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def generate_overview_summary_from_current_directions(
    *,
    library_root: Path,
    settings: RuntimeSettings,
) -> None:
    overview_summary_path = _overview_summary_path(library_root)

    with tempfile.TemporaryDirectory(prefix="paper_ops_overview_rebuild_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        overview_bundle_path = tmp_dir / "overview_rebuild_bundle.md"
        overview_bundle_path.write_text(
            _normalize_text(_overview_full_rebuild_bundle_text(library_root=library_root)),
            encoding="utf-8",
        )

        overview_output_path = tmp_dir / OVERVIEW_SUMMARY_FILENAME
        run_artifact_agent_from_file(
            source_path=overview_bundle_path,
            spec=OVERVIEW_SPEC,
            output_path=overview_output_path,
            context_text=(
                "Total summary rebuild task.\n"
                "- mode: full_rebuild\n"
                "- The attached direction summaries are the source of truth.\n"
                "- Rebuild the full library-level overview from them.\n"
            ),
            settings=settings,
        )
        _write_summary_text(overview_summary_path, _read_text(overview_output_path))
        record_overview_summary_run(library_root, overview_summary_path)


def rebuild_all_direction_and_overview_summaries(
    *,
    library_root: Path,
    settings: RuntimeSettings,
) -> None:
    direction_records = _overview_direction_index(library_root)
    for direction, _, _ in direction_records:
        paper_dirs = _direction_paper_dirs(library_root, direction)
        if not paper_dirs:
            continue
        direction_summary = _generate_direction_summary(
            library_root=library_root,
            direction=direction,
            current_paper_dir=paper_dirs[0],
            previous_direction_summary=None,
            settings=settings,
        )
        _write_summary_text(_direction_summary_path(library_root, direction), direction_summary)
        record_direction_summary_run(
            library_root,
            direction,
            paper_dirs,
            _direction_summary_path(library_root, direction),
        )

    generate_overview_summary_from_current_directions(
        library_root=library_root,
        settings=settings,
    )


def generate_direction_summary_for_direction(
    *,
    library_root: Path,
    direction: str,
    settings: RuntimeSettings,
) -> Path:
    direction_summary_path = _direction_summary_path(library_root, direction)
    previous_direction_summary = (
        _read_text(direction_summary_path) if direction_summary_path.exists() else None
    )
    pending_paper_dirs = pending_paper_dirs_for_direction(library_root, direction)
    if not pending_paper_dirs and previous_direction_summary is None:
        pending_paper_dirs = _direction_paper_dirs(library_root, direction)
    if not pending_paper_dirs:
        return direction_summary_path

    new_direction_summary = _generate_direction_summary(
        library_root=library_root,
        direction=direction,
        current_paper_dir=pending_paper_dirs[0] if len(pending_paper_dirs) == 1 else None,
        previous_direction_summary=previous_direction_summary,
        settings=settings,
        paper_dirs_for_bundle=pending_paper_dirs,
    )
    _write_summary_text(direction_summary_path, new_direction_summary)
    record_direction_summary_run(
        library_root,
        direction,
        pending_paper_dirs,
        direction_summary_path,
    )
    return direction_summary_path


def generate_direction_and_overview_summaries(
    *,
    library_root: Path,
    paper_paths: PaperPaths,
    direction: str,
    settings: RuntimeSettings,
) -> None:
    direction_summary_path = _direction_summary_path(library_root, direction)
    overview_summary_path = _overview_summary_path(library_root)

    previous_direction_summary = (
        _read_text(direction_summary_path) if direction_summary_path.exists() else None
    )
    previous_overview_summary = (
        _read_text(overview_summary_path) if overview_summary_path.exists() else None
    )
    new_direction_summary = _generate_direction_summary(
        library_root=library_root,
        direction=direction,
        current_paper_dir=paper_paths.paper_dir,
        previous_direction_summary=previous_direction_summary,
        settings=settings,
    )
    _write_summary_text(direction_summary_path, new_direction_summary)
    record_direction_summary_run(
        library_root,
        direction,
        [paper_paths.paper_dir],
        direction_summary_path,
    )

    new_overview_summary = _generate_incremental_overview_summary(
        library_root=library_root,
        updated_direction=direction,
        previous_overview_summary=previous_overview_summary,
        previous_direction_summary=previous_direction_summary,
        new_direction_summary=new_direction_summary,
        updated_paper_dir=paper_paths.paper_dir,
        settings=settings,
    )
    _write_summary_text(overview_summary_path, new_overview_summary)
    record_overview_summary_run(library_root, overview_summary_path)
