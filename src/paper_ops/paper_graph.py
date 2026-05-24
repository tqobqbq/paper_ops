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
    dedupe_and_score_candidates,
    load_direction_seeds,
    rank_expansion_candidates,
)
from paper_ops.settings import RuntimeSettings


GRAPH_DB_FILENAME = "paper_graph.sqlite"
PROMPT_VERSION = "rank_citation_expansion_candidates.v1"
PAPER_STATUS_ORDER = {
    "candidate": 10,
    "skipped": 20,
    "queued": 30,
    "downloaded": 40,
    "local": 50,
}
STICKY_CANDIDATE_STATES = {"queued", "downloaded", "skipped"}


@dataclass(frozen=True)
class GraphUpdateResult:
    db_path: Path
    expansion_path: Path
    seed_count: int
    raw_candidate_count: int
    candidate_count: int
    llm_review_count: int


@dataclass(frozen=True)
class GraphReviewResult:
    db_path: Path
    reviewed_count: int
    ranking: dict[str, object]


def graph_db_path(library_root: Path) -> Path:
    return library_root / "indexes" / GRAPH_DB_FILENAME


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


def _description_for_candidate(candidate: ExpansionCandidate) -> str:
    if candidate.relationship_contexts:
        return candidate.relationship_contexts[0]
    if candidate.abstract:
        return candidate.abstract[:500]
    return "; ".join(candidate.reasons)


def _priority_sort_key(priority: str | None) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority or "", 3)


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
                _normalize_title(title),
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
                WHEN candidates.state IN ('queued', 'downloaded', 'skipped') THEN candidates.state
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

    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
        for seed in seeds:
            seed_key = store.upsert_seed(seed)
            for candidate in resolved_provider.candidates_for_seed(seed):
                target_key = store.upsert_candidate_paper(candidate)
                raw_candidates.append(candidate)
                relation_type = _relation_type_from_reasons(candidate.reasons)
                store.record_relation(
                    source_paper_key=seed_key,
                    target_paper_key=target_key,
                    direction=direction,
                    relation_type=relation_type,
                    contexts=candidate.relationship_contexts,
                    intents=_intents_from_reasons(candidate.reasons),
                    description=_description_for_candidate(candidate),
                    provider=provider_name,
                    confidence=0.9 if candidate.relationship_contexts else 0.6,
                    raw=_candidate_to_dict(candidate),
                )

        ranked_candidates = dedupe_and_score_candidates(
            raw_candidates,
            library_root=library_root,
            seeds=seeds,
        )
        for candidate in ranked_candidates[:limit]:
            paper_key = store.upsert_candidate_paper(candidate)
            store.record_candidate(
                paper_key=paper_key,
                direction=direction,
                generated_from=provider_name,
                candidate=candidate,
            )

        llm_ranking = None
        review_count = 0
        if settings is not None and ranked_candidates:
            llm_ranking = rank_expansion_candidates(
                library_root=library_root,
                direction=direction,
                seeds=seeds,
                candidates=ranked_candidates,
                settings=settings,
                limit=llm_limit,
            )
            review_count = store.record_llm_reviews(
                direction=direction,
                candidates=ranked_candidates,
                ranking=llm_ranking,
                model=settings.model,
            )

        store.commit()

    expansion_path = _write_expansion_payload(
        library_root=library_root,
        direction=direction,
        seeds=seeds,
        candidates=ranked_candidates,
        provider_name=provider_name,
        limit=limit,
        llm_ranking=llm_ranking,
        db_path=db_path,
    )
    return GraphUpdateResult(
        db_path=db_path,
        expansion_path=expansion_path,
        seed_count=len(seeds),
        raw_candidate_count=len(raw_candidates),
        candidate_count=min(len(ranked_candidates), limit),
        llm_review_count=review_count,
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


def export_graph_candidates(
    *,
    library_root: Path,
    direction: str,
    limit: int = 50,
    state: str | None = None,
) -> Path:
    db_path = graph_db_path(library_root)
    with PaperGraphStore(db_path) as store:
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
