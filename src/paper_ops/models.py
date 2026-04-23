from pathlib import Path

from pydantic import BaseModel, Field


class StageStatus(BaseModel):
    state: str = "pending"
    updated_at: str | None = None
    last_error: str | None = None


class ProcessingStatus(BaseModel):
    ingested: StageStatus = Field(default_factory=StageStatus)
    classified: StageStatus = Field(default_factory=StageStatus)
    translated: StageStatus = Field(default_factory=StageStatus)
    summarized: StageStatus = Field(default_factory=StageStatus)
    indexed: StageStatus = Field(default_factory=StageStatus)


class SourceInfo(BaseModel):
    type: str
    url: str | None = None
    pdf_url: str | None = None
    local_path: str | None = None


class PaperMetadata(BaseModel):
    title: str
    authors: list[str]
    year: int
    venue: str | None = None
    source_urls: list[str]
    doi: str | None = None
    keywords: list[str] = Field(default_factory=list)
    code_urls: list[str] = Field(default_factory=list)


class PaperRecord(BaseModel):
    paper_id: str
    title: str
    direction: str
    status: ProcessingStatus
    source: SourceInfo
    metadata: PaperMetadata


class PaperPaths(BaseModel):
    paper_dir: Path
    pdf_path: Path
    metadata_path: Path
    translation_path: Path
    summary_path: Path
    experiments_path: Path
    notes_path: Path
    code_links_path: Path
    relevance_path: Path
