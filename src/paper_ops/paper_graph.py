from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from paper_ops.citation_expansion import (
    ExpansionCandidate,
    ExpansionMetadata,
    ExpansionProvider,
    ExpansionSeed,
    SemanticScholarExpansionProvider,
    load_direction_seeds,
    rank_expansion_candidates,
)
from paper_ops.settings import RuntimeSettings


GRAPH_DB_FILENAME = "paper_graph.sqlite"
PROMPT_VERSION = "rank_citation_expansion_candidates.v1"
PAPER_STATUS_ORDER = {
    "candidate": 10,
    "skipped": 20,
    "download_failed": 25,
    "manual_required": 28,
    "queued": 30,
    "downloaded": 40,
    "local": 50,
}
STICKY_CANDIDATE_STATES = {
    "llm_reviewed",
    "manual_required",
    "download_failed",
    "queued",
    "downloaded",
    "skipped",
}
INACTIVE_CANDIDATE_STATES = {
    "manual_required",
    "download_failed",
    "queued",
    "downloaded",
    "skipped",
}


@dataclass(frozen=True)
class GraphUpdateResult:
    db_path: Path
    expansion_path: Path
    seed_count: int
    raw_candidate_count: int
    candidate_count: int
    llm_review_count: int
    relation_count: int = 0


@dataclass(frozen=True)
class GraphReviewResult:
    db_path: Path
    reviewed_count: int
    ranking: dict[str, object]


@dataclass(frozen=True)
class GraphEnqueueResult:
    db_path: Path
    selected_count: int
    downloaded_count: int
    manual_required_count: int
    failed_count: int
    requests: list[dict[str, object]]


@dataclass(frozen=True)
class GraphSyncResult:
    db_path: Path
    directions: list[str]
    results: list[GraphUpdateResult]


def graph_db_path(library_root: Path) -> Path:
    return library_root / "indexes" / GRAPH_DB_FILENAME


def library_directions(library_root: Path) -> list[str]:
    library_dir = library_root / "library"
    if not library_dir.exists():
        return []
    return sorted(
        path.name
        for path in library_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi


def _normalize_title(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def paper_key_for_identity(
    *,
    title: str,
    year: int | None,
    doi: str | None = None,
    source_ids: dict[str, str] | None = None,
    local_paper_id: str | None = None,
) -> str:
    normalized_doi = _normalize_doi(doi or (source_ids or {}).get("doi"))
    if normalized_doi:
        return f"doi:{normalized_doi}"

    for source_name in (
        "semantic_scholar",
        "semantic_scholar_corpus_id",
        "openalex",
        "arxiv",
        "pubmed",
        "pmc",
    ):
        source_id = (source_ids or {}).get(source_name)
        if source_id:
            normalized = str(source_id).strip().lower()
            if normalized:
                return f"{source_name}:{normalized}"

    normalized_title = _normalize_title(title)
    if normalized_title:
        return f"title_year:{year or 'unknown'}:{_stable_hash(normalized_title)}"
    if local_paper_id:
        return f"local:{local_paper_id}"
    return f"unknown:{_stable_hash(title or 'untitled')}"


def _seed_paper_key(seed: ExpansionSeed) -> str:
    return paper_key_for_identity(
        title=seed.title,
        year=seed.year,
        doi=seed.doi,
        local_paper_id=seed.paper_id,
    )


def _candidate_paper_key(candidate: ExpansionCandidate) -> str:
    return paper_key_for_identity(
        title=candidate.title,
        year=candidate.year,
        doi=candidate.doi,
        source_ids=candidate.source_ids,
    )


def _metadata_to_dict(metadata: ExpansionMetadata) -> dict[str, object]:
    return {
        "citation_count": metadata.citation_count,
        "influential_citation_count": metadata.influential_citation_count,
        "reference_count": metadata.reference_count,
        "publication_types": metadata.publication_types,
    }


def _candidate_to_dict(candidate: ExpansionCandidate) -> dict[str, object]:
    return {
        "title": candidate.title,
        "year": candidate.year,
        "doi": candidate.doi,
        "venue": candidate.venue,
        "url": candidate.url,
        "authors": candidate.authors,
        "abstract": candidate.abstract,
        "metadata": _metadata_to_dict(candidate.metadata),
        "reasons": candidate.reasons,
        "relationship_contexts": candidate.relationship_contexts,
        "source_ids": candidate.source_ids,
        "score": candidate.score,
    }


def _candidate_from_payload(payload: dict[str, object]) -> ExpansionCandidate:
    metadata = payload.get("metadata", {})
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    return ExpansionCandidate(
        title=str(payload.get("title") or "Untitled"),
        year=payload.get("year") if isinstance(payload.get("year"), int) else None,
        doi=payload.get("doi") if isinstance(payload.get("doi"), str) else None,
        venue=payload.get("venue") if isinstance(payload.get("venue"), str) else None,
        abstract=str(payload.get("abstract") or ""),
        metadata=ExpansionMetadata(
            citation_count=(
                metadata_dict.get("citation_count")
                if isinstance(metadata_dict.get("citation_count"), int)
                else None
            ),
            influential_citation_count=(
                metadata_dict.get("influential_citation_count")
                if isinstance(metadata_dict.get("influential_citation_count"), int)
                else None
            ),
            reference_count=(
                metadata_dict.get("reference_count")
                if isinstance(metadata_dict.get("reference_count"), int)
                else None
            ),
            publication_types=[
                str(item)
                for item in metadata_dict.get("publication_types", [])
                if str(item).strip()
            ]
            if isinstance(metadata_dict.get("publication_types"), list)
            else [],
        ),
        reasons=[
            str(item)
            for item in payload.get("reasons", [])
            if str(item).strip()
        ]
        if isinstance(payload.get("reasons"), list)
        else [],
        source_ids={
            str(key): str(value)
            for key, value in (payload.get("source_ids") or {}).items()
            if str(value).strip()
        }
        if isinstance(payload.get("source_ids"), dict)
        else {},
        score=float(payload.get("score") or 0),
        url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        authors=[
            str(item)
            for item in payload.get("authors", [])
            if str(item).strip()
        ]
        if isinstance(payload.get("authors"), list)
        else [],
        relationship_contexts=[
            str(item)
            for item in payload.get("relationship_contexts", [])
            if str(item).strip()
        ]
        if isinstance(payload.get("relationship_contexts"), list)
        else [],
    )


def _relation_type_from_reasons(reasons: Iterable[str]) -> str:
    for reason in reasons:
        if reason.startswith("cites seed:"):
            return "cited_by"
        if reason.startswith("referenced by seed:"):
            return "references"
    return "related"


def _intents_from_reasons(reasons: Iterable[str]) -> list[str]:
    prefix = "semantic scholar intent:"
    intents = []
    for reason in reasons:
        if reason.startswith(prefix):
            intent = reason[len(prefix) :].strip()
            if intent and intent not in intents:
                intents.append(intent)
    return intents


def _relation_intents_for_candidate(candidate: ExpansionCandidate) -> list[str]:
    intents = _intents_from_reasons(candidate.reasons)
    for label in _classify_relation_contexts(candidate.relationship_contexts):
        if label not in intents:
            intents.append(label)
    return intents


def _classify_relation_contexts(contexts: Iterable[str]) -> list[str]:
    labels: list[str] = []
    patterns = [
        ("benchmark", ("baseline", "benchmark", "compare", "comparison", "outperform")),
        ("method", ("method", "algorithm", "architecture", "model", "training")),
        ("extension", ("extend", "builds on", "improves", "based on", "inspired by")),
        ("contrast", ("however", "unlike", "contrast", "limitation", "fails")),
        ("dataset", ("dataset", "corpus", "mnist", "cifar", "imagenet", "benchmark suite")),
        ("theory", ("theory", "theoretical", "framework", "principle", "analysis")),
        ("background", ("survey", "review", "background", "prior work", "related work")),
    ]
    for context in contexts:
        lower = context.lower()
        for label, keywords in patterns:
            if any(keyword in lower for keyword in keywords) and label not in labels:
                labels.append(label)
    return labels


def _description_for_candidate(candidate: ExpansionCandidate) -> str:
    if candidate.relationship_contexts:
        return candidate.relationship_contexts[0]
    if candidate.abstract:
        return candidate.abstract[:500]
    return "; ".join(candidate.reasons)


def _augment_candidate_contexts_from_local_text(
    seed: ExpansionSeed,
    candidate: ExpansionCandidate,
) -> list[str]:
    texts: list[str] = []
    for filename in (
        "translation_zh.md",
        "summary_zh.md",
        "experiments_zh.md",
        "relevance_to_my_research.md",
    ):
        path = seed.paper_dir / filename
        if path.exists():
            texts.append(path.read_text(encoding="utf-8", errors="ignore"))
    if not texts:
        return []

    needles = []
    doi = _normalize_doi(candidate.doi or candidate.source_ids.get("doi"))
    if doi:
        needles.append(doi)
    title_terms = [
        term
        for term in _normalize_title(candidate.title).split()
        if len(term) >= 5
    ][:4]
    contexts: list[str] = []
    for sentence in re.split(r"(?<=[。！？.!?])\s+|\n+", "\n".join(texts)):
        lower = sentence.lower()
        if doi and doi in lower:
            _append_unique(contexts, sentence.strip()[:800])
        elif title_terms and sum(1 for term in title_terms if term in lower) >= 2:
            _append_unique(contexts, sentence.strip()[:800])
        if len(contexts) >= 3:
            break
    return contexts


def _append_unique(values: list[str], value: str) -> None:
    normalized = value.strip()
    if normalized and normalized not in values:
        values.append(normalized)


def _score_graph_candidate(
    candidate: ExpansionCandidate,
    *,
    source_count: int,
    relation_count: int,
    reference_relation_count: int,
    cited_by_relation_count: int,
    context_count: int,
) -> float:
    score = 0.0
    score += 3.0 * len(candidate.reasons)
    score += 1.5 * min(source_count, 5)
    score += 0.4 * min(relation_count, 10)
    score += 0.8 * min(reference_relation_count, 5)
    score += 0.4 * min(cited_by_relation_count, 5)
    score += 0.6 * min(context_count, 10)
    score += min(candidate.metadata.citation_count or 0, 200) / 50.0
    score += min(candidate.metadata.influential_citation_count or 0, 50) / 10.0
    if candidate.venue:
        venue = candidate.venue.lower()
        if venue in {"neurips", "iclr", "icml", "nature", "science"}:
            score += 2.0
        elif venue:
            score += 0.5
    if candidate.year is not None:
        if candidate.year >= 2023:
            score += 1.0
        elif candidate.year < 2015:
            score -= 0.5
    if candidate.abstract:
        score += 0.5
    return round(score, 4)


def _priority_sort_key(priority: str | None) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority or "", 3)


def _candidate_request_id(candidate: dict[str, object]) -> str:
    from paper_ops.paths import slugify

    year_part = str(candidate.get("year") or "unknown-year")
    title_slug = slugify(str(candidate.get("title") or "paper")) or "paper"
    return f"{year_part}-{title_slug[:64].rstrip('-') or 'paper'}"


def _concept_terms(*texts: str, limit: int = 8) -> list[str]:
    stopwords = {
        "with",
        "from",
        "that",
        "this",
        "using",
        "based",
        "paper",
        "method",
        "model",
        "study",
        "results",
        "analysis",
        "learning",
    }
    counts: dict[str, int] = {}
    for text in texts:
        for token in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower()):
            if token in stopwords:
                continue
            counts[token] = counts.get(token, 0) + 1
    return [
        term
        for term, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :limit
        ]
    ]


class PaperGraphStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "PaperGraphStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS papers (
              paper_key TEXT PRIMARY KEY,
              local_paper_id TEXT,
              title TEXT NOT NULL,
              normalized_title TEXT NOT NULL,
              year INTEGER,
              doi TEXT,
              venue TEXT,
              abstract TEXT NOT NULL DEFAULT '',
              url TEXT,
              authors_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL,
              local_dir TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi
              ON papers(doi)
              WHERE doi IS NOT NULL AND doi != '';

            CREATE TABLE IF NOT EXISTS paper_external_ids (
              paper_key TEXT NOT NULL,
              source TEXT NOT NULL,
              external_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (source, external_id),
              FOREIGN KEY (paper_key) REFERENCES papers(paper_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS paper_relations (
              relation_id TEXT PRIMARY KEY,
              source_paper_key TEXT NOT NULL,
              target_paper_key TEXT NOT NULL,
              direction TEXT NOT NULL,
              relation_type TEXT NOT NULL,
              contexts_json TEXT NOT NULL DEFAULT '[]',
              intents_json TEXT NOT NULL DEFAULT '[]',
              description TEXT NOT NULL DEFAULT '',
              provider TEXT NOT NULL,
              confidence REAL NOT NULL,
              raw_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE (
                source_paper_key,
                target_paper_key,
                direction,
                relation_type,
                provider
              ),
              FOREIGN KEY (source_paper_key) REFERENCES papers(paper_key) ON DELETE CASCADE,
              FOREIGN KEY (target_paper_key) REFERENCES papers(paper_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS candidates (
              candidate_id TEXT PRIMARY KEY,
              paper_key TEXT NOT NULL,
              direction TEXT NOT NULL,
              generated_from TEXT NOT NULL,
              deterministic_score REAL NOT NULL DEFAULT 0,
              state TEXT NOT NULL DEFAULT 'new',
              reasons_json TEXT NOT NULL DEFAULT '[]',
              contexts_json TEXT NOT NULL DEFAULT '[]',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE (direction, paper_key),
              FOREIGN KEY (paper_key) REFERENCES papers(paper_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS llm_reviews (
              review_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              model TEXT NOT NULL,
              prompt_version TEXT NOT NULL,
              decision TEXT NOT NULL,
              priority TEXT NOT NULL,
              rationale TEXT NOT NULL,
              raw_output_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_llm_reviews_candidate_created
              ON llm_reviews(candidate_id, created_at);

            CREATE TABLE IF NOT EXISTS download_attempts (
              attempt_id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL,
              source TEXT NOT NULL,
              result TEXT NOT NULL,
              pdf_path TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id) ON DELETE CASCADE
            );
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        self.conn.commit()

    def upsert_seed(self, seed: ExpansionSeed) -> str:
        return self.upsert_paper(
            paper_key=_seed_paper_key(seed),
            title=seed.title,
            year=seed.year,
            doi=seed.doi,
            venue=seed.venue,
            abstract="",
            url=None,
            authors=[],
            status="local",
            local_paper_id=seed.paper_id,
            local_dir=str(seed.paper_dir),
            source_ids={},
            metadata={
                "direction": seed.direction,
                "local_summary": seed.local_summary,
                "local_experiments": seed.local_experiments,
                "local_relevance": seed.local_relevance,
            },
        )

    def upsert_candidate_paper(self, candidate: ExpansionCandidate) -> str:
        return self.upsert_paper(
            paper_key=_candidate_paper_key(candidate),
            title=candidate.title,
            year=candidate.year,
            doi=candidate.doi or candidate.source_ids.get("doi"),
            venue=candidate.venue,
            abstract=candidate.abstract,
            url=candidate.url,
            authors=candidate.authors,
            status="candidate",
            local_paper_id=None,
            local_dir=None,
            source_ids=candidate.source_ids,
            metadata=_metadata_to_dict(candidate.metadata),
        )

    def upsert_paper(
        self,
        *,
        paper_key: str,
        title: str,
        year: int | None,
        doi: str | None,
        venue: str | None,
        abstract: str,
        url: str | None,
        authors: list[str],
        status: str,
        local_paper_id: str | None,
        local_dir: str | None,
        source_ids: dict[str, str],
        metadata: dict[str, object],
    ) -> str:
        now = _utc_now()
        normalized_doi = _normalize_doi(doi) or None
        normalized_title = _normalize_title(title)
        paper_key = self._canonicalize_paper_key(
            paper_key=paper_key,
            normalized_title=normalized_title,
            year=year,
            normalized_doi=normalized_doi,
            source_ids=source_ids,
        )
        row = self.conn.execute(
            "SELECT status FROM papers WHERE paper_key = ?",
            (paper_key,),
        ).fetchone()
        resolved_status = status
        if row is not None:
            existing_status = str(row["status"])
            if PAPER_STATUS_ORDER.get(existing_status, 0) > PAPER_STATUS_ORDER.get(
                status, 0
            ):
                resolved_status = existing_status

        self.conn.execute(
            """
            INSERT INTO papers (
              paper_key,
              local_paper_id,
              title,
              normalized_title,
              year,
              doi,
              venue,
              abstract,
              url,
              authors_json,
              status,
              local_dir,
              metadata_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_key) DO UPDATE SET
              local_paper_id = COALESCE(excluded.local_paper_id, papers.local_paper_id),
              title = COALESCE(NULLIF(excluded.title, ''), papers.title),
              normalized_title = COALESCE(NULLIF(excluded.normalized_title, ''), papers.normalized_title),
              year = COALESCE(excluded.year, papers.year),
              doi = COALESCE(excluded.doi, papers.doi),
              venue = COALESCE(excluded.venue, papers.venue),
              abstract = CASE
                WHEN length(excluded.abstract) > length(papers.abstract) THEN excluded.abstract
                ELSE papers.abstract
              END,
              url = COALESCE(excluded.url, papers.url),
              authors_json = CASE
                WHEN excluded.authors_json != '[]' THEN excluded.authors_json
                ELSE papers.authors_json
              END,
              status = excluded.status,
              local_dir = COALESCE(excluded.local_dir, papers.local_dir),
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                paper_key,
                local_paper_id,
                title,
                normalized_title,
                year,
                normalized_doi,
                venue,
                abstract,
                url,
                _json_dumps(authors),
                resolved_status,
                local_dir,
                _json_dumps(metadata),
                now,
                now,
            ),
        )
        if normalized_doi:
            self.record_external_id(paper_key, "doi", normalized_doi, now=now)
        for source, external_id in sorted(source_ids.items()):
            value = str(external_id).strip()
            if value:
                self.record_external_id(paper_key, source, value, now=now)
        return paper_key

    def _canonicalize_paper_key(
        self,
        *,
        paper_key: str,
        normalized_title: str,
        year: int | None,
        normalized_doi: str | None,
        source_ids: dict[str, str],
    ) -> str:
        exact = self.conn.execute(
            "SELECT paper_key FROM papers WHERE paper_key = ?",
            (paper_key,),
        ).fetchone()
        if exact is not None:
            return paper_key

        existing = self._paper_key_from_external_ids(
            normalized_doi=normalized_doi,
            source_ids=source_ids,
        )
        if existing:
            return existing

        if not normalized_title:
            return paper_key

        row = self.conn.execute(
            """
            SELECT paper_key
            FROM papers
            WHERE normalized_title = ?
              AND (year = ? OR year IS NULL OR ? IS NULL)
            ORDER BY
              CASE
                WHEN doi IS NOT NULL AND doi != '' THEN 0
                WHEN paper_key LIKE 'semantic_scholar:%' THEN 1
                WHEN paper_key LIKE 'title_year:%' THEN 2
                ELSE 3
              END,
              updated_at DESC
            LIMIT 1
            """,
            (normalized_title, year, year),
        ).fetchone()
        if row is None:
            return paper_key

        existing_key = str(row["paper_key"])
        if self._identity_strength(paper_key) > self._identity_strength(existing_key):
            self._merge_paper_keys(source_key=existing_key, target_key=paper_key)
            return paper_key
        return existing_key

    def _paper_key_from_external_ids(
        self,
        *,
        normalized_doi: str | None,
        source_ids: dict[str, str],
    ) -> str | None:
        lookups: list[tuple[str, str]] = []
        if normalized_doi:
            lookups.append(("doi", normalized_doi))
        for source, external_id in sorted(source_ids.items()):
            value = str(external_id).strip()
            if value:
                lookups.append((source, value))
        for source, external_id in lookups:
            row = self.conn.execute(
                """
                SELECT paper_key
                FROM paper_external_ids
                WHERE source = ? AND external_id = ?
                """,
                (source, external_id),
            ).fetchone()
            if row is not None:
                return str(row["paper_key"])
        return None

    def _identity_strength(self, paper_key: str) -> int:
        if paper_key.startswith("doi:"):
            return 100
        if paper_key.startswith("semantic_scholar:"):
            return 80
        if paper_key.startswith("semantic_scholar_corpus_id:"):
            return 75
        if paper_key.startswith(("openalex:", "arxiv:", "pubmed:", "pmc:")):
            return 70
        if paper_key.startswith("title_year:"):
            return 20
        return 10

    def _merge_paper_keys(self, *, source_key: str, target_key: str) -> None:
        if source_key == target_key:
            return
        target_exists = self.conn.execute(
            "SELECT 1 FROM papers WHERE paper_key = ?",
            (target_key,),
        ).fetchone()
        if target_exists is None:
            self.conn.execute(
                """
                INSERT INTO papers (
                  paper_key,
                  local_paper_id,
                  title,
                  normalized_title,
                  year,
                  doi,
                  venue,
                  abstract,
                  url,
                  authors_json,
                  status,
                  local_dir,
                  metadata_json,
                  created_at,
                  updated_at
                )
                SELECT
                  ?,
                  local_paper_id,
                  title,
                  normalized_title,
                  year,
                  doi,
                  venue,
                  abstract,
                  url,
                  authors_json,
                  status,
                  local_dir,
                  metadata_json,
                  created_at,
                  ?
                FROM papers
                WHERE paper_key = ?
                """,
                (target_key, _utc_now(), source_key),
            )
        self.conn.execute(
            "UPDATE paper_relations SET source_paper_key = ? WHERE source_paper_key = ?",
            (target_key, source_key),
        )
        self.conn.execute(
            "UPDATE paper_relations SET target_paper_key = ? WHERE target_paper_key = ?",
            (target_key, source_key),
        )
        self.conn.execute(
            """
            UPDATE candidates
            SET paper_key = ?, updated_at = ?
            WHERE paper_key = ?
              AND NOT EXISTS (
                SELECT 1
                FROM candidates existing
                WHERE existing.direction = candidates.direction
                  AND existing.paper_key = ?
              )
            """,
            (target_key, _utc_now(), source_key, target_key),
        )
        self.conn.execute(
            "DELETE FROM candidates WHERE paper_key = ?",
            (source_key,),
        )
        external_rows = self.conn.execute(
            """
            SELECT source, external_id, created_at
            FROM paper_external_ids
            WHERE paper_key = ?
            """,
            (source_key,),
        ).fetchall()
        for row in external_rows:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO paper_external_ids(
                  paper_key,
                  source,
                  external_id,
                  created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    target_key,
                    row["source"],
                    row["external_id"],
                    row["created_at"],
                ),
            )
        self.conn.execute(
            "DELETE FROM paper_external_ids WHERE paper_key = ?",
            (source_key,),
        )
        self.conn.execute("DELETE FROM papers WHERE paper_key = ?", (source_key,))

    def record_external_id(
        self,
        paper_key: str,
        source: str,
        external_id: str,
        *,
        now: str | None = None,
    ) -> None:
        timestamp = now or _utc_now()
        self.conn.execute(
            """
            INSERT INTO paper_external_ids(paper_key, source, external_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET paper_key = excluded.paper_key
            """,
            (paper_key, source, external_id, timestamp),
        )

    def external_ids_for_paper(self, paper_key: str) -> dict[str, str]:
        rows = self.conn.execute(
            """
            SELECT source, external_id
            FROM paper_external_ids
            WHERE paper_key = ?
            ORDER BY source
            """,
            (paper_key,),
        ).fetchall()
        return {
            str(row["source"]): str(row["external_id"])
            for row in rows
            if str(row["external_id"]).strip()
        }

    def record_relation(
        self,
        *,
        source_paper_key: str,
        target_paper_key: str,
        direction: str,
        relation_type: str,
        contexts: list[str],
        intents: list[str],
        description: str,
        provider: str,
        confidence: float,
        raw: dict[str, object],
    ) -> str:
        now = _utc_now()
        relation_id = _stable_hash(
            "\n".join(
                [
                    source_paper_key,
                    target_paper_key,
                    direction,
                    relation_type,
                    provider,
                ]
            ),
            length=24,
        )
        self.conn.execute(
            """
            INSERT INTO paper_relations (
              relation_id,
              source_paper_key,
              target_paper_key,
              direction,
              relation_type,
              contexts_json,
              intents_json,
              description,
              provider,
              confidence,
              raw_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
              source_paper_key,
              target_paper_key,
              direction,
              relation_type,
              provider
            ) DO UPDATE SET
              contexts_json = excluded.contexts_json,
              intents_json = excluded.intents_json,
              description = excluded.description,
              confidence = excluded.confidence,
              raw_json = excluded.raw_json,
              updated_at = excluded.updated_at
            """,
            (
                relation_id,
                source_paper_key,
                target_paper_key,
                direction,
                relation_type,
                _json_dumps(contexts),
                _json_dumps(intents),
                description,
                provider,
                confidence,
                _json_dumps(raw),
                now,
                now,
            ),
        )
        return relation_id

    def record_candidate(
        self,
        *,
        paper_key: str,
        direction: str,
        generated_from: str,
        candidate: ExpansionCandidate,
        state: str = "new",
    ) -> str:
        now = _utc_now()
        candidate_id = _stable_hash(f"{direction}\n{paper_key}", length=24)
        existing = self.conn.execute(
            "SELECT state FROM candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        resolved_state = state
        if existing is not None and str(existing["state"]) in STICKY_CANDIDATE_STATES:
            resolved_state = str(existing["state"])
        self.conn.execute(
            """
            INSERT INTO candidates (
              candidate_id,
              paper_key,
              direction,
              generated_from,
              deterministic_score,
              state,
              reasons_json,
              contexts_json,
              metadata_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(direction, paper_key) DO UPDATE SET
              generated_from = excluded.generated_from,
              deterministic_score = excluded.deterministic_score,
              state = CASE
                WHEN candidates.state IN (
                  'llm_reviewed',
                  'manual_required',
                  'download_failed',
                  'queued',
                  'downloaded',
                  'skipped'
                )
                  THEN candidates.state
                ELSE excluded.state
              END,
              reasons_json = excluded.reasons_json,
              contexts_json = excluded.contexts_json,
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                candidate_id,
                paper_key,
                direction,
                generated_from,
                candidate.score,
                resolved_state,
                _json_dumps(candidate.reasons),
                _json_dumps(candidate.relationship_contexts),
                _json_dumps(_candidate_to_dict(candidate)),
                now,
                now,
            ),
        )
        return candidate_id

    def update_candidate_state(self, candidate_id: str, state: str) -> None:
        self.conn.execute(
            """
            UPDATE candidates
            SET state = ?, updated_at = ?
            WHERE candidate_id = ?
            """,
            (state, _utc_now(), candidate_id),
        )

    def record_download_attempt(
        self,
        *,
        candidate_id: str,
        source: str,
        result: str,
        pdf_path: Path | None = None,
        error: str | None = None,
    ) -> str:
        now = _utc_now()
        attempt_id = _stable_hash(
            f"{candidate_id}\n{source}\n{result}\n{pdf_path or ''}\n{error or ''}\n{now}",
            length=24,
        )
        self.conn.execute(
            """
            INSERT INTO download_attempts (
              attempt_id,
              candidate_id,
              source,
              result,
              pdf_path,
              error,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                candidate_id,
                source,
                result,
                str(pdf_path) if pdf_path is not None else None,
                error,
                now,
            ),
        )
        return attempt_id

    def mark_candidate_processed(
        self,
        *,
        candidate_id: str,
        local_paper_id: str,
        paper_dir: Path,
    ) -> None:
        row = self.conn.execute(
            "SELECT paper_key FROM candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return
        now = _utc_now()
        paper_key = str(row["paper_key"])
        self.conn.execute(
            """
            UPDATE papers
            SET status = 'local',
                local_paper_id = ?,
                local_dir = ?,
                updated_at = ?
            WHERE paper_key = ?
            """,
            (local_paper_id, str(paper_dir), now, paper_key),
        )
        self.update_candidate_state(candidate_id, "downloaded")

    def refresh_candidates_from_graph(
        self,
        *,
        direction: str,
        limit: int = 50,
        generated_from: str = "graph",
    ) -> int:
        candidates = self._candidate_pool_from_graph(direction=direction)
        selected = candidates[:limit]
        for paper_key, candidate in selected:
            self.record_candidate(
                paper_key=paper_key,
                direction=direction,
                generated_from=generated_from,
                candidate=candidate,
            )
        return len(selected)

    def _candidate_pool_from_graph(
        self,
        *,
        direction: str,
    ) -> list[tuple[str, ExpansionCandidate]]:
        rows = self.conn.execute(
            """
            SELECT
              p.paper_key,
              p.title,
              p.year,
              p.doi,
              p.venue,
              p.abstract,
              p.url,
              p.authors_json,
              p.metadata_json,
              COUNT(r.relation_id) AS relation_count,
              COUNT(DISTINCT r.source_paper_key) AS source_count,
              SUM(CASE WHEN r.relation_type = 'references' THEN 1 ELSE 0 END)
                AS reference_relation_count,
              SUM(CASE WHEN r.relation_type = 'cited_by' THEN 1 ELSE 0 END)
                AS cited_by_relation_count
            FROM papers p
            JOIN paper_relations r ON r.target_paper_key = p.paper_key
            LEFT JOIN candidates c
              ON c.paper_key = p.paper_key AND c.direction = ?
            WHERE r.direction = ?
              AND p.status NOT IN ('local', 'downloaded', 'skipped')
              AND (
                c.state IS NULL
                OR c.state NOT IN (
                  'manual_required',
                  'download_failed',
                  'queued',
                  'downloaded',
                  'skipped'
                )
              )
            GROUP BY p.paper_key
            """,
            (direction, direction),
        ).fetchall()

        candidates: list[tuple[str, ExpansionCandidate]] = []
        for row in rows:
            paper_key = str(row["paper_key"])
            relations = self._relations_for_candidate(
                direction=direction,
                paper_key=paper_key,
            )
            contexts: list[str] = []
            reasons: list[str] = []
            for relation in relations:
                source_title = str(relation["source_title"] or "local paper")
                relation_type = str(relation["relation_type"])
                if relation_type == "references":
                    _append_unique(reasons, f"referenced by local paper: {source_title}")
                elif relation_type == "cited_by":
                    _append_unique(reasons, f"cites local paper: {source_title}")
                else:
                    _append_unique(reasons, f"related to local paper: {source_title}")
                for intent in _json_loads(relation["intents_json"], []):
                    _append_unique(reasons, f"semantic scholar intent: {intent}")
                for context in _json_loads(relation["contexts_json"], []):
                    _append_unique(contexts, str(context))
                description = str(relation["description"] or "")
                if description:
                    _append_unique(contexts, description)

            source_ids = self.external_ids_for_paper(paper_key)
            if row["doi"]:
                source_ids.setdefault("doi", str(row["doi"]))
            _append_unique(
                reasons,
                (
                    "graph evidence: "
                    f"{int(row['source_count'] or 0)} local source papers, "
                    f"{int(row['relation_count'] or 0)} relations, "
                    f"{len(contexts)} citation contexts"
                ),
            )
            payload = {
                "title": row["title"],
                "year": row["year"],
                "doi": row["doi"],
                "venue": row["venue"],
                "url": row["url"],
                "authors": _json_loads(row["authors_json"], []),
                "abstract": row["abstract"],
                "metadata": _json_loads(row["metadata_json"], {}),
                "source_ids": source_ids,
                "reasons": reasons,
                "relationship_contexts": contexts,
            }
            candidate = _candidate_from_payload(payload)
            candidate.score = _score_graph_candidate(
                candidate,
                source_count=int(row["source_count"] or 0),
                relation_count=int(row["relation_count"] or 0),
                reference_relation_count=int(row["reference_relation_count"] or 0),
                cited_by_relation_count=int(row["cited_by_relation_count"] or 0),
                context_count=len(contexts),
            )
            candidates.append((paper_key, candidate))

        candidates.sort(
            key=lambda item: (
                -item[1].score,
                -(item[1].year or 0),
                item[1].title,
            )
        )
        return candidates

    def _relations_for_candidate(
        self,
        *,
        direction: str,
        paper_key: str,
    ) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
              r.relation_type,
              r.contexts_json,
              r.intents_json,
              r.description,
              r.confidence,
              source.title AS source_title
            FROM paper_relations r
            JOIN papers source ON source.paper_key = r.source_paper_key
            WHERE r.direction = ?
              AND r.target_paper_key = ?
            ORDER BY r.created_at ASC, source.title ASC
            """,
            (direction, paper_key),
        ).fetchall()

    def mark_candidate_reviewed(self, candidate_id: str) -> None:
        self.conn.execute(
            """
            UPDATE candidates
            SET state = CASE
              WHEN state IN ('queued', 'downloaded', 'skipped') THEN state
              ELSE 'llm_reviewed'
            END,
            updated_at = ?
            WHERE candidate_id = ?
            """,
            (_utc_now(), candidate_id),
        )

    def record_llm_reviews(
        self,
        *,
        direction: str,
        candidates: list[ExpansionCandidate],
        ranking: dict[str, object],
        model: str,
        prompt_version: str = PROMPT_VERSION,
    ) -> int:
        ranked_items = ranking.get("ranked_candidates", [])
        if not isinstance(ranked_items, list):
            return 0
        by_doi: dict[str, tuple[str, ExpansionCandidate]] = {}
        by_title: dict[str, tuple[str, ExpansionCandidate]] = {}
        for candidate in candidates:
            paper_key = _candidate_paper_key(candidate)
            candidate_id = _stable_hash(f"{direction}\n{paper_key}", length=24)
            doi = _normalize_doi(candidate.doi or candidate.source_ids.get("doi"))
            if doi:
                by_doi[doi] = (candidate_id, candidate)
            by_title[_normalize_title(candidate.title)] = (candidate_id, candidate)

        run_id = f"llm-review:{direction}:{_stable_hash(_json_dumps(ranking), 20)}"
        now = _utc_now()
        review_count = 0
        for index, item in enumerate(ranked_items, start=1):
            if not isinstance(item, dict):
                continue
            doi = _normalize_doi(item.get("doi") if isinstance(item.get("doi"), str) else None)
            title_key = _normalize_title(
                item.get("title") if isinstance(item.get("title"), str) else None
            )
            matched = by_doi.get(doi) if doi else None
            if matched is None and title_key:
                matched = by_title.get(title_key)
            if matched is None:
                continue
            candidate_id, _candidate = matched
            raw = dict(item)
            raw["rank"] = item.get("rank", index)
            review_id = _stable_hash(
                f"{run_id}\n{candidate_id}\n{raw.get('rank')}",
                length=24,
            )
            self.conn.execute(
                """
                INSERT OR REPLACE INTO llm_reviews (
                  review_id,
                  candidate_id,
                  run_id,
                  model,
                  prompt_version,
                  decision,
                  priority,
                  rationale,
                  raw_output_json,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    candidate_id,
                    run_id,
                    model,
                    prompt_version,
                    str(item.get("decision") or "review"),
                    str(item.get("priority") or "medium"),
                    str(item.get("rationale") or ""),
                    _json_dumps(raw),
                    now,
                ),
            )
            self.mark_candidate_reviewed(candidate_id)
            review_count += 1
        return review_count

    def list_candidates(
        self,
        *,
        direction: str,
        limit: int = 50,
        state: str | None = None,
    ) -> list[dict[str, object]]:
        params: list[object] = [direction]
        state_clause = ""
        if state:
            state_clause = "AND c.state = ?"
            params.append(state)
        else:
            state_clause = (
                "AND c.state NOT IN ("
                "'manual_required', "
                "'download_failed', "
                "'queued', "
                "'downloaded', "
                "'skipped'"
                ")"
            )
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT
              c.candidate_id,
              c.direction,
              c.generated_from,
              c.deterministic_score,
              c.state,
              c.reasons_json,
              c.contexts_json,
              c.metadata_json,
              c.updated_at AS candidate_updated_at,
              p.paper_key,
              p.title,
              p.year,
              p.doi,
              p.venue,
              p.abstract,
              p.url,
              p.authors_json,
              p.status AS paper_status,
              latest.review_id,
              latest.decision,
              latest.priority,
              latest.rationale,
              latest.model,
              latest.created_at AS reviewed_at
            FROM candidates c
            JOIN papers p ON p.paper_key = c.paper_key
            LEFT JOIN llm_reviews latest ON latest.review_id = (
              SELECT lr.review_id
              FROM llm_reviews lr
              WHERE lr.candidate_id = c.candidate_id
              ORDER BY lr.created_at DESC
              LIMIT 1
            )
            WHERE c.direction = ?
            {state_clause}
            ORDER BY c.deterministic_score DESC, COALESCE(p.year, 0) DESC, p.title ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        candidates = []
        for row in rows:
            candidate_payload = _json_loads(row["metadata_json"], {})
            metadata = (
                candidate_payload.get("metadata", {})
                if isinstance(candidate_payload, dict)
                else {}
            )
            candidates.append(
                {
                    "candidate_id": row["candidate_id"],
                    "paper_key": row["paper_key"],
                    "direction": row["direction"],
                    "title": row["title"],
                    "year": row["year"],
                    "doi": row["doi"],
                    "venue": row["venue"],
                    "url": row["url"],
                    "authors": _json_loads(row["authors_json"], []),
                    "abstract": row["abstract"],
                    "paper_status": row["paper_status"],
                    "candidate_state": row["state"],
                    "generated_from": row["generated_from"],
                    "deterministic_score": row["deterministic_score"],
                    "reasons": _json_loads(row["reasons_json"], []),
                    "relationship_contexts": _json_loads(row["contexts_json"], []),
                    "metadata": metadata,
                    "source_ids": (
                        candidate_payload.get("source_ids", {})
                        if isinstance(candidate_payload, dict)
                        else {}
                    ),
                    "candidate_payload": candidate_payload,
                    "latest_review": {
                        "review_id": row["review_id"],
                        "decision": row["decision"],
                        "priority": row["priority"],
                        "rationale": row["rationale"],
                        "model": row["model"],
                        "reviewed_at": row["reviewed_at"],
                    }
                    if row["review_id"]
                    else None,
                    "updated_at": row["candidate_updated_at"],
                }
            )
        candidates.sort(
            key=lambda item: (
                _priority_sort_key(
                    (item.get("latest_review") or {}).get("priority")  # type: ignore[union-attr]
                    if item.get("latest_review")
                    else None
                ),
                -float(item.get("deterministic_score") or 0),
                str(item.get("title") or ""),
            )
        )
        return candidates

    def expansion_candidates_for_ranking(
        self,
        *,
        direction: str,
        limit: int,
    ) -> list[ExpansionCandidate]:
        rows = self.list_candidates(direction=direction, limit=limit)
        candidates = []
        for row in rows:
            candidate_payload = row.get("candidate_payload", {})
            payload = candidate_payload if isinstance(candidate_payload, dict) else {}
            if "title" not in payload:
                payload = {
                    **payload,
                    "title": row.get("title"),
                    "year": row.get("year"),
                    "doi": row.get("doi"),
                    "venue": row.get("venue"),
                    "url": row.get("url"),
                    "authors": row.get("authors") or [],
                    "abstract": row.get("abstract") or "",
                    "reasons": row.get("reasons") or [],
                    "relationship_contexts": row.get("relationship_contexts") or [],
                    "score": row.get("deterministic_score") or 0,
                }
            candidates.append(_candidate_from_payload(payload))
        return candidates

    def reviewed_candidates_for_download(
        self,
        *,
        direction: str,
        decision: str = "fetch",
        priority: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        rows = self.list_candidates(direction=direction, limit=max(limit * 5, limit))
        selected: list[dict[str, object]] = []
        for row in rows:
            review = row.get("latest_review")
            if not isinstance(review, dict):
                continue
            if str(review.get("decision") or "") != decision:
                continue
            if priority and str(review.get("priority") or "") != priority:
                continue
            if str(row.get("candidate_state") or "") in INACTIVE_CANDIDATE_STATES:
                continue
            selected.append(row)
            if len(selected) >= limit:
                break
        return selected

    def commit(self) -> None:
        self.conn.commit()


def _write_expansion_payload(
    *,
    library_root: Path,
    direction: str,
    seeds: list[ExpansionSeed],
    candidates: list[ExpansionCandidate],
    provider_name: str,
    limit: int,
    llm_ranking: dict[str, object] | None,
    db_path: Path,
) -> Path:
    output_path = (
        library_root / "indexes" / "candidate_expansions" / f"{direction}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected = candidates[:limit]
    payload = {
        "direction": direction,
        "created_at": _utc_now(),
        "provider": provider_name,
        "seed_count": len(seeds),
        "candidate_count": len(selected),
        "candidate_limit": limit,
        "dedupe_stage": "before_pdf_download",
        "database": str(db_path),
        "seeds": [
            {
                "paper_id": seed.paper_id,
                "title": seed.title,
                "direction": seed.direction,
                "year": seed.year,
                "doi": seed.doi,
                "venue": seed.venue,
                "paper_dir": str(seed.paper_dir),
                "local_summary": seed.local_summary,
                "local_experiments": seed.local_experiments,
                "local_relevance": seed.local_relevance,
            }
            for seed in seeds
        ],
        "candidates": [_candidate_to_dict(candidate) for candidate in selected],
        "llm_ranking": llm_ranking,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def _write_graph_update_payload(
    *,
    library_root: Path,
    direction: str,
    seeds: list[ExpansionSeed],
    provider_name: str,
    raw_candidate_count: int,
    discovered_paper_count: int,
    relation_count: int,
    db_path: Path,
) -> Path:
    output_path = library_root / "indexes" / "graph_updates" / f"{direction}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "direction": direction,
        "created_at": _utc_now(),
        "provider": provider_name,
        "seed_count": len(seeds),
        "raw_candidate_count": raw_candidate_count,
        "discovered_paper_count": discovered_paper_count,
        "relation_count": relation_count,
        "dedupe_stage": "identity_upsert_at_discovery",
        "selection_stage": "deferred_until_candidate_export_or_review",
        "database": str(db_path),
        "seeds": [
            {
                "paper_id": seed.paper_id,
                "title": seed.title,
                "direction": seed.direction,
                "year": seed.year,
                "doi": seed.doi,
                "venue": seed.venue,
                "paper_dir": str(seed.paper_dir),
            }
            for seed in seeds
        ],
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def _provider_name(provider: ExpansionProvider) -> str:
    name = getattr(provider, "name", provider.__class__.__name__)
    return str(name)


def update_graph_for_direction(
    *,
    library_root: Path,
    direction: str,
    provider: ExpansionProvider | None = None,
    limit: int = 50,
    settings: RuntimeSettings | None = None,
    llm_limit: int = 30,
) -> GraphUpdateResult:
    seeds = load_direction_seeds(library_root, direction)
    resolved_provider = provider or SemanticScholarExpansionProvider()
    provider_name = _provider_name(resolved_provider)
    raw_candidates: list[ExpansionCandidate] = []
    discovered_paper_keys: set[str] = set()
    relation_count = 0

    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
        for seed in seeds:
            seed_key = store.upsert_seed(seed)
            for candidate in resolved_provider.candidates_for_seed(seed):
                for context in _augment_candidate_contexts_from_local_text(seed, candidate):
                    _append_unique(candidate.relationship_contexts, context)
                target_key = store.upsert_candidate_paper(candidate)
                discovered_paper_keys.add(target_key)
                raw_candidates.append(candidate)
                relation_type = _relation_type_from_reasons(candidate.reasons)
                store.record_relation(
                    source_paper_key=seed_key,
                    target_paper_key=target_key,
                    direction=direction,
                    relation_type=relation_type,
                    contexts=candidate.relationship_contexts,
                    intents=_relation_intents_for_candidate(candidate),
                    description=_description_for_candidate(candidate),
                    provider=provider_name,
                    confidence=0.9 if candidate.relationship_contexts else 0.6,
                    raw=_candidate_to_dict(candidate),
                )
                relation_count += 1

        store.commit()

    expansion_path = _write_graph_update_payload(
        library_root=library_root,
        direction=direction,
        seeds=seeds,
        provider_name=provider_name,
        raw_candidate_count=len(raw_candidates),
        discovered_paper_count=len(discovered_paper_keys),
        relation_count=relation_count,
        db_path=db_path,
    )
    return GraphUpdateResult(
        db_path=db_path,
        expansion_path=expansion_path,
        seed_count=len(seeds),
        raw_candidate_count=len(raw_candidates),
        candidate_count=len(discovered_paper_keys),
        llm_review_count=0,
        relation_count=relation_count,
    )


def sync_graph(
    *,
    library_root: Path,
    provider_factory: Any | None = None,
) -> GraphSyncResult:
    directions = library_directions(library_root)
    results: list[GraphUpdateResult] = []
    for direction in directions:
        provider = provider_factory() if provider_factory is not None else None
        results.append(
            update_graph_for_direction(
                library_root=library_root,
                direction=direction,
                provider=provider,
            )
        )
    return GraphSyncResult(
        db_path=graph_db_path(library_root),
        directions=directions,
        results=results,
    )


def review_graph_candidates(
    *,
    library_root: Path,
    direction: str,
    settings: RuntimeSettings,
    limit: int = 30,
) -> GraphReviewResult:
    seeds = load_direction_seeds(library_root, direction)
    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
        store.refresh_candidates_from_graph(
            direction=direction,
            limit=limit,
        )
        candidates = store.expansion_candidates_for_ranking(
            direction=direction,
            limit=limit,
        )
        if not candidates:
            return GraphReviewResult(
                db_path=db_path,
                reviewed_count=0,
                ranking={"ranked_candidates": [], "notes": ["no candidates"]},
            )
        ranking = rank_expansion_candidates(
            library_root=library_root,
            direction=direction,
            seeds=seeds,
            candidates=candidates,
            settings=settings,
            limit=limit,
        )
        reviewed_count = store.record_llm_reviews(
            direction=direction,
            candidates=candidates,
            ranking=ranking,
            model=settings.model,
        )
        store.commit()
    return GraphReviewResult(
        db_path=db_path,
        reviewed_count=reviewed_count,
        ranking=ranking,
    )


def mark_graph_candidate_processed(
    *,
    library_root: Path,
    candidate_id: str,
    local_paper_id: str,
    paper_dir: Path,
) -> None:
    with PaperGraphStore(graph_db_path(library_root)) as store:
        store.mark_candidate_processed(
            candidate_id=candidate_id,
            local_paper_id=local_paper_id,
            paper_dir=paper_dir,
        )
        store.commit()


def mark_graph_candidate_processing_failed(
    *,
    library_root: Path,
    candidate_id: str,
    error: str,
) -> None:
    with PaperGraphStore(graph_db_path(library_root)) as store:
        store.update_candidate_state(candidate_id, "download_failed")
        store.record_download_attempt(
            candidate_id=candidate_id,
            source="manual-scan",
            result="processing_failed",
            error=error,
        )
        store.commit()


def enqueue_graph_downloads(
    *,
    library_root: Path,
    direction: str,
    decision: str = "fetch",
    priority: str | None = None,
    limit: int = 5,
    client: Any | None = None,
) -> GraphEnqueueResult:
    from paper_ops.manual_downloads import (
        ManualDownloadRequest,
        create_manual_download_request,
    )
    from paper_ops.paper_search_client import PaperSearchClient, PaperSearchError

    resolved_client = client or PaperSearchClient()
    inbox_dir = library_root / "manual_downloads" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, object]] = []
    downloaded_count = 0
    manual_required_count = 0
    failed_count = 0

    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
        candidates = store.reviewed_candidates_for_download(
            direction=direction,
            decision=decision,
            priority=priority,
            limit=limit,
        )
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            request_id = _candidate_request_id(candidate)
            expected_filename = f"{request_id}.pdf"
            source_ids = candidate.get("source_ids")
            paper_id = (
                str(candidate.get("doi") or "")
                or str((source_ids or {}).get("semantic_scholar") or "")
                if isinstance(source_ids, dict)
                else str(candidate.get("doi") or "")
            )
            if not paper_id:
                paper_id = str(candidate.get("paper_key") or candidate_id)
            request = ManualDownloadRequest(
                request_id=request_id,
                title=str(candidate.get("title") or "Untitled"),
                authors=[
                    str(author)
                    for author in candidate.get("authors", [])
                    if str(author).strip()
                ]
                if isinstance(candidate.get("authors"), list)
                else [],
                year=(
                    candidate.get("year")
                    if isinstance(candidate.get("year"), int)
                    else None
                ),
                venue=(
                    str(candidate.get("venue"))
                    if candidate.get("venue") is not None
                    else None
                ),
                doi=(
                    str(candidate.get("doi"))
                    if candidate.get("doi") is not None
                    else None
                ),
                direction=direction,
                abstract=str(candidate.get("abstract") or ""),
                candidate_id=candidate_id,
                source_url=(
                    str(candidate.get("url"))
                    if candidate.get("url") is not None
                    else None
                ),
                legal_pdf_attempts=[],
                expected_filenames=[expected_filename],
            )
            try:
                pdf_path = resolved_client.download_with_fallback(
                    source="semantic",
                    paper_id=paper_id,
                    doi=request.doi,
                    title=request.title,
                    save_path=inbox_dir,
                )
            except PaperSearchError as exc:
                create_manual_download_request(library_root, request)
                store.record_download_attempt(
                    candidate_id=candidate_id,
                    source="paper-search",
                    result="manual_required",
                    error=str(exc),
                )
                store.update_candidate_state(candidate_id, "manual_required")
                manual_required_count += 1
                requests.append(
                    {
                        "candidate_id": candidate_id,
                        "request_id": request_id,
                        "result": "manual_required",
                        "error": str(exc),
                    }
                )
                continue
            except Exception as exc:
                store.record_download_attempt(
                    candidate_id=candidate_id,
                    source="paper-search",
                    result="failed",
                    error=str(exc),
                )
                store.update_candidate_state(candidate_id, "download_failed")
                failed_count += 1
                requests.append(
                    {
                        "candidate_id": candidate_id,
                        "request_id": request_id,
                        "result": "failed",
                        "error": str(exc),
                    }
                )
                continue

            target_path = inbox_dir / expected_filename
            if pdf_path != target_path and pdf_path.exists():
                if target_path.exists():
                    target_path.unlink()
                pdf_path.rename(target_path)
                pdf_path = target_path
            create_manual_download_request(library_root, request)
            store.record_download_attempt(
                candidate_id=candidate_id,
                source="paper-search",
                result="downloaded",
                pdf_path=pdf_path,
            )
            store.update_candidate_state(candidate_id, "queued")
            downloaded_count += 1
            requests.append(
                {
                    "candidate_id": candidate_id,
                    "request_id": request_id,
                    "result": "queued",
                    "pdf_path": str(pdf_path),
                }
            )
        store.commit()

    return GraphEnqueueResult(
        db_path=db_path,
        selected_count=len(requests),
        downloaded_count=downloaded_count,
        manual_required_count=manual_required_count,
        failed_count=failed_count,
        requests=requests,
    )


def export_graph_candidates(
    *,
    library_root: Path,
    direction: str,
    limit: int = 50,
    state: str | None = None,
) -> Path:
    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
        store.refresh_candidates_from_graph(
            direction=direction,
            limit=limit,
        )
        store.commit()
        candidates = store.list_candidates(
            direction=direction,
            limit=limit,
            state=state,
        )
    output_path = library_root / "indexes" / "graph_candidates" / f"{direction}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "direction": direction,
                "created_at": _utc_now(),
                "database": str(db_path),
                "candidate_count": len(candidates),
                "state": state,
                "candidates": candidates,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def export_graph_snapshot(
    *,
    library_root: Path,
    direction: str,
    limit: int = 100,
) -> Path:
    candidate_path = export_graph_candidates(
        library_root=library_root,
        direction=direction,
        limit=limit,
    )
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    timestamp = _utc_now().replace(":", "").replace("+", "Z")
    output_dir = library_root / "indexes" / "graph_snapshots" / direction
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{timestamp}.json"
    payload["snapshot_created_at"] = _utc_now()
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def export_literature_map(
    *,
    library_root: Path,
    direction: str,
    limit: int = 100,
) -> Path:
    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
        store.refresh_candidates_from_graph(direction=direction, limit=limit)
        store.commit()
        candidates = store.list_candidates(direction=direction, limit=limit)

    concept_index: dict[str, list[dict[str, object]]] = {}
    for candidate in candidates:
        contexts = candidate.get("relationship_contexts")
        context_text = " ".join(contexts if isinstance(contexts, list) else [])
        terms = _concept_terms(
            str(candidate.get("title") or ""),
            str(candidate.get("abstract") or ""),
            context_text,
            limit=5,
        )
        for term in terms:
            concept_index.setdefault(term, []).append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "title": candidate["title"],
                    "year": candidate.get("year"),
                    "score": candidate.get("deterministic_score"),
                    "latest_review": candidate.get("latest_review"),
                }
            )

    concepts = [
        {"concept": concept, "paper_count": len(items), "papers": items[:10]}
        for concept, items in sorted(
            concept_index.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]
    output_path = library_root / "indexes" / "literature_maps" / f"{direction}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "direction": direction,
                "created_at": _utc_now(),
                "candidate_count": len(candidates),
                "concepts": concepts,
                "candidates": candidates,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path
