"""Entrypoint for the worker container/process. Separate from api.py on
purpose -- see api.py's module docstring."""

from __future__ import annotations

import asyncio
import logging
import signal

from .bootstrap import build_audit_repository, build_job_queue, build_orchestrator
from .config import get_settings
from .queue.worker import run_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker_main")


async def main() -> None:
    settings = get_settings()
    queue = build_job_queue(settings)
    audit_repository = build_audit_repository(settings)
    orchestrator = build_orchestrator(settings, audit_repository)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("starting_worker")
    await run_worker(queue, orchestrator, poll_timeout=5, stop_event=stop_event)


if __name__ == "__main__":
    asyncio.run(main())
