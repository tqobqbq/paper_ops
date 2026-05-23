import json
from pathlib import Path


def _direction_summary_path(library_root: Path, direction: str) -> Path:
    return library_root / "library" / direction / f"{direction}_summary_zh.md"


def _overview_summary_path(library_root: Path) -> Path:
    return library_root / "library" / "overview_zh.md"


def rebuild_indexes(library_root: Path) -> None:
    papers_index: dict[str, dict] = {}
    directions_index: dict[str, list[str]] = {}
    direction_records: dict[str, list[dict]] = {}

    for metadata_path in sorted((library_root / "library").glob("*/*/metadata.json")):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        paper_id = payload["paper_id"]
        direction = payload["direction"]

        if paper_id in papers_index:
            raise ValueError(
                f"Duplicate paper_id '{paper_id}' found in {metadata_path}"
            )
        papers_index[paper_id] = payload
        directions_index.setdefault(direction, []).append(paper_id)
        direction_records.setdefault(direction, []).append(payload)

    for direction in directions_index:
        directions_index[direction] = sorted(directions_index[direction])
        direction_records[direction] = sorted(
            direction_records[direction],
            key=lambda item: item["paper_id"],
        )

    overview_summary_path = _overview_summary_path(library_root)

    indexes_dir = library_root / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)
    (indexes_dir / "papers_index.json").write_text(
        json.dumps(papers_index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (indexes_dir / "directions_index.json").write_text(
        json.dumps(directions_index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for stale_readme in (library_root / "library").glob("*/README.md"):
        if stale_readme.parent.name not in directions_index:
            stale_readme.unlink()

    for direction, paper_ids in sorted(directions_index.items()):
        direction_dir = library_root / "library" / direction
        direction_dir.mkdir(parents=True, exist_ok=True)
        direction_summary_path = _direction_summary_path(library_root, direction)
        summary_lines: list[str] = []
        if direction_summary_path.exists():
            summary_lines.append(f"- [方向总结](./{direction}_summary_zh.md)")
        if overview_summary_path.exists():
            summary_lines.append("- [全部方向总总结](../overview_zh.md)")
        summary_section = ""
        if summary_lines:
            summary_section = "## Summaries\n\n" + "\n".join(summary_lines) + "\n\n"

        bullets = "\n".join(
            f"- `{record['paper_id']}`: {record['title']} ({record['metadata']['year']})"
            for record in direction_records[direction]
        )
        (direction_dir / "README.md").write_text(
            f"# {direction}\n\n{summary_section}## Archived Papers\n\n{bullets}\n",
            encoding="utf-8",
        )

    summary_lines: list[str] = []
    if overview_summary_path.exists():
        summary_lines.append("- [全部方向总总结](library/overview_zh.md)")
    summaries_section = ""
    if summary_lines:
        summaries_section = "## Summaries\n\n" + "\n".join(summary_lines) + "\n\n"

    directions = "\n".join(
        (
            f"- `{direction}` ({len(paper_ids)} papers)"
            + (
                f" - [方向总结](library/{direction}/{direction}_summary_zh.md)"
                if _direction_summary_path(library_root, direction).exists()
                else ""
            )
        )
        for direction, paper_ids in sorted(directions_index.items())
    )
    (library_root / "README.md").write_text(
        f"# Paper Library\n\n{summaries_section}## Directions\n\n{directions}\n",
        encoding="utf-8",
    )
