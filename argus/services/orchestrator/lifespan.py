from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from argus.services.orchestrator.manager import ResearchManager
from argus.services.orchestrator.routes import init_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    manager = ResearchManager()
    init_manager(manager)
    logger.info("Research manager initialized")

    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, ValueError):
            logger.warning("Signal handler not supported on this platform")

    running = True

    async def _timeout_check() -> None:
        nonlocal running
        while running:
            await asyncio.sleep(10)
            await manager.check_timeouts()

    timeout_task = asyncio.create_task(_timeout_check())

    try:
        yield
    finally:
        running = False
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task

        logger.info("Graceful shutdown starting")
        await manager.shutdown()
        logger.info("Graceful shutdown complete")
