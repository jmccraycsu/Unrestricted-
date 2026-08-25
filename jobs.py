"""
Async job queue for generation requests, backed by Redis.

RedisJobQueue takes an already-constructed client rather than importing
`redis` itself at the class level -- the real import lives in the
`create_redis_job_queue` factory below. This keeps the queuing/serialization
logic (the part worth unit testing) decoupled from having the `redis`
package actually installed; tests can inject any object matching the
AsyncRedisLike protocol.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"  # moderation blocked the request


@dataclass
class Job:
    id: str
    payload: dict[str, Any]
    status: JobStatus = JobStatus.QUEUED
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class AsyncRedisLike(Protocol):
    async def set(self, key: str, value: str) -> Any: ...
    async def get(self, key: str) -> Any: ...
    async def lpush(self, key: str, value: str) -> Any: ...
    async def brpop(self, keys: list[str], timeout: int = 0) -> Any: ...


QUEUE_KEY = "generation:queue"
JOB_KEY_PREFIX = "generation:job:"


def _job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "payload": job.payload,
        "status": job.status.value,
        "result": job.result,
        "error": job.error,
    }


def _job_from_dict(data: dict[str, Any]) -> Job:
    return Job(
        id=data["id"],
        payload=data["payload"],
        status=JobStatus(data["status"]),
        result=data.get("result"),
        error=data.get("error"),
    )


class RedisJobQueue:
    def __init__(self, redis_client: AsyncRedisLike):
        self._redis = redis_client

    async def enqueue(self, payload: dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, payload=payload, status=JobStatus.QUEUED)
        await self._redis.set(JOB_KEY_PREFIX + job_id, json.dumps(_job_to_dict(job)))
        await self._redis.lpush(QUEUE_KEY, job_id)
        return job_id

    async def dequeue(self, timeout: int = 5) -> Optional[str]:
        """Blocks up to `timeout` seconds waiting for a job id. Returns
        None on timeout so the worker loop can check for shutdown signals
        between polls rather than blocking forever."""
        result = await self._redis.brpop([QUEUE_KEY], timeout=timeout)
        if result is None:
            return None
        _, job_id = result
        if isinstance(job_id, bytes):
            job_id = job_id.decode()
        return job_id

    async def get_job(self, job_id: str) -> Optional[Job]:
        raw = await self._redis.get(JOB_KEY_PREFIX + job_id)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return _job_from_dict(json.loads(raw))

    async def update_job(self, job: Job) -> None:
        await self._redis.set(JOB_KEY_PREFIX + job.id, json.dumps(_job_to_dict(job)))


def create_redis_job_queue(redis_url: str) -> RedisJobQueue:
    """Factory that does the actual `redis` import. Call this in
    production wiring; call RedisJobQueue(fake_client) directly in tests."""
    import redis.asyncio as redis  # local import by design -- see module docstring

    client = redis.from_url(redis_url, decode_responses=True)
    return RedisJobQueue(client)
