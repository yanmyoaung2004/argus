from __future__ import annotations

from pydantic import BaseModel

from argus.shared.models import ResearchRequest, ResearchResponse  # noqa: F401


class SSEEvent(BaseModel):
    event: str
    data: str
    retry: int | None = None
