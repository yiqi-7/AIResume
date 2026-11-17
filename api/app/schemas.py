import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SectionKind = Literal["contact", "education", "experience", "projects", "skills", "other"]
Dimension = Literal["structure", "content", "relevance"]


class Block(BaseModel):
    id: str
    text: str
    kind: Literal["paragraph", "bullet", "heading"] = "paragraph"


class Section(BaseModel):
    id: str
    kind: SectionKind
    title: str
    blocks: list[Block]


class Resume(BaseModel):
    sections: list[Section]
    warnings: list[str] = []
    estimated_pages: int | None = None
    page_count_verified: bool = False


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=100)
    priority: Literal["P0", "P1", "P2", "P3"]
    target_block_id: str | None
    resume_quote: str = Field(default="", max_length=2000)
    jd_quote: str = Field(min_length=2, max_length=2000)
    reason: str = Field(min_length=2, max_length=1200)
    rewrite: str = Field(default="", max_length=3000)
    needs_fact: bool = False
    question: str = Field(default="", max_length=500)


class CandidateList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Candidate] = Field(default_factory=list, max_length=12)


class Suggestion(Candidate):
    id: str
    dimension: Dimension
    decision: Literal["pending", "accepted", "skipped"] = "pending"
    edited_text: str | None = None
    user_fact: str = ""
    target_section_id: str | None = None


class Session(BaseModel):
    id: str
    created_at: float = Field(default_factory=time.time)
    last_active: float = Field(default_factory=time.time)
    expires_at: float
    auth_hash: str
    ip_key: str
    state: Literal[
        "parsed", "analyzing", "ready", "partial", "failed", "answering", "interrupted"
    ] = "parsed"
    resume: Resume
    jd: str
    suggestions: list[Suggestion] = []
    dimensions: dict[str, str] = {}
    error: str | None = None
    charged: bool = False
    revision: int = 0


class AnalyzeRequest(BaseModel):
    provider: str = "station"
    model: str = Field(default="", max_length=100)


class SuggestionEdit(BaseModel):
    action: Literal["accept", "skip", "restore", "edit"]
    text: str | None = Field(default=None, max_length=3000)
    revision: int
    confirmed_facts: bool = False


class FactAnswer(AnalyzeRequest):
    answer: str = Field(min_length=2, max_length=2000)
    section_id: str
    confirmed: bool


class Problem(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(code)
