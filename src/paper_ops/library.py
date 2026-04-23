from paper_ops.models import PaperPaths


def ensure_paper_archive(paths: PaperPaths) -> None:
    paths.paper_dir.mkdir(parents=True, exist_ok=True)
