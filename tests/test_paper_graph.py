import json
from pathlib import Path
import sqlite3

from paper_ops.citation_expansion import ExpansionCandidate, ExpansionMetadata
from paper_ops.paper_graph import (
    PaperGraphStore,
    enqueue_graph_downloads,
    export_graph_candidates,
    export_graph_snapshot,
    export_literature_map,
    graph_db_path,
    review_graph_candidates,
    update_graph_for_direction,
)
from paper_ops.paper_search_client import PaperSearchError
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


class FakeProvider:
    name = "fake_provider"

    def candidates_for_seed(self, seed):
        assert seed.title == "Seed Paper"
        return [
            ExpansionCandidate(
                title="Candidate A",
                year=2025,
                doi="10.0/a",
                venue="NeurIPS",
                abstract="A cites the seed.",
                metadata=ExpansionMetadata(
                    citation_count=25,
                    influential_citation_count=4,
                    reference_count=30,
                    publication_types=["Conference"],
                ),
                reasons=[
                    "cites seed: Seed Paper",
                    "semantic scholar intent: methodology",
                ],
                source_ids={"semantic_scholar": "a", "doi": "10.0/a"},
                url="https://example.com/a",
                authors=["Ada Author"],
                relationship_contexts=["Candidate A improves the seed method."],
            ),
            ExpansionCandidate(
                title="Candidate B",
                year=2020,
                doi="10.0/b",
                venue="ICLR",
                abstract="A foundation paper.",
                metadata=ExpansionMetadata(citation_count=120),
                reasons=["referenced by seed: Seed Paper"],
                source_ids={"semantic_scholar": "b", "doi": "10.0/b"},
                relationship_contexts=["Seed Paper builds on Candidate B."],
            ),
        ]


def test_update_graph_for_direction_persists_relations_and_defers_candidates(
    tmp_path: Path,
):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-author-seed-paper",
        title="Seed Paper",
        year=2026,
        doi="10.0/seed",
    )

    result = update_graph_for_direction(
        library_root=library_root,
        direction="predictive_coding",
        provider=FakeProvider(),
        limit=10,
    )

    assert result.db_path == graph_db_path(library_root)
    assert result.expansion_path.exists()
    assert result.seed_count == 1
    assert result.raw_candidate_count == 2
    assert result.candidate_count == 2
    assert result.relation_count == 2

    conn = sqlite3.connect(result.db_path)
    conn.row_factory = sqlite3.Row
    try:
        papers = conn.execute("SELECT paper_key, status FROM papers").fetchall()
        assert {row["status"] for row in papers} == {"local", "candidate"}

        relations = conn.execute(
            "SELECT relation_type, description, contexts_json, intents_json FROM paper_relations"
        ).fetchall()
        assert {row["relation_type"] for row in relations} == {
            "cited_by",
            "references",
        }
        assert any("improves the seed" in row["description"] for row in relations)
        merged_intents = {
            intent
            for row in relations
            for intent in json.loads(row["intents_json"])
        }
        assert {"methodology", "extension"}.issubset(merged_intents)

        candidate_rows = conn.execute(
            "SELECT state, deterministic_score FROM candidates"
        ).fetchall()
        assert candidate_rows == []
    finally:
        conn.close()

    payload = json.loads(result.expansion_path.read_text(encoding="utf-8"))
    assert payload["database"] == str(result.db_path)
    assert payload["dedupe_stage"] == "identity_upsert_at_discovery"
    assert payload["selection_stage"] == "deferred_until_candidate_export_or_review"

    output_path = export_graph_candidates(
        library_root=library_root,
        direction="predictive_coding",
        limit=10,
    )
    candidate_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [candidate["title"] for candidate in candidate_payload["candidates"]] == [
        "Candidate A",
        "Candidate B",
    ]


def test_export_graph_candidates_includes_latest_llm_review(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-author-seed-paper",
        title="Seed Paper",
        year=2026,
        doi="10.0/seed",
    )
    update_graph_for_direction(
        library_root=library_root,
        direction="predictive_coding",
        provider=FakeProvider(),
        limit=10,
    )

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
        source_payload = json.loads(source_path.read_text(encoding="utf-8"))
        assert source_payload["candidate_cards"][0]["title"] == "Candidate A"
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

    review = review_graph_candidates(
        library_root=library_root,
        direction="predictive_coding",
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
        limit=5,
    )

    assert review.reviewed_count == 1

    with PaperGraphStore(graph_db_path(library_root)) as store:
        rows = store.list_candidates(direction="predictive_coding")

    candidate_a = next(row for row in rows if row["title"] == "Candidate A")
    assert candidate_a["candidate_state"] == "llm_reviewed"
    assert candidate_a["latest_review"]["decision"] == "fetch"
    assert candidate_a["latest_review"]["priority"] == "high"
    assert candidate_a["metadata"]["citation_count"] == 25

    output_path = export_graph_candidates(
        library_root=library_root,
        direction="predictive_coding",
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    exported_a = next(
        candidate
        for candidate in payload["candidates"]
        if candidate["title"] == "Candidate A"
    )
    assert exported_a["candidate_state"] == "llm_reviewed"
    assert exported_a["latest_review"]["rationale"] == "Strong citation context."


def test_enqueue_graph_downloads_records_attempts_and_manual_requests(
    tmp_path: Path,
    monkeypatch,
):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-author-seed-paper",
        title="Seed Paper",
        year=2026,
        doi="10.0/seed",
    )
    update_graph_for_direction(
        library_root=library_root,
        direction="predictive_coding",
        provider=FakeProvider(),
        limit=10,
    )

    def fake_run_artifact_agent_from_file(
        *,
        source_path: Path,
        spec,
        output_path: Path,
        context_text: str,
        settings: RuntimeSettings,
    ) -> Path:
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
                            "rationale": "Download first.",
                        },
                        {
                            "rank": 2,
                            "title": "Candidate B",
                            "doi": "10.0/b",
                            "decision": "fetch",
                            "priority": "high",
                            "rationale": "Download second.",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(
        "paper_ops.citation_expansion.run_artifact_agent_from_file",
        fake_run_artifact_agent_from_file,
    )
    review_graph_candidates(
        library_root=library_root,
        direction="predictive_coding",
        settings=RuntimeSettings(
            codex_root=Path("/root/.codex"),
            base_url="https://api.example.com/v1",
            model="gpt-5.4",
            api_key="secret-key",
        ),
        limit=5,
    )

    class FakeClient:
        def download_with_fallback(self, **kwargs):
            if kwargs["doi"] == "10.0/b":
                raise PaperSearchError("no legal pdf")
            path = kwargs["save_path"] / "downloaded.pdf"
            path.write_bytes(b"%PDF-1.4 fake")
            return path

    result = enqueue_graph_downloads(
        library_root=library_root,
        direction="predictive_coding",
        priority="high",
        limit=2,
        client=FakeClient(),
    )

    assert result.selected_count == 2
    assert result.downloaded_count == 1
    assert result.manual_required_count == 1

    conn = sqlite3.connect(result.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.title, c.state
            FROM candidates c
            JOIN papers p ON p.paper_key = c.paper_key
            ORDER BY p.title
            """
        ).fetchall()
        assert [(row["title"], row["state"]) for row in rows] == [
            ("Candidate A", "queued"),
            ("Candidate B", "manual_required"),
        ]
        attempts = conn.execute(
            "SELECT result, pdf_path, error FROM download_attempts ORDER BY result"
        ).fetchall()
        assert {row["result"] for row in attempts} == {
            "downloaded",
            "manual_required",
        }
    finally:
        conn.close()

    request_files = sorted((library_root / "manual_downloads" / "requests").glob("*.yaml"))
    assert len(request_files) == 2
    inbox_files = sorted((library_root / "manual_downloads" / "inbox").glob("*.pdf"))
    assert len(inbox_files) == 1


def test_graph_upsert_merges_title_year_candidate_into_doi_identity(tmp_path: Path):
    db_path = graph_db_path(tmp_path / "papers")
    weak = ExpansionCandidate(
        title="Same Paper",
        year=2024,
        doi=None,
        venue=None,
        abstract="weak identity",
        metadata=ExpansionMetadata(citation_count=1),
        reasons=["referenced by seed: Seed"],
        source_ids={},
    )
    strong = ExpansionCandidate(
        title="Same Paper",
        year=2024,
        doi="10.0/same",
        venue=None,
        abstract="strong identity with doi",
        metadata=ExpansionMetadata(citation_count=10),
        reasons=["referenced by seed: Seed"],
        source_ids={"doi": "10.0/same"},
    )

    with PaperGraphStore(db_path) as store:
        weak_key = store.upsert_candidate_paper(weak)
        strong_key = store.upsert_candidate_paper(strong)
        store.commit()

    assert weak_key.startswith("title_year:")
    assert strong_key == "doi:10.0/same"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT paper_key, doi FROM papers").fetchall()
        assert [(row["paper_key"], row["doi"]) for row in rows] == [
            ("doi:10.0/same", "10.0/same")
        ]
    finally:
        conn.close()


def test_graph_snapshot_and_literature_map_exports(tmp_path: Path):
    library_root = tmp_path / "papers"
    _write_paper(
        library_root,
        direction="predictive_coding",
        paper_id="2026-author-seed-paper",
        title="Seed Paper",
        year=2026,
        doi="10.0/seed",
    )
    update_graph_for_direction(
        library_root=library_root,
        direction="predictive_coding",
        provider=FakeProvider(),
        limit=10,
    )

    snapshot_path = export_graph_snapshot(
        library_root=library_root,
        direction="predictive_coding",
    )
    map_path = export_literature_map(
        library_root=library_root,
        direction="predictive_coding",
    )

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    literature_map = json.loads(map_path.read_text(encoding="utf-8"))
    assert snapshot["candidate_count"] == 2
    assert literature_map["candidate_count"] == 2
    assert literature_map["concepts"]
