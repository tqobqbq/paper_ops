import json
from pathlib import Path


def rebuild_indexes(library_root: Path) -> None:
    papers_index: dict[str, dict] = {}
    directions_index: dict[str, list[str]] = {}

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

    for direction in directions_index:
        directions_index[direction] = sorted(directions_index[direction])

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
        bullets = "\n".join(f"- `{paper_id}`" for paper_id in paper_ids)
        (direction_dir / "README.md").write_text(
            f"# {direction}\n\n## Archived Papers\n\n{bullets}\n",
            encoding="utf-8",
        )

    directions = "\n".join(
        f"- `{direction}` ({len(paper_ids)} papers)"
        for direction, paper_ids in sorted(directions_index.items())
    )
    (library_root / "README.md").write_text(
        f"# Paper Library\n\n## Directions\n\n{directions}\n",
        encoding="utf-8",
    )
