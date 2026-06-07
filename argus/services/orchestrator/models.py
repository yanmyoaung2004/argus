from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class ResearchResponse(BaseModel):
    task_id: UUID
    status: str
    message: str


class SSEEvent(BaseModel):
    event: str
    data: str
    retry: int | None = None
