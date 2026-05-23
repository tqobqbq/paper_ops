from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_ops.models import PaperPaths


SUMMARY_LEDGER_FILENAME = "summary_ledger.json"
PAPER_ARTIFACT_FILENAMES = (
    "summary_zh.md",
    "experiments_zh.md",
    "notes_zh.md",
    "code_links.json",
    "relevance_to_my_research.md",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def summary_ledger_path(library_root: Path) -> Path:
    return library_root / "indexes" / SUMMARY_LEDGER_FILENAME


def _empty_ledger() -> dict[str, Any]:
    return {
        "version": 1,
        "papers": {},
        "directions": {},
        "overview": {},
    }


def load_summary_ledger(library_root: Path) -> dict[str, Any]:
    path = summary_ledger_path(library_root)
    if not path.exists():
        return _empty_ledger()

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return _empty_ledger()

    ledger = _empty_ledger()
    ledger.update(payload)
    ledger.setdefault("papers", {})
    ledger.setdefault("directions", {})
    ledger.setdefault("overview", {})
    return ledger


def save_summary_ledger(library_root: Path, ledger: dict[str, Any]) -> Path:
    path = summary_ledger_path(library_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_to_library(library_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(library_root))
    except ValueError:
        return str(path)


def _paper_payload(paper_dir: Path) -> dict[str, Any]:
    metadata_path = paper_dir / "metadata.json"
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _paper_artifact_hashes(paper_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for filename in PAPER_ARTIFACT_FILENAMES:
        path = paper_dir / filename
        if path.exists():
            hashes[filename] = _sha256_file(path)
        else:
            hashes[filename] = ""
    return hashes


def _combined_hash(items: dict[str, str]) -> str:
    payload = json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(payload)


def record_paper_artifacts(library_root: Path, paths: PaperPaths) -> dict[str, Any]:
    payload = _paper_payload(paths.paper_dir)
    paper_id = str(payload.get("paper_id", paths.paper_dir.name))
    direction = str(payload.get("direction", paths.paper_dir.parent.name))
    artifact_hashes = _paper_artifact_hashes(paths.paper_dir)
    artifact_hash = _combined_hash(artifact_hashes)

    ledger = load_summary_ledger(library_root)
    ledger["papers"][paper_id] = {
        "paper_id": paper_id,
        "direction": direction,
        "paper_dir": _relative_to_library(library_root, paths.paper_dir),
        "artifacts": artifact_hashes,
        "artifact_hash": artifact_hash,
        "recorded_at": _utc_now(),
    }
    save_summary_ledger(library_root, ledger)
    return ledger["papers"][paper_id]


def pending_paper_dirs_for_direction(library_root: Path, direction: str) -> list[Path]:
    ledger = load_summary_ledger(library_root)
    direction_entry = ledger["directions"].get(direction, {})
    included = direction_entry.get("included_papers", {})
    if not isinstance(included, dict):
        included = {}

    pending: list[Path] = []
    for paper_id, paper_entry in sorted(ledger["papers"].items()):
        if not isinstance(paper_entry, dict):
            continue
        if paper_entry.get("direction") != direction:
            continue
        artifact_hash = paper_entry.get("artifact_hash")
        if included.get(paper_id) == artifact_hash:
            continue
        paper_dir_value = paper_entry.get("paper_dir")
        if isinstance(paper_dir_value, str):
            pending.append(library_root / paper_dir_value)
    return pending


def record_direction_summary_run(
    library_root: Path,
    direction: str,
    paper_dirs: list[Path],
    summary_path: Path,
) -> dict[str, Any]:
    ledger = load_summary_ledger(library_root)
    previous_entry = ledger["directions"].get(direction, {})
    previous_included = (
        previous_entry.get("included_papers", {})
        if isinstance(previous_entry, dict)
        else {}
    )
    included: dict[str, str] = (
        dict(previous_included) if isinstance(previous_included, dict) else {}
    )
    for paper_dir in paper_dirs:
        payload = _paper_payload(paper_dir)
        paper_id = str(payload.get("paper_id", paper_dir.name))
        paper_entry = ledger["papers"].get(paper_id)
        if isinstance(paper_entry, dict) and paper_entry.get("artifact_hash"):
            included[paper_id] = str(paper_entry["artifact_hash"])

    summary_hash = _sha256_file(summary_path) if summary_path.exists() else ""
    ledger["directions"][direction] = {
        "direction": direction,
        "summary_path": _relative_to_library(library_root, summary_path),
        "summary_hash": summary_hash,
        "included_papers": included,
        "updated_at": _utc_now(),
    }
    save_summary_ledger(library_root, ledger)
    return ledger["directions"][direction]


def record_overview_summary_run(
    library_root: Path,
    summary_path: Path,
) -> dict[str, Any]:
    ledger = load_summary_ledger(library_root)
    included_directions: dict[str, str] = {}
    for direction, entry in sorted(ledger["directions"].items()):
        if isinstance(entry, dict) and entry.get("summary_hash"):
            included_directions[direction] = str(entry["summary_hash"])

    summary_hash = _sha256_file(summary_path) if summary_path.exists() else ""
    ledger["overview"] = {
        "summary_path": _relative_to_library(library_root, summary_path),
        "summary_hash": summary_hash,
        "included_directions": included_directions,
        "updated_at": _utc_now(),
    }
    save_summary_ledger(library_root, ledger)
    return ledger["overview"]


def pending_directions_for_overview(library_root: Path) -> list[str]:
    ledger = load_summary_ledger(library_root)
    overview = ledger.get("overview", {})
    included = overview.get("included_directions", {}) if isinstance(overview, dict) else {}
    if not isinstance(included, dict):
        included = {}

    pending: list[str] = []
    for direction, entry in sorted(ledger["directions"].items()):
        if not isinstance(entry, dict):
            continue
        summary_hash = entry.get("summary_hash")
        if summary_hash and included.get(direction) != summary_hash:
            pending.append(direction)
    return pending
