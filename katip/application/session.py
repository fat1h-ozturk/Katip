"""One owner for lifecycle transitions and stale-result rejection."""

from dataclasses import dataclass, field, replace
from enum import Enum
import threading
import time
from uuid import uuid4
from ..domain.errors import ProviderError


class State(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    DRAINING = "draining"
    PREPROCESSING = "preprocessing"
    TRANSCRIBING = "transcribing"
    FORMATTING = "formatting"
    READY = "ready"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    ERROR = "recoverable_error"
    CANCELLING = "cancelling"
    SHUTTING_DOWN = "shutting_down"


BUSY = {State.DRAINING, State.PREPROCESSING, State.TRANSCRIBING,
        State.FORMATTING, State.DELIVERING, State.CANCELLING}

_NEXT = {
    State.IDLE: {State.RECORDING, State.ERROR, State.SHUTTING_DOWN},
    State.RECORDING: {State.DRAINING, State.ERROR},
    State.DRAINING: {State.PREPROCESSING, State.TRANSCRIBING, State.ERROR},
    State.PREPROCESSING: {State.TRANSCRIBING, State.ERROR},
    State.TRANSCRIBING: {State.FORMATTING, State.READY, State.DELIVERING, State.ERROR},
    State.FORMATTING: {State.READY, State.DELIVERING, State.ERROR},
    State.READY: {State.DELIVERING, State.RECORDING, State.PREPROCESSING, State.FORMATTING, State.ERROR, State.SHUTTING_DOWN},
    State.DELIVERING: {State.COMPLETED, State.READY, State.ERROR},
    State.COMPLETED: {State.RECORDING, State.FORMATTING, State.ERROR, State.SHUTTING_DOWN},
    State.ERROR: {State.RECORDING, State.PREPROCESSING, State.FORMATTING, State.ERROR, State.SHUTTING_DOWN},
    State.CANCELLING: {State.ERROR},
    State.SHUTTING_DOWN: set(),
}


@dataclass
class Job:
    settings: dict = field(repr=False)
    id: str = field(default_factory=lambda: uuid4().hex)
    attempt: int = 0
    cancelled: threading.Event = field(default_factory=threading.Event, repr=False)
    deadline: float = 0.0
    publish: object = field(default=None, repr=False)
    service: object = field(default=None, repr=False)
    target: object = field(default=None, repr=False)

    def check(self):
        if self.cancelled.is_set():
            raise ProviderError("CANCELLED", "job", "İşlem iptal edildi; alınan kayıt korunuyor.")
        if self.deadline and time.monotonic() >= self.deadline:
            raise ProviderError("DEADLINE", "job", "İşlem süresi doldu; alınan kayıt korunuyor.")


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    attempt: int
    kind: str
    value: object = None


class SessionController:
    def __init__(self):
        self.state = State.IDLE
        self.job = None

    @property
    def busy(self):
        return self.state in BUSY

    def transition(self, state):
        if state == self.state:
            return
        if state not in _NEXT[self.state]:
            raise RuntimeError(f"Geçersiz oturum geçişi: {self.state.value} → {state.value}")
        self.state = state

    def begin(self, settings):
        if self.busy or self.state in (State.RECORDING, State.SHUTTING_DOWN):
            raise RuntimeError("Bir kayıt zaten sürüyor.")
        from copy import deepcopy
        self.job = Job(deepcopy(settings))
        self.state = State.RECORDING
        return self.job

    def accepts(self, event):
        return bool(self.job and not self.job.cancelled.is_set()
                    and self.job.id == event.job_id and self.job.attempt == event.attempt)

    def retry(self, settings=None):
        if not self.job or self.state not in (State.ERROR, State.READY, State.COMPLETED):
            raise RuntimeError("İşlem yeniden başlatılamadı.")
        self.job.cancelled.set()
        from copy import deepcopy
        self.job = replace(self.job, attempt=self.job.attempt + 1, cancelled=threading.Event(),
                           settings=deepcopy(settings if settings is not None else self.job.settings),
                           service=None, deadline=time.monotonic() + 180)
        return self.job

    def cancel(self):
        if self.job:
            self.job.cancelled.set()
        self.state = State.ERROR
