from __future__ import annotations

from pydantic import BaseModel, Field


class TaskStepOutput(BaseModel):
    id: int
    type: str
    goal: str
    agent: str
    depends_on: list[int] = Field(default_factory=list)


class PlanningOutput(BaseModel):
    steps: list[TaskStepOutput]
    estimated_sources: int = 0
    estimated_time_minutes: int = 0


class EntityOutput(BaseModel):
    name: str
    type: str = "unknown"
    description: str | None = None


class ClaimOutput(BaseModel):
    statement: str
    entity_name: str | None = None
    attribute: str | None = None
    source_url: str = ""


class ExtractionOutput(BaseModel):
    entities: list[EntityOutput] = Field(default_factory=list)
    claims: list[ClaimOutput] = Field(default_factory=list)


class ConflictOutput(BaseModel):
    claim_a: str
    claim_b: str
    contradiction: bool
    explanation: str = ""


class VerificationOutput(BaseModel):
    conflicts: list[ConflictOutput] = Field(default_factory=list)
    overall_confidence: float = 0.5


class EntityResolutionOutput(BaseModel):
    should_merge: bool = False
    target_entity_name: str = ""
    confidence: float = 0.0
    reason: str = ""


class RelationOutput(BaseModel):
    source: str
    target: str
    relation_type: str
    weight: float = 0.5


class SynthesisOutput(BaseModel):
    resolutions: list[EntityResolutionOutput] = Field(default_factory=list)
    relations: list[RelationOutput] = Field(default_factory=list)


class SearchQueryOutput(BaseModel):
    queries: list[str] = Field(default_factory=list)
    strategy: str = "breadth_first"
