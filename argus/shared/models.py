from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AgentType(StrEnum):
    SCOUT = "scout"
    DEEP_DIVE = "deep_dive"
    VERIFICATION = "verification"
    SYNTHESIS = "synthesis"


class TaskType(StrEnum):
    DISCOVER = "discover"
    EXTRACT = "extract"
    VERIFY = "verify"
    SYNTHESIZE = "synthesize"


class ResearchStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETING = "completing"
    DONE = "done"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"


class TaskStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LLMProviderType(StrEnum):
    OLLAMA = "ollama"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    OPENAI_COMPATIBLE = "openai_compatible"


class TaskStep(BaseModel):
    id: int
    type: TaskType
    goal: str
    agent: AgentType
    depends_on: list[int] = Field(default_factory=list)
    status: TaskStepStatus = TaskStepStatus.PENDING
    result: dict[str, Any] | None = None
    task_id: str = ""


class ResearchPlan(BaseModel):
    steps: list[TaskStep]
    estimated_sources: int = 0
    estimated_time_minutes: int = 0


class ResearchTask(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    query: str
    status: ResearchStatus = ResearchStatus.PENDING
    plan: ResearchPlan | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    total_cost: float = 0.0
    error_message: str | None = None


class Source(BaseModel):
    url: str
    title: str | None = None
    content_hash: str | None = None
    credibility_score: float = 0.5
    fetched_at: datetime | None = None


class Entity(BaseModel):
    name: str
    type: str = "unknown"
    description: str | None = None
    confidence: float = 0.5
    attributes: dict[str, Any] = Field(default_factory=dict)


class Claim(BaseModel):
    statement: str
    confidence: float = 0.5
    source_urls: list[str] = Field(default_factory=list)
    entity_name: str | None = None
    attribute: str | None = None
    extracted_at: datetime | None = None


class ConflictEdge(BaseModel):
    claim_a: str
    claim_b: str
    relationship: str
    reason: str
    confidence_delta: float = 0.0


class Fact(BaseModel):
    idempotency_key: str
    task_id: str
    step_id: int
    agent: AgentType
    facts: list[Entity | Claim | Source | ConflictEdge]
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProgressEvent(BaseModel):
    type: str
    task_id: str
    step_id: int | None = None
    agent: AgentType | None = None
    message: str
    data: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LLMUsage(BaseModel):
    provider: LLMProviderType
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0


class LLMResponse(BaseModel):
    content: str
    provider_used: LLMProviderType
    usage: LLMUsage


class CostReport(BaseModel):
    task_id: str
    total_cost: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    budget_limit: float = 0.50


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class ResearchResponse(BaseModel):
    task_id: UUID
    status: ResearchStatus
    message: str


class FeedbackRequest(BaseModel):
    source_id: int
    is_correct: bool


class HealthStatus(BaseModel):
    status: str = "ok"
    redis: bool = False
    sqlite: bool = False
    ollama: bool = False
    agents: dict[str, bool] = Field(default_factory=dict)
    uptime_seconds: float = 0.0
