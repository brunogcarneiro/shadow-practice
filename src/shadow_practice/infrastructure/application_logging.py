"""Persistent per-run application logging."""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path


def configure_application_logging(
    log_dir: Path | None = None, *, started_at: datetime | None = None
) -> Path:
    """Create and attach a new timestamped log file for this application run."""
    if log_dir is None:
        from ..config import get_settings

        log_dir = get_settings().log_dir
    log_dir = Path(log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (started_at or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S-%f")
    log_path = log_dir / f"shadow-practice-{timestamp}.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
        )
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    logging.captureWarnings(True)

    previous_excepthook = sys.excepthook

    def log_uncaught_exception(exception_type, exception, traceback) -> None:
        logging.getLogger("shadow_practice.uncaught").critical(
            "Uncaught application exception",
            exc_info=(exception_type, exception, traceback),
        )
        previous_excepthook(exception_type, exception, traceback)

    sys.excepthook = log_uncaught_exception

    if hasattr(threading, "excepthook"):
        previous_threading_hook = threading.excepthook

        def log_thread_exception(args: threading.ExceptHookArgs) -> None:
            logging.getLogger("shadow_practice.thread").critical(
                "Uncaught exception in thread %s",
                args.thread.name if args.thread else "unknown",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            previous_threading_hook(args)

        threading.excepthook = log_thread_exception

    logging.getLogger(__name__).info("Application started; log file: %s", log_path)
    return log_path
