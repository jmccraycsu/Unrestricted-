"""Worker loop: pulls job ids off the queue, runs them through the
LLMOrchestrator (moderation hooks included), and writes the outcome back.
Runs as its own process/container, separate from the API process -- the
API only enqueues and polls; it never touches provider adapters directly."""

from __future__ import annotations

import asyncio
import logging

from ..base import GenerationRequest, Provider
from ..orchestrator import LLMOrchestrator
from .jobs import Job, JobStatus, RedisJobQueue

logger = logging.getLogger("worker")


async def process_one(queue: RedisJobQueue, orchestrator: LLMOrchestrator, job_id: str) -> None:
    job = await queue.get_job(job_id)
    if job is None:
        logger.warning("job_not_found", extra={"job_id": job_id})
        return

    job.status = JobStatus.RUNNING
    await queue.update_job(job)

    payload = job.payload
    provider = Provider(payload["provider"]) if payload.get("provider") else None
    request = GenerationRequest(
        prompt=payload["prompt"],
        system_prompt=payload.get("system_prompt"),
        provider=provider,
        request_id=job_id,
        user_id=payload.get("user_id"),
    )

    try:
        response = await orchestrator.generate(request)
    
    except Exception:
        # Never let an unexpected exception kill the worker loop -- log it,
        # record the job as failed, keep consuming.
        logger.exception("unexpected_worker_error", extra={"job_id": job_id})
        job.status = JobStatus.FAILED
        job.error = "internal error"
    else:
        job.status = JobStatus.DONE
        job.result = {
            "content": response.content,
            "provider": response.provider.value,
            "model": response.model,
        }

    await queue.update_job(job)


async def run_worker(
    queue: RedisJobQueue,
    orchestrator: LLMOrchestrator,
    poll_timeout: int = 5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Main loop. Pass `stop_event` to allow graceful shutdown (set it from
    a signal handler); otherwise this runs until the process is killed."""
    logger.info("worker_started")
    while stop_event is None or not stop_event.is_set():
        job_id = await queue.dequeue(timeout=poll_timeout)
        if job_id is None:
            continue
        await process_one(queue, orchestrator, job_id)
    logger.info("worker_stopped")
