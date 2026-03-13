"""Standalone worker entrypoint.

Runs the DB-polling AnalysisWorker without starting the FastAPI server.
This lets us compare:
    1. API + worker in one process
    2. API-only process + separate worker process
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings
from app.core.dependencies import get_worker

logger = logging.getLogger(__name__)


async def run_worker_forever() -> None:
    settings.ensure_directories()
    worker = get_worker()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    logger.info(
        "Standalone worker booted poll_interval_sec=%s max_concurrent=%s",
        settings.WORKER_POLL_INTERVAL_SEC,
        settings.WORKER_MAX_CONCURRENT,
    )

    def _request_stop() -> None:
        logger.info("Stop signal received, shutting down worker...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: _request_stop())

    await worker.start()
    try:
        await stop_event.wait()
    finally:
        await worker.stop()


def main() -> None:
    asyncio.run(run_worker_forever())


if __name__ == "__main__":
    main()
