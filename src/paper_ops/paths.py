import re
from pathlib import Path

from paper_ops.models import PaperMetadata, PaperPaths


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def paper_id_from_metadata(metadata: PaperMetadata) -> str:
    first_author = slugify(metadata.authors[0].split()[-1])
    title_slug = slugify(metadata.title)[:49].rstrip("-")
    return f"{metadata.year}-{first_author}-{title_slug}"


def paper_paths(library_root: Path, paper_id: str, direction: str) -> PaperPaths:
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
