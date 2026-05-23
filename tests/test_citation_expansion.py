import json
from pathlib import Path

from paper_ops.citation_expansion import (
    ExpansionCandidate,
    ExpansionMetadata,
    ExpansionSeed,
    SemanticScholarExpansionProvider,
    dedupe_and_score_candidates,
    expand_citations_for_direction,
    load_direction_seeds,
    rank_expansion_candidates,
)
from paper_ops.settings import RuntimeSettings


def _write_paper(
    root: Path,
    *,
    direction: str,
    paper_id: str,
    title: str,
    year: int,
    doi: str | None = None,
) -> Path:
    paper_dir = root / "library" / direction / paper_id
    paper_dir.mkdir(parents=True)
    (paper_dir / "metadata.json").write_text(
        json.dumps(
            {
                "paper_id": paper_id,
                "title": title,
                "direction": direction,
                "metadata": {
                    "title": title,
                    "authors": ["Author One"],
                    "year": year,
                    "venue": "ICLR",
                    "doi": doi,
                    "source_urls": ["https://example.com/source"],
                    "keywords": ["predictive coding"],
                },
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "summary_zh.md").write_text("方法说明：局部误差驱动训练。", encoding="utf-8")
    (paper_dir / "experiments_zh.md").write_text("实验说明：MNIST 和 CIFAR。", encoding="utf-8")
    (paper_dir / "relevance_to_my_research.md").write_text(
        "相关性：强相关，适合做局部学习基线。",
        encoding="utf-8",
    )
    return paper_dir


def test_load_direction_seeds_reads_local_artifacts(tmp_path: Path):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-author-seed-paper",
        title="Seed Paper",
        year=2026,
        doi="10.0/seed",
    )

    seeds = load_direction_seeds(library_root, "predictive_coding")

    assert seeds == [
        ExpansionSeed(
            paper_id="2026-author-seed-paper",
            title="Seed Paper",
            direction="predictive_coding",
            year=2026,
            doi="10.0/seed",
            venue="ICLR",
            local_summary="方法说明：局部误差驱动训练。",
            local_experiments="实验说明：MNIST 和 CIFAR。",
            local_relevance="相关性：强相关，适合做局部学习基线。",
            paper_dir=library_root
            / "library"
            / "predictive_coding"
            / "2026-author-seed-paper",
        )
    ]


def test_dedupe_and_score_candidates_merges_reasons_and_skips_existing(tmp_path: Path):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-existing-paper",
        title="Existing Paper",
        year=2026,
        doi="10.0/existing",
    )
    seed = ExpansionSeed(
        paper_id="2026-seed",
        title="Seed",
        direction="predictive_coding",
        year=2026,
        doi="10.0/seed",
        venue="ICLR",
        local_summary="",
        local_experiments="",
        local_relevance="",
        paper_dir=tmp_path,
    )
    candidates = [
        ExpansionCandidate(
            title="Existing Paper",
            year=2026,
            doi="10.0/existing",
            venue="ICLR",
            abstract="already present",
            metadata=ExpansionMetadata(citation_count=100),
            reasons=["cites seed"],
            source_ids={"semantic_scholar": "existing"},
        ),
        ExpansionCandidate(
            title="New Strong Paper",
            year=2025,
            doi="10.0/new",
            venue="NeurIPS",
            abstract="new candidate",
            metadata=ExpansionMetadata(
                citation_count=80,
                influential_citation_count=9,
                reference_count=40,
            ),
            reasons=["cites seed"],
            source_ids={"semantic_scholar": "new-a"},
        ),
        ExpansionCandidate(
            title="New Strong Paper",
            year=2025,
            doi="10.0/new",
            venue="NeurIPS",
            abstract="duplicate candidate",
            metadata=ExpansionMetadata(
                citation_count=120,
                influential_citation_count=3,
                reference_count=44,
                publication_types=["Conference"],
            ),
            reasons=["referenced by seed"],
            source_ids={"openalex": "W1"},
        ),
        ExpansionCandidate(
            title="Weak Paper",
            year=2018,
            doi="10.0/weak",
            venue="Workshop",
            abstract="older candidate",
            metadata=ExpansionMetadata(citation_count=2),
            reasons=["cites seed"],
            source_ids={},
        ),
    ]

    ranked = dedupe_and_score_candidates(
        candidates,
        library_root=library_root,
        seeds=[seed],
    )

    assert [candidate.title for candidate in ranked] == ["New Strong Paper", "Weak Paper"]
    assert ranked[0].score > ranked[1].score
    assert sorted(ranked[0].reasons) == ["cites seed", "referenced by seed"]
    assert ranked[0].source_ids == {"semantic_scholar": "new-a", "openalex": "W1"}
    assert ranked[0].metadata.citation_count == 120
    assert ranked[0].metadata.influential_citation_count == 9
    assert ranked[0].metadata.reference_count == 44
    assert ranked[0].metadata.publication_types == ["Conference"]


def test_expand_citations_for_direction_uses_provider_and_writes_json(tmp_path: Path):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-author-seed-paper",
        title="Seed Paper",
        year=2026,
        doi="10.0/seed",
    )

    class FakeProvider:
        def candidates_for_seed(self, seed):
            assert seed.title == "Seed Paper"
            return [
                ExpansionCandidate(
                    title="Candidate A",
                    year=2025,
                    doi="10.0/a",
                    venue="NeurIPS",
                    abstract="A cites the seed.",
                    metadata=ExpansionMetadata(citation_count=25),
                    reasons=["cites seed: Seed Paper"],
                    source_ids={"semantic_scholar": "a"},
                )
            ]

    output_path = expand_citations_for_direction(
        library_root=library_root,
        direction="predictive_coding",
        provider=FakeProvider(),
        limit=10,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["direction"] == "predictive_coding"
    assert payload["seed_count"] == 1
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["title"] == "Candidate A"
    assert payload["candidates"][0]["score"] > 0
    assert output_path == (
        library_root
        / "indexes"
        / "candidate_expansions"
        / "predictive_coding.json"
    )


def test_semantic_scholar_provider_reads_citations_references_and_contexts():
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, params, headers, timeout):
            self.calls.append((url, params, headers, timeout))
            if url.endswith("/paper/DOI:10.0%2Fseed"):
                return FakeResponse({"paperId": "seed-s2", "title": "Seed Paper"})
            if url.endswith("/paper/seed-s2/citations"):
                return FakeResponse(
                    {
                        "data": [
                            {
                                "contexts": ["Candidate A improves the seed method."],
                                "intents": ["methodology"],
                                "isInfluential": True,
                                "citingPaper": {
                                    "paperId": "candidate-a",
                                    "corpusId": 123,
                                    "title": "Candidate A",
                                    "year": 2025,
                                    "venue": "NeurIPS",
                                    "abstract": "A useful follow-up.",
                                    "externalIds": {"DOI": "10.0/a"},
                                    "citationCount": 40,
                                    "influentialCitationCount": 6,
                                    "referenceCount": 30,
                                    "publicationTypes": ["Conference"],
                                    "authors": [{"name": "Ada Author"}],
                                    "url": "https://semanticscholar.org/paper/a",
                                },
                            }
                        ]
                    }
                )
            if url.endswith("/paper/seed-s2/references"):
                return FakeResponse(
                    {
                        "data": [
                            {
                                "contexts": ["Seed Paper builds on Candidate B."],
                                "intents": ["background"],
                                "isInfluential": False,
                                "citedPaper": {
                                    "paperId": "candidate-b",
                                    "title": "Candidate B",
                                    "year": 2020,
                                    "venue": "ICLR",
                                    "abstract": "A foundation paper.",
                                    "externalIds": {"DOI": "10.0/b"},
                                    "citationCount": 120,
                                },
                            }
                        ]
                    }
                )
            raise AssertionError(f"unexpected URL: {url}")

    provider = SemanticScholarExpansionProvider(session=FakeSession())
    seed = ExpansionSeed(
        paper_id="2026-seed",
        title="Seed Paper",
        direction="predictive_coding",
        year=2026,
        doi="10.0/seed",
        venue="ICLR",
        local_summary="",
        local_experiments="",
        local_relevance="",
        paper_dir=Path("/tmp/seed"),
    )

    candidates = list(provider.candidates_for_seed(seed))

    assert {candidate.title for candidate in candidates} == {"Candidate A", "Candidate B"}
    candidate_a = next(candidate for candidate in candidates if candidate.title == "Candidate A")
    assert candidate_a.doi == "10.0/a"
    assert candidate_a.metadata.citation_count == 40
    assert candidate_a.relationship_contexts == ["Candidate A improves the seed method."]
    assert "cites seed: Seed Paper" in candidate_a.reasons
    assert "semantic scholar intent: methodology" in candidate_a.reasons
    assert "influential citation relation to seed: Seed Paper" in candidate_a.reasons
    assert candidate_a.source_ids["semantic_scholar"] == "candidate-a"
    assert candidate_a.authors == ["Ada Author"]


def test_rank_expansion_candidates_uses_compact_cards_and_returns_json(
    tmp_path: Path,
    monkeypatch,
):
    captured = {}

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
        captured["spec"] = spec
        captured["source"] = json.loads(source_path.read_text(encoding="utf-8"))
        captured["context_text"] = context_text
        output_path.write_text(
            json.dumps(
                {
                    "ranked_candidates": [
                        {
                            "rank": 1,
                            "title": "Candidate A",
                            "doi": "10.0/a",
                            "decision": "fetch",
                            "priority": "high",
                            "rationale": "Strong citation context.",
                        }
                    ],
                    "notes": [],
                }
            ),
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(
        "paper_ops.citation_expansion.run_artifact_agent_from_file",
        fake_run_artifact_agent_from_file,
    )
    seed = ExpansionSeed(
        paper_id="2026-seed",
        title="Seed Paper",
        direction="predictive_coding",
        year=2026,
        doi="10.0/seed",
        venue="ICLR",
        local_summary="summary",
        local_experiments="experiments",
        local_relevance="relevance",
        paper_dir=tmp_path,
    )
    candidate = ExpansionCandidate(
        title="Candidate A",
        year=2025,
        doi="10.0/a",
        venue="NeurIPS",
        abstract="abstract",
        metadata=ExpansionMetadata(citation_count=25),
        reasons=["cites seed: Seed Paper"],
        source_ids={"semantic_scholar": "a"},
        score=4.0,
    )

    ranking = rank_expansion_candidates(
        library_root=tmp_path / "papers",
        direction="predictive_coding",
        seeds=[seed],
        candidates=[candidate],
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
    )

    assert captured["spec"].name == "citation_expansion_ranking"
    assert captured["source"]["direction"] == "predictive_coding"
    assert captured["source"]["candidate_cards"][0]["title"] == "Candidate A"
    assert ranking["ranked_candidates"][0]["decision"] == "fetch"
