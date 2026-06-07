from __future__ import annotations

import logging
import threading
import time

import uvicorn

from argus.services.knowledge_graph.writer import KGWriter
from argus.shared.config import settings
from argus.shared.models import AgentType

logging.basicConfig(
    level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def _run_task_agent(agent_type: AgentType) -> None:
    from argus.services.orchestrator.agent_runner import AgentRunner
    runner = AgentRunner(agent_type=agent_type)
    logger.info("Starting task agent runner: %s", agent_type.value)
    runner.start()


def _run_synthesis_agent() -> None:
    from argus.services.agents.synthesis import SynthesisAgent
    agent = SynthesisAgent()
    logger.info("Starting synthesis agent (fact consumer)")
    agent.start()


def _run_kg_writer() -> None:
    writer = KGWriter()
    logger.info("Starting KG writer")
    writer.start()


def main() -> None:
    import sys

    workers_only = "--workers-only" in sys.argv

    threads: list[threading.Thread] = []

    for agent_type in AgentType:
        if agent_type == AgentType.SYNTHESIS:
            continue
        t = threading.Thread(target=_run_task_agent, args=(agent_type,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.1)

    t = threading.Thread(target=_run_synthesis_agent, daemon=True)
    t.start()
    threads.append(t)

    t = threading.Thread(target=_run_kg_writer, daemon=True)
    t.start()
    threads.append(t)

    logger.info("All workers started.")

    if workers_only:
        logger.info("Workers-only mode. Keeping thread alive...")
        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            logger.info("Shutting down workers.")
    else:
        logger.info("Launching HTTP server...")
        port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else settings.app_port
        uvicorn.run(
            "argus.app:app",
            host=settings.app_host,
            port=port,
            log_level=settings.app_log_level,
        )


if __name__ == "__main__":
    main()
