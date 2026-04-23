import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


class DiscoveryCandidate(BaseModel):
    candidate_id: str
    title: str
    source_url: str
    source_type: str
    discovered_from: str
    priority: str
    matched_keywords: list[str] = Field(default_factory=list)
    reason: str
    accepted: bool | None = None
    linked_paper_id: str | None = None


class CandidateQueue:
    def __init__(self, queue_path: Path):
        self.queue_path = queue_path
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_path.exists():
            self.queue_path.write_text("[]", encoding="utf-8")

    def load(self) -> list[DiscoveryCandidate]:
        payload = json.loads(self.queue_path.read_text(encoding="utf-8"))
        return [DiscoveryCandidate.model_validate(item) for item in payload]

    def save(self, entries: list[DiscoveryCandidate]) -> None:
        payload = [entry.model_dump(mode="json") for entry in entries]
        self.queue_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def enqueue(
        self,
        *,
        title: str,
        source_url: str,
        source_type: str,
        discovered_from: str,
        priority: str,
        matched_keywords: list[str],
        reason: str,
    ) -> DiscoveryCandidate:
        entries = self.load()
        for entry in entries:
            if entry.title == title and entry.source_url == source_url:
                return entry

        candidate = DiscoveryCandidate(
            candidate_id=str(uuid4()),
            title=title,
            source_url=source_url,
            source_type=source_type,
            discovered_from=discovered_from,
            priority=priority,
            matched_keywords=matched_keywords,
            reason=reason,
        )
        entries.append(candidate)
        self.save(entries)
        return candidate

    def accept(self, candidate_id: str, linked_paper_id: str) -> DiscoveryCandidate:
        entries = self.load()
        for entry in entries:
            if entry.candidate_id == candidate_id:
                entry.accepted = True
                entry.linked_paper_id = linked_paper_id
                self.save(entries)
                return entry
        raise ValueError(f"Candidate not found: {candidate_id}")

    def reject(self, candidate_id: str) -> DiscoveryCandidate:
        entries = self.load()
        for entry in entries:
            if entry.candidate_id == candidate_id:
                entry.accepted = False
                self.save(entries)
                return entry
        raise ValueError(f"Candidate not found: {candidate_id}")
