"""
API process. Deliberately thin: it only enqueues jobs and reports status --
it never calls a provider adapter directly. All generation, moderation
hook execution, and provider fallback happens in the worker process
(worker_main.py), which is what actually holds an LLMOrchestrator.

This split matters for deployment: the API can scale independently of
generation throughput, and a slow/stuck provider call can never block an
HTTP request thread.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .audit.repository import AuditLogRepository
from .base import Provider
from .bootstrap import build_audit_repository, build_job_queue
from .config import get_settings
from .queue.jobs import JobStatus, RedisJobQueue

app = FastAPI(title="Generation Service")

_queue: RedisJobQueue | None = None
_audit_repository: AuditLogRepository | None = None


def get_queue() -> RedisJobQueue:
    global _queue
    if _queue is None:
        _queue = build_job_queue(get_settings())
    return _queue


def get_audit_repository() -> AuditLogRepository:
    global _audit_repository
    if _audit_repository is None:
        _audit_repository = build_audit_repository(get_settings())
    return _audit_repository


class GenerateRequestBody(BaseModel):
    prompt: str = Field(..., max_length=8000)
    provider: Provider | None = None


class EnqueueResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: dict | None = None
    error: str | None = None


@app.post("/v1/generate", response_model=EnqueueResponse, status_code=202)
async def enqueue_generation(
    body: GenerateRequestBody,
    queue: RedisJobQueue = Depends(get_queue),
    # In production, a real auth dependency sits here, resolving the
    # session to a user_id only after KYC/age verification succeeded.
    # user_id: str = Depends(get_verified_user_id),
):
    job_id = await queue.enqueue(
        {
            "prompt": body.prompt,
            "provider": body.provider.value if body.provider else None,
            # "user_id": user_id,
        }
    )
    return EnqueueResponse(job_id=job_id, status=JobStatus.QUEUED.value)


@app.get("/v1/generate/{job_id}", response_model=JobStatusResponse)
async def get_generation_status(job_id: str, queue: RedisJobQueue = Depends(get_queue)):
    job = await queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=job.id, status=job.status.value, result=job.result, error=job.error
    )


class ReviewItemResponse(BaseModel):
    request_id: str
    status: str
    created_at: str


class ResolveReviewBody(BaseModel):
    reviewer_id: str
    approved: bool


@app.get("/v1/review-queue", response_model=list[ReviewItemResponse])
async def list_review_queue(
    limit: int = 50,
    audit: AuditLogRepository = Depends(get_audit_repository),
    # A real deployment gates this route behind a moderator-role auth
    # dependency -- this is internal tooling, not a user-facing endpoint.
):
    items = await audit.list_pending_reviews(limit=limit)
    return [
        ReviewItemResponse(
            request_id=item.request_id,
            status=item.status,
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]


@app.post("/v1/review-queue/{request_id}/resolve")
async def resolve_review(
    request_id: str,
    body: ResolveReviewBody,
    audit: AuditLogRepository = Depends(get_audit_repository),
):
    await audit.resolve_review(request_id, body.reviewer_id, body.approved)
    return {"status": "ok"}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
