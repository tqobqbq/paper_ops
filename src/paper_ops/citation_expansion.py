from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import tempfile
import time
from typing import Iterable, Protocol
from urllib.parse import quote

import requests

from paper_ops.artifact_agents import ArtifactSpec, run_artifact_agent_from_file
from paper_ops.settings import RuntimeSettings


SEMANTIC_SCHOLAR_PAPER_FIELD_NAMES = [
    "paperId",
    "corpusId",
    "url",
    "title",
    "abstract",
    "venue",
    "year",
    "externalIds",
    "citationCount",
    "influentialCitationCount",
    "referenceCount",
    "publicationTypes",
    "publicationVenue",
    "authors",
]
SEMANTIC_SCHOLAR_PAPER_FIELDS = ",".join(SEMANTIC_SCHOLAR_PAPER_FIELD_NAMES)
SEMANTIC_SCHOLAR_RELATION_FIELDS = ",".join(
    [
        "contexts",
        "intents",
        "isInfluential",
    ]
    + [f"citingPaper.{field}" for field in SEMANTIC_SCHOLAR_PAPER_FIELD_NAMES]
    + [f"citedPaper.{field}" for field in SEMANTIC_SCHOLAR_PAPER_FIELD_NAMES]
)
EXPANSION_RANKING_SPEC = ArtifactSpec(
    name="citation_expansion_ranking",
    prompt_filename="rank_citation_expansion_candidates.md",
    output_path_attr="",
    output_kind="json",
)


@dataclass(frozen=True)
class ExpansionSeed:
    paper_id: str
    title: str
    direction: str
    year: int | None
    doi: str | None
    venue: str | None
    local_summary: str
    local_experiments: str
    local_relevance: str
    paper_dir: Path


@dataclass
class ExpansionMetadata:
    citation_count: int | None = None
    influential_citation_count: int | None = None
    reference_count: int | None = None
    publication_types: list[str] = field(default_factory=list)


@dataclass
class ExpansionCandidate:
    title: str
    year: int | None
    doi: str | None
    venue: str | None
    abstract: str
    metadata: ExpansionMetadata
    reasons: list[str]
    source_ids: dict[str, str]
    score: float = 0.0
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    relationship_contexts: list[str] = field(default_factory=list)


class ExpansionProvider(Protocol):
    def candidates_for_seed(self, seed: ExpansionSeed) -> Iterable[ExpansionCandidate]:
        """Return citation-neighborhood candidates for one local seed paper."""


def _validate_direction_component(direction: str) -> None:
    if (
        not direction
        or direction in {".", ".."}
        or "/" in direction
        or "\\" in direction
    ):
        raise ValueError(f"unsafe direction: {direction!r}")


def _read_text(path: Path, *, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:max_chars].strip()


def _paper_payload(paper_dir: Path) -> dict[str, object] | None:
    metadata_path = paper_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _metadata_dict(payload: dict[str, object]) -> dict[str, object]:
    metadata = payload.get("metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def load_direction_seeds(library_root: Path, direction: str) -> list[ExpansionSeed]:
    _validate_direction_component(direction)
    direction_root = library_root / "library" / direction
    if not direction_root.exists():
        return []

    seeds: list[ExpansionSeed] = []
    for paper_dir in sorted(path for path in direction_root.iterdir() if path.is_dir()):
        payload = _paper_payload(paper_dir)
        if payload is None:
            continue
        metadata = _metadata_dict(payload)
        title = _coerce_str(payload.get("title") or metadata.get("title"))
        if title is None:
            continue
        seed = ExpansionSeed(
            paper_id=str(payload.get("paper_id") or paper_dir.name),
            title=title,
            direction=str(payload.get("direction") or direction),
            year=_coerce_int(metadata.get("year") or payload.get("year")),
            doi=_coerce_str(payload.get("doi") or metadata.get("doi")),
            venue=_coerce_str(metadata.get("venue") or payload.get("venue")),
            local_summary=_read_text(paper_dir / "summary_zh.md"),
            local_experiments=_read_text(paper_dir / "experiments_zh.md"),
            local_relevance=_read_text(paper_dir / "relevance_to_my_research.md"),
            paper_dir=paper_dir,
        )
        seeds.append(seed)
    return seeds


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


def _candidate_key(candidate: ExpansionCandidate) -> tuple[str, str, int | None]:
    doi = _normalize_doi(candidate.doi or candidate.source_ids.get("doi"))
    if doi:
        return ("doi", doi, None)
    for source_name in (
        "semantic_scholar",
        "semantic_scholar_corpus_id",
        "openalex",
        "arxiv",
        "pubmed",
        "pmc",
    ):
        source_id = candidate.source_ids.get(source_name)
        if source_id:
            return (source_name, str(source_id).strip().lower(), None)
    return ("title_year", _normalize_title(candidate.title), candidate.year)


def _library_identity_keys(library_root: Path) -> set[tuple[str, str, int | None]]:
    keys: set[tuple[str, str, int | None]] = set()
    library_dir = library_root / "library"
    if not library_dir.exists():
        return keys

    for metadata_path in sorted(library_dir.glob("*/*/metadata.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        metadata = _metadata_dict(payload)
        doi = _normalize_doi(_coerce_str(payload.get("doi") or metadata.get("doi")))
        if doi:
            keys.add(("doi", doi, None))
        title = _normalize_title(
            _coerce_str(payload.get("title") or metadata.get("title"))
        )
        year = _coerce_int(metadata.get("year") or payload.get("year"))
        if title:
            keys.add(("title_year", title, year))
    return keys


def _merge_int_max(a: int | None, b: int | None) -> int | None:
    values = [value for value in (a, b) if value is not None]
    return max(values) if values else None


def _merge_metadata(existing: ExpansionMetadata, new: ExpansionMetadata) -> None:
    existing.citation_count = _merge_int_max(
        existing.citation_count,
        new.citation_count,
    )
    existing.influential_citation_count = _merge_int_max(
        existing.influential_citation_count,
        new.influential_citation_count,
    )
    existing.reference_count = _merge_int_max(
        existing.reference_count,
        new.reference_count,
    )
    for publication_type in new.publication_types:
        if publication_type not in existing.publication_types:
            existing.publication_types.append(publication_type)


def _merge_candidate(existing: ExpansionCandidate, new: ExpansionCandidate) -> None:
    if not existing.doi and new.doi:
        existing.doi = new.doi
    if existing.year is None and new.year is not None:
        existing.year = new.year
    if not existing.venue and new.venue:
        existing.venue = new.venue
    if new.abstract and len(new.abstract) > len(existing.abstract):
        existing.abstract = new.abstract
    if not existing.url and new.url:
        existing.url = new.url
    _merge_metadata(existing.metadata, new.metadata)
    for reason in new.reasons:
        if reason not in existing.reasons:
            existing.reasons.append(reason)
    for key, value in new.source_ids.items():
        if value and key not in existing.source_ids:
            existing.source_ids[key] = value
    for author in new.authors:
        if author not in existing.authors:
            existing.authors.append(author)
    for context in new.relationship_contexts:
        if context not in existing.relationship_contexts:
            existing.relationship_contexts.append(context)


def _score_candidate(candidate: ExpansionCandidate) -> float:
    score = 0.0
    score += 3.0 * len(candidate.reasons)
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


def dedupe_and_score_candidates(
    candidates: list[ExpansionCandidate],
    *,
    library_root: Path,
    seeds: list[ExpansionSeed],
) -> list[ExpansionCandidate]:
    existing_keys = _library_identity_keys(library_root)
    for seed in seeds:
        doi = _normalize_doi(seed.doi)
        if doi:
            existing_keys.add(("doi", doi, None))
        title = _normalize_title(seed.title)
        if title:
            existing_keys.add(("title_year", title, seed.year))

    deduped: dict[tuple[str, str, int | None], ExpansionCandidate] = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        if not key[1] or key in existing_keys:
            continue
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
        else:
            _merge_candidate(existing, candidate)

    ranked = list(deduped.values())
    for candidate in ranked:
        candidate.score = _score_candidate(candidate)
    ranked.sort(key=lambda item: (-item.score, item.year or 0, item.title))
    return ranked


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metadata_to_dict(metadata: ExpansionMetadata) -> dict[str, object]:
    return {
        "citation_count": metadata.citation_count,
        "influential_citation_count": metadata.influential_citation_count,
        "reference_count": metadata.reference_count,
        "publication_types": metadata.publication_types,
    }


def _seed_to_dict(seed: ExpansionSeed) -> dict[str, object]:
    return {
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


def _candidate_cards(candidates: list[ExpansionCandidate]) -> list[dict[str, object]]:
    return [
        {
            "title": candidate.title,
            "year": candidate.year,
            "doi": candidate.doi,
            "venue": candidate.venue,
            "authors": candidate.authors,
            "abstract": candidate.abstract[:1200],
            "citation_count": candidate.metadata.citation_count,
            "influential_citation_count": candidate.metadata.influential_citation_count,
            "reference_count": candidate.metadata.reference_count,
            "reasons": candidate.reasons,
            "relationship_contexts": candidate.relationship_contexts[:5],
            "source_ids": candidate.source_ids,
            "deterministic_score": candidate.score,
        }
        for candidate in candidates
    ]


def _expansion_output_path(library_root: Path, direction: str) -> Path:
    _validate_direction_component(direction)
    return library_root / "indexes" / "candidate_expansions" / f"{direction}.json"


def _provider_name(provider: ExpansionProvider) -> str:
    name = getattr(provider, "name", provider.__class__.__name__)
    return str(name)


def _write_expansion_payload(
    *,
    library_root: Path,
    direction: str,
    seeds: list[ExpansionSeed],
    candidates: list[ExpansionCandidate],
    provider_name: str,
    limit: int,
    llm_ranking: dict[str, object] | None = None,
) -> Path:
    output_path = _expansion_output_path(library_root, direction)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected = candidates[:limit]
    payload: dict[str, object] = {
        "direction": direction,
        "created_at": _utc_now(),
        "provider": provider_name,
        "seed_count": len(seeds),
        "candidate_count": len(selected),
        "candidate_limit": limit,
        "dedupe_stage": "before_pdf_download",
        "seeds": [_seed_to_dict(seed) for seed in seeds],
        "candidates": [_candidate_to_dict(candidate) for candidate in selected],
        "llm_ranking": llm_ranking,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def rank_expansion_candidates(
    *,
    library_root: Path,
    direction: str,
    seeds: list[ExpansionSeed],
    candidates: list[ExpansionCandidate],
    settings: RuntimeSettings,
    limit: int = 30,
) -> dict[str, object]:
    selected_candidates = candidates[:limit]
    source_payload = {
        "direction": direction,
        "library_root": str(library_root),
        "ranking_limit": limit,
        "seeds": [
            {
                "paper_id": seed.paper_id,
                "title": seed.title,
                "year": seed.year,
                "venue": seed.venue,
                "local_summary": seed.local_summary[:1600],
                "local_experiments": seed.local_experiments[:1200],
                "local_relevance": seed.local_relevance[:1200],
            }
            for seed in seeds
        ],
        "candidate_cards": _candidate_cards(selected_candidates),
    }
    with tempfile.TemporaryDirectory(prefix="paper-ops-citation-expansion-") as tmpdir:
        tmp_path = Path(tmpdir)
        source_path = tmp_path / "candidate_cards.json"
        output_path = tmp_path / "llm_ranking.json"
        source_path.write_text(
            json.dumps(source_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        run_artifact_agent_from_file(
            source_path=source_path,
            spec=EXPANSION_RANKING_SPEC,
            output_path=output_path,
            context_text=(
                "Rank citation-expansion candidates for a paper library direction. "
                "Use only the provided seed dossiers and candidate cards."
            ),
            settings=settings,
        )
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"ranked_candidates": []}


def expand_citations_for_direction(
    *,
    library_root: Path,
    direction: str,
    provider: ExpansionProvider | None = None,
    limit: int = 50,
    settings: RuntimeSettings | None = None,
    llm_limit: int = 30,
) -> Path:
    seeds = load_direction_seeds(library_root, direction)
    resolved_provider = provider or SemanticScholarExpansionProvider()
    raw_candidates: list[ExpansionCandidate] = []
    for seed in seeds:
        raw_candidates.extend(list(resolved_provider.candidates_for_seed(seed)))

    ranked_candidates = dedupe_and_score_candidates(
        raw_candidates,
        library_root=library_root,
        seeds=seeds,
    )
    llm_ranking = None
    if settings is not None and ranked_candidates:
        llm_ranking = rank_expansion_candidates(
            library_root=library_root,
            direction=direction,
            seeds=seeds,
            candidates=ranked_candidates,
            settings=settings,
            limit=llm_limit,
        )
    return _write_expansion_payload(
        library_root=library_root,
        direction=direction,
        seeds=seeds,
        candidates=ranked_candidates,
        provider_name=_provider_name(resolved_provider),
        limit=limit,
        llm_ranking=llm_ranking,
    )


def _compact_context(value: str, *, max_chars: int = 700) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _semantic_scholar_auth_headers(api_key: str | None) -> dict[str, str]:
    return {"x-api-key": api_key} if api_key else {}


def _external_ids(payload: dict[str, object]) -> dict[str, object]:
    external_ids = payload.get("externalIds", {})
    return external_ids if isinstance(external_ids, dict) else {}


def _doi_from_external_ids(payload: dict[str, object]) -> str | None:
    external_ids = _external_ids(payload)
    return _coerce_str(external_ids.get("DOI") or external_ids.get("doi"))


def _venue_from_semantic_scholar(payload: dict[str, object]) -> str | None:
    publication_venue = payload.get("publicationVenue")
    if isinstance(publication_venue, dict):
        venue_name = _coerce_str(publication_venue.get("name"))
        if venue_name:
            return venue_name
    return _coerce_str(payload.get("venue"))


def _source_ids_from_semantic_scholar(payload: dict[str, object]) -> dict[str, str]:
    source_ids: dict[str, str] = {}
    paper_id = _coerce_str(payload.get("paperId"))
    if paper_id:
        source_ids["semantic_scholar"] = paper_id
    corpus_id = payload.get("corpusId")
    if corpus_id is not None:
        source_ids["semantic_scholar_corpus_id"] = str(corpus_id)
    external_ids = _external_ids(payload)
    external_key_map = {
        "DOI": "doi",
        "ArXiv": "arxiv",
        "PubMed": "pubmed",
        "PubMedCentral": "pmc",
        "CorpusId": "semantic_scholar_corpus_id",
        "OpenAlex": "openalex",
    }
    for external_key, local_key in external_key_map.items():
        external_value = _coerce_str(external_ids.get(external_key))
        if external_value and local_key not in source_ids:
            source_ids[local_key] = external_value
    return source_ids


def _authors_from_semantic_scholar(payload: dict[str, object]) -> list[str]:
    authors = payload.get("authors", [])
    if not isinstance(authors, list):
        return []
    names = []
    for author in authors:
        if isinstance(author, dict):
            name = _coerce_str(author.get("name"))
            if name:
                names.append(name)
        elif isinstance(author, str) and author.strip():
            names.append(author.strip())
    return names


def _candidate_from_semantic_scholar_paper(
    payload: dict[str, object],
    *,
    seed: ExpansionSeed,
    relation_reason: str,
    contexts: list[str],
    intents: list[str],
    is_influential_relation: bool,
) -> ExpansionCandidate | None:
    title = _coerce_str(payload.get("title"))
    if title is None:
        return None
    reasons = [relation_reason]
    for intent in intents:
        reasons.append(f"semantic scholar intent: {intent}")
    if is_influential_relation:
        reasons.append(f"influential citation relation to seed: {seed.title}")
    return ExpansionCandidate(
        title=title,
        year=_coerce_int(payload.get("year")),
        doi=_doi_from_external_ids(payload),
        venue=_venue_from_semantic_scholar(payload),
        abstract=_coerce_str(payload.get("abstract")) or "",
        metadata=ExpansionMetadata(
            citation_count=_coerce_int(payload.get("citationCount")),
            influential_citation_count=_coerce_int(
                payload.get("influentialCitationCount")
            ),
            reference_count=_coerce_int(payload.get("referenceCount")),
            publication_types=_coerce_str_list(payload.get("publicationTypes")),
        ),
        reasons=list(dict.fromkeys(reasons)),
        source_ids=_source_ids_from_semantic_scholar(payload),
        url=_coerce_str(payload.get("url")),
        authors=_authors_from_semantic_scholar(payload),
        relationship_contexts=[_compact_context(context) for context in contexts],
    )


class SemanticScholarExpansionProvider:
    name = "semantic_scholar"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
        citations_limit: int = 25,
        references_limit: int = 25,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
        request_delay_seconds: float | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
            or os.environ.get("S2_API_KEY")
        )
        self.base_url = base_url.rstrip("/")
        self.citations_limit = citations_limit
        self.references_limit = references_limit
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.request_delay_seconds = (
            request_delay_seconds
            if request_delay_seconds is not None
            else float(os.environ.get("PAPER_OPS_S2_REQUEST_DELAY_SECONDS", "0"))
        )

    def candidates_for_seed(self, seed: ExpansionSeed) -> Iterable[ExpansionCandidate]:
        seed_payload = self._resolve_seed(seed)
        if not seed_payload:
            return []
        paper_id = _coerce_str(seed_payload.get("paperId"))
        if paper_id is None:
            return []

        candidates: list[ExpansionCandidate] = []
        candidates.extend(
            self._relation_candidates(
                seed=seed,
                paper_id=paper_id,
                endpoint="citations",
                paper_key="citingPaper",
                relation_reason=f"cites seed: {seed.title}",
                limit=self.citations_limit,
            )
        )
        candidates.extend(
            self._relation_candidates(
                seed=seed,
                paper_id=paper_id,
                endpoint="references",
                paper_key="citedPaper",
                relation_reason=f"referenced by seed: {seed.title}",
                limit=self.references_limit,
            )
        )
        return candidates

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _get_json(self, path: str, params: dict[str, object]) -> dict[str, object]:
        url = self._url(path)
        last_error: Exception | None = None
        for attempt in range(1, 4):
            if self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)
            response = self.session.get(
                url,
                params=params,
                headers=_semantic_scholar_auth_headers(self.api_key),
                timeout=self.timeout_seconds,
            )
            if response.status_code == 404:
                return {}
            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_seconds = float(retry_after) if retry_after else 2**attempt
                except ValueError:
                    sleep_seconds = 2**attempt
                time.sleep(min(sleep_seconds, 30))
                continue
            try:
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(min(2**attempt, 8))
        assert last_error is not None
        raise last_error

    def _resolve_seed(self, seed: ExpansionSeed) -> dict[str, object] | None:
        if seed.doi:
            doi_payload = self._get_json(
                f"paper/{quote(f'DOI:{_normalize_doi(seed.doi)}', safe=':')}",
                {"fields": SEMANTIC_SCHOLAR_PAPER_FIELDS},
            )
            if doi_payload:
                return doi_payload

        search_payload = self._get_json(
            "paper/search",
            {
                "query": seed.title,
                "limit": 5,
                "fields": SEMANTIC_SCHOLAR_PAPER_FIELDS,
            },
        )
        data = search_payload.get("data", [])
        if not isinstance(data, list):
            return None
        normalized_seed_title = _normalize_title(seed.title)
        for item in data:
            if not isinstance(item, dict):
                continue
            title = _normalize_title(_coerce_str(item.get("title")))
            year = _coerce_int(item.get("year"))
            if title == normalized_seed_title and (
                seed.year is None or year is None or year == seed.year
            ):
                return item
        for item in data:
            if isinstance(item, dict):
                return item
        return None

    def _relation_candidates(
        self,
        *,
        seed: ExpansionSeed,
        paper_id: str,
        endpoint: str,
        paper_key: str,
        relation_reason: str,
        limit: int,
    ) -> list[ExpansionCandidate]:
        if limit <= 0:
            return []
        payload = self._get_json(
            f"paper/{quote(paper_id, safe='')}/{endpoint}",
            {
                "limit": limit,
                "fields": SEMANTIC_SCHOLAR_RELATION_FIELDS,
            },
        )
        data = payload.get("data", [])
        if not isinstance(data, list):
            return []

        candidates: list[ExpansionCandidate] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            related_payload = item.get(paper_key)
            if not isinstance(related_payload, dict):
                continue
            contexts = _coerce_str_list(item.get("contexts"))
            intents = _coerce_str_list(item.get("intents"))
            candidate = _candidate_from_semantic_scholar_paper(
                related_payload,
                seed=seed,
                relation_reason=relation_reason,
                contexts=contexts,
                intents=intents,
                is_influential_relation=item.get("isInfluential") is True,
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates
