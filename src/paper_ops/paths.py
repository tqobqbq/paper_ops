import hashlib
import re
from pathlib import Path

from paper_ops.models import PaperMetadata, PaperPaths


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _stable_slug(value: str, prefix: str) -> str:
    normalized = slugify(value)
    if normalized:
        return normalized
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def _validate_safe_component(component: str, field_name: str) -> None:
    if not component or component in {".", ".."} or "/" in component or "\\" in component:
        raise ValueError(f"unsafe {field_name}: {component!r}")


def paper_id_from_metadata(metadata: PaperMetadata) -> str:
    first_author_raw = ""
    if metadata.authors:
        tokens = metadata.authors[0].split()
        if tokens:
            first_author_raw = tokens[-1]

    first_author = _stable_slug(first_author_raw, "author")
    title_slug = _stable_slug(metadata.title, "title")[:49].rstrip("-")
    return f"{metadata.year}-{first_author}-{title_slug}"


def paper_paths(library_root: Path, paper_id: str, direction: str) -> PaperPaths:
    _validate_safe_component(direction, "direction")
    _validate_safe_component(paper_id, "paper_id")
    paper_dir = library_root / "library" / direction / paper_id
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
