from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DiscoverySubtopic(BaseModel):
    name: str = Field(min_length=1)
    rationale: str = ""
    objective: str = ""
    required_evidence: list[str] = Field(default_factory=list, max_length=6)
    risk_focus: list[str] = Field(default_factory=list, max_length=6)
    search_queries: list[str] = Field(default_factory=list, max_length=5)
    source_intents: list[str] = Field(default_factory=list, max_length=6)


class CandidateCompany(BaseModel):
    ticker: str = Field(pattern=r"^\d{4}$")
    name: str = Field(min_length=1)
    segment: str = Field(min_length=1)
    rationale: str = ""
    evidence_keywords: list[str] = Field(default_factory=list, max_length=8)


class TopicDiscoveryPlan(BaseModel):
    subtopics: list[DiscoverySubtopic] = Field(default_factory=list, max_length=10)
    candidate_companies: list[CandidateCompany] = Field(default_factory=list, max_length=24)


class DiscoveryPlanQuality(BaseModel):
    status: str
    score: int
    missing: list[str]
    coverage: dict[str, bool]
    query_quality: dict = Field(default_factory=dict)
    subtopic_count: int
    candidate_count: int
    recommendation: str


class ValidatedCandidate(BaseModel):
    ticker: str
    name: str
    segment: str
    rationale: str
    evidence_keywords: list[str]
    evidence_count: int
    evidence_source_count: int = 0
    evidence_titles: list[str]
    evidence_sources: list[dict] = Field(default_factory=list)
    evidence_confidence_score: int = 0
    evidence_confidence_label: str = "低"
    source_credibility_score: int = 0
    source_credibility_label: str = "未分級"
    source_credibility_counts: dict = Field(default_factory=dict)
    latest_evidence_date: Optional[str] = None
    evidence_age_days: Optional[int] = None
    evidence_stale: bool = False
    status: str
    validation_reason: str = ""
    next_action: str = ""
    promotion_eligible: bool = False
