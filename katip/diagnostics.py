"""Bounded metadata-only diagnostics, with an allowlist at the logging boundary."""

from collections import deque
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

_FIELDS = {"stage", "code", "source", "provider", "audio_bytes", "duration_ms", "errno", "exception_type",
           "sample_rate", "http_status", "request_bytes", "host", "network_error", "version"}
LOG_NAME = "diagnostics.jsonl"
CRASH_LOG_NAME = "crash-traceback.log"
_CRASH_LOG_LIMIT = 1024 * 1024
_crash_file = None


class Diagnostics:
    def __init__(self, clock=time.monotonic, logger=None, wall_clock=time.time):
        self.job_id = uuid4().hex
        self._clock = clock
        self._wall_clock = wall_clock
        self._start = clock()
        self._events = deque(maxlen=256)
        self._lock = threading.Lock()
        self._sequence = 0
        self._logger = logger

    def event(self, name: str, **fields):
        with self._lock:
            self._sequence += 1
            # Wall time correlates a reported incident with system logs and coredumps.
            record = {"job_id": self.job_id, "sequence": self._sequence, "event": name,
                      "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall_clock())),
                      "elapsed_ms": round((self._clock() - self._start) * 1000)}
            record.update({key: value for key, value in fields.items()
                           if key in _FIELDS and isinstance(value, (str, int, float, bool))})
            self._events.append(record)
            if self._logger:
                self._logger.info(json.dumps(record, ensure_ascii=False))
            return dict(record)

    def snapshot(self):
        with self._lock:
            return [dict(event) for event in self._events]


def diagnostic_logger(directory: Path):
    logger = logging.getLogger(f"katip.diagnostics.{directory}")
    if not logger.handlers:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / LOG_NAME, maxBytes=1024 * 1024,
                                          backupCount=4, encoding="utf-8")
        except OSError:
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def last_logged_event(directory: Path):
    """Name of the final event a previous run wrote, or None when there is no readable log."""
    try:
        with open(directory / LOG_NAME, "rb") as file:
            file.seek(0, 2)
            file.seek(max(0, file.tell() - 8192))
            lines = file.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line).get("event")
        except (ValueError, AttributeError):
            continue
    return None


def record_app_start(directory: Path, logger, version: str):
    """Mark a run's start; a previous run without app_stopped ended by crash, kill or power loss."""
    previous = last_logged_event(directory)
    diagnostics = Diagnostics(logger=logger)
    diagnostics.job_id = "app"
    if previous is not None and previous != "app_stopped":
        diagnostics.event("previous_run_unclean", code="PROCESS_EXIT_UNCLEAN", source=str(previous)[:64])
    diagnostics.event("app_started", version=version)
    return diagnostics


def install_crash_reporting(directory: Path, diagnostics: Diagnostics) -> bool:
    """Native crash stacks go to a bounded file; uncaught exceptions log only their type."""
    global _crash_file
    import faulthandler
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / CRASH_LOG_NAME
        mode = "w" if path.exists() and path.stat().st_size > _CRASH_LOG_LIMIT else "a"
        _crash_file = open(path, mode, encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        return False

    previous_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def excepthook(kind, value, traceback):
        diagnostics.event("unhandled_exception", code="UNEXPECTED_ERROR", exception_type=kind.__name__)
        previous_hook(kind, value, traceback)

    def thread_excepthook(args):
        diagnostics.event("unhandled_exception", code="UNEXPECTED_ERROR", source="thread",
                          exception_type=args.exc_type.__name__)
        previous_thread_hook(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return True
