from __future__ import annotations

import logging
import sys


def setup_logging() -> None:
    from argus.shared.config import settings
    level = getattr(logging, settings.app_log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    for name in ("httpx", "httpcore", "urllib3", "chardet"):
        logging.getLogger(name).setLevel(logging.WARNING)
