from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from paper_ops.models import PaperMetadata
from paper_ops.queue import DiscoveryCandidate


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "paper-search-cli"
VENDOR_CLI_PATH = VENDOR_DIR / "dist" / "cli.js"


class PaperSearchError(RuntimeError):
    pass


class PaperSearchResult(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    doi: str = ""
    pdf_url: str = ""
    url: str = ""
    source: str = ""
    journal: str = ""
    year: int | None = None

    @classmethod
    def from_paper_search_dict(cls, payload: dict[str, Any]) -> "PaperSearchResult":
        authors_raw = payload.get("authors", "")
        if isinstance(authors_raw, str):
            authors_list = [a.strip() for a in authors_raw.split(";") if a.strip()]
        elif isinstance(authors_raw, list):
            authors_list = [str(a).strip() for a in authors_raw if str(a).strip()]
        else:
            authors_list = []
        year_value = payload.get("year")
        year_int: int | None
        if isinstance(year_value, int):
            year_int = year_value
        elif isinstance(year_value, str) and year_value.strip().isdigit():
            year_int = int(year_value.strip())
        else:
            year_int = None
        return cls(
            paper_id=str(payload.get("paper_id", "")),
            title=str(payload.get("title", "")),
            authors=authors_list,
            abstract=str(payload.get("abstract", "")),
            doi=str(payload.get("doi", "")),
            pdf_url=str(payload.get("pdf_url", "")),
            url=str(payload.get("url", "")),
            source=str(payload.get("source", "")),
            journal=str(payload.get("journal", "")),
            year=year_int,
        )


@dataclass(frozen=True)
class SetupReport:
    node_version: str
    npm_version: str
    dist_built: bool
    cli_path: Path
    install_log_tail: str
    build_log_tail: str


def _capture(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def _log_tail(text: str, lines: int = 10) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def setup_paper_search(*, vendor_dir: Path = VENDOR_DIR) -> SetupReport:
    if not vendor_dir.exists():
        raise PaperSearchError(f"Vendor directory not found: {vendor_dir}")

    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        raise PaperSearchError(
            "node and npm must be on PATH. Install Node.js >= 18.0.0."
        )

    node_version = _capture(["node", "--version"]).stdout.strip()
    npm_version = _capture(["npm", "--version"]).stdout.strip()

    install_result = _capture(["npm", "install"], cwd=vendor_dir)
    if install_result.returncode != 0:
        raise PaperSearchError(
            f"npm install failed in {vendor_dir}:\n{install_result.stderr.strip()}"
        )

    build_result = _capture(["npm", "run", "build"], cwd=vendor_dir)
    if build_result.returncode != 0:
        raise PaperSearchError(
            f"npm run build failed in {vendor_dir}:\n{build_result.stderr.strip()}"
        )

    cli_path = vendor_dir / "dist" / "cli.js"
    return SetupReport(
        node_version=node_version,
        npm_version=npm_version,
        dist_built=cli_path.exists(),
        cli_path=cli_path,
        install_log_tail=_log_tail(install_result.stdout),
        build_log_tail=_log_tail(build_result.stdout),
    )


def _extract_pdf_path_from_message(message: str) -> str | None:
    marker = "to: "
    idx = message.find(marker)
    if idx == -1:
        return None
    candidate = message[idx + len(marker):].strip()
    newline = candidate.find("\n")
    if newline != -1:
        candidate = candidate[:newline].strip()
    return candidate or None


class PaperSearchClient:
    def __init__(self, *, cli_path: Path | None = None) -> None:
        self.cli_path = cli_path or VENDOR_CLI_PATH

    def _ensure_built(self) -> None:
        if not self.cli_path.exists():
            raise PaperSearchError(
                f"paper-search CLI not built at {self.cli_path}. "
                "Run `paper-ops setup` first."
            )

    def _run(self, args: list[str]) -> dict[str, Any]:
        self._ensure_built()
        result = subprocess.run(
            ["node", str(self.cli_path), *args],
            capture_output=True,
            text=True,
            check=False,
            env=dict(os.environ),
        )
        stdout = result.stdout.strip()
        if not stdout:
            raise PaperSearchError(
                f"paper-search returned empty stdout (exit={result.returncode}). "
                f"stderr: {result.stderr.strip()[:500]}"
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PaperSearchError(
                f"paper-search returned non-JSON output: {stdout[:200]!r}"
            ) from exc

        if not isinstance(payload, dict):
            raise PaperSearchError(f"paper-search returned non-object JSON: {payload!r}")

        if payload.get("ok") is False:
            message = payload.get("message", "unknown error")
            raise PaperSearchError(f"paper-search failed: {message}")

        return payload

    def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        sources: str | None = None,
        max_results: int = 10,
        year: str | None = None,
    ) -> list[PaperSearchResult]:
        args = ["search", query, "--max-results", str(max_results)]
        if platform:
            args.extend(["--platform", platform])
        if sources:
            args.extend(["--sources", sources])
        if year:
            args.extend(["--year", year])

        payload = self._run(args)
        data = payload.get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise PaperSearchError(
                f"Expected list of papers, got: {type(data).__name__}"
            )
        return [
            PaperSearchResult.from_paper_search_dict(item)
            for item in data
            if isinstance(item, dict)
        ]

    def download(
        self,
        paper_id: str,
        *,
        platform: str,
        save_path: Path,
    ) -> Path:
        save_path.mkdir(parents=True, exist_ok=True)
        args = [
            "download",
            paper_id,
            "--platform",
            platform,
            "--save-path",
            str(save_path),
        ]
        payload = self._run(args)
        message = str(payload.get("message", ""))
        pdf_path = _extract_pdf_path_from_message(message)
        if pdf_path is None:
            raise PaperSearchError(
                f"Could not parse download path from message: {message!r}"
            )
        return Path(pdf_path)

    def download_with_fallback(
        self,
        *,
        source: str,
        paper_id: str,
        save_path: Path,
        doi: str | None = None,
        title: str | None = None,
    ) -> Path:
        save_path.mkdir(parents=True, exist_ok=True)
        json_args: dict[str, str] = {
            "source": source,
            "paperId": paper_id,
            "savePath": str(save_path),
        }
        if doi:
            json_args["doi"] = doi
        if title:
            json_args["title"] = title

        payload = self._run([
            "run",
            "download_with_fallback",
            "--json-args",
            json.dumps(json_args),
        ])
        data = payload.get("data") or {}
        if not isinstance(data, dict) or data.get("status") != "ok":
            attempts = data.get("attempts", []) if isinstance(data, dict) else []
            raise PaperSearchError(
                f"download_with_fallback returned no PDF. attempts={attempts}"
            )
        result_path = data.get("path")
        if not result_path:
            raise PaperSearchError(f"download_with_fallback ok but no path: {data}")
        return Path(str(result_path))

    def status(self) -> dict[str, Any]:
        return self._run(["status"])

    def tools(self) -> dict[str, Any]:
        return self._run(["tools"])

    def config_doctor(self) -> dict[str, Any]:
        return self._run(["config", "doctor"])


def to_paper_metadata(result: PaperSearchResult) -> PaperMetadata:
    return PaperMetadata(
        title=result.title or "Untitled",
        authors=result.authors,
        year=result.year or 0,
        venue=result.journal or None,
        source_urls=[result.url] if result.url else [],
        doi=result.doi or None,
        keywords=[],
        code_urls=[],
    )


def to_discovery_candidate(
    result: PaperSearchResult,
    *,
    discovered_from: str,
    priority: str = "medium",
    matched_keywords: list[str] | None = None,
    reason: str = "paper-search result",
) -> DiscoveryCandidate:
    source_url = result.url or result.pdf_url or result.doi or result.paper_id
    return DiscoveryCandidate(
        candidate_id=str(uuid4()),
        title=result.title or "Untitled",
        source_url=source_url,
        source_type=result.source or "paper-search",
        discovered_from=discovered_from,
        priority=priority,
        matched_keywords=matched_keywords or [],
        reason=reason,
    )
