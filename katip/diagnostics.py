"""Bounded metadata-only diagnostics, with an allowlist at the logging boundary."""

from collections import deque
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import time
from uuid import uuid4

_FIELDS = {"stage", "code", "source", "provider", "audio_bytes", "duration_ms", "errno", "exception_type"}


class Diagnostics:
    def __init__(self, clock=time.monotonic, logger=None):
        self.job_id = uuid4().hex
        self._clock = clock
        self._start = clock()
        self._events = deque(maxlen=256)
        self._lock = threading.Lock()
        self._sequence = 0
        self._logger = logger

    def event(self, name: str, **fields):
        with self._lock:
            self._sequence += 1
            record = {"job_id": self.job_id, "sequence": self._sequence,
                      "event": name, "elapsed_ms": round((self._clock() - self._start) * 1000)}
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
            handler = RotatingFileHandler(directory / "diagnostics.jsonl", maxBytes=1024 * 1024,
                                          backupCount=4, encoding="utf-8")
        except OSError:
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
