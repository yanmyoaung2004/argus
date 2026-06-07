from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from argus.services.orchestrator.manager import ResearchManager
from argus.services.orchestrator.models import ResearchRequest, ResearchResponse
from argus.services.orchestrator.sse import SSEStreamer
from argus.shared.models import FeedbackRequest

router = APIRouter(prefix="/research", tags=["research"])

_manager: ResearchManager | None = None


def init_manager(manager: ResearchManager) -> None:
    global _manager
    _manager = manager


@router.post("", response_model=ResearchResponse)
async def create_research(req: ResearchRequest) -> ResearchResponse:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Research manager not initialized")
    task = await _manager.create_task(req.query)
    return ResearchResponse(
        task_id=task.task_id,
        status=task.status.value,
        message=f"Research task created: {task.task_id}",
    )


@router.get("/{task_id}/status")
async def stream_status(task_id: str) -> StreamingResponse:
    streamer = SSEStreamer(task_id)
    return StreamingResponse(
        streamer.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}/report")
async def get_report(task_id: str) -> dict[str, str | None]:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Research manager not initialized")
    report = await _manager.get_report(task_id)
    return {"task_id": task_id, "report": report}


@router.get("/{task_id}/html")
async def get_html_report(task_id: str) -> HTMLResponse:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Research manager not initialized")
    html = await _manager.get_html_report(task_id)
    if html is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(content=html)


@router.post("/feedback/{source_id}")
async def submit_feedback(source_id: int, req: FeedbackRequest) -> dict[str, str | float]:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Research manager not initialized")
    new_score = await _manager.apply_feedback(source_id, req.is_correct)
    return {"source_id": source_id, "new_credibility_score": new_score}
